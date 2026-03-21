"""
ComfyUI Studio — Model Manager
FastAPI backend for managing ComfyUI model downloads with a parallel download
pool, per-download speed tracking, SSE progress streaming, and HTTP Basic Auth.
"""

import asyncio
import glob
import json
import os
import random
import secrets
import shutil
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import httpx
import requests
import yaml  # requires: pyyaml
from fastapi import Depends, FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="ComfyUI Studio — Model Manager")

# ── Configuration ────────────────────────────────────────────────────────────

API_KEY = os.environ.get("API_KEY", "changeme")
CIVITAI_API_KEY = os.environ.get("CIVITAI_API_KEY", "")
HF_TOKEN = os.environ.get("HF_TOKEN", "")

COMFYUI_DIR = os.environ.get("COMFYUI_DIR", "/workspace/ComfyUI")
MODELS_BASE = os.path.join(COMFYUI_DIR, "models")

MODELS_JSON = Path("/workspace/models.json")
MODELS_JSON_DEFAULT = Path("/app/models.json")

WWW_ROOT = Path("/workspace/www")
WWW_DEFAULT = Path("/app/www")

COMFY_URL = "http://127.0.0.1:8188"

MODELS_REPO = os.environ.get(
    "MODELS_REPO",
    "https://raw.githubusercontent.com/diego-devita/comfyui-studio/main/app/models.json",
)

# Paths for workflows
WORKFLOWS_DIR = Path("/workspace/workflows")
WORKFLOWS_DIR_DEFAULT = Path("/app/workflows")

# ── Auth ─────────────────────────────────────────────────────────────────────
# All endpoints except /api/health require HTTP Basic Auth.
# Username: anything — Password: must match API_KEY.

security = HTTPBasic()


def require_auth(credentials: HTTPBasicCredentials = Depends(security)):
    if not secrets.compare_digest(credentials.password.encode(), API_KEY.encode()):
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials


# ── Models catalog ───────────────────────────────────────────────────────────


def _load_models() -> dict:
    """Load models.json, preferring /workspace override. Returns empty structure on failure."""
    models_file = MODELS_JSON if MODELS_JSON.exists() else MODELS_JSON_DEFAULT
    try:
        return json.loads(models_file.read_text())
    except Exception:
        return {"categories": []}


_models_data: dict = _load_models()


def _reload_models() -> None:
    """Reload models catalog from disk (allows hot-reload without restart)."""
    global _models_data
    _models_data = _load_models()


def _find_model(filename: str) -> dict | None:
    """Find a model entry by filename across all categories."""
    for cat in _models_data.get("categories", []):
        for m in cat.get("models", []):
            if m["file"] == filename:
                return m
    return None


# ── Static files helper ─────────────────────────────────────────────────────


def _www(filename: str) -> Path:
    """Resolve a www file, preferring /workspace/www override."""
    p = WWW_ROOT / filename
    if p.exists():
        return p
    return WWW_DEFAULT / filename


# ── Download state & parallel pool ──────────────────────────────────────────
# In-memory state, resets on process restart.
# filename -> {"status": "queued"|"downloading"|"done"|"error",
#              "bytes": int, "total": int, "speed": float, "error": str|None,
#              "_last_bytes": int, "_last_time": float}

_download_state: dict = {}

_max_concurrent = int(os.environ.get("MAX_CONCURRENT_DOWNLOADS", "3"))
_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="dl")
_pending_queue: list[dict] = []  # ordered list of model dicts waiting to download
_active_count = 0
_queue_lock = threading.Lock()


def _inject_auth(url: str) -> tuple[str, dict]:
    """
    Inject authentication for known model hosts.
    Returns (possibly modified url, extra headers dict).
    """
    headers: dict = {}

    if "civitai.com/api/download" in url and CIVITAI_API_KEY:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}token={CIVITAI_API_KEY}"

    if "huggingface.co" in url and HF_TOKEN:
        headers["Authorization"] = f"Bearer {HF_TOKEN}"

    return url, headers


def _schedule_downloads() -> None:
    """
    Scheduler: submit pending downloads to the executor up to _max_concurrent.
    Must be called with _queue_lock held.
    """
    global _active_count
    while _active_count < _max_concurrent and _pending_queue:
        item = _pending_queue.pop(0)
        _active_count += 1
        _executor.submit(_do_download, item)


def _on_download_complete() -> None:
    """Called when a download finishes (success or error). Decrements active count
    and tries to schedule more pending downloads."""
    global _active_count
    with _queue_lock:
        _active_count -= 1
        _schedule_downloads()


def _do_download(item: dict) -> None:
    """
    Download a single model file. Submitted to the thread pool executor.
    Writes to a .tmp file during transfer and renames on success.
    Updates _download_state with byte progress and rolling speed every 8 MB chunk.
    """
    filename = item["file"]
    dest_dir = Path(MODELS_BASE) / item["dest"]
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_file = dest_dir / filename
    tmp_file = dest_dir / f"{filename}.tmp"

    now = time.time()
    _download_state[filename] = {
        "status": "downloading",
        "bytes": 0,
        "total": 0,
        "speed": 0.0,
        "error": None,
        "_last_bytes": 0,
        "_last_time": now,
    }

    url, headers = _inject_auth(item["url"])

    try:
        with requests.get(url, stream=True, timeout=60, allow_redirects=True, headers=headers) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", 0))
            state = _download_state[filename]
            state["total"] = total

            written = 0
            with open(tmp_file, "wb") as f:
                for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):  # 8 MB
                    if chunk:
                        f.write(chunk)
                        written += len(chunk)
                        state["bytes"] = written

                        # Update rolling speed estimate (approx every 1 second)
                        now = time.time()
                        elapsed = now - state["_last_time"]
                        if elapsed >= 1.0:
                            state["speed"] = (state["bytes"] - state["_last_bytes"]) / elapsed
                            state["_last_bytes"] = state["bytes"]
                            state["_last_time"] = now

        # Atomic rename on success
        tmp_file.rename(dest_file)
        final_size = dest_file.stat().st_size
        _download_state[filename] = {
            "status": "done",
            "bytes": final_size,
            "total": total,
            "speed": 0.0,
            "error": None,
            "_last_bytes": 0,
            "_last_time": 0.0,
        }

    except Exception as e:
        if tmp_file.exists():
            tmp_file.unlink()
        _download_state[filename] = {
            "status": "error",
            "bytes": 0,
            "total": 0,
            "speed": 0.0,
            "error": str(e),
            "_last_bytes": 0,
            "_last_time": 0.0,
        }

    finally:
        _on_download_complete()


def _enqueue_download(model: dict) -> None:
    """Add a model to the pending queue and trigger the scheduler."""
    filename = model["file"]
    _download_state[filename] = {
        "status": "queued",
        "bytes": 0,
        "total": 0,
        "speed": 0.0,
        "error": None,
        "_last_bytes": 0,
        "_last_time": 0.0,
    }
    with _queue_lock:
        _pending_queue.append(model)
        _schedule_downloads()


def _clean_state(state: dict) -> dict:
    """Return a copy of a download state dict with internal fields stripped out."""
    return {k: v for k, v in state.items() if not k.startswith("_")}


# ── Request schemas ──────────────────────────────────────────────────────────


class BatchDownloadRequest(BaseModel):
    filenames: list[str]


class SettingsUpdate(BaseModel):
    max_concurrent: int = None


# ── Endpoints ────────────────────────────────────────────────────────────────

# Health check — no auth required
@app.get("/api/health")
async def health():
    return {"status": "ok"}


# List all models with current status and global stats
@app.get("/api/admin/models")
async def models_list(_: HTTPBasicCredentials = Depends(require_auth)):
    _reload_models()

    result_categories = []
    for cat in _models_data.get("categories", []):
        models_out = []
        for m in cat.get("models", []):
            filename = m["file"]
            dest_path = Path(MODELS_BASE) / m["dest"] / filename
            state = _download_state.get(filename)

            # Determine status, progress, and byte counts
            entry = {
                "name": m.get("name", ""),
                "file": filename,
                "dest": m.get("dest", ""),
                "url": m.get("url", ""),
                "source": m.get("source", ""),
                "size_gb": m.get("size_gb", 0),
                "tags": m.get("tags", []),
                "status": "missing",
                "progress": 0.0,
                "on_disk_bytes": 0,
                "expected_bytes": int(m.get("size_gb", 0) * 1_000_000_000),
                "speed": 0.0,
                "error": None,
            }

            if state and state.get("status") == "downloading":
                entry["status"] = "downloading"
                entry["on_disk_bytes"] = state["bytes"]
                entry["expected_bytes"] = state["total"] or entry["expected_bytes"]
                entry["speed"] = state.get("speed", 0.0)
                if state["total"] > 0:
                    entry["progress"] = round(state["bytes"] / state["total"] * 100, 1)
                else:
                    entry["progress"] = None

            elif state and state.get("status") == "error":
                entry["status"] = "error"
                entry["error"] = state.get("error", "")

            elif state and state.get("status") == "queued":
                entry["status"] = "queued"

            elif dest_path.exists():
                on_disk = dest_path.stat().st_size
                entry["status"] = "present"
                entry["progress"] = 100.0
                entry["on_disk_bytes"] = on_disk
                entry["expected_bytes"] = on_disk

            # else: remains "missing"

            models_out.append(entry)

        result_categories.append({
            "id": cat.get("id", ""),
            "name": cat.get("name", ""),
            "models": models_out,
        })

    # ── Compute stats ────────────────────────────────────────────────────
    queued_count = sum(1 for s in _download_state.values() if s.get("status") == "queued")
    downloading_count = sum(1 for s in _download_state.values() if s.get("status") == "downloading")
    global_speed = sum(s.get("speed", 0) for s in _download_state.values() if s.get("status") == "downloading")

    # Disk usage
    try:
        usage = shutil.disk_usage(str(MODELS_BASE))
        models_bytes = sum(f.stat().st_size for f in Path(MODELS_BASE).rglob("*") if f.is_file())
        free_bytes = usage.free
    except Exception:
        models_bytes = 0
        free_bytes = 0

    # Count present/missing from the response data
    present_count = sum(1 for cat in result_categories for m in cat["models"] if m["status"] == "present")
    total_count = sum(len(cat["models"]) for cat in result_categories)

    return JSONResponse({
        "version": _models_data.get("version", "0.0.0"),
        "date": _models_data.get("date", ""),
        "stats": {
            "queued_count": queued_count,
            "downloading_count": downloading_count,
            "present_count": present_count,
            "total_count": total_count,
            "global_speed": global_speed,
            "models_bytes": models_bytes,
            "free_bytes": free_bytes,
        },
        "categories": result_categories,
    })


# Queue a single model download
@app.post("/api/admin/models/download/{filename}")
async def models_download(
    filename: str,
    _: HTTPBasicCredentials = Depends(require_auth),
):
    _reload_models()
    model = _find_model(filename)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{filename}' not found in catalog")

    # Idempotent: if already in progress or queued, return current status
    state = _download_state.get(filename, {})
    if state.get("status") in ("downloading", "queued"):
        return JSONResponse({"status": state["status"], "file": filename})

    # Enqueue via the parallel pool scheduler
    _enqueue_download(model)
    return JSONResponse({"status": "queued", "file": filename})


# Queue multiple model downloads at once
@app.post("/api/admin/models/download-batch")
async def models_download_batch(
    body: BatchDownloadRequest,
    _: HTTPBasicCredentials = Depends(require_auth),
):
    _reload_models()
    queued = []
    skipped = []

    for filename in body.filenames:
        model = _find_model(filename)
        if not model:
            skipped.append(filename)
            continue

        state = _download_state.get(filename, {})
        if state.get("status") in ("downloading", "queued"):
            skipped.append(filename)
            continue

        _enqueue_download(model)
        queued.append(filename)

    return JSONResponse({"queued": queued, "skipped": skipped})


# SSE stream of download progress
@app.get("/api/admin/models/status")
async def models_status(_: HTTPBasicCredentials = Depends(require_auth)):

    async def event_stream():
        while True:
            downloads = {}
            for filename, state in _download_state.items():
                downloads[filename] = _clean_state(state)
            payload = json.dumps({"downloads": downloads, "timestamp": time.time()})
            yield f"data: {payload}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# Delete a model file from disk
@app.delete("/api/admin/models/{filename}")
async def models_delete(
    filename: str,
    _: HTTPBasicCredentials = Depends(require_auth),
):
    _reload_models()
    model = _find_model(filename)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{filename}' not found in catalog")

    dest_path = Path(MODELS_BASE) / model["dest"] / filename

    if dest_path.exists():
        dest_path.unlink()

    # Clear error state so the model shows as "missing" again
    if filename in _download_state:
        state = _download_state[filename]
        if state.get("status") in ("error", "done"):
            del _download_state[filename]

    return JSONResponse({"status": "deleted", "file": filename})


# ── Settings endpoints ───────────────────────────────────────────────────────

@app.get("/api/admin/settings")
async def get_settings(_: HTTPBasicCredentials = Depends(require_auth)):
    return {"max_concurrent": _max_concurrent}


@app.put("/api/admin/settings")
async def update_settings(body: SettingsUpdate, _=Depends(require_auth)):
    global _max_concurrent
    if body.max_concurrent is not None:
        _max_concurrent = max(1, min(10, body.max_concurrent))
        with _queue_lock:
            _schedule_downloads()  # might start more downloads
    return {"max_concurrent": _max_concurrent}


# Sync models catalog from remote repo
@app.post("/api/admin/models/sync")
async def sync_models(_=Depends(require_auth)):
    """Fetch the latest models.json from the configured MODELS_REPO."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(MODELS_REPO)
            r.raise_for_status()
            remote = r.json()

        remote_version = remote.get("version", "0.0.0")
        local_version = _models_data.get("version", "0.0.0")

        if remote_version > local_version:
            # Write to /workspace so it persists and overrides the baked-in version
            MODELS_JSON.parent.mkdir(parents=True, exist_ok=True)
            MODELS_JSON.write_text(json.dumps(remote, indent=2, ensure_ascii=False))
            _reload_models()
            return {
                "status": "updated",
                "old_version": local_version,
                "new_version": remote_version,
                "new_date": remote.get("date", ""),
            }
        else:
            return {
                "status": "up_to_date",
                "version": local_version,
            }
    except Exception as e:
        raise HTTPException(500, f"Sync failed: {str(e)}")


# ── Workflow helpers ──────────────────────────────────────────────────────────


def _workflows_path(subpath: str) -> Path:
    """Resolve a workflow subpath: /workspace/workflows first, /app/workflows fallback."""
    p = WORKFLOWS_DIR / subpath
    if p.exists():
        return p
    return WORKFLOWS_DIR_DEFAULT / subpath


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
        return {"version": "0.0.0", "date": "", "workflows": []}
    return json.loads(p.read_text())


def _load_workflows_index() -> list:
    """Load just the workflows list from index.json."""
    return _load_workflows_index_raw().get("workflows", [])


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
    # First try to find dest from models.json
    _reload_models()
    for cat in _models_data.get("categories", []):
        for m in cat.get("models", []):
            if m["file"] == filename:
                dest_path = Path(MODELS_BASE) / m["dest"] / m["file"]
                return dest_path.exists()
    # Fallback: search recursively
    for p in Path(MODELS_BASE).rglob(filename):
        if p.is_file():
            return True
    return False


# ── Workflow Manager endpoints ───────────────────────────────────────────────


@app.get("/api/admin/workflows")
async def list_workflows(_=Depends(require_auth)):
    index_raw = _load_workflows_index_raw()
    index = index_raw.get("workflows", [])
    installed_nodes = await _get_installed_nodes()

    result = []
    for entry in index:
        manifest = _load_manifest(entry["id"])
        if not manifest:
            continue

        # Check models
        required_models = manifest.get("required_models", [])
        missing_models = [m for m in required_models if not _check_model_exists(m)]

        # Check nodes
        required_nodes = manifest.get("required_nodes", [])
        missing_nodes = [n for n in required_nodes if n not in installed_nodes]

        ready = len(missing_models) == 0 and len(missing_nodes) == 0

        result.append({
            "id": manifest["id"],
            "name": manifest["name"],
            "version": manifest.get("version", "0.0.0"),
            "date": manifest.get("date", ""),
            "description": manifest.get("description", ""),
            "author": manifest.get("author", ""),
            "inputs": manifest.get("inputs", []),
            "outputs": manifest.get("outputs", []),
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
        "version": index_raw.get("version", "0.0.0"),
        "date": index_raw.get("date", ""),
        "workflows": result,
    }


@app.get("/api/admin/workflows/{workflow_id}")
async def get_workflow(workflow_id: str, _=Depends(require_auth)):
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


@app.post("/api/admin/workflows/{workflow_id}/install-models")
async def install_workflow_models(workflow_id: str, _=Depends(require_auth)):
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


@app.post("/api/admin/workflows/sync")
async def sync_workflows(_=Depends(require_auth)):
    REPO_BASE = os.environ.get(
        "WORKFLOWS_REPO",
        "https://raw.githubusercontent.com/diego-devita/comfyui-studio/main/workflows",
    )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Fetch remote index
            r = await client.get(f"{REPO_BASE}/index.json")
            r.raise_for_status()
            remote_index = r.json().get("workflows", [])

            # Load local index
            local_index = {e["id"]: e for e in _load_workflows_index()}

            updated = []
            for remote in remote_index:
                wf_id = remote["id"]
                local = local_index.get(wf_id)
                if not local or remote["version"] > local["version"]:
                    # Ensure workspace directory for this workflow
                    wf_dir = WORKFLOWS_DIR / wf_id
                    wf_dir.mkdir(parents=True, exist_ok=True)

                    # Download manifest.yaml
                    mr = await client.get(f"{REPO_BASE}/{wf_id}/manifest.yaml")
                    mr.raise_for_status()
                    (wf_dir / "manifest.yaml").write_text(mr.text)

                    # Download workflow.json
                    wr = await client.get(f"{REPO_BASE}/{wf_id}/workflow.json")
                    if wr.status_code == 200:
                        (wf_dir / "workflow.json").write_text(wr.text)

                    updated.append(wf_id)

            # Update local index
            if updated:
                WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
                idx_r = await client.get(f"{REPO_BASE}/index.json")
                if idx_r.status_code == 200:
                    (WORKFLOWS_DIR / "index.json").write_text(idx_r.text)

            return {"updated": updated, "checked": len(remote_index)}
    except Exception as e:
        raise HTTPException(500, f"Sync failed: {str(e)}")


# ── Node Manager endpoints ───────────────────────────────────────────────────


@app.get("/api/admin/nodes")
async def list_nodes(_=Depends(require_auth)):
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{COMFY_URL}/object_info")
            r.raise_for_status()
            object_info = r.json()
    except Exception as e:
        raise HTTPException(503, f"ComfyUI unreachable: {str(e)}")

    # Group nodes by package using cnr_id or python_module
    packages = {}
    for node_name, node_info in object_info.items():
        # Try to determine package from node info
        pkg_name = "ComfyUI Core"
        if isinstance(node_info, dict):
            # Modern ComfyUI includes python_module
            module = node_info.get("python_module", "")
            if "custom_nodes" in module:
                parts = module.split(".")
                idx = parts.index("custom_nodes") if "custom_nodes" in parts else -1
                if idx >= 0 and idx + 1 < len(parts):
                    pkg_name = parts[idx + 1]
            elif module.startswith("nodes"):
                pkg_name = "ComfyUI Core"

        if pkg_name not in packages:
            packages[pkg_name] = {"name": pkg_name, "nodes": [], "node_count": 0}
        packages[pkg_name]["nodes"].append(node_name)
        packages[pkg_name]["node_count"] += 1

    # Sort packages by name, nodes within each package
    pkg_list = sorted(packages.values(), key=lambda p: p["name"])
    for pkg in pkg_list:
        pkg["nodes"].sort()

    return {
        "packages": pkg_list,
        "total_nodes": len(object_info),
        "total_packages": len(pkg_list),
    }


@app.post("/api/admin/nodes/install")
async def install_node(body: dict, _=Depends(require_auth)):
    repo_url = body.get("repo_url", "").strip()
    if not repo_url or not repo_url.startswith("https://"):
        raise HTTPException(400, "Invalid repo URL")

    custom_nodes_dir = Path(COMFYUI_DIR) / "custom_nodes"
    custom_nodes_dir.mkdir(parents=True, exist_ok=True)

    # Extract repo name
    name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
    dest = custom_nodes_dir / name

    if dest.exists():
        return {"status": "already_installed", "name": name}

    try:
        # Clone
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(dest)],
            check=True, capture_output=True, text=True, timeout=120
        )

        # Install requirements
        req = dest / "requirements.txt"
        if req.exists():
            subprocess.run(
                ["pip", "install", "-r", str(req)],
                check=True, capture_output=True, text=True, timeout=300
            )

        # Run install.py if exists
        install_py = dest / "install.py"
        if install_py.exists():
            subprocess.run(
                ["python", str(install_py)],
                check=True, capture_output=True, text=True, timeout=300,
                cwd=str(dest)
            )

        return {"status": "installed", "name": name, "restart_required": True}
    except subprocess.CalledProcessError as e:
        # Clean up on failure
        if dest.exists():
            import shutil as sh
            sh.rmtree(dest, ignore_errors=True)
        raise HTTPException(500, f"Installation failed: {e.stderr[:500]}")
    except subprocess.TimeoutExpired:
        if dest.exists():
            import shutil as sh
            sh.rmtree(dest, ignore_errors=True)
        raise HTTPException(500, "Installation timed out")


# ── Workflow Runner endpoints ────────────────────────────────────────────────


@app.get("/api/run/{workflow_id}")
async def get_runner_manifest(workflow_id: str, _=Depends(require_auth)):
    index = _load_workflows_index()
    entry = next((e for e in index if e["id"] == workflow_id), None)
    if not entry:
        raise HTTPException(404)
    manifest = _load_manifest(entry["id"])
    if not manifest:
        raise HTTPException(404)
    return manifest


@app.post("/api/run/{workflow_id}/execute")
async def execute_workflow(
    workflow_id: str,
    _=Depends(require_auth),
    input_image: Optional[UploadFile] = File(None),
    params: str = Form("{}"),
):
    # Load manifest and workflow
    index = _load_workflows_index()
    entry = next((e for e in index if e["id"] == workflow_id), None)
    if not entry:
        raise HTTPException(404)

    manifest = _load_manifest(entry["id"])
    if not manifest:
        raise HTTPException(404)

    workflow = _load_workflow_json(workflow_id)
    if not workflow:
        raise HTTPException(404, "Workflow JSON not found")
    form_params = json.loads(params)

    # Upload image to ComfyUI if provided
    if input_image:
        image_bytes = await input_image.read()
        ext = input_image.filename.rsplit(".", 1)[-1] if "." in (input_image.filename or "") else "png"
        unique_name = f"{uuid.uuid4().hex}.{ext}"

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{COMFY_URL}/upload/image",
                files={"image": (unique_name, image_bytes, input_image.content_type or "image/png")},
                data={"overwrite": "true"},
            )
            r.raise_for_status()
            uploaded_name = r.json()["name"]

        # Find image input in manifest and set it
        for inp in manifest.get("inputs", []):
            if inp["type"] == "image":
                node_id = str(inp["node_id"])
                field = inp["field"]
                if node_id in workflow:
                    workflow[node_id]["inputs"][field] = uploaded_name

    # Apply form parameters
    for inp in manifest.get("inputs", []):
        if inp["id"] in form_params:
            node_id = str(inp["node_id"])
            field = inp["field"]
            value = form_params[inp["id"]]

            if node_id in workflow:
                # Type casting
                if inp["type"] == "int":
                    value = int(value)
                elif inp["type"] == "float":
                    value = float(value)
                elif inp["type"] == "select":
                    value = int(value) if isinstance(value, str) and value.isdigit() else value
                elif inp["type"] == "seed":
                    value = int(value)
                    if value == -1:
                        value = random.randint(0, 2**53)

                workflow[node_id]["inputs"][field] = value

    # Handle seed -1 for seed type inputs not in form_params
    for inp in manifest.get("inputs", []):
        if inp["type"] == "seed" and inp["id"] not in form_params:
            node_id = str(inp["node_id"])
            field = inp["field"]
            if node_id in workflow:
                current = workflow[node_id]["inputs"].get(field, -1)
                if current == -1:
                    workflow[node_id]["inputs"][field] = random.randint(0, 2**53)

    # Send to ComfyUI
    client_id = uuid.uuid4().hex
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{COMFY_URL}/prompt",
            json={"prompt": workflow, "client_id": client_id},
        )
        r.raise_for_status()
        data = r.json()

    if "error" in data:
        raise HTTPException(400, str(data["error"]))

    return {"prompt_id": data["prompt_id"], "client_id": client_id}


@app.get("/api/run/status/{prompt_id}")
async def run_status(prompt_id: str, _=Depends(require_auth)):
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{COMFY_URL}/history/{prompt_id}")
        r.raise_for_status()
        history = r.json()

    if prompt_id not in history:
        # Check if in queue
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                qr = await client.get(f"{COMFY_URL}/queue")
                qr.raise_for_status()
                queue_data = qr.json()
                running = queue_data.get("queue_running", [])
                pending = queue_data.get("queue_pending", [])

                for item in running:
                    if len(item) > 1 and item[1] == prompt_id:
                        return {"status": "running", "progress": None}
                for item in pending:
                    if len(item) > 1 and item[1] == prompt_id:
                        return {"status": "pending", "progress": None}
        except Exception:
            pass
        return {"status": "pending", "progress": None}

    job = history[prompt_id]
    status_str = job.get("status", {}).get("status_str", "")

    if status_str == "error":
        messages = job.get("status", {}).get("messages", [])
        return {"status": "error", "error": str(messages)}

    # Find outputs
    outputs = job.get("outputs", {})
    result_outputs = {}

    for node_id, node_out in outputs.items():
        # Check for videos
        for key in ("gifs", "videos"):
            if key in node_out and node_out[key]:
                info = node_out[key][0]
                result_outputs["video"] = {
                    "filename": info["filename"],
                    "subfolder": info.get("subfolder", ""),
                    "type": info.get("type", "output"),
                }
                break
        # Check for images
        if "images" in node_out and node_out["images"]:
            info = node_out["images"][0]
            result_outputs["image"] = {
                "filename": info["filename"],
                "subfolder": info.get("subfolder", ""),
                "type": info.get("type", "output"),
            }

    return {
        "status": "completed",
        "outputs": result_outputs,
    }


@app.get("/api/run/result/{prompt_id}")
async def run_result(prompt_id: str, output_type: str = "video", _=Depends(require_auth)):
    # Get status to find the output file
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{COMFY_URL}/history/{prompt_id}")
        r.raise_for_status()
        history = r.json()

    if prompt_id not in history:
        raise HTTPException(404, "Result not ready")

    outputs = history[prompt_id].get("outputs", {})
    file_info = None

    for node_id, node_out in outputs.items():
        for key in ("gifs", "videos"):
            if key in node_out and node_out[key]:
                file_info = node_out[key][0]
                break
        if file_info:
            break
        if "images" in node_out and node_out["images"]:
            file_info = node_out["images"][0]
            break

    if not file_info:
        raise HTTPException(404, "No output found")

    params = {"filename": file_info["filename"], "type": file_info.get("type", "output")}
    if file_info.get("subfolder"):
        params["subfolder"] = file_info["subfolder"]

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.get(f"{COMFY_URL}/view", params=params)
        r.raise_for_status()
        content = r.content

    # Determine content type
    fname = file_info["filename"]
    if fname.endswith(".mp4"):
        media_type = "video/mp4"
    elif fname.endswith(".webm"):
        media_type = "video/webm"
    elif fname.endswith(".png"):
        media_type = "image/png"
    elif fname.endswith(".jpg") or fname.endswith(".jpeg"):
        media_type = "image/jpeg"
    else:
        media_type = "application/octet-stream"

    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )


# ── HTML pages ───────────────────────────────────────────────────────────────

@app.get("/admin/workflows", response_class=HTMLResponse)
async def serve_workflows(_=Depends(require_auth)):
    return HTMLResponse(_www("workflows.html").read_text())


@app.get("/admin/nodes", response_class=HTMLResponse)
async def serve_nodes(_=Depends(require_auth)):
    return HTMLResponse(_www("nodes.html").read_text())


@app.get("/run/{workflow_id}", response_class=HTMLResponse)
async def serve_runner(workflow_id: str, _=Depends(require_auth)):
    return HTMLResponse(_www("runner.html").read_text())


@app.get("/static/{filename}")
async def serve_static(filename: str):
    """Serve static assets (CSS, JS) from www directory — no auth required."""
    p = _www(filename)
    if not p.exists():
        raise HTTPException(404)
    content = p.read_text()
    media = "text/css" if filename.endswith(".css") else "application/javascript"
    return HTMLResponse(content, media_type=media)


@app.get("/admin/models", response_class=HTMLResponse)
async def serve_admin_models(_: HTTPBasicCredentials = Depends(require_auth)):
    return HTMLResponse(_www("index.html").read_text())


@app.get("/admin", response_class=HTMLResponse)
async def serve_admin(_: HTTPBasicCredentials = Depends(require_auth)):
    return HTMLResponse(_www("index.html").read_text())
