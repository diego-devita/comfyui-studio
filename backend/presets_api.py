"""ComfyUI Studio — Presets API: save/load/delete/list job presets.

Placeholder syntax in prompts:
  [[question:option1|option2|...]]  → choice (buttons/select)
  [[question]]                      → free text input

Each occurrence is independent (same question in different scenes = separate answers).
"""

import json
import re
from pathlib import Path

from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
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
            entry = {
                "id": data.get("id", f.stem),
                "name": data.get("name", f.stem),
                "description": data.get("description", ""),
                "private": data.get("private", False),
                "workflow_id": data.get("workflow", {}).get("workflow_id", ""),
                "workflow_name": data.get("workflow", {}).get("workflow_name", ""),
            }
            if "source" in data and isinstance(data["source"], dict):
                src = data["source"]
                entry["source_type"] = src.get("type", "")
                entry["civitai_image_id"] = src.get("civitai_image_id")
                entry["civitai_url"] = src.get("civitai_url", "")
                entry["detected_type"] = src.get("detected_type", "")
            presets.append(entry)
        except Exception:
            pass
    return presets


@router.get("/api/admin/presets/{preset_id}")
async def get_preset(preset_id: str):
    """Get a single preset with full params."""
    data = _load_preset(preset_id)
    if not data:
        raise HTTPException(404, f"Preset '{preset_id}' not found")
    data.setdefault("private", False)
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
        "private": bool(body.get("private", False)),
        "workflow": body.get("workflow", {}),
    }
    if body.get("source") and isinstance(body["source"], dict):
        preset["source"] = body["source"]

    p = _presets_dir() / f"{preset_id}.json"
    p.write_text(json.dumps(preset, indent=2, ensure_ascii=False))
    return {"id": preset_id, "message": "Preset saved"}


@router.put("/api/admin/presets/{preset_id}/rename")
async def rename_preset(preset_id: str, request: Request):
    """Update preset name, id, and/or description. Renames file if id changes."""
    body = await request.json()
    data = _load_preset(preset_id)
    if not data:
        raise HTTPException(404)

    new_name = body.get("name", "").strip()
    new_id = body.get("id", "").strip()
    new_desc = body.get("description")

    if new_name:
        data["name"] = new_name
    if new_desc is not None:
        data["description"] = new_desc
    if "private" in body:
        data["private"] = bool(body["private"])

    old_path = _presets_dir() / f"{preset_id}.json"

    if new_id and new_id != preset_id:
        if not re.match(r'^[a-zA-Z0-9_\-]+$', new_id):
            raise HTTPException(400, "ID must be alphanumeric (a-z, 0-9, _, -)")
        new_path = _presets_dir() / f"{new_id}.json"
        if new_path.exists():
            raise HTTPException(409, f"Preset '{new_id}' already exists")
        data["id"] = new_id
        new_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        old_path.unlink()
        return {"id": new_id, "name": data["name"]}

    old_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return {"id": preset_id, "name": data["name"]}


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


# ── Placeholder utilities ──

_PLACEHOLDER_RE = re.compile(r'\[\[(.+?)\]\]')


def extract_placeholders(params: dict) -> list[dict]:
    """Scan params for [[...]] placeholders. Returns list of {index, scene, question, options, raw}."""
    found = []
    idx = 0

    scenes = params.get("scenes", [])
    if scenes:
        for si, scene in enumerate(scenes):
            prompt = scene.get("prompt", "")
            for m in _PLACEHOLDER_RE.finditer(prompt):
                inner = m.group(1)
                if ":" in inner:
                    question, opts_str = inner.split(":", 1)
                    options = [o.strip() for o in opts_str.split("|")]
                else:
                    question = inner
                    options = []
                found.append({
                    "index": idx,
                    "scene": si + 1,
                    "question": question.strip(),
                    "options": options,
                    "raw": m.group(0),
                })
                idx += 1

    # Also check top-level prompt fields
    for key in ("positive_prompt", "negative_prompt"):
        prompt = params.get(key, "")
        if not isinstance(prompt, str):
            continue
        for m in _PLACEHOLDER_RE.finditer(prompt):
            inner = m.group(1)
            if ":" in inner:
                question, opts_str = inner.split(":", 1)
                options = [o.strip() for o in opts_str.split("|")]
            else:
                question = inner
                options = []
            found.append({
                "index": idx,
                "scene": 0,
                "question": question.strip(),
                "options": options,
                "raw": m.group(0),
                "field": key,
            })
            idx += 1

    return found


def apply_placeholders(params: dict, answers: dict) -> dict:
    """Replace placeholders with answers. answers = {index: value}."""
    import copy
    params = copy.deepcopy(params)

    scenes = params.get("scenes", [])
    if scenes:
        for si, scene in enumerate(scenes):
            prompt = scene.get("prompt", "")
            for m in _PLACEHOLDER_RE.finditer(prompt):
                # Find matching answer by scanning
                pass
            # Rebuild with replacements
            def _replace(m):
                # Find this placeholder's index
                for ph in extract_placeholders({"scenes": [{"prompt": scene.get("prompt", "")}]}):
                    pass
                return m.group(0)

    # Simpler approach: sequential replacement
    idx = [0]
    def _replacer(m):
        val = answers.get(str(idx[0]), answers.get(idx[0], m.group(0)))
        idx[0] += 1
        return str(val)

    if scenes:
        for si, scene in enumerate(scenes):
            scene["prompt"] = _PLACEHOLDER_RE.sub(_replacer, scene.get("prompt", ""))

    for key in ("positive_prompt", "negative_prompt"):
        if key in params and isinstance(params[key], str):
            params[key] = _PLACEHOLDER_RE.sub(_replacer, params[key])

    return params


@router.get("/api/admin/presets/{preset_id}/placeholders")
async def get_preset_placeholders(preset_id: str):
    """Extract placeholders from a preset's params."""
    data = _load_preset(preset_id)
    if not data:
        raise HTTPException(404)
    params = data.get("workflow", {}).get("params", {})
    return extract_placeholders(params)


@router.post("/api/admin/presets/{preset_id}/run")
async def run_preset(
    preset_id: str,
    input_image: Optional[UploadFile] = File(None),
    seed: str = Form("-1"),
    answers: str = Form("{}"),
    existing_image: str = Form(""),
):
    """Run a preset. Loads params, applies placeholders, executes job."""
    import copy, httpx, os

    data = _load_preset(preset_id)
    if not data:
        raise HTTPException(404, f"Preset '{preset_id}' not found")

    wf = data.get("workflow", {})
    workflow_id = wf.get("workflow_id", "")
    if not workflow_id:
        raise HTTPException(400, "Preset has no workflow_id")

    params = copy.deepcopy(wf.get("params", {}))
    try:
        params["seed"] = int(seed)
    except (ValueError, TypeError):
        params["seed"] = -1

    try:
        ans = json.loads(answers) if answers and answers != "{}" else {}
    except Exception:
        ans = {}
    if ans:
        params = apply_placeholders(params, ans)

    if existing_image:
        params["_existing_input_image"] = existing_image

    studio_port = os.environ.get("STUDIO_PORT", "8000")
    api_key = os.environ.get("API_KEY", "changeme")

    form_data = {"params": json.dumps(params)}
    files = {}
    if input_image:
        image_bytes = await input_image.read()
        files["input_image"] = (input_image.filename or "input.jpg", image_bytes, input_image.content_type or "image/jpeg")

    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(
            f"http://127.0.0.1:{studio_port}/api/run/{workflow_id}/execute",
            headers={"X-API-Key": api_key},
            data=form_data,
            files=files if files else None,
        )
        if r.status_code != 200:
            raise HTTPException(r.status_code, r.text)
        return r.json()


@router.get("/api/admin/presets/{preset_id}/export")
async def export_preset(preset_id: str):
    """Export a preset as JSON (for download)."""
    data = _load_preset(preset_id)
    if not data:
        raise HTTPException(404)
    data.setdefault("private", False)
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f'attachment; filename="{preset_id}.json"'},
    )
