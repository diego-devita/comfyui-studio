"""ComfyUI Studio — CivitAI proxy endpoints (generation data, resource cross-reference, catalog add)."""

import json
import os
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from config import MODELS_BASE, MODELS_JSON, LORAS_JSON
import catalogs as _catalogs
from loras_api import _gallery_download_one, _url_to_id
import gallery_db as _gdb

router = APIRouter()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _build_civitai_map() -> dict:
    """Build version-indexed map of all CivitAI entries across models+loras catalogs.

    Returns dict keyed by str(civitai_version_id) → {file, dest, name, base_model, status, catalog}.
    """
    by_version = {}
    for catalog_name, catalog_data in [("models", _catalogs._models_data), ("loras", _catalogs._loras_data)]:
        for cat in catalog_data.get("categories", []):
            for m in cat.get("models", []):
                vid = m.get("civitai_version_id")
                if not vid:
                    continue
                vid_str = str(vid)
                dest = m.get("dest", "")
                fname = m.get("file", "")
                disk_path = Path(MODELS_BASE) / dest / fname if dest else Path(MODELS_BASE) / fname
                by_version[vid_str] = {
                    "file": fname,
                    "dest": dest,
                    "name": m.get("name", ""),
                    "base_model": m.get("base_model") or m.get("civitai_base_model") or "",
                    "status": "present" if disk_path.exists() else "missing",
                    "catalog": catalog_name,
                }
    return by_version


def _detect_workflow_type(type_: str, process: str | None, techniques: list) -> str:
    """Heuristic detection of workflow type from CivitAI generation data."""
    # techniques can be [{name: "txt2img"}, ...] or ["txt2img", ...]
    techniques_lower = []
    for t in techniques:
        if isinstance(t, dict):
            techniques_lower.append((t.get("name") or "").lower())
        elif isinstance(t, str):
            techniques_lower.append(t.lower())
        else:
            techniques_lower.append("")
    process_lower = (process or "").lower()

    if type_ == "video":
        if "img2vid" in techniques_lower:
            return "i2v"
        if "txt2vid" in techniques_lower:
            return "t2v"
        return "t2v"

    if process_lower == "txt2img" or "txt2img" in techniques_lower:
        return "t2i"
    if "img2img" in process_lower:
        return "i2i"

    return "unknown"


def _enrich_resources(resources: list, civitai_map: dict) -> list:
    """Cross-reference resources against local catalog, adding catalog_status."""
    enriched = []
    for r in resources:
        entry = dict(r)
        vid = r.get("versionId") or r.get("modelVersionId")
        if vid:
            vid_str = str(vid)
            catalog_entry = civitai_map.get(vid_str)
            if catalog_entry:
                entry["catalog_status"] = catalog_entry["status"]  # "present" or "missing"
                entry["catalog_file"] = catalog_entry["file"]
                entry["catalog_dest"] = catalog_entry["dest"]
                entry["catalog_name"] = catalog_entry["name"]
            else:
                entry["catalog_status"] = "not_found"
        else:
            entry["catalog_status"] = "not_found"
        enriched.append(entry)
    return enriched


import re as _re


def _parse_lora_tags(prompt: str) -> tuple[list[dict], str]:
    """Parse <lora:Name:weight> tags from prompt. Returns (lora_list, clean_prompt)."""
    loras = []
    def _repl(m):
        loras.append({"name": m.group(1), "weight": float(m.group(2)), "source": "prompt"})
        return ""
    clean = _re.sub(r"<lora:([^:>]+):([0-9.]+)>", _repl, prompt)
    clean = _re.sub(r"\s{2,}", " ", clean).strip()  # collapse whitespace
    clean = _re.sub(r"^[\s,]+|[\s,]+$", "", clean)   # trim leading/trailing commas
    return loras, clean


def _parse_embeddings(negative: str, meta_resources: list) -> list[dict]:
    """Detect embedding names in negative prompt by matching against meta.resources."""
    # Build hash lookup from meta.resources
    hash_lookup = {}
    for r in meta_resources:
        if r.get("hash"):
            hash_lookup[r.get("name", "").lower()] = r["hash"]

    embeddings = []
    for line in negative.split("\n"):
        token = line.strip()
        if not token:
            continue
        # Embedding names are typically single tokens with underscores, no commas
        if _re.match(r"^[A-Za-z0-9_-]+$", token):
            emb = {"name": token, "type": "embedding", "source": "negative_prompt"}
            # Try to find hash
            emb["hash"] = hash_lookup.get(token.lower(), "")
            embeddings.append(emb)
    return embeddings


async def _resolve_by_hash(hash_val: str, client: httpx.AsyncClient, headers: dict) -> dict | None:
    """Resolve a CivitAI model version by hash."""
    if not hash_val:
        return None
    try:
        resp = await client.get(f"https://civitai.com/api/v1/model-versions/by-hash/{hash_val.upper()}", headers=headers)
        if resp.status_code == 200:
            return resp.json()
    except httpx.HTTPError:
        pass
    return None


async def _resolve_detected_deps(detected: list, civitai_map: dict) -> list:
    """Resolve detected dependencies via hash lookup, enrich with catalog status."""
    civitai_key = os.environ.get("CIVITAI_API_KEY", "")
    headers = {"Authorization": f"Bearer {civitai_key}"} if civitai_key else {}

    enriched = []
    async with httpx.AsyncClient(timeout=15) as client:
        for dep in detected:
            entry = dict(dep)

            # Try hash resolution
            resolved = await _resolve_by_hash(dep.get("hash", ""), client, headers)
            if resolved:
                entry["civitai_model_id"] = resolved.get("modelId")
                entry["civitai_version_id"] = resolved.get("id")
                entry["civitai_model_name"] = resolved.get("model", {}).get("name", "")
                entry["civitai_version_name"] = resolved.get("name", "")
                entry["civitai_base_model"] = resolved.get("baseModel", "")
                entry["civitai_type"] = resolved.get("model", {}).get("type", "")
                files = resolved.get("files", [])
                primary = next((f for f in files if f.get("primary")), files[0] if files else {})
                entry["civitai_file"] = primary.get("name", "")
                entry["civitai_download_url"] = primary.get("downloadUrl", "")

                # Check catalog
                vid_str = str(resolved.get("id", ""))
                catalog_entry = civitai_map.get(vid_str)
                if catalog_entry:
                    entry["catalog_status"] = catalog_entry["status"]
                    entry["catalog_file"] = catalog_entry["file"]
                    entry["catalog_dest"] = catalog_entry["dest"]
                else:
                    entry["catalog_status"] = "not_found"
            else:
                entry["catalog_status"] = "unknown"

            enriched.append(entry)
    return enriched


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/api/admin/civitai/image/{image_id}")
async def civitai_image_generation_data(image_id: int):
    """Proxy for CivitAI tRPC image.getGenerationData — enriched with catalog cross-reference."""
    input_json = f'{{"json":{{"id":{image_id}}}}}'
    url = f"https://civitai.com/api/trpc/image.getGenerationData?input={quote(input_json)}"

    headers = {"Content-Type": "application/json"}
    civitai_key = os.environ.get("CIVITAI_API_KEY", "")
    if civitai_key:
        headers["Authorization"] = f"Bearer {civitai_key}"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            raw = resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"CivitAI API returned {e.response.status_code}",
        )
    except httpx.RequestError as e:
        raise HTTPException(502, f"Failed to reach CivitAI: {str(e)}")

    # Parse tRPC envelope: result.data.json
    try:
        data = raw["result"]["data"]["json"]
    except (KeyError, TypeError):
        raise HTTPException(502, "Unexpected tRPC response structure")

    resources = data.get("resources", [])
    meta = data.get("meta", {})
    type_ = data.get("type", "image")
    process = data.get("process")
    techniques = data.get("techniques", [])
    tools = data.get("tools", [])

    civitai_map = _build_civitai_map()
    enriched_resources = _enrich_resources(resources, civitai_map)
    detected_type = _detect_workflow_type(type_, process, techniques)

    # Parse hidden dependencies from prompts
    meta_resources = (meta or {}).get("resources", [])
    prompt_text = (meta or {}).get("prompt", "")
    negative_text = (meta or {}).get("negativePrompt", "")

    prompt_loras, clean_prompt = _parse_lora_tags(prompt_text)
    negative_embeddings = _parse_embeddings(negative_text, meta_resources)

    # Also check if meta.resources has loras NOT in the top-level resources
    top_level_names = {r.get("modelName", "").lower() for r in resources}
    extra_from_meta = []
    for mr in meta_resources:
        mr_name = mr.get("name", "")
        mr_type = mr.get("type", "").lower()
        if mr_type in ("lora", "lycoris") and mr_name.lower() not in top_level_names:
            # Not in structured resources — was only in meta
            matched_prompt_lora = next((pl for pl in prompt_loras if pl["name"] == mr_name), None)
            if not matched_prompt_lora:
                extra_from_meta.append({
                    "name": mr_name, "type": mr_type, "hash": mr.get("hash", ""),
                    "source": "meta_resources",
                })

    all_detected = prompt_loras + negative_embeddings + extra_from_meta

    # Add hashes from meta.resources to prompt loras
    hash_lookup = {r.get("name", ""): r.get("hash", "") for r in meta_resources}
    for dep in all_detected:
        if not dep.get("hash"):
            dep["hash"] = hash_lookup.get(dep["name"], "")

    # Resolve all detected deps via CivitAI hash lookup
    resolved_detected = await _resolve_detected_deps(all_detected, civitai_map)

    return JSONResponse({
        "raw": raw,
        "resources": enriched_resources,
        "detected_deps": resolved_detected,
        "clean_prompt": clean_prompt,
        "meta": meta,
        "type": type_,
        "process": process,
        "techniques": techniques,
        "tools": tools,
        "detected_type": detected_type,
    })


# ── CivitAI type → catalog category mapping ─────────────────────────────────

# CivitAI model.type values → (category_id, dest subfolder)
_TYPE_TO_CATEGORY = {
    "Checkpoint":        ("checkpoints", "checkpoints"),
    "LORA":              ("loras", "loras"),
    "VAE":               ("vae", "vae"),
    "TextualInversion":  ("embeddings", "embeddings"),
    "Controlnet":        ("controlnet", "controlnet"),
    "Upscaler":          ("upscalers", "upscale_models"),
    "AestheticGradient": ("embeddings", "embeddings"),
    "Poses":             ("controlnet", "controlnet"),
}

# Some CivitAI baseModels hint at diffusion_models instead of checkpoints
_DIFFUSION_BASE_MODELS = {"Flux.1 D", "Flux.1 S", "Wan Video", "Hunyuan Video", "LTX Video", "CogVideoX"}


def _civitai_to_catalog_entry(ver_data: dict) -> dict:
    """Build a models.json entry from CivitAI model-version API response."""
    model_info = ver_data.get("model", {})
    model_type = model_info.get("type", "Checkpoint")
    base_model = ver_data.get("baseModel", "")

    # Pick category and dest
    cat_id, dest = _TYPE_TO_CATEGORY.get(model_type, ("checkpoints", "checkpoints"))

    # Diffusion models override: some base models go to diffusion_models instead of checkpoints
    if cat_id == "checkpoints" and base_model in _DIFFUSION_BASE_MODELS:
        cat_id = "diffusion_models"
        dest = "diffusion_models"

    # Pick the primary file
    files = ver_data.get("files", [])
    primary = next((f for f in files if f.get("primary")), files[0] if files else {})
    filename = primary.get("name", "")
    size_kb = primary.get("sizeKB", 0)
    fp = primary.get("metadata", {}).get("fp", "")

    # Clean name: "ModelName VersionName [BaseModel FP]"
    model_name = model_info.get("name", "")
    ver_name = ver_data.get("name", "")
    name_parts = [model_name]
    if ver_name and ver_name.lower() != model_name.lower():
        name_parts.append(ver_name)
    suffix = base_model
    if fp:
        suffix += f" {fp.upper()}"
    name = " ".join(name_parts) + f" [{suffix}]" if suffix else " ".join(name_parts)

    entry = {
        "name": name,
        "file": filename,
        "dest": dest,
        "source": "civitai",
        "civitai_version_id": ver_data.get("id"),
        "civitai_model_id": ver_data.get("modelId"),
        "civitai_file_id": primary.get("id"),
        "size_gb": round(size_kb / 1_000_000, 3),
        "base_model": base_model,
        "tags": [],
    }

    trigger = ver_data.get("trainedWords", [])
    if trigger:
        entry["trigger_words"] = trigger

    stats = ver_data.get("stats", {})
    if stats.get("downloadCount"):
        entry["downloads"] = stats["downloadCount"]

    sha = primary.get("hashes", {}).get("SHA256", "")
    if sha:
        entry["hash"] = sha

    return entry, cat_id


def _save_models_json():
    """Persist _models_data to disk."""
    now = datetime.now(timezone(timedelta(hours=2)))
    _catalogs._models_data["version"] = _catalogs._models_data.get("version", 0) + 1
    _catalogs._models_data["date"] = now.strftime("%Y-%m-%d %H:%M")
    MODELS_JSON.parent.mkdir(parents=True, exist_ok=True)
    MODELS_JSON.write_text(json.dumps(_catalogs._models_data, indent=2, ensure_ascii=False))


def _save_loras_json():
    """Persist _loras_data to disk."""
    now = datetime.now(timezone(timedelta(hours=2)))
    _catalogs._loras_data["version"] = _catalogs._loras_data.get("version", 0) + 1
    _catalogs._loras_data["date"] = now.strftime("%Y-%m-%d %H:%M")
    LORAS_JSON.parent.mkdir(parents=True, exist_ok=True)
    LORAS_JSON.write_text(json.dumps(_catalogs._loras_data, indent=2, ensure_ascii=False))


@router.post("/api/admin/civitai/add/{version_id}")
async def add_from_civitai(version_id: int):
    """Fetch a CivitAI model version and add it to models.json catalog (no download)."""
    # Check not already in catalog
    _catalogs._reload_models()
    existing = set()
    for cat in _catalogs._models_data.get("categories", []):
        for m in cat.get("models", []):
            if m.get("civitai_version_id") == version_id:
                return JSONResponse({"status": "already_exists", "file": m.get("file", "")})
            existing.add(m.get("file", ""))

    # Fetch from CivitAI
    url = f"https://civitai.com/api/v1/model-versions/{version_id}"
    civitai_key = os.environ.get("CIVITAI_API_KEY", "")
    headers = {}
    if civitai_key:
        headers["Authorization"] = f"Bearer {civitai_key}"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            ver_data = resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"CivitAI API returned {e.response.status_code}")
    except httpx.RequestError as e:
        raise HTTPException(502, f"Failed to reach CivitAI: {str(e)}")

    # Check download restriction
    usage_control = ver_data.get("usageControl", "")
    if usage_control and usage_control != "Download":
        return JSONResponse({"status": "restricted", "reason": f"This model is '{usage_control}' only — download not allowed by the creator"}, status_code=200)

    entry, cat_id = _civitai_to_catalog_entry(ver_data)

    if entry["file"] in existing:
        return JSONResponse({"status": "already_exists", "file": entry["file"]})

    # Find or create category
    cat_map = {c["id"]: c for c in _catalogs._models_data.get("categories", [])}
    if cat_id not in cat_map:
        new_cat = {"id": cat_id, "name": cat_id.replace("_", " ").title(), "models": []}
        _catalogs._models_data.setdefault("categories", []).append(new_cat)
        cat_map[cat_id] = new_cat

    cat_map[cat_id]["models"].append(entry)
    _save_models_json()

    return JSONResponse({"status": "added", "file": entry["file"], "name": entry["name"],
                         "category": cat_id, "dest": entry["dest"]})


@router.post("/api/admin/civitai/promote-to-lora/{version_id}")
async def promote_to_style_lora(version_id: int):
    """Move a LoRA from models.json to loras.json (promote to style LoRA)."""
    _catalogs._reload_models()

    # Find the entry in models.json
    found_entry = None
    found_cat = None
    for cat in _catalogs._models_data.get("categories", []):
        for m in cat.get("models", []):
            if m.get("civitai_version_id") == version_id:
                found_entry = m
                found_cat = cat
                break
        if found_entry:
            break

    if not found_entry:
        raise HTTPException(404, "Version not found in models catalog")

    if found_entry.get("dest") != "loras":
        raise HTTPException(400, "Only LoRA entries can be promoted to style LoRAs")

    # Check not already in loras.json
    for cat in _catalogs._loras_data.get("categories", []):
        for m in cat.get("models", []):
            if m.get("civitai_version_id") == version_id:
                return JSONResponse({"status": "already_exists"})

    # Determine loras.json category by base_model
    base = found_entry.get("base_model", "")
    lora_cat_id = "other_loras"
    lora_cat_name = "Other LoRAs"
    base_lower = base.lower()
    if "wan" in base_lower:
        lora_cat_id, lora_cat_name = "wan_loras", "WAN LoRAs"
    elif "flux" in base_lower:
        lora_cat_id, lora_cat_name = "flux_loras", "Flux LoRAs"
    elif "sdxl" in base_lower or "pony" in base_lower or "illustrious" in base_lower:
        lora_cat_id, lora_cat_name = "sdxl_loras", "SDXL / Pony / Illustrious LoRAs"
    elif "sd 1" in base_lower or "sd1" in base_lower:
        lora_cat_id, lora_cat_name = "sd15_loras", "SD 1.5 LoRAs"

    # Add to loras.json
    lora_cat_map = {c["id"]: c for c in _catalogs._loras_data.get("categories", [])}
    if lora_cat_id not in lora_cat_map:
        new_cat = {"id": lora_cat_id, "name": lora_cat_name, "models": []}
        _catalogs._loras_data.setdefault("categories", []).append(new_cat)
        lora_cat_map[lora_cat_id] = new_cat

    lora_cat_map[lora_cat_id]["models"].append(dict(found_entry))

    # Remove from models.json
    found_cat["models"].remove(found_entry)

    _save_models_json()
    _save_loras_json()

    return JSONResponse({"status": "promoted", "file": found_entry.get("file", ""),
                         "category": lora_cat_id})


@router.post("/api/admin/civitai/download-asset/{image_id}")
async def download_civitai_asset(image_id: int):
    """Download a CivitAI image/video asset to the gallery flat store.

    Reuses the existing gallery download infrastructure (_gallery_download_one).
    Returns the local file path for linking in presets.
    """
    # Check if already downloaded
    iid = str(image_id)
    if _gdb.image_exists(iid):
        row = _gdb.get_image(iid)
        return JSONResponse({
            "status": "exists",
            "file_path": row["file_path"] if row else None,
            "thumb_path": row.get("thumb_path") if row else None,
        })

    # Fetch image info from CivitAI REST API to get the URL
    civitai_key = os.environ.get("CIVITAI_API_KEY", "")
    headers = {"Authorization": f"Bearer {civitai_key}"} if civitai_key else {}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://civitai.com/api/v1/images?imageId={image_id}&limit=1",
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"CivitAI API error: {e}")

    items = data.get("items", [])
    if not items:
        raise HTTPException(404, "Image not found on CivitAI")

    img = items[0]
    url = img.get("url", "")
    if not url:
        raise HTTPException(404, "No URL for this image")

    img_type = img.get("type", "image")
    file_uuid = _url_to_id(url)

    # Find model_id from the image's posted model (use 0 as fallback for unlinked images)
    posted_model_id = 0
    if img.get("meta") and isinstance(img["meta"], dict):
        # REST meta sometimes has model info
        pass

    meta = {
        "_source": "community",
        "type": img_type,
        "civitai_id": iid,
        "url": url,
        "width": img.get("width"),
        "height": img.get("height"),
    }

    # Download using existing gallery infrastructure (sync, in a thread)
    stop = threading.Event()
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            _gallery_download_one,
            iid, url, meta,
            posted_model_id, None,
            False, stop,
        )
        result = future.result(timeout=60)

    if result == "failed":
        raise HTTPException(502, "Failed to download asset")

    # Get the saved file info from DB
    row = _gdb.get_image(iid)
    return JSONResponse({
        "status": "downloaded" if result == "ok" else result,
        "file_path": row["file_path"] if row else None,
        "thumb_path": row.get("thumb_path") if row else None,
    })
