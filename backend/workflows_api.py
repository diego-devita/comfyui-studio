"""ComfyUI Studio — Workflow list endpoint, readiness check, sync, install models."""

import shutil

from fastapi import APIRouter, HTTPException

from config import REPO_DIR, WORKFLOWS_DIR
from catalogs import _find_model, _reload_models
import db
from download import _enqueue_download
from workflows import (
    _load_workflows_index_raw, _load_workflows_index,
    _load_manifest, _get_installed_nodes, _check_model_exists,
)

router = APIRouter()


@router.get("/api/admin/workflows")
async def list_workflows():
    index_raw = _load_workflows_index_raw()
    index = index_raw.get("workflows", [])
    installed_nodes = await _get_installed_nodes()

    result = []
    for entry in index:
        manifest = _load_manifest(entry["id"])
        if not manifest:
            continue

        required_models = manifest.get("required_models", [])
        missing_models = [m for m in required_models if not _check_model_exists(m)]

        # Check download state from DB for missing models
        dl_records = db.get_downloads_for_files(missing_models) if missing_models else {}
        downloading = [f for f in missing_models if dl_records.get(f, {}).get("status") in ("queued", "downloading")]
        still_missing = [f for f in missing_models if f not in downloading]

        required_nodes = manifest.get("required_nodes", [])
        missing_nodes = [n for n in required_nodes if n not in installed_nodes]

        ready = len(missing_models) == 0 and len(missing_nodes) == 0

        result.append({
            "id": manifest["id"],
            "name": manifest["name"],
            "category": manifest.get("category", ""),
            "type": manifest.get("type", "static"),
            "version": manifest.get("version", 0),
            "date": manifest.get("date", ""),
            "description": manifest.get("description", ""),
            "author": manifest.get("author", ""),
            "inputs": manifest.get("inputs", []),
            "outputs": manifest.get("outputs", []),
            "required_models": required_models,
            "required_nodes": required_nodes,
            "models_status": {
                "total": len(required_models),
                "present": len(required_models) - len(missing_models),
                "missing": still_missing,
                "downloading": downloading,
            },
            "nodes_status": {
                "total": len(required_nodes),
                "installed": len(required_nodes) - len(missing_nodes),
                "missing": missing_nodes,
            },
            "ready": ready,
        })

    return {
        "version": index_raw.get("version", 0),
        "date": index_raw.get("date", ""),
        "workflows": result,
    }


@router.get("/api/admin/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    index = _load_workflows_index()
    entry = next((e for e in index if e["id"] == workflow_id), None)
    if not entry:
        raise HTTPException(404, f"Workflow '{workflow_id}' not found")

    manifest = _load_manifest(entry["id"])
    if not manifest:
        raise HTTPException(404, f"Manifest for '{workflow_id}' not found")

    installed_nodes = await _get_installed_nodes()
    required_models = manifest.get("required_models", [])
    missing_models = [m for m in required_models if not _check_model_exists(m)]
    required_nodes = manifest.get("required_nodes", [])
    missing_nodes = [n for n in required_nodes if n not in installed_nodes]

    return {
        **manifest,
        "models_status": {
            "total": len(required_models),
            "present": len(required_models) - len(missing_models),
            "missing": missing_models,
        },
        "nodes_status": {
            "total": len(required_nodes),
            "installed": len(required_nodes) - len(missing_nodes),
            "missing": missing_nodes,
        },
        "ready": len(missing_models) == 0 and len(missing_nodes) == 0,
    }


@router.post("/api/admin/workflows/{workflow_id}/install-models")
async def install_workflow_models(workflow_id: str):
    index = _load_workflows_index()
    entry = next((e for e in index if e["id"] == workflow_id), None)
    if not entry:
        raise HTTPException(404)

    manifest = _load_manifest(entry["id"])
    if not manifest:
        raise HTTPException(404)

    required_models = manifest.get("required_models", [])
    missing = [m for m in required_models if not _check_model_exists(m)]

    queued = []
    skipped = []
    for filename in missing:
        model = _find_model(filename)
        if model:
            _enqueue_download(model, source=f"workflow:{workflow_id}")
            queued.append(filename)
        else:
            skipped.append(filename)

    return {"queued": queued, "skipped": skipped, "message": f"{len(queued)} models queued for download"}


@router.post("/api/admin/workflows/sync")
async def sync_workflows():
    """Sync workflows from the local git repo clone."""
    try:
        src_dir = REPO_DIR / "workflows"
        if not src_dir.exists():
            raise HTTPException(500, "Repo clone not found — run Check for Updates first")

        import json as _json
        remote_index_data = _json.loads((src_dir / "index.json").read_text())
        remote_index = remote_index_data.get("workflows", [])

        local_index = {e["id"]: e for e in _load_workflows_index()}

        updated = []
        for remote in remote_index:
            wf_id = remote["id"]
            local = local_index.get(wf_id)
            remote_v = remote.get("version", 0)
            local_v = local.get("version", 0) if local else None
            if not local or type(remote_v) != type(local_v) or remote_v > local_v:
                src_wf = src_dir / wf_id
                dest_wf = WORKFLOWS_DIR / wf_id
                if src_wf.exists():
                    if dest_wf.exists():
                        shutil.rmtree(str(dest_wf))
                    shutil.copytree(str(src_wf), str(dest_wf))
                    updated.append(wf_id)

        if updated:
            WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src_dir / "index.json"), str(WORKFLOWS_DIR / "index.json"))

        return {"updated": updated, "checked": len(remote_index)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Sync failed: {str(e)}")
