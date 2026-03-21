"""
ComfyUI Studio — Model Manager
FastAPI backend for managing ComfyUI model downloads with queue-based
downloading, SSE progress streaming, and HTTP Basic Auth.
"""

import asyncio
import json
import os
import queue
import secrets
import threading
import time
from pathlib import Path

import requests
from fastapi import Depends, FastAPI, HTTPException
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


# ── Download state & queue ───────────────────────────────────────────────────
# In-memory state, resets on process restart.
# filename -> {"status": "queued"|"downloading"|"done"|"error",
#              "bytes": int, "total": int, "error": str}

_download_state: dict = {}
_download_queue: queue.Queue = queue.Queue()


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


def _do_download(item: dict) -> None:
    """
    Download a single model file. Called by the worker thread.
    Writes to a .tmp file during transfer and renames on success.
    Updates _download_state with byte progress every 8 MB chunk.
    """
    filename = item["file"]
    dest_dir = Path(MODELS_BASE) / item["dest"]
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_file = dest_dir / filename
    tmp_file = dest_dir / f"{filename}.tmp"

    _download_state[filename] = {"status": "downloading", "bytes": 0, "total": 0}

    url, headers = _inject_auth(item["url"])

    try:
        with requests.get(url, stream=True, timeout=60, allow_redirects=True, headers=headers) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", 0))
            _download_state[filename]["total"] = total

            written = 0
            with open(tmp_file, "wb") as f:
                for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):  # 8 MB
                    if chunk:
                        f.write(chunk)
                        written += len(chunk)
                        _download_state[filename]["bytes"] = written

        # Atomic rename on success
        tmp_file.rename(dest_file)
        _download_state[filename] = {
            "status": "done",
            "bytes": dest_file.stat().st_size,
            "total": total,
        }

    except Exception as e:
        if tmp_file.exists():
            tmp_file.unlink()
        _download_state[filename] = {
            "status": "error",
            "bytes": 0,
            "total": 0,
            "error": str(e),
        }


def _download_worker() -> None:
    """Background worker that processes the download queue sequentially."""
    while True:
        item = _download_queue.get()
        try:
            _do_download(item)
        except Exception as e:
            _download_state[item["file"]] = {
                "status": "error",
                "bytes": 0,
                "total": 0,
                "error": str(e),
            }
        finally:
            _download_queue.task_done()


# Start the single download worker on module load
threading.Thread(target=_download_worker, daemon=True).start()


# ── Request schemas ──────────────────────────────────────────────────────────


class BatchDownloadRequest(BaseModel):
    filenames: list[str]


# ── Endpoints ────────────────────────────────────────────────────────────────

# Health check — no auth required
@app.get("/api/health")
async def health():
    return {"status": "ok"}


# List all models with current status
@app.get("/api/admin/models")
async def models_list(_: HTTPBasicCredentials = Depends(require_auth)):
    _reload_models()

    categories_out = []
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
                "error": None,
            }

            if state and state.get("status") == "downloading":
                entry["status"] = "downloading"
                entry["on_disk_bytes"] = state["bytes"]
                entry["expected_bytes"] = state["total"] or entry["expected_bytes"]
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

        categories_out.append({
            "id": cat.get("id", ""),
            "name": cat.get("name", ""),
            "models": models_out,
        })

    return JSONResponse({"categories": categories_out})


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

    # Enqueue
    _download_state[filename] = {"status": "queued", "bytes": 0, "total": 0}
    _download_queue.put(model)
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

        _download_state[filename] = {"status": "queued", "bytes": 0, "total": 0}
        _download_queue.put(model)
        queued.append(filename)

    return JSONResponse({"queued": queued, "skipped": skipped})


# SSE stream of download progress
@app.get("/api/admin/models/status")
async def models_status(_: HTTPBasicCredentials = Depends(require_auth)):

    async def event_stream():
        while True:
            downloads = {}
            for filename, state in _download_state.items():
                downloads[filename] = {
                    "status": state.get("status", "unknown"),
                    "bytes": state.get("bytes", 0),
                    "total": state.get("total", 0),
                    "error": state.get("error"),
                }
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


# ── HTML pages ───────────────────────────────────────────────────────────────

@app.get("/admin/models", response_class=HTMLResponse)
async def serve_admin_models(_: HTTPBasicCredentials = Depends(require_auth)):
    return HTMLResponse(_www("index.html").read_text())


@app.get("/admin", response_class=HTMLResponse)
async def serve_admin(_: HTTPBasicCredentials = Depends(require_auth)):
    return HTMLResponse(_www("index.html").read_text())
