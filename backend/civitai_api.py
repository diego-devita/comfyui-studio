"""ComfyUI Studio — CivitAI proxy endpoints (generation data, resource cross-reference)."""

from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

import os
from config import MODELS_BASE
import catalogs as _catalogs

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

    return JSONResponse({
        "raw": raw,
        "resources": enriched_resources,
        "meta": meta,
        "type": type_,
        "process": process,
        "techniques": techniques,
        "tools": tools,
        "detected_type": detected_type,
    })
