#!/usr/bin/env python3
"""ComfyUI Stub Server — fake responses for local development.

Responds to all ComfyUI API endpoints with plausible fake data so the
Studio backend can run without a real ComfyUI instance. No GPU, no models,
no actual inference — just enough to make the UI functional.

Generates real placeholder images (512x512 PNG) and stub MP4 videos so
the runner's output detection, history, and assets pages all work correctly.

Usage: python3 comfyui_stub.py --port 8188
"""

import argparse
import asyncio
import io
import json
import os
import random
import subprocess
import time
import uuid

from aiohttp import web
from PIL import Image, ImageDraw, ImageFont

# ── Configuration ─────────────────────────────────────────────

STUDIO_DIR = os.environ.get("STUDIO_DIR", "/workspace/studio")
OUTPUT_BASE = os.path.join(STUDIO_DIR, "assets", "output")

# ── Fake data ─────────────────────────────────────────────────

FAKE_SYSTEM_STATS = {
    "system": {
        "os": "posix",
        "python_version": "3.12.0",
        "embedded_python": False,
    },
    "devices": [
        {
            "name": "cuda:0 NVIDIA Stub GPU (Development)",
            "type": "cuda",
            "index": 0,
            "vram_total": 24 * 1024 * 1024 * 1024,  # 24 GB
            "vram_free": 20 * 1024 * 1024 * 1024,   # 20 GB free
            "torch_vram_total": 24 * 1024 * 1024 * 1024,
            "torch_vram_free": 20 * 1024 * 1024 * 1024,
        }
    ],
}

# Object info for all nodes required by workflows + common built-in nodes.
# Kept in sync with workflows/*/manifest.yaml required_nodes lists.
def _n(name, display_name, category, module, output=None, output_node=False):
    """Helper to build a minimal object_info entry."""
    entry = {
        "input": {"required": {}},
        "output": output or [],
        "output_name": output or [],
        "name": name,
        "display_name": display_name,
        "category": category,
        "python_module": module,
    }
    if output_node:
        entry["output_node"] = True
    return entry

FAKE_OBJECT_INFO = {
    # ── Built-in ComfyUI nodes ──
    "CheckpointLoaderSimple": _n("CheckpointLoaderSimple", "Load Checkpoint", "loaders", "nodes", ["MODEL", "CLIP", "VAE"]),
    "CLIPLoader":             _n("CLIPLoader", "Load CLIP", "loaders", "nodes", ["CLIP"]),
    "CLIPSetLastLayer":       _n("CLIPSetLastLayer", "CLIP Set Last Layer", "conditioning", "nodes", ["CLIP"]),
    "CLIPTextEncode":         _n("CLIPTextEncode", "CLIP Text Encode", "conditioning", "nodes", ["CONDITIONING"]),
    "DisableNoise":           _n("DisableNoise", "Disable Noise", "sampling/custom_sampling/noise", "nodes", ["NOISE"]),
    "EmptyLatentImage":       _n("EmptyLatentImage", "Empty Latent Image", "latent", "nodes", ["LATENT"]),
    "ImageScale":             _n("ImageScale", "Upscale Image", "image/upscaling", "nodes", ["IMAGE"]),
    "ImageScaleToTotalPixels":_n("ImageScaleToTotalPixels", "Scale To Total Pixels", "image/upscaling", "nodes", ["IMAGE"]),
    "KSampler":               _n("KSampler", "KSampler", "sampling", "nodes", ["LATENT"]),
    "KSamplerAdvanced":       _n("KSamplerAdvanced", "KSampler (Advanced)", "sampling", "nodes", ["LATENT"]),
    "KSamplerSelect":         _n("KSamplerSelect", "KSampler Select", "sampling/custom_sampling/samplers", "nodes", ["SAMPLER"]),
    "LoadImage":              _n("LoadImage", "Load Image", "image", "nodes", ["IMAGE", "MASK"]),
    "LoraLoaderModelOnly":    _n("LoraLoaderModelOnly", "Load LoRA (Model Only)", "loaders", "nodes", ["MODEL"]),
    "ModelSamplingSD3":       _n("ModelSamplingSD3", "Model Sampling SD3", "advanced/model", "nodes", ["MODEL"]),
    "PreviewImage":           _n("PreviewImage", "Preview Image", "image", "nodes", output_node=True),
    "RandomNoise":            _n("RandomNoise", "Random Noise", "sampling/custom_sampling/noise", "nodes", ["NOISE"]),
    "BasicScheduler":         _n("BasicScheduler", "Basic Scheduler", "sampling/custom_sampling/schedulers", "nodes", ["SIGMAS"]),
    "SamplerCustomAdvanced":  _n("SamplerCustomAdvanced", "Sampler Custom Advanced", "sampling/custom_sampling", "nodes", ["OUTPUT", "DENOISED_OUTPUT"]),
    "SaveImage":              _n("SaveImage", "Save Image", "image", "nodes", output_node=True),
    "SplitSigmas":            _n("SplitSigmas", "Split Sigmas", "sampling/custom_sampling/sigmas", "nodes", ["SIGMAS", "SIGMAS"]),
    "UNETLoader":             _n("UNETLoader", "Load Diffusion Model", "loaders", "nodes", ["MODEL"]),
    "UpscaleModelLoader":     _n("UpscaleModelLoader", "Load Upscale Model", "loaders", "nodes", ["UPSCALE_MODEL"]),
    "VAEDecode":              _n("VAEDecode", "VAE Decode", "latent", "nodes", ["IMAGE"]),
    "VAEEncode":              _n("VAEEncode", "VAE Encode", "latent", "nodes", ["LATENT"]),
    "VAELoader":              _n("VAELoader", "Load VAE", "loaders", "nodes", ["VAE"]),
    "LoraLoader":             _n("LoraLoader", "Load LoRA", "loaders", "nodes", ["MODEL", "CLIP"]),
    # ── WAN Video Wrapper (kijai/ComfyUI-WanVideoWrapper) ──
    "WanImageToVideo":             _n("WanImageToVideo", "WAN Image to Video", "conditioning/wan", "custom_nodes.ComfyUI-WanVideoWrapper", ["CONDITIONING"]),
    "WanImageToVideoSVIPro":       _n("WanImageToVideoSVIPro", "WAN I2V SVI Pro", "conditioning/wan", "custom_nodes.ComfyUI-WanVideoWrapper", ["CONDITIONING"]),
    "WanVideoBlockSwap":           _n("WanVideoBlockSwap", "WAN Block Swap", "wan", "custom_nodes.ComfyUI-WanVideoWrapper", ["BLOCKSWAP_ARGS"]),
    "WanVideoDecode":              _n("WanVideoDecode", "WAN Video Decode", "wan", "custom_nodes.ComfyUI-WanVideoWrapper", ["IMAGE"]),
    "WanVideoImageToVideoEncode":  _n("WanVideoImageToVideoEncode", "WAN I2V Encode", "wan", "custom_nodes.ComfyUI-WanVideoWrapper", ["WAN_DATA"]),
    "WanVideoLoraSelect":          _n("WanVideoLoraSelect", "WAN LoRA Select", "wan", "custom_nodes.ComfyUI-WanVideoWrapper", ["WAN_LORA"]),
    "WanVideoModelLoader":         _n("WanVideoModelLoader", "WAN Model Loader", "wan", "custom_nodes.ComfyUI-WanVideoWrapper", ["MODEL"]),
    "WanVideoSampler":             _n("WanVideoSampler", "WAN Video Sampler", "wan", "custom_nodes.ComfyUI-WanVideoWrapper", ["LATENT"]),
    "WanVideoSetBlockSwap":        _n("WanVideoSetBlockSwap", "WAN Set Block Swap", "wan", "custom_nodes.ComfyUI-WanVideoWrapper", ["MODEL"]),
    "WanVideoSetLoRAs":            _n("WanVideoSetLoRAs", "WAN Set LoRAs", "wan", "custom_nodes.ComfyUI-WanVideoWrapper", ["WAN_LORA"]),
    "WanVideoTextEncode":          _n("WanVideoTextEncode", "WAN Text Encode", "wan", "custom_nodes.ComfyUI-WanVideoWrapper", ["CONDITIONING"]),
    "WanVideoTorchCompileSettings":_n("WanVideoTorchCompileSettings", "WAN Torch Compile", "wan", "custom_nodes.ComfyUI-WanVideoWrapper", ["TORCH_COMPILE_ARGS"]),
    "WanVideoVAELoader":           _n("WanVideoVAELoader", "WAN VAE Loader", "wan", "custom_nodes.ComfyUI-WanVideoWrapper", ["VAE"]),
    "LoadWanVideoT5TextEncoder":   _n("LoadWanVideoT5TextEncoder", "Load WAN T5 Encoder", "wan", "custom_nodes.ComfyUI-WanVideoWrapper", ["CLIP"]),
    "wanBlockSwap":                _n("wanBlockSwap", "WAN Block Swap (legacy)", "wan", "custom_nodes.ComfyUI-WanVideoWrapper", ["BLOCKSWAP_ARGS"]),
    # ── Video Helper Suite (ComfyUI-VideoHelperSuite) ──
    "VHS_VideoCombine":       _n("VHS_VideoCombine", "Video Combine", "Video Helper Suite", "custom_nodes.ComfyUI-VideoHelperSuite", ["VHS_FILENAMES"], output_node=True),
    # ── Frame Interpolation (ComfyUI-Frame-Interpolation) ──
    "RIFE VFI":               _n("RIFE VFI", "RIFE VFI", "Video Helper Suite", "custom_nodes.ComfyUI-Frame-Interpolation", ["IMAGE"]),
    # ── IP-Adapter (ComfyUI_IPAdapter_plus) ──
    "IPAdapterAdvanced":           _n("IPAdapterAdvanced", "IP-Adapter Advanced", "ipadapter", "custom_nodes.ComfyUI_IPAdapter_plus", ["MODEL"]),
    "IPAdapterFaceID":             _n("IPAdapterFaceID", "IP-Adapter FaceID", "ipadapter", "custom_nodes.ComfyUI_IPAdapter_plus", ["MODEL"]),
    "IPAdapterInsightFaceLoader":  _n("IPAdapterInsightFaceLoader", "IP-Adapter InsightFace Loader", "ipadapter", "custom_nodes.ComfyUI_IPAdapter_plus", ["INSIGHTFACE"]),
    "IPAdapterUnifiedLoader":      _n("IPAdapterUnifiedLoader", "IP-Adapter Unified Loader", "ipadapter", "custom_nodes.ComfyUI_IPAdapter_plus", ["MODEL", "IPADAPTER"]),
    "IPAdapterUnifiedLoaderFaceID":_n("IPAdapterUnifiedLoaderFaceID", "IP-Adapter Unified Loader FaceID", "ipadapter", "custom_nodes.ComfyUI_IPAdapter_plus", ["MODEL", "IPADAPTER"]),
    # ── cg-use-everywhere ──
    "Anything Everywhere":    _n("Anything Everywhere", "Anything Everywhere", "everywhere", "custom_nodes.cg-use-everywhere"),
    "Anything Everywhere3":   _n("Anything Everywhere3", "Anything Everywhere3", "everywhere", "custom_nodes.cg-use-everywhere"),
    "Prompts Everywhere":     _n("Prompts Everywhere", "Prompts Everywhere", "everywhere", "custom_nodes.cg-use-everywhere"),
    # ── Impact Pack (ComfyUI-Impact-Pack) ──
    "FaceDetailer":                _n("FaceDetailer", "Face Detailer", "ImpactPack", "custom_nodes.ComfyUI-Impact-Pack", ["IMAGE", "IMAGE", "IMAGE", "MASK", "DETAILER_PIPE", "IMAGE"]),
    "UltralyticsDetectorProvider": _n("UltralyticsDetectorProvider", "Ultralytics Detector Provider", "ImpactPack", "custom_nodes.ComfyUI-Impact-Pack", ["BBOX_DETECTOR"]),
    # ── KJNodes (ComfyUI-KJNodes) ──
    "GetImageSizeAndCount":   _n("GetImageSizeAndCount", "Get Image Size And Count", "KJNodes/image", "custom_nodes.ComfyUI-KJNodes", ["IMAGE", "INT", "INT", "INT"]),
    "ImageResizeKJv2":        _n("ImageResizeKJv2", "Image Resize KJ v2", "KJNodes/image", "custom_nodes.ComfyUI-KJNodes", ["IMAGE", "INT", "INT"]),
    "CreateCFGScheduleFloatList": _n("CreateCFGScheduleFloatList", "Create CFG Schedule Float List", "KJNodes", "custom_nodes.ComfyUI-KJNodes", ["FLOAT"]),
    "ScheduledCFGGuidance":   _n("ScheduledCFGGuidance", "Scheduled CFG Guidance", "KJNodes/sampling", "custom_nodes.ComfyUI-KJNodes", ["MODEL"]),
    "ImageBatchExtendWithOverlap": _n("ImageBatchExtendWithOverlap", "Image Batch Extend With Overlap", "KJNodes/image", "custom_nodes.ComfyUI-KJNodes", ["IMAGE"]),
    # ── ComfyUI-GGUF ──
    "UnetLoaderGGUF":         _n("UnetLoaderGGUF", "Load GGUF UNet", "loaders", "custom_nodes.ComfyUI-GGUF", ["MODEL"]),
    # ── rgthree-comfy ──
    "Power Lora Loader (rgthree)": _n("Power Lora Loader (rgthree)", "Power LoRA Loader", "rgthree", "custom_nodes.rgthree-comfy", ["MODEL", "CLIP"]),
    # ── ComfyLiterals ──
    "Float":                  _n("Float", "Float", "literals", "custom_nodes.ComfyLiterals", ["FLOAT"]),
    "INTConstant":            _n("INTConstant", "INT Constant", "literals", "custom_nodes.ComfyLiterals", ["INT"]),
    "PrimitiveInt":           _n("PrimitiveInt", "Primitive Int", "literals", "custom_nodes.ComfyLiterals", ["INT"]),
    # ── ComfyUI_essentials ──
    "GetImageSize+":          _n("GetImageSize+", "Get Image Size+", "essentials/image", "custom_nodes.ComfyUI_essentials", ["INT", "INT"]),
    "ImageFromBatch+":        _n("ImageFromBatch+", "Image From Batch+", "essentials/image", "custom_nodes.ComfyUI_essentials", ["IMAGE"]),
    "ImageListToImageBatch":  _n("ImageListToImageBatch", "Image List To Image Batch", "essentials/image", "custom_nodes.ComfyUI_essentials", ["IMAGE"]),
    "SimpleMath+":            _n("SimpleMath+", "Simple Math+", "essentials/utilities", "custom_nodes.ComfyUI_essentials", ["INT", "FLOAT"]),
}

# Load external object_info dump if available (exported from production)
_object_info_path = os.path.join(os.path.dirname(__file__), "object_info.json")
if os.path.exists(_object_info_path):
    try:
        with open(_object_info_path) as f:
            FAKE_OBJECT_INFO = json.load(f)
        print(f"[stub] Loaded object_info from {_object_info_path} ({len(FAKE_OBJECT_INFO)} nodes)")
    except Exception as e:
        print(f"[stub] Warning: failed to load {_object_info_path}: {e}")

# Store for active prompts
active_prompts = {}


# ── Output generators ─────────────────────────────────────────

def _generate_placeholder_image(width=512, height=512, text="DEV MODE"):
    """Generate a placeholder PNG image with centered text."""
    img = Image.new("RGB", (width, height), color=(40, 40, 50))
    draw = ImageDraw.Draw(img)

    # Draw grid pattern
    for x in range(0, width, 64):
        draw.line([(x, 0), (x, height)], fill=(55, 55, 65), width=1)
    for y in range(0, height, 64):
        draw.line([(0, y), (width, y)], fill=(55, 55, 65), width=1)

    # Draw text — try large font, fall back to default
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (width - tw) // 2
    y = (height - th) // 2
    # Shadow
    draw.text((x + 2, y + 2), text, fill=(0, 0, 0), font=font)
    # Main text
    draw.text((x, y), text, fill=(180, 180, 255), font=font)

    # Timestamp
    ts = time.strftime("%H:%M:%S")
    try:
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    except Exception:
        font_sm = ImageFont.load_default()
    draw.text((10, height - 26), f"Stub output • {ts}", fill=(100, 100, 120), font=font_sm)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _generate_placeholder_video(output_path, width=512, height=512, duration=1, fps=8):
    """Generate a stub MP4 video using ffmpeg with lavfi color + text overlay."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=#28283A:size={width}x{height}:duration={duration}:rate={fps}",
        "-vf", "drawtext=text='DEV MODE':fontsize=36:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=10)
    except Exception:
        # Fallback: write a minimal file so something exists
        with open(output_path, "wb") as f:
            f.write(b"\x00" * 1024)


def _generate_preview_jpeg(width=256, height=256):
    """Generate a small JPEG for WS binary preview frames."""
    img = Image.new("RGB", (width, height), color=(40, 40, 50))
    draw = ImageDraw.Draw(img)
    draw.text((width // 4, height // 2 - 10), "PREVIEW", fill=(180, 180, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# ── Output file creation ──────────────────────────────────────

def _find_output_nodes(workflow):
    """Find output nodes and their output directories from the workflow."""
    outputs = []
    for nid, ndata in workflow.items():
        ct = ndata.get("class_type", "")
        inputs = ndata.get("inputs", {})
        prefix = inputs.get("filename_prefix", "")
        if ct == "SaveImage" and prefix:
            outputs.append({"node_id": nid, "type": "image", "prefix": prefix})
        elif ct == "PreviewImage" and prefix:
            outputs.append({"node_id": nid, "type": "preview", "prefix": prefix})
        elif ct == "VHS_VideoCombine" and prefix:
            outputs.append({"node_id": nid, "type": "video", "prefix": prefix})
    return outputs


def _create_output_files(workflow):
    """Create stub output files on disk matching what the runner expects.

    Returns a dict of {node_id: output_data} for the /history response.
    """
    output_nodes = _find_output_nodes(workflow)
    history_outputs = {}

    for out in output_nodes:
        prefix = out["prefix"]
        # prefix is like "20260326_120000_abc123/final" or "20260326_120000_abc123/preview"
        # ComfyUI writes to {output_directory}/{prefix}_00001.ext
        # The subfolder in history is the directory part of the prefix
        parts = prefix.rsplit("/", 1)
        if len(parts) == 2:
            subfolder = parts[0]
            base_name = parts[1]
        else:
            subfolder = ""
            base_name = parts[0]

        out_dir = os.path.join(OUTPUT_BASE, subfolder) if subfolder else OUTPUT_BASE
        os.makedirs(out_dir, exist_ok=True)

        if out["type"] == "video":
            filename = f"{base_name}_00001.mp4"
            filepath = os.path.join(out_dir, filename)
            _generate_placeholder_video(filepath)
            history_outputs[out["node_id"]] = {
                "gifs": [{"filename": filename, "subfolder": subfolder, "type": "output", "format": "video/h264-mp4"}]
            }
        elif out["type"] == "image":
            filename = f"{base_name}_00001_.png"
            filepath = os.path.join(out_dir, filename)
            with open(filepath, "wb") as f:
                f.write(_generate_placeholder_image())
            history_outputs[out["node_id"]] = {
                "images": [{"filename": filename, "subfolder": subfolder, "type": "output"}]
            }
        elif out["type"] == "preview":
            filename = f"{base_name}_00001_.png"
            filepath = os.path.join(out_dir, filename)
            with open(filepath, "wb") as f:
                f.write(_generate_placeholder_image(256, 256, "PREVIEW"))
            history_outputs[out["node_id"]] = {
                "images": [{"filename": filename, "subfolder": subfolder, "type": "output"}]
            }

    return history_outputs


# ── Handlers ──────────────────────────────────────────────────

async def system_stats(request):
    return web.json_response(FAKE_SYSTEM_STATS)


async def object_info(request):
    return web.json_response(FAKE_OBJECT_INFO)


async def prompt_handler(request):
    """Accept a workflow prompt and simulate queuing it."""
    data = await request.json()
    prompt_id = str(uuid.uuid4())
    client_id = data.get("client_id", "stub")
    workflow = data.get("prompt", {})

    active_prompts[prompt_id] = {
        "status": "queued",
        "client_id": client_id,
        "queued_at": time.time(),
        "workflow": workflow,
        "history_outputs": {},
    }

    # Simulate execution in background
    asyncio.create_task(_simulate_execution(prompt_id, client_id, workflow))

    return web.json_response({
        "prompt_id": prompt_id,
        "number": len(active_prompts),
        "node_errors": {},
    })


async def _simulate_execution(prompt_id, client_id, workflow):
    """Simulate a workflow execution with realistic progress messages.

    Sends the same WebSocket message sequence as real ComfyUI:
    execution_start → execution_cached → executing(node) → progress → executed → executing(None)
    """
    await asyncio.sleep(0.3)

    info = active_prompts.get(prompt_id)
    if not info:
        return

    # Create output files on disk
    history_outputs = _create_output_files(workflow)
    info["history_outputs"] = history_outputs
    info["status"] = "running"

    node_ids = list(workflow.keys())
    total_nodes = len(node_ids)

    # Track WS messages to send (the websocket_handler reads these)
    info["ws_queue"] = []

    # execution_start
    info["ws_queue"].append({
        "type": "execution_start",
        "data": {"prompt_id": prompt_id},
    })

    await asyncio.sleep(0.2)

    # Simulate each node executing
    for i, nid in enumerate(node_ids):
        ct = workflow[nid].get("class_type", "")

        # executing(node)
        info["ws_queue"].append({
            "type": "executing",
            "data": {"node": nid, "prompt_id": prompt_id},
        })

        # For sampler nodes, send progress steps
        if ct in ("KSampler", "KSamplerAdvanced"):
            total_steps = 20
            for step in range(1, total_steps + 1):
                info["ws_queue"].append({
                    "type": "progress",
                    "data": {"value": step, "max": total_steps, "prompt_id": prompt_id, "node": nid},
                })
                await asyncio.sleep(0.1)
        else:
            await asyncio.sleep(0.05)

        # If this node produced output, send executed message
        if nid in history_outputs:
            info["ws_queue"].append({
                "type": "executed",
                "data": {"node": nid, "output": history_outputs[nid], "prompt_id": prompt_id},
            })

    # executing(None) = completion signal
    info["ws_queue"].append({
        "type": "executing",
        "data": {"node": None, "prompt_id": prompt_id},
    })

    info["status"] = "completed"


async def upload_image(request):
    """Accept an image upload and save it to the ComfyUI input directory."""
    reader = await request.multipart()
    filename = None
    image_data = b""

    while True:
        field = await reader.next()
        if field is None:
            break
        if field.name == "image":
            filename = field.filename or f"stub_upload_{uuid.uuid4().hex[:8]}.png"
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                image_data += chunk

    if not filename:
        filename = f"stub_upload_{uuid.uuid4().hex[:8]}.png"

    # Save to ComfyUI input dir so LoadImage can find it
    input_dir = os.path.join(os.environ.get("COMFYUI_DIR", "/workspace/ComfyUI"), "input")
    os.makedirs(input_dir, exist_ok=True)
    with open(os.path.join(input_dir, filename), "wb") as f:
        if image_data:
            f.write(image_data)
        else:
            f.write(_generate_placeholder_image(512, 512, "UPLOADED"))

    return web.json_response({
        "name": filename,
        "subfolder": "",
        "type": "input",
    })


async def history(request):
    """Return history for a prompt_id with real output references."""
    prompt_id = request.match_info.get("prompt_id", "")
    info = active_prompts.get(prompt_id, {})

    if info.get("status") == "completed":
        outputs = info.get("history_outputs", {})
        return web.json_response({
            prompt_id: {
                "outputs": outputs,
                "status": {"completed": True, "messages": []},
            }
        })

    return web.json_response({})


async def queue(request):
    """Return fake queue status."""
    running = [pid for pid, p in active_prompts.items() if p.get("status") == "running"]
    pending = [pid for pid, p in active_prompts.items() if p.get("status") == "queued"]
    return web.json_response({
        "queue_running": [[0, pid, {}, {}] for pid in running],
        "queue_pending": [[0, pid, {}, {}] for pid in pending],
    })


async def view(request):
    """Return a placeholder image for /view requests."""
    return web.Response(
        body=_generate_placeholder_image(512, 512, "VIEW"),
        content_type="image/png",
    )


async def websocket_handler(request):
    """WebSocket that sends progress messages matching real ComfyUI protocol."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    client_id = request.query.get("clientId", "stub")
    preview_jpeg = _generate_preview_jpeg()

    try:
        while True:
            for pid, info in list(active_prompts.items()):
                if info.get("client_id") != client_id:
                    continue

                ws_queue = info.get("ws_queue", [])
                while ws_queue:
                    msg = ws_queue.pop(0)

                    # Send text message
                    await ws.send_json(msg)

                    # Send binary preview frame after progress messages
                    if msg["type"] == "progress":
                        # ComfyUI sends a 4-byte header before the JPEG data
                        header = (1).to_bytes(4, byteorder="big")
                        await ws.send_bytes(header + preview_jpeg)

                    # If this is the completion signal, clean up after a delay
                    if msg["type"] == "executing" and msg["data"].get("node") is None:
                        # Keep in active_prompts briefly so /history can serve it
                        await asyncio.sleep(0.5)
                        break

            await asyncio.sleep(0.05)
    except Exception:
        pass

    return ws


# ── App ───────────────────────────────────────────────────────

def create_app():
    app = web.Application()
    app.router.add_get("/system_stats", system_stats)
    app.router.add_get("/object_info", object_info)
    app.router.add_post("/prompt", prompt_handler)
    app.router.add_post("/upload/image", upload_image)
    app.router.add_get("/history/{prompt_id}", history)
    app.router.add_get("/history", lambda r: web.json_response({}))
    app.router.add_get("/queue", queue)
    app.router.add_get("/view", view)
    app.router.add_get("/ws", websocket_handler)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ComfyUI Stub Server")
    parser.add_argument("--port", type=int, default=8188)
    args = parser.parse_args()

    print(f"[stub] ComfyUI stub server starting on port {args.port}")
    print(f"[stub] Endpoints: /system_stats, /object_info, /prompt, /upload/image, /history, /queue, /view, /ws")
    print(f"[stub] Output base: {OUTPUT_BASE}")
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=args.port, print=None)
