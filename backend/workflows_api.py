"""ComfyUI Studio — Workflow list endpoint, readiness check, sync, install models."""

import shutil

from fastapi import APIRouter, HTTPException

from config import REPO_DIR, WORKFLOWS_DIR
from catalogs import _find_model, _reload_models
import db
from download import _enqueue_download
from workflows import _load_manifest, _get_installed_nodes, _check_model_exists

router = APIRouter()


@router.get("/api/admin/workflows")
async def list_workflows():
    all_wf = db.list_workflows()
    installed_nodes = await _get_installed_nodes()

    result = []
    for wf in all_wf:
        required_models = wf.get("required_models", [])
        missing_models = [m for m in required_models if not _check_model_exists(m)]

        dl_records = db.get_downloads_for_files(missing_models) if missing_models else {}
        downloading = [f for f in missing_models if dl_records.get(f, {}).get("status") in ("queued", "downloading")]
        still_missing = [f for f in missing_models if f not in downloading]

        required_nodes = wf.get("required_nodes", [])
        missing_nodes = [n for n in required_nodes if n not in installed_nodes]

        ready = len(missing_models) == 0 and len(missing_nodes) == 0

        result.append({
            **wf,
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

    return {"workflows": result}


@router.get("/api/admin/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    wf = db.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, f"Workflow '{workflow_id}' not found")

    installed_nodes = await _get_installed_nodes()
    required_models = wf.get("required_models", [])
    missing_models = [m for m in required_models if not _check_model_exists(m)]
    required_nodes = wf.get("required_nodes", [])
    missing_nodes = [n for n in required_nodes if n not in installed_nodes]

    return {
        **wf,
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
    wf = db.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404)

    required_models = wf.get("required_models", [])
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
    """Sync workflows from the local git repo clone, then re-import into DB."""
    try:
        src_dir = REPO_DIR / "workflows"
        if not src_dir.exists():
            raise HTTPException(500, "Repo clone not found — run Check for Updates first")

        # Compare versions using DB (local) vs manifest files (remote)
        local_wfs = {w["id"]: w for w in db.list_workflows()}

        updated = []
        for wf_dir in sorted(src_dir.iterdir()):
            if not wf_dir.is_dir() or not (wf_dir / "manifest.yaml").exists():
                continue
            import yaml
            with open(wf_dir / "manifest.yaml") as f:
                remote_manifest = yaml.safe_load(f)
            wf_id = remote_manifest.get("id", wf_dir.name)
            remote_v = remote_manifest.get("version", 0)
            local = local_wfs.get(wf_id)
            local_v = local.get("version", 0) if local else None
            if not local or type(remote_v) != type(local_v) or remote_v > local_v:
                dest_wf = WORKFLOWS_DIR / wf_id
                if dest_wf.exists():
                    shutil.rmtree(str(dest_wf))
                shutil.copytree(str(wf_dir), str(dest_wf))
                updated.append(wf_id)

        # Re-sync DB from disk
        if updated:
            db.sync_workflows_from_disk()

        return {"updated": updated}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Sync failed: {str(e)}")
