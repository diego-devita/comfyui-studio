"""ComfyUI Studio — Presets API: save/load/delete/list job presets."""

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse

from config import PRESETS_DIR

router = APIRouter()


def _presets_dir():
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    return PRESETS_DIR


def _load_preset(preset_id: str) -> dict:
    p = _presets_dir() / f"{preset_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


@router.get("/api/admin/presets")
async def list_presets():
    """List all saved presets."""
    presets = []
    for f in sorted(_presets_dir().glob("*.json")):
        try:
            data = json.loads(f.read_text())
            presets.append({
                "id": data.get("id", f.stem),
                "name": data.get("name", f.stem),
                "description": data.get("description", ""),
                "workflow_id": data.get("workflow", {}).get("workflow_id", ""),
                "workflow_name": data.get("workflow", {}).get("workflow_name", ""),
            })
        except Exception:
            pass
    return presets


@router.get("/api/admin/presets/{preset_id}")
async def get_preset(preset_id: str):
    """Get a single preset with full params."""
    data = _load_preset(preset_id)
    if not data:
        raise HTTPException(404, f"Preset '{preset_id}' not found")
    return data


@router.post("/api/admin/presets")
async def save_preset(request: Request):
    """Save a new preset. Body: {id, name, description, workflow: {workflow_id, workflow_name, params}}"""
    body = await request.json()
    preset_id = body.get("id", "").strip()
    if not preset_id:
        raise HTTPException(400, "Preset ID is required")
    if not re.match(r'^[a-zA-Z0-9_\-]+$', preset_id):
        raise HTTPException(400, "Preset ID must be alphanumeric (a-z, 0-9, _, -)")

    preset = {
        "id": preset_id,
        "name": body.get("name", preset_id),
        "description": body.get("description", ""),
        "workflow": body.get("workflow", {}),
    }

    p = _presets_dir() / f"{preset_id}.json"
    p.write_text(json.dumps(preset, indent=2, ensure_ascii=False))
    return {"id": preset_id, "message": "Preset saved"}


@router.delete("/api/admin/presets/{preset_id}")
async def delete_preset(preset_id: str):
    """Delete a preset."""
    p = _presets_dir() / f"{preset_id}.json"
    if not p.exists():
        raise HTTPException(404)
    p.unlink()
    return {"ok": True}


@router.post("/api/admin/presets/import")
async def import_preset(file: UploadFile = File(...)):
    """Import a preset from a JSON file."""
    try:
        content = await file.read()
        data = json.loads(content)
    except Exception as e:
        raise HTTPException(400, f"Invalid JSON: {e}")

    preset_id = data.get("id", "")
    if not preset_id:
        raise HTTPException(400, "Preset has no ID")

    p = _presets_dir() / f"{preset_id}.json"
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return {"id": preset_id, "message": "Preset imported"}


@router.get("/api/admin/presets/{preset_id}/export")
async def export_preset(preset_id: str):
    """Export a preset as JSON (for download)."""
    data = _load_preset(preset_id)
    if not data:
        raise HTTPException(404)
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f'attachment; filename="{preset_id}.json"'},
    )
