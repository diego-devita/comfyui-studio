"""ComfyUI Studio — Workflow list endpoint, readiness check, sync, install models."""

import yaml
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from config import COMFY_URL, REPO_BASE, WORKFLOWS_DIR
from catalogs import _find_model, _reload_models
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
                "missing": missing_models,
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
            _enqueue_download(model)
            queued.append(filename)
        else:
            skipped.append(filename)

    return {"queued": queued, "skipped": skipped, "message": f"{len(queued)} models queued for download"}


@router.post("/api/admin/workflows/sync")
async def sync_workflows():
    WORKFLOWS_REPO_BASE = f"{REPO_BASE}/workflows"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{WORKFLOWS_REPO_BASE}/index.json")
            r.raise_for_status()
            remote_index = r.json().get("workflows", [])

            local_index = {e["id"]: e for e in _load_workflows_index()}

            updated = []
            for remote in remote_index:
                wf_id = remote["id"]
                local = local_index.get(wf_id)
                remote_v = remote.get("version", 0)
                local_v = local.get("version", 0) if local else None
                if not local or type(remote_v) != type(local_v) or remote_v > local_v:
                    wf_dir = WORKFLOWS_DIR / wf_id
                    wf_dir.mkdir(parents=True, exist_ok=True)

                    mr = await client.get(f"{WORKFLOWS_REPO_BASE}/{wf_id}/manifest.yaml")
                    mr.raise_for_status()
                    (wf_dir / "manifest.yaml").write_text(mr.text)

                    manifest_data = yaml.safe_load(mr.text) if mr.text else {}
                    if manifest_data.get("type") == "dynamic":
                        blocks_dir_name = manifest_data.get("blocks_dir", "blocks")
                        blocks_dir = wf_dir / blocks_dir_name
                        blocks_dir.mkdir(parents=True, exist_ok=True)
                        for stage in manifest_data.get("pipeline", []):
                            block_file = stage.get("file", "")
                            if block_file:
                                br = await client.get(f"{WORKFLOWS_REPO_BASE}/{wf_id}/{blocks_dir_name}/{block_file}")
                                if br.status_code == 200:
                                    (blocks_dir / block_file).write_text(br.text)
                    else:
                        wr = await client.get(f"{WORKFLOWS_REPO_BASE}/{wf_id}/workflow.json")
                        if wr.status_code == 200:
                            (wf_dir / "workflow.json").write_text(wr.text)

                    updated.append(wf_id)

            if updated:
                WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
                idx_r = await client.get(f"{WORKFLOWS_REPO_BASE}/index.json")
                if idx_r.status_code == 200:
                    (WORKFLOWS_DIR / "index.json").write_text(idx_r.text)

            return {"updated": updated, "checked": len(remote_index)}
    except Exception as e:
        raise HTTPException(500, f"Sync failed: {str(e)}")
