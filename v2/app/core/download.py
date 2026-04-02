"""Download Scheduler — queued, resumable file downloads with callback delivery.

An independent background process that executes queued file downloads.
Runs as its own process (studio-downloader), separate from backend and CLI.

Architecture:
  - Callers write to the 'downloads' table (enqueue). This is just an INSERT.
  - The scheduler process polls the table when woken, downloads files, delivers via callback.
  - Only one scheduler at a time (DB lock with PID, verified via os.kill).
  - Event-driven wake via filesystem sentinel (.wake file + inotify).
  - Zero DB access when idle — sleeps on inotify, no polling.

Wake mechanism:
  1. Caller does enqueue() → INSERT into DB + touch .wake file
  2. Scheduler sleeps on inotify watching downloads/ dir
  3. .wake appears → scheduler wakes, processes entire queue
  4. Queue empty → deletes .wake, goes back to sleep
  5. Safety: 60s timeout on inotify in case events are missed

Tables:
  downloads       — queued/active/done file downloads
  scheduler_lock  — singleton row with PID of owning process

See DOWNLOAD_SCHEDULER.md for full architecture docs.
"""

import json
import os
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from v2.app.core.db import get_conn, register_schema
from v2.app.core.settings import DOWNLOADS_DIR, MAX_CONCURRENT_DOWNLOADS, now_iso


# ══════════════════════════════════════════════════════════════════════════════
#  CALLBACK REGISTRY
# ══════════════════════════════════════════════════════════════════════════════

_callbacks: dict[str, callable] = {}


def register_callback(name: str, func: callable):
    """Register a delivery callback.

    Called by modules at import time. The name is stored in the DB so it
    survives restarts. The function must be re-registered every startup.

    Args:
        name: Short name (e.g. "media_store", "gallery_deliver").
        func: Callable(file_path: Path, args: dict) -> Any.
    """
    _callbacks[name] = func


# ══════════════════════════════════════════════════════════════════════════════
#  SCHEMA
# ══════════════════════════════════════════════════════════════════════════════

def _init_schema(conn: sqlite3.Connection):
    """Create downloads + scheduler_lock tables."""
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

        -- Singleton: only one scheduler process at a time.
        -- PID verified via os.kill(pid, 0) — no heartbeat needed.
        CREATE TABLE IF NOT EXISTS scheduler_lock (
            id          INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            pid         INTEGER NOT NULL,
            started_at  TEXT NOT NULL
        );
    """)


register_schema("download_scheduler", _init_schema)


# ══════════════════════════════════════════════════════════════════════════════
#  SENTINEL — wake mechanism for cross-process notification
# ══════════════════════════════════════════════════════════════════════════════

_WAKE_FILE = DOWNLOADS_DIR / ".wake"
_INOTIFY_TIMEOUT_S = 60  # safety wake even if inotify misses events


def _touch_wake():
    """Create the sentinel file to wake the scheduler.

    Called by enqueue() after inserting a download. If the scheduler is
    sleeping on inotify, this wakes it immediately. If it's already awake
    or not running, the file just sits there harmlessly.
    """
    try:
        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        _WAKE_FILE.touch()
    except Exception:
        pass  # Non-fatal — scheduler will wake on timeout


def _clear_wake():
    """Remove the sentinel file after processing the queue."""
    try:
        _WAKE_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _wait_for_wake():
    """Block until .wake appears or timeout expires.

    Uses inotify (Linux kernel notification) for zero-CPU waiting.
    Falls back to simple sleep if inotify is unavailable.

    Returns when:
      - .wake file is created/modified (immediate wake)
      - Timeout expires (safety wake, every 60s)
      - _running becomes False (shutdown)
    """
    # If .wake already exists, return immediately
    if _WAKE_FILE.exists():
        return

    try:
        import inotify.adapters
        i = inotify.adapters.Inotify()
        i.add_watch(str(DOWNLOADS_DIR))
        for event in i.event_gen(timeout_s=_INOTIFY_TIMEOUT_S):
            if not _running:
                break
            if event is not None:
                _, type_names, _, filename = event
                if filename == ".wake":
                    break
            else:
                # Timeout — safety wake
                break
    except ImportError:
        # inotify not available — fall back to polling with long sleep
        for _ in range(_INOTIFY_TIMEOUT_S):
            if not _running or _WAKE_FILE.exists():
                break
            time.sleep(1)
    except Exception:
        # inotify error — fall back to sleep
        time.sleep(_INOTIFY_TIMEOUT_S)


# ══════════════════════════════════════════════════════════════════════════════
#  LOCK — ensures only one scheduler process at a time
# ══════════════════════════════════════════════════════════════════════════════

def _pid_alive(pid: int) -> bool:
    """Check if a process with the given PID exists."""
    try:
        os.kill(pid, 0)  # Signal 0 = check existence, don't actually signal
        return True
    except ProcessLookupError:
        return False  # Process does not exist
    except PermissionError:
        return True  # Exists but we can't signal it (different user)


def _acquire_lock() -> bool:
    """Acquire the scheduler lock via exclusive DB transaction.

    Checks if another scheduler is alive (PID check). If not, claims
    the lock with our PID. Atomic via BEGIN EXCLUSIVE.

    Returns True if acquired, False if another scheduler is running.
    """
    global _our_pid
    conn = get_conn()

    try:
        conn.execute("BEGIN EXCLUSIVE")
        row = conn.execute("SELECT pid FROM scheduler_lock WHERE id = 1").fetchone()

        if row and _pid_alive(row["pid"]):
            conn.execute("ROLLBACK")
            print(f"[downloader] Another scheduler is running (PID {row['pid']})", flush=True)
            return False

        # Claim the lock
        _our_pid = os.getpid()
        conn.execute("DELETE FROM scheduler_lock")
        conn.execute(
            "INSERT INTO scheduler_lock (id, pid, started_at) VALUES (1, ?, ?)",
            (_our_pid, now_iso()),
        )
        conn.execute("COMMIT")
        return True

    except Exception as e:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        print(f"[downloader] Failed to acquire lock: {e}", flush=True)
        return False


def _release_lock():
    """Release the scheduler lock. Non-fatal if it fails."""
    try:
        conn = get_conn()
        conn.execute("DELETE FROM scheduler_lock WHERE id = 1 AND pid = ?", (_our_pid,))
        conn.commit()
    except Exception:
        pass  # Stale lock will be detected by PID check


def is_running() -> bool:
    """Check if the download scheduler is running (any process).

    Reads the PID from the lock table and checks if the process exists.
    Safe to call from any process — read-only, no lock needed.
    """
    try:
        conn = get_conn()
        row = conn.execute("SELECT pid FROM scheduler_lock WHERE id = 1").fetchone()
        if not row:
            return False
        return _pid_alive(row["pid"])
    except Exception:
        return False


def get_lock_info() -> dict | None:
    """Get scheduler lock info (PID, started_at). None if not locked."""
    conn = get_conn()
    row = conn.execute("SELECT pid, started_at FROM scheduler_lock WHERE id = 1").fetchone()
    return dict(row) if row else None


# ══════════════════════════════════════════════════════════════════════════════
#  WORKER — downloads a single file
# ══════════════════════════════════════════════════════════════════════════════

_PROGRESS_FLUSH_BYTES = 256 * 1024


def _get_next_queued() -> dict | None:
    """Pop the highest-priority queued download. Atomically marks it 'downloading'."""
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
    """Execute a single download: stream file, deliver via callback.

    Steps:
      1. Resume from partial file if it exists (Range header)
      2. Stream HTTP response to disk, flush progress periodically
      3. Call registered callback to deliver file to its store
      4. Mark done or retry on error
    """
    dl_id = record["id"]
    url = record["url"]
    headers = json.loads(record["headers"]) if record["headers"] else {}
    callback_name = record["callback"]
    callback_args = json.loads(record["callback_args"]) if record["callback_args"] else {}

    filename = record["filename"] or f"{dl_id}.partial"
    temp_path = DOWNLOADS_DIR / filename

    # Save filename if not set
    if not record["filename"]:
        conn = get_conn()
        conn.execute("UPDATE downloads SET filename = ? WHERE id = ?", (filename, dl_id))
        conn.commit()

    try:
        # Resume support
        existing_bytes = 0
        if temp_path.exists():
            existing_bytes = temp_path.stat().st_size
            if existing_bytes > 0:
                headers["Range"] = f"bytes={existing_bytes}-"

        with httpx.stream("GET", url, headers=headers, timeout=60,
                          follow_redirects=True) as response:

            if response.status_code == 200 and existing_bytes > 0:
                existing_bytes = 0
                temp_path.unlink(missing_ok=True)
            elif response.status_code not in (200, 206):
                response.raise_for_status()

            # Parse total size
            total = None
            if response.status_code == 206:
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

            if total:
                conn = get_conn()
                conn.execute("UPDATE downloads SET total_bytes = ? WHERE id = ?", (total, dl_id))
                conn.commit()

            # Stream to disk
            downloaded = existing_bytes
            last_flush = downloaded
            mode = "ab" if existing_bytes > 0 else "wb"

            with open(temp_path, mode) as f:
                for chunk in response.iter_bytes(65536):
                    f.write(chunk)
                    downloaded += len(chunk)

                    if downloaded - last_flush >= _PROGRESS_FLUSH_BYTES:
                        conn = get_conn()
                        conn.execute(
                            "UPDATE downloads SET downloaded_bytes = ? WHERE id = ?",
                            (downloaded, dl_id),
                        )
                        conn.commit()
                        last_flush = downloaded

                        # Check cancellation
                        row = conn.execute(
                            "SELECT status FROM downloads WHERE id = ?", (dl_id,)
                        ).fetchone()
                        if row and row["status"] == "cancelled":
                            return

            # Final progress
            conn = get_conn()
            conn.execute(
                "UPDATE downloads SET downloaded_bytes = ? WHERE id = ?",
                (downloaded, dl_id),
            )
            conn.commit()

        # Deliver via callback
        if callback_name not in _callbacks:
            raise ValueError(f"Unknown callback '{callback_name}'. "
                             f"Registered: {list(_callbacks.keys())}")

        _callbacks[callback_name](temp_path, callback_args)
        temp_path.unlink(missing_ok=True)

        conn = get_conn()
        conn.execute(
            "UPDATE downloads SET status = 'done', completed_at = ?, error = NULL WHERE id = ?",
            (now_iso(), dl_id),
        )
        conn.commit()

    except Exception as e:
        error_msg = str(e)[:500]
        conn = get_conn()
        retries = record["retries"] + 1
        if retries < record["max_retries"]:
            conn.execute(
                "UPDATE downloads SET status = 'queued', retries = ?, error = ? WHERE id = ?",
                (retries, error_msg, dl_id),
            )
        else:
            conn.execute(
                "UPDATE downloads SET status = 'error', retries = ?, error = ? WHERE id = ?",
                (retries, error_msg, dl_id),
            )
        conn.commit()


# ══════════════════════════════════════════════════════════════════════════════
#  SCHEDULER LIFECYCLE — init, run loop, stop
# ══════════════════════════════════════════════════════════════════════════════

_pool: ThreadPoolExecutor | None = None
_running = False
_main_thread: threading.Thread | None = None
_our_pid: int | None = None


def _drain_queue() -> int:
    """Process all queued downloads. Returns number submitted to pool."""
    submitted = 0
    while _running:
        record = _get_next_queued()
        if not record:
            break
        _pool.submit(_do_download, record)
        submitted += 1
    return submitted


def _scheduler_loop():
    """Main scheduler loop: sleep → wake → drain queue → repeat.

    Runs until _running is False. Zero DB access while sleeping.
    """
    while _running:
        # Wait for wake signal (inotify) or timeout (60s safety)
        _wait_for_wake()

        if not _running:
            break

        # Woken — process the entire queue
        _clear_wake()
        submitted = _drain_queue()

        if submitted > 0:
            print(f"[downloader] Submitted {submitted} download(s)", flush=True)


def init_scheduler() -> bool:
    """Start the download scheduler in this process.

    Acquires exclusive lock, recovers interrupted downloads, starts
    worker pool and main loop. Only one scheduler across all processes.

    Returns True if started, False if another is already running.
    """
    global _pool, _running, _main_thread

    # Same-process guard
    if _running:
        return True

    # Cross-process lock
    if not _acquire_lock():
        return False

    # Recovery: downloads stuck in 'downloading' from a crash
    conn = get_conn()
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

    # Start main loop thread
    _main_thread = threading.Thread(target=_scheduler_loop, daemon=True, name="dl-main")
    _main_thread.start()

    queued = conn.execute("SELECT COUNT(*) FROM downloads WHERE status = 'queued'").fetchone()[0]
    print(f"[downloader] Started (PID {_our_pid}, {MAX_CONCURRENT_DOWNLOADS} workers, {queued} queued)", flush=True)

    # If there's already work, wake immediately
    if queued > 0:
        _touch_wake()

    return True


def stop_scheduler():
    """Stop the scheduler gracefully: finish active downloads, release lock, checkpoint WAL."""
    global _running, _pool, _main_thread, _our_pid

    if not _running:
        return

    _running = False

    # Wake the main loop so it exits the inotify wait
    _touch_wake()

    if _pool:
        _pool.shutdown(wait=True)
        _pool = None
    _main_thread = None

    # Release lock
    _release_lock()

    # WAL checkpoint — flush everything to disk for clean shutdown
    try:
        conn = get_conn()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass

    _our_pid = None
    print("[downloader] Stopped", flush=True)


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC API — enqueue, cancel, retry, status, list
# ══════════════════════════════════════════════════════════════════════════════

def enqueue(
    url: str,
    callback: str,
    callback_args: dict | None = None,
    headers: dict | None = None,
    priority: int = 0,
    max_retries: int = 3,
) -> str:
    """Add a download to the queue and wake the scheduler.

    The download record is written to the DB, then the .wake sentinel file
    is touched to notify the scheduler (if running). If the scheduler is
    not running, the record waits until it starts.

    Args:
        url: URL to download.
        callback: Registered callback name.
        callback_args: Dict passed to callback on completion.
        headers: HTTP headers (auth tokens, etc).
        priority: Higher = picked first.
        max_retries: Max attempts on failure.

    Returns:
        Download ID (UUID string).
    """
    if callback not in _callbacks:
        raise ValueError(f"Unknown callback '{callback}'. "
                         f"Registered: {list(_callbacks.keys())}")

    dl_id = uuid.uuid4().hex
    conn = get_conn()
    conn.execute("""
        INSERT INTO downloads (id, url, headers, callback, callback_args,
                               status, priority, max_retries, created_at)
        VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?)
    """, (
        dl_id, url,
        json.dumps(headers) if headers else None,
        callback, json.dumps(callback_args or {}),
        priority, max_retries, now_iso(),
    ))
    conn.commit()

    # Wake the scheduler
    _touch_wake()

    return dl_id


def cancel(dl_id: str) -> bool:
    """Cancel a download. Signals active worker to stop at next progress flush."""
    conn = get_conn()
    row = conn.execute("SELECT status FROM downloads WHERE id = ?", (dl_id,)).fetchone()
    if not row or row["status"] in ("done", "error", "cancelled"):
        return False
    conn.execute(
        "UPDATE downloads SET status = 'cancelled', completed_at = ? WHERE id = ?",
        (now_iso(), dl_id),
    )
    conn.commit()
    (DOWNLOADS_DIR / f"{dl_id}.partial").unlink(missing_ok=True)
    return True


def retry(dl_id: str) -> bool:
    """Retry a failed/cancelled download. Requeues and wakes scheduler."""
    conn = get_conn()
    row = conn.execute("SELECT status FROM downloads WHERE id = ?", (dl_id,)).fetchone()
    if not row or row["status"] not in ("error", "cancelled"):
        return False
    conn.execute(
        "UPDATE downloads SET status = 'queued', error = NULL WHERE id = ?",
        (dl_id,),
    )
    conn.commit()
    _touch_wake()
    return True


def get_status(dl_id: str) -> dict | None:
    """Get current status of a single download."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM downloads WHERE id = ?", (dl_id,)).fetchone()
    return dict(row) if row else None


def list_active() -> list[dict]:
    """List queued + downloading records, ordered by priority."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM downloads
        WHERE status IN ('queued', 'downloading')
        ORDER BY priority DESC, created_at ASC
    """).fetchall()
    return [dict(r) for r in rows]


def list_all(limit: int = 50) -> list[dict]:
    """List all downloads, newest first."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM downloads ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def cleanup_temp() -> int:
    """Remove temp .partial files for non-active downloads."""
    conn = get_conn()
    active_ids = {
        r[0] for r in conn.execute(
            "SELECT id FROM downloads WHERE status IN ('queued', 'downloading')"
        ).fetchall()
    }
    removed = 0
    if DOWNLOADS_DIR.exists():
        for f in DOWNLOADS_DIR.iterdir():
            if f.is_file() and f.suffix == ".partial" and f.stem not in active_ids:
                f.unlink()
                removed += 1
    return removed


def queue_size() -> dict:
    """Get counts by status: queued, downloading, done, error, cancelled."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT status, COUNT(*) FROM downloads GROUP BY status"
    ).fetchall()
    result = {"queued": 0, "downloading": 0, "done": 0, "error": 0, "cancelled": 0}
    for r in rows:
        result[r[0]] = r[1]
    return result
