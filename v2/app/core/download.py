"""Download Scheduler — queued, resumable file downloads with callback delivery.

Manages a pool of worker threads that download files from remote URLs.
Downloads are persisted in SQLite — they survive restarts and support resume.

Flow:
  1. Caller calls enqueue(url, headers, callback, callback_args, ...)
  2. Record created in DB with status='queued'
  3. A worker thread picks it up, sets status='downloading'
  4. File downloaded to V2_DIR/downloads/{id}.partial with streaming
  5. Progress (downloaded_bytes) updated in DB periodically
  6. On completion: callback function called to deliver file to destination store
  7. Status set to 'done', temp file cleaned up
  8. On error: retries up to max_retries, then status='error'

Resume:
  If a partial file exists from a previous attempt, the worker sends
  a Range header to resume from where it left off.

Boot recovery:
  init_scheduler() finds any downloads stuck in 'downloading' status
  (from a crash) and resets them to 'queued' for retry.

Callback registry:
  Modules register delivery functions by name (e.g. "media_store").
  The name is stored in the DB. On completion, the scheduler looks up
  the function by name and calls it with the downloaded file path + args.
"""

import json
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from v2.app.core.db import get_conn, register_schema
from v2.app.core.settings import DOWNLOADS_DIR, MAX_CONCURRENT_DOWNLOADS, now_iso


# ── Callback registry ────────────────────────────────────────────────────────
#
# Modules register their delivery functions here at import time.
# The scheduler calls them when a download completes.
# Names are stored in the DB so they survive restarts.

_callbacks: dict[str, callable] = {}


def register_callback(name: str, func: callable):
    """Register a delivery callback.

    The function receives (file_path: Path, args: dict) and is responsible
    for moving the file into its final destination (e.g. media store, model store).

    Args:
        name: Short name stored in DB (e.g. "media_store", "model_store").
        func: Callable(file_path: Path, args: dict) -> Any.
    """
    _callbacks[name] = func


# ── Schema ───────────────────────────────────────────────────────────────────

def _init_schema(conn: sqlite3.Connection):
    """Create downloads + scheduler_lock tables. Called by db.init_db()."""
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS downloads (
            id              TEXT PRIMARY KEY,
            url             TEXT NOT NULL,
            headers         TEXT,
            callback        TEXT NOT NULL,
            callback_args   TEXT DEFAULT '{}',
            filename        TEXT,
            status          TEXT NOT NULL DEFAULT 'queued'
                            CHECK (status IN ('queued', 'downloading', 'done', 'error', 'cancelled')),
            total_bytes     INTEGER,
            downloaded_bytes INTEGER DEFAULT 0,
            error           TEXT,
            retries         INTEGER DEFAULT 0,
            max_retries     INTEGER DEFAULT 3,
            priority        INTEGER DEFAULT 0,
            created_at      TEXT NOT NULL,
            started_at      TEXT,
            completed_at    TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_dl_status   ON downloads(status);
        CREATE INDEX IF NOT EXISTS idx_dl_priority ON downloads(priority DESC);

        -- Singleton lock: only one scheduler process at a time.
        -- CHECK (id = 1) guarantees at most one row.
        -- heartbeat is updated every poll cycle; if stale (>30s), scheduler is dead.
        CREATE TABLE IF NOT EXISTS scheduler_lock (
            id          INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            pid         INTEGER NOT NULL,
            started_at  TEXT NOT NULL,
            heartbeat   TEXT NOT NULL
        );
    """)


register_schema("download_scheduler", _init_schema)


# ── Scheduler state ──────────────────────────────────────────────────────────

_pool: ThreadPoolExecutor | None = None
_running = False
_poll_thread: threading.Thread | None = None
_our_pid: int | None = None

# How often the poll thread checks for new queued downloads (seconds)
_POLL_INTERVAL = 2

# Heartbeat older than this = scheduler is dead (seconds)
_HEARTBEAT_TIMEOUT = 30

# How often download progress is flushed to DB (bytes between flushes)
_PROGRESS_FLUSH_BYTES = 256 * 1024  # every 256 KB


def _get_next_queued() -> dict | None:
    """Pop the highest-priority queued download from DB.

    Atomically sets status to 'downloading' so no other worker picks it.

    Returns:
        Download record dict, or None if queue is empty.
    """
    conn = get_conn()
    row = conn.execute("""
        SELECT * FROM downloads
        WHERE status = 'queued'
        ORDER BY priority DESC, created_at ASC
        LIMIT 1
    """).fetchone()
    if not row:
        return None
    record = dict(row)
    conn.execute(
        "UPDATE downloads SET status = 'downloading', started_at = ? WHERE id = ?",
        (now_iso(), record["id"]),
    )
    conn.commit()
    return record


def _do_download(record: dict):
    """Execute a single download. Called by a worker thread.

    Steps:
    1. Determine temp file path and check for partial file (resume)
    2. Build HTTP request with Range header if resuming
    3. Stream response, writing chunks to disk
    4. Update progress in DB periodically
    5. On completion, call the registered callback to deliver the file
    6. Update status to 'done' or 'error'

    Args:
        record: Download record dict from the DB.
    """
    dl_id = record["id"]
    url = record["url"]
    headers = json.loads(record["headers"]) if record["headers"] else {}
    callback_name = record["callback"]
    callback_args = json.loads(record["callback_args"]) if record["callback_args"] else {}

    # Temp file path
    filename = record["filename"] or f"{dl_id}.partial"
    temp_path = DOWNLOADS_DIR / filename
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    # Update filename in DB if it wasn't set
    if not record["filename"]:
        conn = get_conn()
        conn.execute("UPDATE downloads SET filename = ? WHERE id = ?", (filename, dl_id))
        conn.commit()

    try:
        # Check for existing partial file (resume support)
        existing_bytes = 0
        if temp_path.exists():
            existing_bytes = temp_path.stat().st_size
            if existing_bytes > 0:
                # Ask server to resume from where we left off
                headers["Range"] = f"bytes={existing_bytes}-"

        # Stream download
        with httpx.stream("GET", url, headers=headers, timeout=60,
                          follow_redirects=True) as response:

            # Handle resume response
            # 206 = partial content (resume accepted)
            # 200 = full content (server ignored Range, start over)
            if response.status_code == 200 and existing_bytes > 0:
                # Server didn't support resume — start from scratch
                existing_bytes = 0
                temp_path.unlink(missing_ok=True)
            elif response.status_code not in (200, 206):
                response.raise_for_status()

            # Get total size from Content-Length or Content-Range
            total = None
            if response.status_code == 206:
                # Content-Range: bytes 1000-9999/10000
                cr = response.headers.get("content-range", "")
                if "/" in cr:
                    try:
                        total = int(cr.split("/")[1])
                    except (ValueError, IndexError):
                        pass
            if total is None:
                cl = response.headers.get("content-length")
                if cl:
                    total = int(cl) + existing_bytes

            # Update total_bytes in DB
            if total:
                conn = get_conn()
                conn.execute(
                    "UPDATE downloads SET total_bytes = ? WHERE id = ?",
                    (total, dl_id),
                )
                conn.commit()

            # Write chunks to disk
            downloaded = existing_bytes
            last_flush = downloaded
            mode = "ab" if existing_bytes > 0 else "wb"

            with open(temp_path, mode) as f:
                for chunk in response.iter_bytes(65536):
                    f.write(chunk)
                    downloaded += len(chunk)

                    # Periodic progress flush to DB
                    if downloaded - last_flush >= _PROGRESS_FLUSH_BYTES:
                        conn = get_conn()
                        conn.execute(
                            "UPDATE downloads SET downloaded_bytes = ? WHERE id = ?",
                            (downloaded, dl_id),
                        )
                        conn.commit()
                        last_flush = downloaded

                        # Check if cancelled
                        row = conn.execute(
                            "SELECT status FROM downloads WHERE id = ?", (dl_id,)
                        ).fetchone()
                        if row and row["status"] == "cancelled":
                            return

            # Final progress update
            conn = get_conn()
            conn.execute(
                "UPDATE downloads SET downloaded_bytes = ? WHERE id = ?",
                (downloaded, dl_id),
            )
            conn.commit()

        # ── Delivery: call the callback to move file to its store ──

        if callback_name not in _callbacks:
            raise ValueError(f"Unknown callback '{callback_name}'. "
                             f"Registered: {list(_callbacks.keys())}")

        deliver = _callbacks[callback_name]
        deliver(temp_path, callback_args)

        # If callback succeeded, the file was moved out of temp.
        # If it's still there (callback copies instead of moves), clean up.
        temp_path.unlink(missing_ok=True)

        # Mark done
        conn = get_conn()
        conn.execute(
            "UPDATE downloads SET status = 'done', completed_at = ?, error = NULL WHERE id = ?",
            (now_iso(), dl_id),
        )
        conn.commit()

    except Exception as e:
        # Download or delivery failed
        error_msg = str(e)[:500]
        conn = get_conn()
        retries = record["retries"] + 1
        max_retries = record["max_retries"]

        if retries < max_retries:
            # Retry: set back to queued with incremented retry count
            conn.execute(
                "UPDATE downloads SET status = 'queued', retries = ?, error = ? WHERE id = ?",
                (retries, error_msg, dl_id),
            )
        else:
            # Max retries reached: mark as error
            conn.execute(
                "UPDATE downloads SET status = 'error', retries = ?, error = ? WHERE id = ?",
                (retries, error_msg, dl_id),
            )
        conn.commit()


def _poll_loop():
    """Background thread: update heartbeat, feed worker pool, repeat.

    Runs until _running is False. Updates the scheduler_lock heartbeat
    every cycle so other processes know we're alive. If the heartbeat
    update fails (someone stole our lock), we stop.
    """
    while _running:
        try:
            # Update heartbeat — proves we're alive
            conn = get_conn()
            rows = conn.execute(
                "UPDATE scheduler_lock SET heartbeat = ? WHERE id = 1 AND pid = ?",
                (now_iso(), _our_pid),
            ).rowcount
            conn.commit()
            if rows == 0:
                # Someone deleted our lock or replaced it — stop gracefully
                print("[downloader] Lost lock ownership, stopping.", flush=True)
                break

            # Check for queued work
            record = _get_next_queued()
            if record:
                _pool.submit(_do_download, record)
            else:
                time.sleep(_POLL_INTERVAL)
        except Exception as e:
            print(f"[downloader] Poll error: {e}", flush=True)
            time.sleep(_POLL_INTERVAL)


# ── Public API ───────────────────────────────────────────────────────────────

def _is_heartbeat_alive(conn) -> bool:
    """Check if an existing scheduler lock has a fresh heartbeat."""
    row = conn.execute("SELECT heartbeat FROM scheduler_lock WHERE id = 1").fetchone()
    if not row:
        return False
    from datetime import datetime, timezone
    try:
        hb = datetime.fromisoformat(row["heartbeat"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - hb).total_seconds()
        return age < _HEARTBEAT_TIMEOUT
    except Exception:
        return False


def is_running() -> bool:
    """Check if the download scheduler is running (any process).

    Reads the heartbeat from the DB. If it's recent, the scheduler is alive.
    Safe to call from any process (CLI, backend, etc.) — read-only.
    """
    try:
        conn = get_conn()
        return _is_heartbeat_alive(conn)
    except Exception:
        return False


def init_scheduler() -> bool:
    """Start the download scheduler in this process.

    Acquires an exclusive lock in the DB to ensure only one scheduler
    runs at a time across all processes. If another scheduler is alive
    (fresh heartbeat), refuses to start.

    Steps:
      1. Check _running flag (same-process guard)
      2. BEGIN EXCLUSIVE (cross-process guard)
      3. Check heartbeat — if alive, abort
      4. Claim lock with our PID
      5. Recovery: reset 'downloading' → 'queued'
      6. Start worker pool + poll thread

    Returns:
        True if started, False if another scheduler is already running.
    """
    global _pool, _running, _poll_thread, _our_pid
    import os

    # Same-process guard
    if _running:
        return True

    conn = get_conn()

    # Cross-process guard: exclusive transaction
    try:
        conn.execute("BEGIN EXCLUSIVE")
        if _is_heartbeat_alive(conn):
            conn.execute("ROLLBACK")
            row = conn.execute("SELECT pid FROM scheduler_lock WHERE id = 1").fetchone()
            pid = row["pid"] if row else "?"
            print(f"[downloader] Another scheduler is running (PID {pid})", flush=True)
            return False

        # Claim the lock
        _our_pid = os.getpid()
        now = now_iso()
        conn.execute("DELETE FROM scheduler_lock")
        conn.execute(
            "INSERT INTO scheduler_lock (id, pid, started_at, heartbeat) VALUES (1, ?, ?, ?)",
            (_our_pid, now, now),
        )
        conn.execute("COMMIT")
    except Exception as e:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        print(f"[downloader] Failed to acquire lock: {e}", flush=True)
        return False

    # Recovery: downloads stuck in 'downloading' from a previous crash
    stuck = conn.execute(
        "UPDATE downloads SET status = 'queued' WHERE status = 'downloading'"
    ).rowcount
    conn.commit()
    if stuck:
        print(f"[downloader] Recovered {stuck} interrupted download(s)", flush=True)

    # Start worker pool
    _pool = ThreadPoolExecutor(
        max_workers=MAX_CONCURRENT_DOWNLOADS,
        thread_name_prefix="dl",
    )
    _running = True

    # Start poll thread (updates heartbeat + feeds pool)
    _poll_thread = threading.Thread(target=_poll_loop, daemon=True, name="dl-poll")
    _poll_thread.start()

    queued = conn.execute("SELECT COUNT(*) FROM downloads WHERE status = 'queued'").fetchone()[0]
    print(f"[downloader] Started (PID {_our_pid}, {MAX_CONCURRENT_DOWNLOADS} workers, {queued} queued)", flush=True)
    return True


def stop_scheduler():
    """Stop the download scheduler gracefully.

    Signals the poll loop to stop, waits for running downloads to complete,
    then releases the lock. If the lock release fails (crash), the heartbeat
    goes stale and another process can take over.
    """
    global _running, _pool, _poll_thread, _our_pid

    if not _running:
        return

    _running = False

    if _pool:
        _pool.shutdown(wait=True)
        _pool = None
    _poll_thread = None

    # Release lock
    try:
        conn = get_conn()
        conn.execute("DELETE FROM scheduler_lock WHERE id = 1 AND pid = ?", (_our_pid,))
        conn.commit()
    except Exception:
        pass  # Lock will expire via stale heartbeat

    _our_pid = None
    print("[downloader] Stopped", flush=True)


def enqueue(
    url: str,
    callback: str,
    callback_args: dict | None = None,
    headers: dict | None = None,
    priority: int = 0,
    max_retries: int = 3,
) -> str:
    """Add a download to the queue.

    The download will be picked up by a worker thread and executed.
    When complete, the callback function delivers the file to its store.

    Args:
        url: URL to download.
        callback: Registered callback name (e.g. "media_store", "model_store").
        callback_args: Dict passed to the callback function alongside the file path.
                       Must be JSON-serializable. Contains everything the store
                       needs (origin, origin_id, file, dest, format, etc.).
        headers: HTTP headers for the request (e.g. auth tokens).
        priority: Higher = picked first. Default 0.
        max_retries: Max retry attempts on failure. Default 3.

    Returns:
        Download ID (UUID string).

    Raises:
        ValueError: If callback name is not registered.
    """
    if callback not in _callbacks:
        raise ValueError(f"Unknown callback '{callback}'. "
                         f"Registered: {list(_callbacks.keys())}")

    dl_id = uuid.uuid4().hex
    conn = get_conn()
    conn.execute("""
        INSERT INTO downloads (id, url, headers, callback, callback_args, status, priority, max_retries, created_at)
        VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?)
    """, (
        dl_id,
        url,
        json.dumps(headers) if headers else None,
        callback,
        json.dumps(callback_args or {}),
        priority,
        max_retries,
        now_iso(),
    ))
    conn.commit()
    return dl_id


def cancel(dl_id: str) -> bool:
    """Cancel a download.

    If queued, removes it. If downloading, signals the worker to stop
    (checked at next progress flush).

    Args:
        dl_id: Download ID.

    Returns:
        True if found and cancelled, False if not found.
    """
    conn = get_conn()
    row = conn.execute("SELECT status FROM downloads WHERE id = ?", (dl_id,)).fetchone()
    if not row:
        return False
    if row["status"] in ("done", "error", "cancelled"):
        return False
    conn.execute(
        "UPDATE downloads SET status = 'cancelled', completed_at = ? WHERE id = ?",
        (now_iso(), dl_id),
    )
    conn.commit()
    # Clean up temp file
    temp = DOWNLOADS_DIR / f"{dl_id}.partial"
    temp.unlink(missing_ok=True)
    return True


def retry(dl_id: str) -> bool:
    """Retry a failed or cancelled download.

    Resets status to 'queued' and clears error. Retries counter is NOT reset.

    Args:
        dl_id: Download ID.

    Returns:
        True if found and reset, False if not found or not in retryable state.
    """
    conn = get_conn()
    row = conn.execute("SELECT status FROM downloads WHERE id = ?", (dl_id,)).fetchone()
    if not row or row["status"] not in ("error", "cancelled"):
        return False
    conn.execute(
        "UPDATE downloads SET status = 'queued', error = NULL WHERE id = ?",
        (dl_id,),
    )
    conn.commit()
    return True


def get_status(dl_id: str) -> dict | None:
    """Get current status of a download.

    Args:
        dl_id: Download ID.

    Returns:
        Dict with all download fields, or None if not found.
    """
    conn = get_conn()
    row = conn.execute("SELECT * FROM downloads WHERE id = ?", (dl_id,)).fetchone()
    return dict(row) if row else None


def list_active() -> list[dict]:
    """List all non-terminal downloads (queued + downloading).

    Returns:
        List of download record dicts, ordered by priority then created_at.
    """
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM downloads
        WHERE status IN ('queued', 'downloading')
        ORDER BY priority DESC, created_at ASC
    """).fetchall()
    return [dict(r) for r in rows]


def list_all(limit: int = 50) -> list[dict]:
    """List all downloads, newest first.

    Args:
        limit: Max results.

    Returns:
        List of download record dicts.
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM downloads ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def cleanup_temp():
    """Remove temp files for completed, failed, or cancelled downloads.

    Scans V2_DIR/downloads/ for .partial files that aren't actively downloading.

    Returns:
        Number of files removed.
    """
    conn = get_conn()
    # Get IDs of active downloads
    active_ids = {
        r[0] for r in conn.execute(
            "SELECT id FROM downloads WHERE status IN ('queued', 'downloading')"
        ).fetchall()
    }

    removed = 0
    if DOWNLOADS_DIR.exists():
        for f in DOWNLOADS_DIR.iterdir():
            if f.is_file() and f.suffix == ".partial":
                # Extract ID from filename (format: {id}.partial)
                file_id = f.stem
                if file_id not in active_ids:
                    f.unlink()
                    removed += 1

    return removed


def queue_size() -> dict:
    """Get queue statistics.

    Returns:
        Dict with counts: queued, downloading, done, error, cancelled.
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT status, COUNT(*) FROM downloads GROUP BY status"
    ).fetchall()
    result = {"queued": 0, "downloading": 0, "done": 0, "error": 0, "cancelled": 0}
    for r in rows:
        result[r[0]] = r[1]
    return result
