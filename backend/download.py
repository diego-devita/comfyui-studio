"""ComfyUI Studio — Download pool, state tracking, URL construction, auth injection."""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from config import MODELS_BASE, CIVITAI_API_KEY, HF_TOKEN

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


def _get_download_url(model: dict) -> str:
    """Construct download URL from model IDs."""
    # Civitai
    vid = model.get("civitai_version_id")
    if vid:
        return f"https://civitai.com/api/download/models/{vid}"
    # HuggingFace
    repo = model.get("hf_repo")
    hf_file = model.get("hf_file")
    if repo and hf_file:
        return f"https://huggingface.co/{repo}/resolve/main/{hf_file}"
    # Legacy fallback
    return model.get("url", "")


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
    from events import _events

    filename = item["file"]
    base_dir = item.get("_base_dir", MODELS_BASE)
    dest_dir = Path(base_dir) / item["dest"] if item.get("dest") else Path(base_dir)
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

    url, headers = _inject_auth(_get_download_url(item))

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
        _events.emit("model.download.completed", f"Downloaded: {filename}", severity="success", data={"filename": filename, "size": final_size})

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
        _events.emit("model.download.failed", f"Download failed: {filename}", severity="error", data={"filename": filename, "error": str(e)})

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
