"""
ComfyUI Studio — Model Manager
FastAPI backend for managing ComfyUI model downloads with a parallel download
pool, per-download speed tracking, SSE progress streaming, and HTTP Basic Auth.
"""

import asyncio
import json
import os
import secrets
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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


# ── HTML pages ───────────────────────────────────────────────────────────────

@app.get("/admin/models", response_class=HTMLResponse)
async def serve_admin_models(_: HTTPBasicCredentials = Depends(require_auth)):
    return HTMLResponse(_www("index.html").read_text())


@app.get("/admin", response_class=HTMLResponse)
async def serve_admin(_: HTTPBasicCredentials = Depends(require_auth)):
    return HTMLResponse(_www("index.html").read_text())
