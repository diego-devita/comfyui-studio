"""ComfyUI Studio — Workflow loading, dynamic assembly, API-to-UI conversion."""

import copy
import json
import random
from pathlib import Path

import httpx
import yaml

from config import (
    COMFY_URL, COMFYUI_DIR, MODELS_BASE,
    WORKFLOWS_DIR,
)
from catalogs import _all_categories, _reload_models


# ── Workflow path resolution ────────────────────────────────────────────────


def _workflows_path(subpath: str) -> Path:
    """Resolve a workflow subpath within WORKFLOWS_DIR."""
    return WORKFLOWS_DIR / subpath


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


# ── Dynamic workflow assembly v2 — Generic declarative pipeline assembler ────


def _eval_condition(condition: str, params: dict) -> bool:
    """Evaluate a condition string against params.

    Supports:
      - "param_name"         → truthy check (exists, non-empty, non-false)
      - "param != value"     → inequality
      - "param == value"     → equality
    """
    if not condition:
        return True
    condition = condition.strip()
    for op in ("!=", "=="):
        if op in condition:
            left, right = condition.split(op, 1)
            left, right = left.strip(), right.strip()
            val = str(params.get(left, ""))
            if op == "!=":
                return val != right
            return val == right
    # Simple truthy check
    val = params.get(condition)
    if val is None or val == "" or val is False or val == "false":
        return False
    return True


def _stage_is_active(stage: dict, params: dict) -> bool:
    """Check if a pipeline stage should be included based on its condition."""
    cond = stage.get("condition")
    if cond and not _eval_condition(cond, params):
        return False
    return True


def _resolve_block_file(stage: dict, params: dict) -> str | None:
    """Determine which block file to load for a stage. Returns None to skip."""
    if "switch" in stage:
        value = str(params.get(stage["switch"], stage.get("default", "")))
        cases = stage.get("cases", {})
        file = cases.get(value, cases.get(stage.get("default", ""), None))
        return file  # None means skip
    return stage.get("file")


def _normalize_loras(raw_loras: list) -> list[dict]:
    """Normalize LoRA list from params into a consistent format."""
    result = []
    for item in raw_loras:
        if isinstance(item, str):
            result.append({"pair_id": item, "strength_high": 1.0, "strength_low": 1.0})
        elif isinstance(item, dict):
            sh = float(item.get("strength_high", item.get("strength", 1.0)))
            sl = float(item.get("strength_low", item.get("strength", 1.0)))
            result.append({
                "pair_id": item.get("pair_id", ""),
                "file": item.get("file", ""),
                "strength": float(item.get("strength", 1.0)),
                "strength_high": sh,
                "strength_low": sl,
            })
    return result


def _build_lora_file_map() -> dict:
    """Build pair_id → {high: file, low: file, both: file} from catalogs."""
    _reload_models()
    lora_map = {}
    for cat in _all_categories():
        for m in cat.get("models", []):
            pid = m.get("pair_id")
            if pid:
                role = m.get("pair_role", "both")
                if pid not in lora_map:
                    lora_map[pid] = {}
                lora_map[pid][role] = m["file"]
    return lora_map


def _inject_loras_chain(template: dict, loras: list[dict]) -> dict:
    """Inject a LoRA chain into a setup block template.

    Creates LoraLoader nodes chained from the model/clip export sources.
    Rewires clip consumers and updates model/clip exports.
    """
    template = copy.deepcopy(template)
    if not loras:
        return template

    model_exp = template.get("exports", {}).get("model")
    clip_exp = template.get("exports", {}).get("clip")
    if not model_exp or not clip_exp:
        return template

    model_source = [model_exp["node"], model_exp["output"]]
    clip_source = [clip_exp["node"], clip_exp["output"]]

    prev_model = model_source
    prev_clip = clip_source
    lora_nodes = {}

    for i, lora in enumerate(loras):
        lora_file = lora.get("file", "")
        if not lora_file:
            continue
        strength = float(lora.get("strength", 1.0))
        lora_id = f"_lora_{i}"
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

    if not lora_nodes:
        return template

    template["nodes"].update(lora_nodes)

    # Rewire all nodes that referenced the original clip source
    for node_id, node_def in template["nodes"].items():
        if node_id.startswith("_lora_"):
            continue
        for key, val in node_def.get("inputs", {}).items():
            if (isinstance(val, list) and len(val) == 2
                    and val[0] == clip_source[0] and val[1] == clip_source[1]):
                node_def["inputs"][key] = list(prev_clip)

    last_lora = list(lora_nodes.keys())[-1]
    template["exports"]["model"] = {"node": last_lora, "output": 0}
    template["exports"]["clip"] = {"node": last_lora, "output": 1}

    return template


def _inject_loras_paired(template: dict, loras: list[dict], lora_file_map: dict,
                         nodes: list[str] = None, start_slot: int = 3) -> dict:
    """Inject LoRA pairs into Power Lora Loader nodes (WAN-style).

    Each LoRA pair has high/low files injected into the respective nodes.
    """
    template = copy.deepcopy(template)
    if not loras:
        return template

    if nodes is None:
        nodes = ["lora_high", "lora_low"]

    slot_idx = start_slot
    for lora_sel in loras:
        pid = lora_sel.get("pair_id", "")
        str_h = lora_sel.get("strength_high", 1.0)
        str_l = lora_sel.get("strength_low", 1.0)
        pair = lora_file_map.get(pid, {})
        high_file = pair.get("high", pair.get("both", ""))
        low_file = pair.get("low", pair.get("both", ""))
        if not high_file:
            continue
        slot = f"lora_{slot_idx}"
        if len(nodes) >= 1 and nodes[0] in template["nodes"]:
            template["nodes"][nodes[0]]["inputs"][slot] = {"on": True, "lora": high_file, "strength": str_h}
        if len(nodes) >= 2 and nodes[1] in template["nodes"]:
            template["nodes"][nodes[1]]["inputs"][slot] = {"on": True, "lora": low_file or high_file, "strength": str_l}
        slot_idx += 1

    # Remove template placeholders from Power Lora Loader nodes
    for node_key in nodes:
        if node_key in template["nodes"]:
            inputs = template["nodes"][node_key]["inputs"]
            for k in list(inputs.keys()):
                if k.startswith("{{"):
                    del inputs[k]

    return template


def _inject_vae_override(template: dict, vae_name: str) -> dict:
    """Add a VAELoader node and redirect the vae export."""
    template = copy.deepcopy(template)
    template["nodes"]["_vae_override"] = {
        "inputs": {"vae_name": vae_name},
        "class_type": "VAELoader",
        "_meta": {"title": "VAE Override"}
    }
    template["exports"]["vae"] = {"node": "_vae_override", "output": 0}
    return template


def _resolve_seed(params: dict, iteration: int, seed_key: str = "seed") -> int:
    """Resolve seed for a given iteration. -1 = random, otherwise increment."""
    seed = int(params.get(seed_key, -1))
    if seed == -1:
        return random.randint(0, 2**53)
    if iteration > 0:
        return seed + iteration
    return seed


def _assemble_dynamic_workflow(manifest: dict, params: dict) -> tuple:
    """Generic assembler: build any dynamic workflow from its manifest pipeline.

    Handles: condition, switch, repeat, chain, lora_injection, vae_override.
    Returns (workflow_dict, resolved_seeds).
    """
    wf_id = manifest["id"]
    blocks_subdir = manifest.get("blocks_dir", "blocks")
    blocks_dir = WORKFLOWS_DIR / wf_id / blocks_subdir
    if not blocks_dir.exists():
        raise FileNotFoundError(
            f"Blocks directory not found: {blocks_dir}. Run Check for Updates."
        )
    defaults = manifest.get("defaults", {})
    pipeline = manifest["pipeline"]

    def load_block(filename):
        return json.loads((blocks_dir / filename).read_text())

    # LoRA preparation
    selected_loras = _normalize_loras(params.get("loras", []))
    lora_file_map = _build_lora_file_map() if selected_loras else {}

    # Workflow state
    workflow = {}
    node_counter = [100]
    block_exports = {}  # instance_name -> {export_name: [global_id, output_idx]}
    resolved_seeds = {}

    def next_id():
        node_counter[0] += 1
        return str(node_counter[0])

    def _resolve_value(val, local_to_global, imports_map, variables):
        """Resolve a value: local refs, import refs, variable substitutions."""
        if isinstance(val, list) and len(val) == 2:
            ref_id, ref_out = val
            if isinstance(ref_id, str):
                if ref_id in local_to_global:
                    return [local_to_global[ref_id], ref_out]
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

    def instantiate_block(instance_name, template, variables, imports_map):
        """Instantiate a block: assign global IDs, resolve imports and variables."""
        local_to_global = {lid: next_id() for lid in template["nodes"]}
        for local_id, node_def in template["nodes"].items():
            global_id = local_to_global[local_id]
            node = {"class_type": node_def["class_type"], "_meta": dict(node_def.get("_meta", {}))}
            title = node["_meta"].get("title", "")
            for vk, vv in variables.items():
                title = title.replace("{{" + vk + "}}", str(vv))
            node["_meta"]["title"] = title
            inputs = {}
            for key, val in node_def.get("inputs", {}).items():
                if key.startswith("{{") and key.endswith("}}"):
                    continue
                inputs[key] = _resolve_value(val, local_to_global, imports_map, variables)
            node["inputs"] = inputs
            workflow[global_id] = node
        exports = {}
        for exp_name, exp_def in template.get("exports", {}).items():
            if exp_def["node"] in local_to_global:
                exports[exp_name] = [local_to_global[exp_def["node"]], exp_def["output"]]
        block_exports[instance_name] = exports
        return exports

    def _latest_exports() -> dict:
        """Flatten all block exports into a single dict (later exports override earlier)."""
        merged = {}
        for _inst, exps in block_exports.items():
            merged.update(exps)
        return merged

    def _build_variables(stage: dict, iteration: int = 0, seed: int = None) -> dict:
        """Build the variables dict for a stage from params + defaults + iteration info."""
        variables = dict(defaults)
        # Add all params as variables (strings get cast by the block template)
        for k, v in params.items():
            if not k.startswith("_") and not isinstance(v, (list, dict)):
                variables[k] = v
        # Special computed variables
        variables["_output_dir"] = params.get("_output_dir", wf_id)
        variables["output_dir"] = params.get("_output_dir", wf_id)
        variables["output_prefix"] = params.get("_output_dir", wf_id)
        variables["input_image"] = params.get("_uploaded_image", "input.png")
        # Resolution
        variables["width"] = int(params.get("width", defaults.get("width", 1024)))
        variables["height"] = int(params.get("height", defaults.get("height", 1024)))
        # Iteration
        variables["batch_num"] = str(iteration + 1)
        variables["_iteration"] = iteration
        if seed is not None:
            variables["seed"] = seed
        # Hires computed dimensions
        if params.get("hires_enabled"):
            scale = float(params.get("hires_scale", 1.5))
            variables["hires_width"] = int(variables["width"] * scale)
            variables["hires_height"] = int(variables["height"] * scale)
        return variables

    # ── Group pipeline stages into execution units ──
    # A repeat group: all stages from a block with `repeat` until a block with
    # `in_repeat: false` or the end of pipeline. Stages before any repeat are singles.
    # Chain groups (WAN SVI): `chain: true` on a repeat block means each iteration's
    # exports feed into the next via `chain_imports`.

    groups = []  # Each: {"type": "single"|"repeat"|"chain", "stages": [...], "param": ...}
    current_repeat = None

    for stage in pipeline:
        has_repeat = stage.get("repeat") is not None
        if has_repeat and current_repeat is None:
            current_repeat = {
                "type": "chain" if stage.get("chain") else "repeat",
                "param": stage["repeat"],
                "chain_imports": stage.get("chain_imports", {}),
                "stages": [stage],
            }
        elif current_repeat is not None and not stage.get("in_repeat") is False:
            # Check explicit opt-out
            if stage.get("in_repeat", True) is False:
                groups.append(current_repeat)
                current_repeat = None
                groups.append({"type": "single", "stages": [stage]})
            elif has_repeat:
                # New repeat block — flush previous group
                groups.append(current_repeat)
                current_repeat = {
                    "type": "chain" if stage.get("chain") else "repeat",
                    "param": stage["repeat"],
                    "chain_imports": stage.get("chain_imports", {}),
                    "stages": [stage],
                }
            else:
                current_repeat["stages"].append(stage)
        else:
            groups.append({"type": "single", "stages": [stage]})

    if current_repeat:
        groups.append(current_repeat)

    # ── Execute groups ──

    def _process_stage(stage, variables, extra_imports=None):
        """Process a single pipeline stage. Returns exports or None if skipped."""
        if not _stage_is_active(stage, params):
            return None

        block_file = _resolve_block_file(stage, params)
        if block_file is None:
            return None

        template = load_block(block_file)

        # LoRA injection
        lora_mode = stage.get("lora_injection")
        if lora_mode and selected_loras:
            if lora_mode == "paired":
                template = _inject_loras_paired(
                    template, selected_loras, lora_file_map,
                    nodes=stage.get("lora_nodes"),
                    start_slot=stage.get("lora_start_slot", 3),
                )
            else:
                template = _inject_loras_chain(template, selected_loras)

        # VAE override
        if stage.get("vae_override") and params.get("vae_override"):
            template = _inject_vae_override(template, params["vae_override"])

        # Build imports from all previous exports
        imports_map = _latest_exports()
        if extra_imports:
            imports_map.update(extra_imports)

        return instantiate_block(
            f"{stage['block']}_{variables.get('_iteration', 0)}",
            template, variables, imports_map,
        )

    # ── Scene-based variable provider (WAN SVI) ──

    def _scene_variables(iteration):
        """Build variables for scene-based workflows."""
        scenes = params.get("scenes", [])
        if not scenes:
            scenes = [{"prompt": "", "duration": 5}]
        scene = scenes[iteration] if iteration < len(scenes) else {"prompt": "", "duration": 5}
        duration_sec = int(scene.get("duration", 5))
        scene_seed = int(scene.get("seed", params.get("seed", -1)))
        if scene_seed == -1:
            scene_seed = random.randint(0, 2**53)
        resolved_seeds[f"scene_{iteration + 1}"] = scene_seed
        return {
            **defaults,
            "prompt": scene.get("prompt", ""),
            "negative_prompt": defaults.get("negative_prompt", ""),
            "duration_frames": duration_sec * 16 + 1,
            "seed": scene_seed,
            "scene_num": str(iteration + 1),
            "input_image": params.get("_uploaded_image", "input.png"),
        }

    for group in groups:
        if group["type"] == "single":
            for stage in group["stages"]:
                if stage.get("scene_index") is not None:
                    variables = _scene_variables(stage["scene_index"])
                else:
                    variables = _build_variables(stage)
                _process_stage(stage, variables)

        elif group["type"] == "repeat":
            param = group["param"]
            if isinstance(param, int):
                count = param
            else:
                count = int(params.get(param, 1))

            for i in range(count):
                seed = _resolve_seed(params, i)
                resolved_seeds[f"batch_{i + 1}"] = seed
                for stage in group["stages"]:
                    variables = _build_variables(stage, iteration=i, seed=seed)
                    _process_stage(stage, variables)

        elif group["type"] == "chain":
            param = group["param"]
            chain_imports_map = group.get("chain_imports", {})

            # For scene-based chains, count comes from scenes list
            scenes = params.get("scenes", [])
            if not scenes:
                scenes = [{"prompt": "", "duration": 5}]

            if isinstance(param, int):
                count = param
            elif param == "extra_scenes":
                count = max(len(scenes) - 1, 0)
            else:
                count = int(params.get(param, 0))

            prev_chain_exports = None
            for i in range(count):
                # For scene-based chains, use scene variables
                if params.get("scenes") and group["stages"][0].get("file", "").startswith("scene"):
                    variables = _scene_variables(i + 1 if param == "extra_scenes" else i)
                else:
                    seed = _resolve_seed(params, i)
                    variables = _build_variables(group["stages"][0], iteration=i, seed=seed)

                # Map previous chain exports to import names
                extra_imports = {}
                if prev_chain_exports and chain_imports_map:
                    for import_name, export_name in chain_imports_map.items():
                        if export_name in prev_chain_exports:
                            extra_imports[import_name] = prev_chain_exports[export_name]

                for stage in group["stages"]:
                    exports = _process_stage(stage, variables, extra_imports)
                    if exports:
                        prev_chain_exports = exports

    return workflow, resolved_seeds


def get_required_models(manifest: dict, params: dict = None) -> set:
    """Determine required models based on active pipeline stages.

    If params is provided, only models from active stages are included.
    Otherwise, returns all models from always + all stages.
    """
    models = set(manifest.get("required_models", []))
    always = manifest.get("required_models_map", {}).get("always", [])
    models.update(always)

    for stage in manifest.get("pipeline", []):
        if params and not _stage_is_active(stage, params):
            continue
        stage_models = stage.get("models", [])
        if isinstance(stage_models, list):
            models.update(stage_models)
        elif isinstance(stage_models, dict):
            if params and "switch" in stage:
                value = str(params.get(stage["switch"], stage.get("default", "")))
                models.update(stage_models.get(value, []))
            else:
                for case_models in stage_models.values():
                    if isinstance(case_models, list):
                        models.update(case_models)
    return models


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
