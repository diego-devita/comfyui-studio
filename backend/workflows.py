"""ComfyUI Studio — Workflow loading, dynamic assembly, API-to-UI conversion."""

import copy
import json
import random
from pathlib import Path

import httpx
import yaml

from config import (
    COMFY_URL, COMFYUI_DIR, MODELS_BASE,
    WORKFLOWS_DIR, WORKFLOWS_DIR_DEFAULT,
)
from catalogs import _all_categories, _reload_models


# ── Workflow path resolution ────────────────────────────────────────────────


def _workflows_path(subpath: str) -> Path:
    """Resolve a workflow subpath: WORKFLOWS_DIR first, WORKFLOWS_DIR_DEFAULT fallback."""
    p = WORKFLOWS_DIR / subpath
    if p.exists():
        return p
    return WORKFLOWS_DIR_DEFAULT / subpath


def _make_input_filename(original_filename: str) -> str:
    """Generate a descriptive input filename: YYYYMMDD_HHMMSS_originalname.ext"""
    import re
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=1)))
    ts = now.strftime("%Y%m%d_%H%M%S")

    original = original_filename or "image.png"
    # Split name and extension
    if "." in original:
        name, ext = original.rsplit(".", 1)
    else:
        name, ext = original, "png"

    # Sanitize: keep only alphanumeric, dash, underscore
    name = re.sub(r'[^a-zA-Z0-9_\-]', '_', name)
    # Truncate long names
    if len(name) > 60:
        name = name[:60]
    ext = ext.lower()

    return f"{ts}_{name}.{ext}"


# ── Manifest / index loading ────────────────────────────────────────────────


def _load_manifest(workflow_id: str) -> dict:
    """Load manifest.yaml for a workflow by its ID."""
    p = _workflows_path(f"{workflow_id}/manifest.yaml")
    if not p.exists():
        return None
    with open(p) as f:
        return yaml.safe_load(f)


def _load_workflow_json(workflow_id: str) -> dict:
    """Load workflow.json for a workflow by its ID."""
    p = _workflows_path(f"{workflow_id}/workflow.json")
    if not p.exists():
        return None
    return json.loads(p.read_text())


def _load_workflows_index_raw() -> dict:
    """Load the full workflows index.json including version/date."""
    p = _workflows_path("index.json")
    if not p.exists():
        return {"version": 0, "date": "", "workflows": []}
    return json.loads(p.read_text())


def _load_workflows_index() -> list:
    """Load just the workflows list from index.json."""
    return _load_workflows_index_raw().get("workflows", [])


# ── Readiness checks ────────────────────────────────────────────────────────


async def _get_installed_nodes() -> set:
    """Query ComfyUI /object_info to get all installed node class_types."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{COMFY_URL}/object_info")
            r.raise_for_status()
            return set(r.json().keys())
    except Exception:
        return set()


def _check_model_exists(filename: str) -> bool:
    """Check if a model file exists anywhere under MODELS_BASE."""
    # First try to find dest from models.json / loras.json
    _reload_models()
    for cat in _all_categories():
        for m in cat.get("models", []):
            if m["file"] == filename:
                dest_path = Path(MODELS_BASE) / m["dest"] / m["file"]
                return dest_path.exists()
    # Fallback: search recursively
    for p in Path(MODELS_BASE).rglob(filename):
        if p.is_file():
            return True
    return False


# ── Dynamic workflow assembly ────────────────────────────────────────────────


def _assemble_dynamic_workflow(manifest: dict, params: dict) -> dict:
    """Assemble a dynamic workflow from block templates based on manifest and runtime params."""
    wf_id = manifest["id"]
    blocks_subdir = manifest.get("blocks_dir", "blocks")
    # Check /workspace first, then /app
    blocks_dir = WORKFLOWS_DIR / wf_id / blocks_subdir
    if not blocks_dir.exists():
        blocks_dir = WORKFLOWS_DIR_DEFAULT / wf_id / blocks_subdir
    if not blocks_dir.exists():
        raise FileNotFoundError(f"Blocks directory not found: tried {WORKFLOWS_DIR / wf_id / blocks_subdir} and {WORKFLOWS_DIR_DEFAULT / wf_id / blocks_subdir}. Run Check for Updates to download workflow blocks.")
    defaults = manifest.get("defaults", {})

    # Load block templates
    def load_block(filename):
        return json.loads((blocks_dir / filename).read_text())

    pipeline = manifest["pipeline"]
    block_templates = {}
    for stage in pipeline:
        block_templates[stage["block"]] = load_block(stage["file"])

    # Scene count comes from the scenes list itself
    scenes = params.get("scenes", [])
    if not scenes:
        scenes = [{"prompt": "", "duration": 5}]
    num_scenes = len(scenes)

    neg_prompt = defaults.get("negative_prompt", "")
    lora_accelerator = defaults.get("lora_accelerator", "")
    lora_acc_str_high = defaults.get("lora_accelerator_strength_high", 3)
    lora_acc_str_low = defaults.get("lora_accelerator_strength_low", 1.5)
    steps = defaults.get("steps", 6)
    split_step = defaults.get("split_step", 3)

    # Build LoRA inputs from picker
    raw_loras = params.get("loras", [])
    # Normalize: can be list of strings (pair_ids) or list of {pair_id, strength}
    selected_loras = []
    for item in raw_loras:
        if isinstance(item, str):
            selected_loras.append({"pair_id": item, "strength_high": 1.0, "strength_low": 1.0})
        elif isinstance(item, dict):
            # Support both single strength and separate H/L
            sh = float(item.get("strength_high", item.get("strength", 1.0)))
            sl = float(item.get("strength_low", item.get("strength", 1.0)))
            selected_loras.append({"pair_id": item.get("pair_id", ""), "strength_high": sh, "strength_low": sl})

    # Resolve pair_ids to high/low files from models catalog
    _reload_models()
    lora_file_map = {}  # pair_id -> {high: file, low: file, both: file}
    for cat in _all_categories():
        for m in cat.get("models", []):
            pid = m.get("pair_id")
            if pid:
                role = m.get("pair_role", "both")
                if pid not in lora_file_map:
                    lora_file_map[pid] = {}
                lora_file_map[pid][role] = m["file"]

    # Collected workflow nodes (global ID -> node)
    workflow = {}
    node_counter = [100]  # mutable counter

    def next_id():
        node_counter[0] += 1
        return str(node_counter[0])

    # Track block instance exports: block_instance_name -> {export_name: [global_id, output_idx]}
    block_exports = {}

    def instantiate_block(block_name, template, variables, imports_map):
        """Instantiate a block: assign global IDs, resolve imports and variables."""
        local_to_global = {}
        instance_name = block_name

        # Assign global IDs to all nodes
        for local_id in template["nodes"]:
            local_to_global[local_id] = next_id()

        # Process each node
        for local_id, node_def in template["nodes"].items():
            global_id = local_to_global[local_id]
            node = {
                "class_type": node_def["class_type"],
                "_meta": dict(node_def.get("_meta", {})),
            }

            # Resolve _meta title variables
            title = node["_meta"].get("title", "")
            for vk, vv in variables.items():
                title = title.replace("{{" + vk + "}}", str(vv))
            node["_meta"]["title"] = title

            # Process inputs
            inputs = {}
            for key, val in node_def.get("inputs", {}).items():
                # Skip template LoRA slot placeholders
                if key.startswith("{{") and key.endswith("}}"):
                    continue
                resolved = _resolve_value(val, local_to_global, imports_map, variables)
                inputs[key] = resolved
            node["inputs"] = inputs
            workflow[global_id] = node

        # Record exports
        exports = {}
        for exp_name, exp_def in template.get("exports", {}).items():
            exp_node = exp_def["node"]
            exp_output = exp_def["output"]
            if exp_node in local_to_global:
                exports[exp_name] = [local_to_global[exp_node], exp_output]
        block_exports[instance_name] = exports

        return exports

    def _resolve_value(val, local_to_global, imports_map, variables):
        """Resolve a value: local refs, import refs, variable substitutions."""
        if isinstance(val, list) and len(val) == 2:
            ref_id, ref_out = val
            if isinstance(ref_id, str):
                if ref_id in local_to_global:
                    return [local_to_global[ref_id], ref_out]
                # Might be a global reference already
                return val
            return val
        if isinstance(val, str):
            if val.startswith("{{") and val.endswith("}}"):
                var_name = val[2:-2]
                if var_name in imports_map:
                    return imports_map[var_name]
                if var_name in variables:
                    return variables[var_name]
                return val
            # Replace inline {{var}} in strings
            for vk, vv in variables.items():
                val = val.replace("{{" + vk + "}}", str(vv))
            return val
        if isinstance(val, dict):
            resolved = {}
            for k, v in val.items():
                rk = k
                for vk, vv in variables.items():
                    rk = rk.replace("{{" + vk + "}}", str(vv))
                resolved[rk] = _resolve_value(v, local_to_global, imports_map, variables)
            return resolved
        return val

    # --- Instantiate setup block ---
    setup_vars = {
        "steps": steps,
        "split_step": split_step,
        "input_image": params.get("_uploaded_image", "input.png"),
        "lora_accelerator": lora_accelerator,
        "lora_accelerator_strength_high": lora_acc_str_high,
        "lora_accelerator_strength_low": lora_acc_str_low,
        "svi_pro_high": "SVI_v2_PRO_Wan2.2-I2V-A14B_HIGH_lora_rank_128_fp16.safetensors",
        "svi_pro_low": "SVI_v2_PRO_Wan2.2-I2V-A14B_LOW_lora_rank_128_fp16.safetensors",
    }
    setup_tmpl = block_templates["setup"]

    # Inject user-selected LoRAs into setup template before instantiation
    setup_tmpl = copy.deepcopy(setup_tmpl)
    lora_idx = 3  # lora_1 = accelerator, lora_2 = SVI Pro (both hardcoded)
    for lora_sel in selected_loras:
        pid = lora_sel["pair_id"]
        str_h = lora_sel["strength_high"]
        str_l = lora_sel["strength_low"]
        pair = lora_file_map.get(pid, {})
        high_file = pair.get("high", pair.get("both", ""))
        low_file = pair.get("low", pair.get("both", ""))
        if high_file:
            slot = f"lora_{lora_idx}"
            setup_tmpl["nodes"]["lora_high"]["inputs"][slot] = {"on": True, "lora": high_file, "strength": str_h}
            setup_tmpl["nodes"]["lora_low"]["inputs"][slot] = {"on": True, "lora": low_file or high_file, "strength": str_l}
            lora_idx += 1

    # Remove template placeholders
    for node_key in ["lora_high", "lora_low"]:
        inputs = setup_tmpl["nodes"][node_key]["inputs"]
        for k in list(inputs.keys()):
            if k.startswith("{{"):
                del inputs[k]

    setup_exports = instantiate_block("setup", setup_tmpl, setup_vars, {})

    # --- Instantiate scenes ---
    prev_scene_exports = None
    last_scene_exports = None
    resolved_seeds = {}

    for i in range(num_scenes):
        scene = scenes[i] if i < len(scenes) else {"prompt": "", "duration": 5}
        duration_sec = int(scene.get("duration", 5))
        duration_frames = duration_sec * 16 + 1
        scene_seed = int(scene.get("seed", params.get("seed", -1)))
        if scene_seed == -1:
            scene_seed = random.randint(0, 2**53)
        resolved_seeds[f"scene_{i+1}"] = scene_seed

        scene_vars = {
            "prompt": scene.get("prompt", ""),
            "negative_prompt": neg_prompt,
            "duration_frames": duration_frames,
            "seed": scene_seed,
            "scene_num": str(i + 1),
        }

        # Build imports map from setup exports
        imports_map = {
            "model_high": setup_exports["model_high"],
            "model_low": setup_exports["model_low"],
            "clip": setup_exports["clip"],
            "vae": setup_exports["vae"],
            "sampler": setup_exports["sampler"],
            "sigmas_high": setup_exports["sigmas_high"],
            "sigmas_low": setup_exports["sigmas_low"],
            "anchor_samples": setup_exports["anchor_samples"],
        }

        if i == 0:
            tmpl = block_templates["scene_first"]
            scene_exports = instantiate_block(f"scene_{i}", tmpl, scene_vars, imports_map)
        else:
            tmpl = block_templates["scene_extend"]
            imports_map["prev_samples"] = prev_scene_exports["samples"]
            imports_map["prev_images"] = prev_scene_exports["images"]
            scene_exports = instantiate_block(f"scene_{i}", tmpl, scene_vars, imports_map)

        prev_scene_exports = scene_exports
        last_scene_exports = scene_exports

    # --- Instantiate output block ---
    output_tmpl = block_templates["output"]
    # For single scene, images come from vae_decode; for multi, from last overlap
    final_images = last_scene_exports["images"]
    output_imports = {"final_images": final_images}
    instantiate_block("output", output_tmpl, {}, output_imports)

    return workflow, resolved_seeds


def _assemble_faceid_batch_workflow(manifest: dict, params: dict) -> tuple:
    """Assemble a FaceID workflow: checkpoint + clip_skip + loras + InsightFace + FaceID + generate."""
    wf_id = manifest["id"]
    blocks_subdir = manifest.get("blocks_dir", "blocks")
    blocks_dir = WORKFLOWS_DIR / wf_id / blocks_subdir
    if not blocks_dir.exists():
        blocks_dir = WORKFLOWS_DIR_DEFAULT / wf_id / blocks_subdir
    if not blocks_dir.exists():
        raise FileNotFoundError(f"Blocks directory not found for {wf_id}")

    def load_block(filename):
        return json.loads((blocks_dir / filename).read_text())

    workflow = {}
    node_counter = [100]

    def next_id():
        node_counter[0] += 1
        return str(node_counter[0])

    def resolve_val(val, local_map, imports, variables):
        if isinstance(val, list) and len(val) == 2:
            ref_id, ref_out = val
            if isinstance(ref_id, str) and ref_id in local_map:
                return [local_map[ref_id], ref_out]
            return val
        if isinstance(val, str):
            if val.startswith("{{") and val.endswith("}}"):
                vn = val[2:-2]
                if vn in imports:
                    return imports[vn]
                if vn in variables:
                    return variables[vn]
                return val
            for vk, vv in variables.items():
                val = val.replace("{{" + vk + "}}", str(vv))
            return val
        if isinstance(val, dict):
            return {k: resolve_val(v, local_map, imports, variables) for k, v in val.items()}
        return val

    def instantiate(name, template, variables, imports):
        local_to_global = {lid: next_id() for lid in template["nodes"]}
        for lid, ndef in template["nodes"].items():
            gid = local_to_global[lid]
            node = {"class_type": ndef["class_type"], "_meta": dict(ndef.get("_meta", {}))}
            title = node["_meta"].get("title", "")
            for vk, vv in variables.items():
                title = title.replace("{{" + vk + "}}", str(vv))
            node["_meta"]["title"] = title
            inputs_resolved = {}
            for k, v in ndef.get("inputs", {}).items():
                if k.startswith("{{"):
                    continue
                inputs_resolved[k] = resolve_val(v, local_to_global, imports, variables)
            node["inputs"] = inputs_resolved
            workflow[gid] = node
        exports = {}
        for en, ed in template.get("exports", {}).items():
            if ed["node"] in local_to_global:
                exports[en] = [local_to_global[ed["node"]], ed["output"]]
        return exports

    # Extract params
    checkpoint = params.get("checkpoint", "")
    positive_prompt = params.get("positive_prompt", "")
    negative_prompt = params.get("negative_prompt", "")
    clip_skip = int(params.get("clip_skip", -2))
    faceid_preset = params.get("faceid_preset", "FACEID PLUS V2")
    faceid_lora_strength = float(params.get("faceid_lora_strength", 0.6))
    faceid_weight = float(params.get("faceid_weight", 0.85))
    faceid_v2_weight = float(params.get("faceid_v2_weight", 0.85))
    width = int(params.get("width", 832))
    height = int(params.get("height", 1216))
    batch_size = int(params.get("batch_size", 1))
    steps = int(params.get("steps", 19))
    cfg = float(params.get("cfg", 4.0))
    sampler_name = params.get("sampler_name", "euler_ancestral")
    scheduler = params.get("scheduler", "normal")
    denoise = float(params.get("denoise", 1.0))
    seed = int(params.get("seed", -1))
    if seed == -1:
        seed = random.randint(0, 2**53)
    output_dir = params.get("_output_dir", "faceid-batch")
    uploaded_image = params.get("_uploaded_image", "input.png")

    # --- Setup block (checkpoint + clip_skip + prompts) ---
    setup_tmpl = copy.deepcopy(load_block("setup.json"))

    # Inject user LoRAs (before FaceID modifies the model)
    raw_loras = params.get("loras", [])
    if raw_loras:
        _reload_models()
        prev_model = ["checkpoint", 0]
        prev_clip = ["clip_skip", 0]
        lora_nodes = {}
        for i, lora in enumerate(raw_loras):
            lora_file = lora.get("file", "") if isinstance(lora, dict) else lora
            strength = float(lora.get("strength", 1.0)) if isinstance(lora, dict) else 1.0
            if not lora_file:
                continue
            lora_id = f"lora_{i}"
            lora_nodes[lora_id] = {
                "inputs": {
                    "lora_name": lora_file,
                    "strength_model": strength,
                    "strength_clip": strength,
                    "model": prev_model,
                    "clip": prev_clip,
                },
                "class_type": "LoraLoader",
                "_meta": {"title": f"LoRA: {lora_file[:30]}"}
            }
            prev_model = [lora_id, 0]
            prev_clip = [lora_id, 1]

        if lora_nodes:
            setup_tmpl["nodes"].update(lora_nodes)
            setup_tmpl["nodes"]["pos_prompt"]["inputs"]["clip"] = prev_clip
            setup_tmpl["nodes"]["neg_prompt"]["inputs"]["clip"] = prev_clip
            last_lora = list(lora_nodes.keys())[-1]
            setup_tmpl["exports"]["model"] = {"node": last_lora, "output": 0}
            setup_tmpl["exports"]["clip"] = {"node": last_lora, "output": 1}

    setup_vars = {
        "checkpoint": checkpoint,
        "clip_skip": clip_skip,
        "positive_prompt": positive_prompt,
        "negative_prompt": negative_prompt,
    }
    setup_exports = instantiate("setup", setup_tmpl, setup_vars, {})

    # --- LoadImage (face reference) ---
    load_img_id = next_id()
    workflow[load_img_id] = {
        "inputs": {"image": uploaded_image},
        "class_type": "LoadImage",
        "_meta": {"title": "Load Face Reference"}
    }

    # --- InsightFaceLoader ---
    insightface_id = next_id()
    workflow[insightface_id] = {
        "inputs": {
            "provider": "CUDA",
            "model_name": "buffalo_l",
        },
        "class_type": "IPAdapterInsightFaceLoader",
        "_meta": {"title": "InsightFace Loader"}
    }

    # --- IPAdapterUnifiedLoaderFaceID (loads FaceID model + applies LoRA) ---
    faceid_loader_id = next_id()
    workflow[faceid_loader_id] = {
        "inputs": {
            "model": setup_exports["model"],
            "preset": faceid_preset,
            "lora_strength": faceid_lora_strength,
            "provider": "CUDA",
        },
        "class_type": "IPAdapterUnifiedLoaderFaceID",
        "_meta": {"title": "FaceID Loader"}
    }

    # --- IPAdapterFaceID (apply face reference) ---
    faceid_apply_id = next_id()
    workflow[faceid_apply_id] = {
        "inputs": {
            "model": [faceid_loader_id, 0],
            "ipadapter": [faceid_loader_id, 1],
            "image": [load_img_id, 0],
            "weight": faceid_weight,
            "weight_faceidv2": faceid_v2_weight,
            "weight_type": "linear",
            "combine_embeds": "concat",
            "start_at": 0.0,
            "end_at": 1.0,
            "embeds_scaling": "V only",
            "insightface": [insightface_id, 0],
        },
        "class_type": "IPAdapterFaceID",
        "_meta": {"title": "FaceID Apply"}
    }
    faceid_model_ref = [faceid_apply_id, 0]

    # --- Generate block (EmptyLatentImage + KSampler + VAEDecode + SaveImage) ---
    gen_tmpl = load_block("generate.json")
    gen_vars = {
        "width": width, "height": height, "batch_size": batch_size,
        "seed": seed, "steps": steps, "cfg": cfg,
        "sampler_name": sampler_name, "scheduler": scheduler,
        "denoise": denoise, "output_prefix": output_dir,
    }
    gen_imports = {
        "model": faceid_model_ref,
        "positive": setup_exports["positive"],
        "negative": setup_exports["negative"],
        "vae": setup_exports["vae"],
    }
    instantiate("gen", gen_tmpl, gen_vars, gen_imports)

    return workflow, {"seed": seed}


def _assemble_ipa_batch_workflow(manifest: dict, params: dict) -> tuple:
    """Assemble an IP-Adapter workflow: checkpoint + clip_skip + loras + IPA + generate."""
    wf_id = manifest["id"]
    blocks_subdir = manifest.get("blocks_dir", "blocks")
    blocks_dir = WORKFLOWS_DIR / wf_id / blocks_subdir
    if not blocks_dir.exists():
        blocks_dir = WORKFLOWS_DIR_DEFAULT / wf_id / blocks_subdir
    if not blocks_dir.exists():
        raise FileNotFoundError(f"Blocks directory not found for {wf_id}")

    def load_block(filename):
        return json.loads((blocks_dir / filename).read_text())

    workflow = {}
    node_counter = [100]

    def next_id():
        node_counter[0] += 1
        return str(node_counter[0])

    def resolve_val(val, local_map, imports, variables):
        if isinstance(val, list) and len(val) == 2:
            ref_id, ref_out = val
            if isinstance(ref_id, str) and ref_id in local_map:
                return [local_map[ref_id], ref_out]
            return val
        if isinstance(val, str):
            if val.startswith("{{") and val.endswith("}}"):
                vn = val[2:-2]
                if vn in imports:
                    return imports[vn]
                if vn in variables:
                    return variables[vn]
                return val
            for vk, vv in variables.items():
                val = val.replace("{{" + vk + "}}", str(vv))
            return val
        if isinstance(val, dict):
            return {k: resolve_val(v, local_map, imports, variables) for k, v in val.items()}
        return val

    def instantiate(name, template, variables, imports):
        local_to_global = {lid: next_id() for lid in template["nodes"]}
        for lid, ndef in template["nodes"].items():
            gid = local_to_global[lid]
            node = {"class_type": ndef["class_type"], "_meta": dict(ndef.get("_meta", {}))}
            title = node["_meta"].get("title", "")
            for vk, vv in variables.items():
                title = title.replace("{{" + vk + "}}", str(vv))
            node["_meta"]["title"] = title
            inputs_resolved = {}
            for k, v in ndef.get("inputs", {}).items():
                if k.startswith("{{"):
                    continue
                inputs_resolved[k] = resolve_val(v, local_to_global, imports, variables)
            node["inputs"] = inputs_resolved
            workflow[gid] = node
        exports = {}
        for en, ed in template.get("exports", {}).items():
            if ed["node"] in local_to_global:
                exports[en] = [local_to_global[ed["node"]], ed["output"]]
        return exports

    # Extract params
    checkpoint = params.get("checkpoint", "")
    positive_prompt = params.get("positive_prompt", "")
    negative_prompt = params.get("negative_prompt", "")
    clip_skip = int(params.get("clip_skip", -2))
    ipa_preset = params.get("ipa_preset", "PLUS FACE (portraits)")
    ipa_weight = float(params.get("ipa_weight", 0.8))
    ipa_start = float(params.get("ipa_start", 0.0))
    ipa_end = float(params.get("ipa_end", 1.0))
    width = int(params.get("width", 832))
    height = int(params.get("height", 1216))
    batch_size = int(params.get("batch_size", 1))
    steps = int(params.get("steps", 19))
    cfg = float(params.get("cfg", 4.0))
    sampler_name = params.get("sampler_name", "euler_ancestral")
    scheduler = params.get("scheduler", "normal")
    denoise = float(params.get("denoise", 1.0))
    seed = int(params.get("seed", -1))
    if seed == -1:
        seed = random.randint(0, 2**53)
    output_dir = params.get("_output_dir", "ipa-batch")
    uploaded_image = params.get("_uploaded_image", "input.png")

    # --- Setup block (checkpoint + clip_skip + prompts) ---
    setup_tmpl = copy.deepcopy(load_block("setup.json"))

    # Inject LoRAs (chain after checkpoint, before IPA)
    raw_loras = params.get("loras", [])
    if raw_loras:
        _reload_models()
        prev_model = ["checkpoint", 0]
        prev_clip = ["clip_skip", 0]
        lora_nodes = {}
        for i, lora in enumerate(raw_loras):
            lora_file = lora.get("file", "") if isinstance(lora, dict) else lora
            strength = float(lora.get("strength", 1.0)) if isinstance(lora, dict) else 1.0
            if not lora_file:
                continue
            lora_id = f"lora_{i}"
            lora_nodes[lora_id] = {
                "inputs": {
                    "lora_name": lora_file,
                    "strength_model": strength,
                    "strength_clip": strength,
                    "model": prev_model,
                    "clip": prev_clip,
                },
                "class_type": "LoraLoader",
                "_meta": {"title": f"LoRA: {lora_file[:30]}"}
            }
            prev_model = [lora_id, 0]
            prev_clip = [lora_id, 1]

        if lora_nodes:
            setup_tmpl["nodes"].update(lora_nodes)
            setup_tmpl["nodes"]["pos_prompt"]["inputs"]["clip"] = prev_clip
            setup_tmpl["nodes"]["neg_prompt"]["inputs"]["clip"] = prev_clip
            last_lora = list(lora_nodes.keys())[-1]
            setup_tmpl["exports"]["model"] = {"node": last_lora, "output": 0}
            setup_tmpl["exports"]["clip"] = {"node": last_lora, "output": 1}

    setup_vars = {
        "checkpoint": checkpoint,
        "clip_skip": clip_skip,
        "positive_prompt": positive_prompt,
        "negative_prompt": negative_prompt,
    }
    setup_exports = instantiate("setup", setup_tmpl, setup_vars, {})

    # --- LoadImage (reference for IP-Adapter) ---
    load_img_id = next_id()
    workflow[load_img_id] = {
        "inputs": {"image": uploaded_image},
        "class_type": "LoadImage",
        "_meta": {"title": "Load Reference Image"}
    }

    # --- IPAdapterUnifiedLoader (auto-loads the right IPA model) ---
    ipa_loader_id = next_id()
    workflow[ipa_loader_id] = {
        "inputs": {
            "model": setup_exports["model"],
            "preset": ipa_preset,
        },
        "class_type": "IPAdapterUnifiedLoader",
        "_meta": {"title": "IP-Adapter Loader"}
    }

    # --- IPAdapterAdvanced (apply reference image) ---
    ipa_apply_id = next_id()
    workflow[ipa_apply_id] = {
        "inputs": {
            "model": [ipa_loader_id, 0],
            "ipadapter": [ipa_loader_id, 1],
            "image": [load_img_id, 0],
            "weight": ipa_weight,
            "weight_type": "linear",
            "combine_embeds": "concat",
            "start_at": ipa_start,
            "end_at": ipa_end,
            "embeds_scaling": "V only",
        },
        "class_type": "IPAdapterAdvanced",
        "_meta": {"title": "IP-Adapter Apply"}
    }
    # The IPA-modified model replaces setup model for generation
    ipa_model_ref = [ipa_apply_id, 0]

    # --- Generate block (EmptyLatentImage + KSampler + VAEDecode + SaveImage) ---
    gen_tmpl = load_block("generate.json")
    gen_vars = {
        "width": width, "height": height, "batch_size": batch_size,
        "seed": seed, "steps": steps, "cfg": cfg,
        "sampler_name": sampler_name, "scheduler": scheduler,
        "denoise": denoise, "output_prefix": output_dir,
    }
    gen_imports = {
        "model": ipa_model_ref,
        "positive": setup_exports["positive"],
        "negative": setup_exports["negative"],
        "vae": setup_exports["vae"],
    }
    instantiate("gen", gen_tmpl, gen_vars, gen_imports)

    return workflow, {"seed": seed}


def _assemble_i2i_batch_workflow(manifest: dict, params: dict) -> tuple:
    """Assemble an img2img batch workflow: checkpoint + clip_skip + loras + encode input + N variations."""
    wf_id = manifest["id"]
    blocks_subdir = manifest.get("blocks_dir", "blocks")
    blocks_dir = WORKFLOWS_DIR / wf_id / blocks_subdir
    if not blocks_dir.exists():
        blocks_dir = WORKFLOWS_DIR_DEFAULT / wf_id / blocks_subdir
    if not blocks_dir.exists():
        raise FileNotFoundError(f"Blocks directory not found for {wf_id}")

    def load_block(filename):
        return json.loads((blocks_dir / filename).read_text())

    workflow = {}
    node_counter = [100]

    def next_id():
        node_counter[0] += 1
        return str(node_counter[0])

    def resolve_val(val, local_map, imports, variables):
        if isinstance(val, list) and len(val) == 2:
            ref_id, ref_out = val
            if isinstance(ref_id, str) and ref_id in local_map:
                return [local_map[ref_id], ref_out]
            return val
        if isinstance(val, str):
            if val.startswith("{{") and val.endswith("}}"):
                vn = val[2:-2]
                if vn in imports:
                    return imports[vn]
                if vn in variables:
                    return variables[vn]
                return val
            for vk, vv in variables.items():
                val = val.replace("{{" + vk + "}}", str(vv))
            return val
        if isinstance(val, dict):
            return {k: resolve_val(v, local_map, imports, variables) for k, v in val.items()}
        return val

    def instantiate(name, template, variables, imports):
        local_to_global = {lid: next_id() for lid in template["nodes"]}
        for lid, ndef in template["nodes"].items():
            gid = local_to_global[lid]
            node = {"class_type": ndef["class_type"], "_meta": dict(ndef.get("_meta", {}))}
            title = node["_meta"].get("title", "")
            for vk, vv in variables.items():
                title = title.replace("{{" + vk + "}}", str(vv))
            node["_meta"]["title"] = title
            inputs_resolved = {}
            for k, v in ndef.get("inputs", {}).items():
                if k.startswith("{{"):
                    continue
                inputs_resolved[k] = resolve_val(v, local_to_global, imports, variables)
            node["inputs"] = inputs_resolved
            workflow[gid] = node
        exports = {}
        for en, ed in template.get("exports", {}).items():
            if ed["node"] in local_to_global:
                exports[en] = [local_to_global[ed["node"]], ed["output"]]
        return exports

    # Extract params
    checkpoint = params.get("checkpoint", "")
    positive_prompt = params.get("positive_prompt", "")
    negative_prompt = params.get("negative_prompt", "")
    clip_skip = int(params.get("clip_skip", -2))
    steps = int(params.get("steps", 19))
    cfg = float(params.get("cfg", 4.0))
    sampler_name = params.get("sampler_name", "euler_ancestral")
    scheduler = params.get("scheduler", "normal")
    denoise = float(params.get("denoise", 0.5))
    batch_count = int(params.get("batch_count", 1))
    output_dir = params.get("_output_dir", "i2i-batch")
    uploaded_image = params.get("_uploaded_image", "input.png")

    # --- Setup block (checkpoint + clip_skip + prompts) ---
    setup_tmpl = copy.deepcopy(load_block("setup.json"))

    # Inject LoRAs
    raw_loras = params.get("loras", [])
    if raw_loras:
        _reload_models()
        prev_model = ["checkpoint", 0]
        prev_clip = ["clip_skip", 0]
        lora_nodes = {}
        for i, lora in enumerate(raw_loras):
            lora_file = lora.get("file", "") if isinstance(lora, dict) else lora
            strength = float(lora.get("strength", 1.0)) if isinstance(lora, dict) else 1.0
            if not lora_file:
                continue
            lora_id = f"lora_{i}"
            lora_nodes[lora_id] = {
                "inputs": {
                    "lora_name": lora_file,
                    "strength_model": strength,
                    "strength_clip": strength,
                    "model": prev_model,
                    "clip": prev_clip,
                },
                "class_type": "LoraLoader",
                "_meta": {"title": f"LoRA: {lora_file[:30]}"}
            }
            prev_model = [lora_id, 0]
            prev_clip = [lora_id, 1]

        if lora_nodes:
            setup_tmpl["nodes"].update(lora_nodes)
            setup_tmpl["nodes"]["pos_prompt"]["inputs"]["clip"] = prev_clip
            setup_tmpl["nodes"]["neg_prompt"]["inputs"]["clip"] = prev_clip
            last_lora = list(lora_nodes.keys())[-1]
            setup_tmpl["exports"]["model"] = {"node": last_lora, "output": 0}
            setup_tmpl["exports"]["clip"] = {"node": last_lora, "output": 1}

    setup_vars = {
        "checkpoint": checkpoint,
        "clip_skip": clip_skip,
        "positive_prompt": positive_prompt,
        "negative_prompt": negative_prompt,
    }
    setup_exports = instantiate("setup", setup_tmpl, setup_vars, {})

    # --- LoadImage + VAEEncode (injected directly) ---
    load_img_id = next_id()
    workflow[load_img_id] = {
        "inputs": {"image": uploaded_image},
        "class_type": "LoadImage",
        "_meta": {"title": "Load Input Image"}
    }
    vae_enc_id = next_id()
    workflow[vae_enc_id] = {
        "inputs": {
            "pixels": [load_img_id, 0],
            "vae": setup_exports["vae"],
        },
        "class_type": "VAEEncode",
        "_meta": {"title": "VAE Encode Input"}
    }
    latent_ref = [vae_enc_id, 0]

    # --- Generate blocks (batch variations with different seeds) ---
    resolved_seeds = {}
    gen_tmpl = load_block("generate.json")

    for i in range(batch_count):
        seed = int(params.get("seed", -1))
        if seed == -1:
            seed = random.randint(0, 2**53)
        elif batch_count > 1 and i > 0:
            seed = seed + i
        resolved_seeds[f"batch_{i+1}"] = seed

        gen_vars = {
            "seed": seed, "steps": steps, "cfg": cfg,
            "sampler_name": sampler_name, "scheduler": scheduler,
            "denoise": denoise, "output_prefix": output_dir,
            "batch_num": str(i + 1),
        }
        gen_imports = {
            "model": setup_exports["model"],
            "positive": setup_exports["positive"],
            "negative": setup_exports["negative"],
            "vae": setup_exports["vae"],
            "latent_image": latent_ref,
        }
        instantiate(f"gen_{i}", gen_tmpl, gen_vars, gen_imports)

    return workflow, resolved_seeds


def _assemble_t2i_batch_workflow(manifest: dict, params: dict) -> tuple:
    """Assemble a simple T2I batch workflow: checkpoint + clip_skip + loras + generate."""
    wf_id = manifest["id"]
    blocks_subdir = manifest.get("blocks_dir", "blocks")
    blocks_dir = WORKFLOWS_DIR / wf_id / blocks_subdir
    if not blocks_dir.exists():
        blocks_dir = WORKFLOWS_DIR_DEFAULT / wf_id / blocks_subdir
    if not blocks_dir.exists():
        raise FileNotFoundError(f"Blocks directory not found for {wf_id}")

    def load_block(filename):
        return json.loads((blocks_dir / filename).read_text())

    workflow = {}
    node_counter = [100]

    def next_id():
        node_counter[0] += 1
        return str(node_counter[0])

    def resolve_val(val, local_map, imports, variables):
        if isinstance(val, list) and len(val) == 2:
            ref_id, ref_out = val
            if isinstance(ref_id, str) and ref_id in local_map:
                return [local_map[ref_id], ref_out]
            return val
        if isinstance(val, str):
            if val.startswith("{{") and val.endswith("}}"):
                vn = val[2:-2]
                if vn in imports:
                    return imports[vn]
                if vn in variables:
                    return variables[vn]
                return val
            for vk, vv in variables.items():
                val = val.replace("{{" + vk + "}}", str(vv))
            return val
        if isinstance(val, dict):
            return {k: resolve_val(v, local_map, imports, variables) for k, v in val.items()}
        return val

    def instantiate(name, template, variables, imports):
        local_to_global = {lid: next_id() for lid in template["nodes"]}
        for lid, ndef in template["nodes"].items():
            gid = local_to_global[lid]
            node = {"class_type": ndef["class_type"], "_meta": dict(ndef.get("_meta", {}))}
            title = node["_meta"].get("title", "")
            for vk, vv in variables.items():
                title = title.replace("{{" + vk + "}}", str(vv))
            node["_meta"]["title"] = title
            inputs_resolved = {}
            for k, v in ndef.get("inputs", {}).items():
                if k.startswith("{{"):
                    continue
                inputs_resolved[k] = resolve_val(v, local_to_global, imports, variables)
            node["inputs"] = inputs_resolved
            workflow[gid] = node
        exports = {}
        for en, ed in template.get("exports", {}).items():
            if ed["node"] in local_to_global:
                exports[en] = [local_to_global[ed["node"]], ed["output"]]
        return exports

    # Extract params
    checkpoint = params.get("checkpoint", "")
    positive_prompt = params.get("positive_prompt", "")
    negative_prompt = params.get("negative_prompt", "")
    clip_skip = int(params.get("clip_skip", -2))
    width = int(params.get("width", 832))
    height = int(params.get("height", 1216))
    batch_size = int(params.get("batch_size", 1))
    steps = int(params.get("steps", 19))
    cfg = float(params.get("cfg", 4.0))
    sampler_name = params.get("sampler_name", "euler_ancestral")
    scheduler = params.get("scheduler", "normal")
    denoise = float(params.get("denoise", 1.0))
    seed = int(params.get("seed", -1))
    if seed == -1:
        seed = random.randint(0, 2**53)
    output_dir = params.get("_output_dir", "t2i-batch")

    # --- Setup block ---
    setup_tmpl = copy.deepcopy(load_block("setup.json"))

    # Inject LoRAs
    raw_loras = params.get("loras", [])
    if raw_loras:
        _reload_models()
        prev_model = ["checkpoint", 0]
        prev_clip = ["clip_skip", 0]
        lora_nodes = {}
        for i, lora in enumerate(raw_loras):
            lora_file = lora.get("file", "") if isinstance(lora, dict) else lora
            strength = float(lora.get("strength", 1.0)) if isinstance(lora, dict) else 1.0
            if not lora_file:
                continue
            lora_id = f"lora_{i}"
            lora_nodes[lora_id] = {
                "inputs": {
                    "lora_name": lora_file,
                    "strength_model": strength,
                    "strength_clip": strength,
                    "model": prev_model,
                    "clip": prev_clip,
                },
                "class_type": "LoraLoader",
                "_meta": {"title": f"LoRA: {lora_file[:30]}"}
            }
            prev_model = [lora_id, 0]
            prev_clip = [lora_id, 1]

        if lora_nodes:
            setup_tmpl["nodes"].update(lora_nodes)
            setup_tmpl["nodes"]["pos_prompt"]["inputs"]["clip"] = prev_clip
            setup_tmpl["nodes"]["neg_prompt"]["inputs"]["clip"] = prev_clip
            last_lora = list(lora_nodes.keys())[-1]
            setup_tmpl["exports"]["model"] = {"node": last_lora, "output": 0}
            setup_tmpl["exports"]["clip"] = {"node": last_lora, "output": 1}

    setup_vars = {
        "checkpoint": checkpoint,
        "clip_skip": clip_skip,
        "positive_prompt": positive_prompt,
        "negative_prompt": negative_prompt,
    }
    setup_exports = instantiate("setup", setup_tmpl, setup_vars, {})

    # --- Generate block ---
    gen_tmpl = load_block("generate.json")
    gen_vars = {
        "width": width, "height": height, "batch_size": batch_size,
        "seed": seed, "steps": steps, "cfg": cfg,
        "sampler_name": sampler_name, "scheduler": scheduler,
        "denoise": denoise, "output_prefix": output_dir,
    }
    gen_imports = {
        "model": setup_exports["model"],
        "positive": setup_exports["positive"],
        "negative": setup_exports["negative"],
        "vae": setup_exports["vae"],
    }
    instantiate("gen", gen_tmpl, gen_vars, gen_imports)

    return workflow, {"seed": seed}


def _assemble_t2i_workflow(manifest: dict, params: dict) -> tuple:
    """Assemble a T2I workflow from blocks."""
    wf_id = manifest["id"]
    blocks_subdir = manifest.get("blocks_dir", "blocks")
    blocks_dir = WORKFLOWS_DIR / wf_id / blocks_subdir
    if not blocks_dir.exists():
        blocks_dir = WORKFLOWS_DIR_DEFAULT / wf_id / blocks_subdir
    if not blocks_dir.exists():
        raise FileNotFoundError(f"Blocks directory not found for {wf_id}")

    def load_block(filename):
        return json.loads((blocks_dir / filename).read_text())

    workflow = {}
    node_counter = [100]

    def next_id():
        node_counter[0] += 1
        return str(node_counter[0])

    def resolve_val(val, local_map, imports, variables):
        if isinstance(val, list) and len(val) == 2:
            ref_id, ref_out = val
            if isinstance(ref_id, str) and ref_id in local_map:
                return [local_map[ref_id], ref_out]
            return val
        if isinstance(val, str):
            if val.startswith("{{") and val.endswith("}}"):
                vn = val[2:-2]
                if vn in imports:
                    return imports[vn]
                if vn in variables:
                    return variables[vn]
                return val
            for vk, vv in variables.items():
                val = val.replace("{{" + vk + "}}", str(vv))
            return val
        if isinstance(val, dict):
            return {k: resolve_val(v, local_map, imports, variables) for k, v in val.items()}
        return val

    def instantiate(name, template, variables, imports):
        local_to_global = {lid: next_id() for lid in template["nodes"]}
        for lid, ndef in template["nodes"].items():
            gid = local_to_global[lid]
            node = {"class_type": ndef["class_type"], "_meta": dict(ndef.get("_meta", {}))}
            title = node["_meta"].get("title", "")
            for vk, vv in variables.items():
                title = title.replace("{{" + vk + "}}", str(vv))
            node["_meta"]["title"] = title
            inputs_resolved = {}
            for k, v in ndef.get("inputs", {}).items():
                if k.startswith("{{"):
                    continue
                inputs_resolved[k] = resolve_val(v, local_to_global, imports, variables)
            node["inputs"] = inputs_resolved
            workflow[gid] = node
        exports = {}
        for en, ed in template.get("exports", {}).items():
            if ed["node"] in local_to_global:
                exports[en] = [local_to_global[ed["node"]], ed["output"]]
        return exports

    # Extract params
    checkpoint = params.get("checkpoint", "")
    positive_prompt = params.get("positive_prompt", "")
    negative_prompt = params.get("negative_prompt", "")
    width = int(params.get("width", 1024))
    height = int(params.get("height", 1024))
    steps = int(params.get("steps", 25))
    cfg = float(params.get("cfg", 7.0))
    sampler_name = params.get("sampler_name", "euler")
    scheduler = params.get("scheduler", "normal")
    batch_count = int(params.get("batch_count", 1))
    hires_enabled = params.get("hires_enabled", False)
    hires_scale = float(params.get("hires_scale", 1.5))
    hires_steps = int(params.get("hires_steps", 15))
    hires_denoise = float(params.get("hires_denoise", 0.5))
    facefix_enabled = params.get("facefix_enabled", False)
    facefix_steps = int(params.get("facefix_steps", 20))
    facefix_denoise = float(params.get("facefix_denoise", 0.4))
    output_dir = params.get("_output_dir", "t2i")

    # --- Setup block ---
    setup_tmpl = copy.deepcopy(load_block("setup.json"))

    # Inject LoRAs into setup
    raw_loras = params.get("loras", [])
    if raw_loras:
        _reload_models()
        # Resolve LoRA filenames
        lora_files = {}
        for cat in _all_categories():
            for m in cat.get("models", []):
                if m.get("file"):
                    lora_files[m["file"]] = m

        # Add LoraLoader nodes chained after checkpoint
        prev_model = ["checkpoint", 0]
        prev_clip = ["checkpoint", 1]
        lora_nodes = {}
        for i, lora in enumerate(raw_loras):
            lora_file = lora.get("file", "") if isinstance(lora, dict) else lora
            strength = float(lora.get("strength", 1.0)) if isinstance(lora, dict) else 1.0
            if not lora_file:
                continue
            lora_id = f"lora_{i}"
            lora_nodes[lora_id] = {
                "inputs": {
                    "lora_name": lora_file,
                    "strength_model": strength,
                    "strength_clip": strength,
                    "model": prev_model,
                    "clip": prev_clip,
                },
                "class_type": "LoraLoader",
                "_meta": {"title": f"LoRA: {lora_file[:30]}"}
            }
            prev_model = [lora_id, 0]
            prev_clip = [lora_id, 1]

        if lora_nodes:
            setup_tmpl["nodes"].update(lora_nodes)
            setup_tmpl["nodes"]["pos_prompt"]["inputs"]["clip"] = prev_clip
            setup_tmpl["nodes"]["neg_prompt"]["inputs"]["clip"] = prev_clip
            last_lora = list(lora_nodes.keys())[-1]
            setup_tmpl["exports"]["model"] = {"node": last_lora, "output": 0}
            setup_tmpl["exports"]["clip"] = {"node": last_lora, "output": 1}

    # VAE override
    vae_override = params.get("vae_override", "")
    if vae_override:
        setup_tmpl["nodes"]["vae_override"] = {
            "inputs": {"vae_name": vae_override},
            "class_type": "VAELoader",
            "_meta": {"title": "VAE Override"}
        }
        setup_tmpl["exports"]["vae"] = {"node": "vae_override", "output": 0}

    setup_vars = {"checkpoint": checkpoint, "positive_prompt": positive_prompt, "negative_prompt": negative_prompt}
    setup_exports = instantiate("setup", setup_tmpl, setup_vars, {})

    # --- Generate blocks (batch) ---
    resolved_seeds = {}
    gen_tmpl = load_block("generate.json")
    last_gen_exports = None

    for i in range(batch_count):
        seed = int(params.get("seed", -1))
        if seed == -1:
            seed = random.randint(0, 2**53)
        elif batch_count > 1 and i > 0:
            seed = seed + i  # Increment seed for batch
        resolved_seeds[f"batch_{i+1}"] = seed

        gen_vars = {
            "width": width, "height": height,
            "seed": seed, "steps": steps, "cfg": cfg,
            "sampler_name": sampler_name, "scheduler": scheduler,
            "batch_num": str(i + 1),
        }
        gen_imports = {
            "model": setup_exports["model"],
            "positive": setup_exports["positive"],
            "negative": setup_exports["negative"],
            "vae": setup_exports["vae"],
        }
        gen_exports = instantiate(f"gen_{i}", gen_tmpl, gen_vars, gen_imports)

        # --- Optional hires fix ---
        current_image = gen_exports["image"]
        if hires_enabled:
            hires_tmpl = load_block("hires.json")
            hires_w = int(width * hires_scale)
            hires_h = int(height * hires_scale)
            hires_vars = {
                "hires_width": hires_w, "hires_height": hires_h,
                "hires_steps": hires_steps, "hires_denoise": hires_denoise,
                "seed": seed, "cfg": cfg,
                "sampler_name": sampler_name, "scheduler": scheduler,
            }
            hires_imports = {
                "model": setup_exports["model"],
                "positive": setup_exports["positive"],
                "negative": setup_exports["negative"],
                "vae": setup_exports["vae"],
                "image": current_image,
            }
            hires_exports = instantiate(f"hires_{i}", hires_tmpl, hires_vars, hires_imports)
            current_image = hires_exports["image"]

        # --- Optional face fix ---
        if facefix_enabled:
            facefix_tmpl = load_block("face_fix.json")
            facefix_vars = {
                "seed": seed, "cfg": cfg,
                "sampler_name": sampler_name, "scheduler": scheduler,
                "facefix_steps": facefix_steps, "facefix_denoise": facefix_denoise,
            }
            facefix_imports = {
                "model": setup_exports["model"],
                "clip": setup_exports["clip"],
                "positive": setup_exports["positive"],
                "negative": setup_exports["negative"],
                "vae": setup_exports["vae"],
                "image": current_image,
            }
            facefix_exports = instantiate(f"facefix_{i}", facefix_tmpl, facefix_vars, facefix_imports)
            current_image = facefix_exports["image"]

        # --- Output block ---
        out_tmpl = load_block("output.json")
        out_vars = {"output_dir": output_dir, "batch_num": str(i + 1)}
        instantiate(f"output_{i}", out_tmpl, out_vars, {"final_image": current_image})

        last_gen_exports = gen_exports

    return workflow, resolved_seeds


# ── API-to-workflow format conversion ────────────────────────────────────────


async def _api_to_workflow_format(workflow: dict, manifest: dict) -> dict:
    """Convert API-format workflow to ComfyUI workflow (UI) format.

    Fetches node schemas from ComfyUI /object_info to build correct
    inputs/outputs/widgets for each node type.  Lays out nodes in
    topologically-sorted columns with an input sidebar, optional LoRA
    stack column, and a comprehensive note node.
    """

    COLLAPSE_TYPES = {"Anything Everywhere", "Anything Everywhere3",
                      "Prompts Everywhere", "Reroute"}
    OUTPUT_TYPES = {"SaveImage", "VHS_VideoCombine", "SaveAnimatedWEBP"}

    # Step 1: Fetch node schemas from ComfyUI
    node_schemas = {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{COMFY_URL}/object_info")
            if r.status_code == 200:
                node_schemas = r.json()
    except Exception:
        pass

    # Step 2: Schema helpers

    def _is_connection_type(type_info) -> bool:
        if isinstance(type_info, list):
            return False
        return str(type_info).upper() not in {
            "INT", "FLOAT", "STRING", "BOOLEAN", "COMBO",
        }

    def _get_schema(class_type: str) -> dict:
        schema = node_schemas.get(class_type, {})
        inputs_order = []
        for section in ("required", "optional"):
            section_data = schema.get("input", {}).get(section, {})
            if isinstance(section_data, dict):
                for name, info in section_data.items():
                    type_info = (info[0]
                                 if isinstance(info, (list, tuple)) and info
                                 else info)
                    type_str = (str(type_info)
                                if not isinstance(type_info, list)
                                else "COMBO")
                    inputs_order.append(
                        (name, _is_connection_type(type_info), type_str))

        output_types = schema.get("output", [])
        output_names = schema.get("output_name", [])
        outputs = []
        for i, otype in enumerate(output_types):
            oname = output_names[i] if i < len(output_names) else str(otype)
            outputs.append({"name": oname, "type": str(otype)})

        return {"inputs_order": inputs_order, "outputs": outputs}

    def _is_api_connection(value) -> bool:
        return (isinstance(value, list)
                and len(value) == 2
                and isinstance(value[0], (str, int))
                and isinstance(value[1], int))

    # Step 3: Classify nodes into groups

    input_node_order = []
    input_ids = set()
    for inp in manifest.get("inputs", []):
        nid = str(inp.get("node_id", ""))
        if ":" in nid:
            for part in nid.split(":"):
                if part and part not in input_ids:
                    input_ids.add(part)
                    input_node_order.append(part)
        elif nid and nid not in input_ids:
            input_ids.add(nid)
            input_node_order.append(nid)
    input_node_order = [n for n in input_node_order if n in workflow]
    input_ids = set(input_node_order)

    lora_ids = set()
    lora_nids = []
    for nid, ndata in workflow.items():
        ct = ndata.get("class_type", "")
        if "loraloader" in ct.lower():
            lora_ids.add(nid)
            lora_nids.append(nid)

    output_ids = set()
    output_nids = []
    for nid, ndata in workflow.items():
        if ndata.get("class_type", "") in OUTPUT_TYPES:
            output_ids.add(nid)
            output_nids.append(nid)

    pipeline_nids = []
    for nid in workflow:
        if nid not in input_ids and nid not in lora_ids and nid not in output_ids:
            pipeline_nids.append(nid)

    all_node_ids = list(workflow.keys())

    # Step 4: Topological sort

    skip_ids = input_ids | lora_ids

    def _compute_depths():
        deps = {}
        for nid in workflow:
            if nid in skip_ids:
                continue
            deps[nid] = set()
            for _field, value in workflow[nid].get("inputs", {}).items():
                if _is_api_connection(value):
                    src = str(value[0])
                    if src not in skip_ids:
                        deps[nid].add(src)

        depth = {}

        def _get(nid, visiting=None):
            if nid in depth:
                return depth[nid]
            if nid in skip_ids:
                depth[nid] = -1
                return -1
            if visiting is None:
                visiting = set()
            if nid in visiting:
                depth[nid] = 0
                return 0
            visiting.add(nid)
            d = 0
            for dep in deps.get(nid, set()):
                d = max(d, _get(dep, visiting) + 1)
            depth[nid] = d
            return d

        for nid in workflow:
            if nid not in skip_ids:
                _get(nid)
        return depth

    depths = _compute_depths()

    # Step 5: Estimate node sizes

    sizes = {}

    def _estimate_size(node_id, node_data, schema):
        class_type = node_data.get("class_type", "")
        s = schema
        n_widgets = sum(1 for _, is_conn, _ in s["inputs_order"]
                        if not is_conn)
        n_conn = sum(1 for _, is_conn, _ in s["inputs_order"]
                     if is_conn)
        n_out = len(s["outputs"])
        has_text = any(t == "STRING"
                       for _, _, t in s["inputs_order"])

        width = 350 if has_text else 280
        height = 30 + n_widgets * 35 + max(n_conn, n_out) * 26 + 20
        height = max(height, 100)

        if class_type in COLLAPSE_TYPES:
            height = 30

        return [width, height]

    for nid, ndata in workflow.items():
        schema = _get_schema(ndata.get("class_type", ""))
        sizes[nid] = _estimate_size(nid, ndata, schema)

    # Step 6: Layout

    positions = {}

    # 6a: Note node dimensions
    inputs_table_lines = []
    for inp in manifest.get("inputs", []):
        name = inp.get("name", inp.get("id", "?"))
        itype = inp.get("type", "?")
        default = inp.get("default")
        tooltip = inp.get("tooltip", "")
        line = f"  {name}  ({itype})"
        if default is not None:
            line += f"  [default: {default}]"
        if tooltip:
            short = tooltip[:120] + ("..." if len(tooltip) > 120 else "")
            line += f"\n    {short}"
        inputs_table_lines.append(line)

    models_list = "\n".join(
        f"  - {m}" for m in manifest.get("required_models", []))
    nodes_list = "\n".join(
        f"  - {n}" for n in manifest.get("required_nodes", []))

    note_text = (
        f"{'=' * 50}\n"
        f"  {manifest.get('name', 'Unknown Workflow')}\n"
        f"{'=' * 50}\n"
        f"\n"
        f"ID:          {manifest.get('id', '?')}\n"
        f"Version:     {manifest.get('version', '?')}\n"
        f"Author:      {manifest.get('author', 'N/A') or 'N/A'}\n"
        f"Description: {manifest.get('description', 'N/A')}\n"
        f"\n"
        + "\u2500" * 40 + "\n"
        f"  INPUTS\n"
        + "\u2500" * 40 + "\n"
        + "\n".join(inputs_table_lines) + "\n"
        f"\n"
        + "\u2500" * 40 + "\n"
        f"  REQUIRED MODELS\n"
        + "\u2500" * 40 + "\n"
        + (models_list or "  (none)") + "\n"
        f"\n"
        + "\u2500" * 40 + "\n"
        f"  REQUIRED CUSTOM NODES\n"
        + "\u2500" * 40 + "\n"
        + (nodes_list or "  (none)") + "\n"
        f"\n"
        + "\u2500" * 40 + "\n"
        f"  RECOMMENDATIONS\n"
        + "\u2500" * 40 + "\n"
        f"  - Ensure all required models are downloaded\n"
        f"  - Ensure all required custom nodes are installed\n"
        f"  - Exported from ComfyUI Studio\n"
    )
    note_lines = note_text.count("\n") + 1
    note_width = 500
    note_height = note_lines * 18 + 40
    note_height = max(note_height, 200)

    # 6b: Input nodes below the note
    x_input = 100
    y_cursor = 100 + note_height + 50

    for nid in input_node_order:
        positions[nid] = [x_input, y_cursor]
        y_cursor += sizes[nid][1] + 20

    # 6c: LoRA stack column
    if lora_nids:
        lora_x = 700
        lora_y = 100
        for nid in lora_nids:
            positions[nid] = [lora_x, lora_y]
            lora_y += sizes[nid][1] + 20

    # 6d: Pipeline + output columns via depth
    pipeline_start_x = 700 if not lora_nids else 1100

    depth_columns = {}
    for nid, d in depths.items():
        if nid not in input_ids and nid not in lora_ids:
            depth_columns.setdefault(d, []).append(nid)

    def _sort_by_source_y(nids):
        def avg_y(nid):
            ys = []
            for _field, value in workflow[nid].get("inputs", {}).items():
                if _is_api_connection(value):
                    src = str(value[0])
                    if src in positions:
                        ys.append(positions[src][1]
                                  + sizes.get(src, [0, 0])[1] / 2)
            return sum(ys) / len(ys) if ys else 0
        return sorted(nids, key=avg_y)

    col_x = pipeline_start_x
    for d in sorted(depth_columns.keys()):
        col_nids = _sort_by_source_y(depth_columns[d])
        col_y = 100
        max_w = 0
        for nid in col_nids:
            positions[nid] = [col_x, col_y]
            col_y += sizes[nid][1] + 20
            max_w = max(max_w, sizes[nid][0])
        col_x += max_w + 100

    # Build connections and links

    links_out = []
    link_id_counter = 1
    node_link_map = {}

    for node_id in all_node_ids:
        node_data = workflow[node_id]
        node_link_map[node_id] = {}
        for field_name, value in node_data.get("inputs", {}).items():
            if _is_api_connection(value):
                src_node_id = str(value[0])
                src_slot = value[1]
                lid = link_id_counter
                link_id_counter += 1
                node_link_map[node_id][field_name] = lid
                links_out.append({
                    "id": lid,
                    "src": int(src_node_id),
                    "src_slot": src_slot,
                    "tgt": int(node_id),
                    "tgt_field": field_name,
                })

    outgoing = {}
    for link in links_out:
        sid = link["src"]
        slot = link["src_slot"]
        outgoing.setdefault(sid, {}).setdefault(slot, []).append(link["id"])

    # Step 7: Build node objects

    all_depths_for_order = {}
    for nid in all_node_ids:
        if nid in depths:
            all_depths_for_order[nid] = depths[nid]
        elif nid in input_ids:
            all_depths_for_order[nid] = -2
        elif nid in lora_ids:
            all_depths_for_order[nid] = -1
        else:
            all_depths_for_order[nid] = 0
    sorted_for_order = sorted(all_node_ids,
                              key=lambda n: all_depths_for_order.get(n, 0))
    execution_order = {nid: idx for idx, nid in enumerate(sorted_for_order)}

    nodes_out = []

    for node_id in all_node_ids:
        node_data = workflow[node_id]
        class_type = node_data.get("class_type", "Unknown")
        meta = node_data.get("_meta", {})
        schema = _get_schema(class_type)
        api_inputs = node_data.get("inputs", {})

        node_inputs = []
        widgets_values = []

        if schema["inputs_order"]:
            for field_name, is_conn, type_str in schema["inputs_order"]:
                value = api_inputs.get(field_name)
                has_link = field_name in node_link_map.get(node_id, {})

                if is_conn:
                    node_inputs.append({
                        "name": field_name,
                        "type": type_str,
                        "link": (node_link_map[node_id][field_name]
                                 if has_link else None),
                    })
                else:
                    if has_link:
                        node_inputs.append({
                            "name": field_name,
                            "type": type_str,
                            "link": node_link_map[node_id][field_name],
                            "widget": {"name": field_name},
                        })
                    if (value is not None
                            and not _is_api_connection(value)):
                        widgets_values.append(value)
        else:
            for field_name, value in api_inputs.items():
                is_conn = _is_api_connection(value)
                if is_conn:
                    node_inputs.append({
                        "name": field_name,
                        "type": "*",
                        "link": node_link_map[node_id].get(field_name),
                    })
                else:
                    widgets_values.append(value)

        node_outputs = []
        for i, out_info in enumerate(schema["outputs"]):
            node_outputs.append({
                "name": out_info["name"],
                "type": out_info["type"],
                "links": outgoing.get(int(node_id), {}).get(i, []),
                "slot_index": i,
                "shape": 3,
            })
        if not node_outputs and int(node_id) in outgoing:
            for slot in sorted(outgoing[int(node_id)].keys()):
                node_outputs.append({
                    "name": f"output_{slot}",
                    "type": "*",
                    "links": outgoing[int(node_id)][slot],
                    "slot_index": slot,
                    "shape": 3,
                })

        is_collapsed = class_type in COLLAPSE_TYPES

        node_obj = {
            "id": int(node_id),
            "type": class_type,
            "pos": positions.get(node_id, [0, 0]),
            "size": sizes.get(node_id, [280, 100]),
            "flags": {"collapsed": True} if is_collapsed else {},
            "order": execution_order.get(node_id, 0),
            "mode": 0,
            "inputs": node_inputs,
            "outputs": node_outputs,
            "properties": {"Node name for S&R": class_type},
            "widgets_values": widgets_values,
        }
        if meta.get("title"):
            node_obj["title"] = meta["title"]
        nodes_out.append(node_obj)

    # Step 8: Build links with correct target slots

    final_links = []
    for link in links_out:
        tgt_node_id = link["tgt"]
        tgt_field = link["tgt_field"]
        tgt_slot = 0
        for node_obj in nodes_out:
            if node_obj["id"] == tgt_node_id:
                for i, inp in enumerate(node_obj["inputs"]):
                    if inp["name"] == tgt_field:
                        tgt_slot = i
                        break
                break
        src_type = "*"
        for node_obj in nodes_out:
            if node_obj["id"] == link["src"]:
                if link["src_slot"] < len(node_obj["outputs"]):
                    src_type = node_obj["outputs"][link["src_slot"]]["type"]
                break
        final_links.append([link["id"], link["src"], link["src_slot"],
                            tgt_node_id, tgt_slot, src_type])

    # Step 9: Note node

    max_node_id = max((int(nid) for nid in all_node_ids), default=0)
    note_id = max_node_id + 1

    note_node = {
        "id": note_id,
        "type": "Note",
        "pos": [100, 100],
        "size": [note_width, note_height],
        "flags": {},
        "order": len(all_node_ids),
        "mode": 0,
        "inputs": [],
        "outputs": [],
        "properties": {"text": note_text},
        "widgets_values": [note_text],
        "color": "#335533",
        "bgcolor": "#1a2e1a",
    }
    nodes_out.append(note_node)

    # Step 10: Groups

    groups = []

    if input_node_order:
        inp_positions = [positions[n] for n in input_node_order
                         if n in positions]
        inp_sizes = [sizes[n] for n in input_node_order if n in sizes]
        all_x = [100] + [p[0] for p in inp_positions]
        all_y = [100] + [p[1] for p in inp_positions]
        all_right = [100 + note_width] + [p[0] + s[0]
                                           for p, s in zip(inp_positions,
                                                           inp_sizes)]
        all_bottom = ([100 + note_height]
                      + [p[1] + s[1]
                         for p, s in zip(inp_positions, inp_sizes)])
        gx = min(all_x) - 30
        gy = min(all_y) - 50
        gw = max(all_right) - gx + 30
        gh = max(all_bottom) - gy + 20
        groups.append({
            "title": "Studio Inputs",
            "bounding": [gx, gy, gw, gh],
            "color": "#335533",
            "font_size": 24,
        })

    if lora_nids:
        lora_positions = [positions[n] for n in lora_nids if n in positions]
        lora_sizes_list = [sizes[n] for n in lora_nids if n in sizes]
        if lora_positions:
            lx = min(p[0] for p in lora_positions) - 30
            ly = min(p[1] for p in lora_positions) - 50
            lr = max(p[0] + s[0]
                     for p, s in zip(lora_positions, lora_sizes_list))
            lb = max(p[1] + s[1]
                     for p, s in zip(lora_positions, lora_sizes_list))
            groups.append({
                "title": "LoRA Stack",
                "bounding": [lx, ly, lr - lx + 30, lb - ly + 20],
                "color": "#553333",
                "font_size": 24,
            })

    # Step 11: Return

    last_link_id = link_id_counter - 1

    return {
        "last_node_id": note_id,
        "last_link_id": last_link_id,
        "nodes": nodes_out,
        "links": final_links,
        "groups": groups,
        "config": {},
        "extra": {"ds": {"scale": 0.8, "offset": [0, 0]}},
        "version": 0.4,
    }
