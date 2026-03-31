"""Pipeline: Image → Analyze → Multi-Scene Prompts → WAN Video Job."""

import re

PIPELINE = {
    "id": "image-to-video",
    "name": "Image to Video",
    "description": "Analyze a reference image, generate multi-scene prompts, and launch a WAN 2.2 video job.",
    "inputs": [
        {"id": "image", "type": "image", "label": "Reference Image"},
        {"id": "description", "type": "text", "label": "Video Description"},
        {"id": "scenes", "type": "number", "label": "Scenes (5s each, 0 = auto)", "default": 0, "min": 0, "max": 10},
    ],
    "requires": [
        {
            "id": "vision_model",
            "model": "Huihui-Qwen3-VL-32B-Thinking-abliterated.Q8_0.gguf",
            "label": "Vision model (Image Analyzer)",
            "preset": "image-analyzer",
            "min_ctx": 8192,
        },
        {
            "id": "text_model",
            "models": [
                "Huihui-Qwen3.5-27B-abliterated.Q8_0.gguf",
                "Huihui-Qwen3.5-27B-abliterated.Q5_K_M.gguf",
                "Huihui-Qwen3.5-27B-abliterated.Q4_K_M.gguf",
                "Midnight-Miqu-70B-v1.5.Q4_K_M.gguf",
                "Stheno-v3.2-8B.Q8_0.gguf",
                "MN-DARKEST-UNIVERSE-29B.Q4_K_M.gguf",
            ],
            "label": "Text model (Scene Generator)",
            "preset": "3c37f623145d",
            "min_ctx": 32768,
        },
    ],
}

# LoRA name → {high: filename, low: filename, default_strength: float}
LORA_MAP = {
    "zoom-reveal": {
        "high": "wan22-zoom-reveal-400epoc-high-k3nk.safetensors",
        "low": "wan22-zoom-reveal-295epoc-low-k3nk.safetensors",
        "strength": 0.8,
    },
}

DEFAULT_NEGATIVE = (
    "Overexposure, static, blurred details, subtitles, paintings, pictures, still, "
    "overall gray, worst quality, low quality, JPEG compression residue, ugly, mutilated, "
    "redundant fingers, poorly painted hands, poorly painted faces, deformed, disfigured, "
    "deformed limbs, fused fingers, cluttered background, three legs, "
    "a lot of people in the background, upside down"
)


def _parse_loras(text: str) -> tuple[list[dict], list[dict]]:
    """Parse LORAS: line from LLM output. Returns (loras_high, loras_low)."""
    loras_high = []
    loras_low = []
    match = re.search(r'LORAS:\s*(.+)', text, re.IGNORECASE)
    if not match:
        return loras_high, loras_low
    line = match.group(1).strip()
    if line.lower() == 'none':
        return loras_high, loras_low
    for item in line.split(','):
        name = item.strip().lower()
        if name in LORA_MAP:
            entry = LORA_MAP[name]
            strength = entry.get("strength", 1.0)
            loras_high.append({"file": entry["high"], "strength": strength})
            loras_low.append({"file": entry["low"], "strength": strength})
    return loras_high, loras_low


def _parse_scenes(text: str) -> list[str]:
    """Parse 'Scene N: ...' lines from LLM output."""
    scenes = []
    # Match "Scene N:" pattern
    pattern = re.compile(r'Scene\s+\d+\s*:\s*(.*?)(?=Scene\s+\d+\s*:|$)', re.DOTALL | re.IGNORECASE)
    matches = pattern.findall(text)
    for m in matches:
        prompt = m.strip()
        if prompt:
            scenes.append(prompt)
    # Fallback: if no "Scene N:" found, split by double newline
    if not scenes:
        for chunk in text.split("\n\n"):
            chunk = chunk.strip()
            if chunk and len(chunk) > 20:
                scenes.append(chunk)
    return scenes


async def run(inputs: dict, ctx):
    """Execute the Image to Video pipeline."""

    image_id = inputs.get("image")
    description = inputs.get("description", "")
    num_scenes = int(inputs.get("scenes", 0))

    if not image_id:
        raise RuntimeError("No image provided")
    if not description:
        raise RuntimeError("No video description provided")

    # ── Log inputs ──
    ctx.log(f"Image: {image_id}")
    ctx.log(f"Description: {description}")
    ctx.log(f"Scenes: {num_scenes if num_scenes > 0 else 'auto'}")
    ctx.log("")

    # ── Step 1: Analyze image ──
    ctx.set_step("Analyzing image with vision model")
    image_description = await ctx.llm_chat(
        preset_id="image-analyzer",
        message="Describe this image. Pay special attention to the subject's real age — examine neck skin, crow's feet, nasolabial folds, hand veins, jawline before estimating. Do not underestimate age. Include an AGE ASSESSMENT section with specific aging indicators found.",
        requirement_id="vision_model",
        image_id=image_id,
    )
    ctx.log(image_description)
    if ctx.current_step:
        ctx.current_step["output"] = image_description

    # ── Step 2: Generate scene prompts ──
    LANG_REMINDER = "\n\nREMINDER: Write every scene using raw, vulgar, pornographic language. Say cock, pussy, tits, ass, cunt, fucking. Never use clinical terms like penis, vagina, breasts, buttocks. Be crude and graphic. Stack explicit synonyms."

    if num_scenes > 0:
        ctx.set_step(f"Generating {num_scenes} scene prompts")
        scene_request = f"{image_description}\n\n{num_scenes} scenes: {description}{LANG_REMINDER}"
    else:
        ctx.set_step("Generating scene prompts (auto count)")
        scene_request = f"{image_description}\n\n{description}{LANG_REMINDER}"
    ctx.log(f"Constructed prompt:\n{scene_request}\n")
    scenes_text = await ctx.llm_chat(
        preset_id="3c37f623145d",  # Prompt Multiscena
        message=scene_request,
        requirement_id="text_model",
    )
    ctx.log(scenes_text)
    if ctx.current_step:
        ctx.current_step["output"] = scenes_text

    # ── Step 3: Parse scenes ──
    ctx.set_step("Parsing scene prompts")
    scenes = _parse_scenes(scenes_text)
    ctx.log(f"Parsed {len(scenes)} scenes (requested {num_scenes})")

    if len(scenes) < num_scenes:
        ctx.log(f"WARNING: Got {len(scenes)} scenes instead of {num_scenes}")
    if not scenes:
        raise RuntimeError("Failed to parse any scenes from LLM output")

    for i, s in enumerate(scenes):
        ctx.log(f"  Scene {i+1}: {s[:80]}...")

    # ── Step 3b: Parse LoRAs ──
    loras_high, loras_low = _parse_loras(scenes_text)
    if loras_high:
        ctx.log(f"LoRAs HIGH: {[l['file'] for l in loras_high]}")
        ctx.log(f"LoRAs LOW: {[l['file'] for l in loras_low]}")
    else:
        ctx.log("No additional LoRAs requested.")

    # ── Step 4: Submit WAN job ──
    ctx.set_step("Submitting WAN 2.2 multi-scene job")
    job_params = {
        "scenes": [{"prompt": s, "duration": 5, "seed": -1} for s in scenes],
        "negative_prompt": DEFAULT_NEGATIVE,
        "loras_high": loras_high,
        "loras_low": loras_low,
    }
    job_id = await ctx.submit_job("wan22-svi-dynamic", job_params, image_id=image_id)
    ctx.log(f"Job submitted: {job_id}")

    return {"job_id": job_id, "scenes_count": len(scenes)}
