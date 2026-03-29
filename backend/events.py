"""ComfyUI Studio — EventBus, WebSocketPusher, startup consumer."""

import asyncio
import json
import queue
import signal
import uuid

from fastapi import WebSocket

from config import app, STUDIO_DIR, _now_rome


# ── Event Bus ───────────────────────────────────────────────────────────


class EventSubscriber:
    """Base class for event subscribers."""
    event_types: set | None = None  # None = all events

    def accepts(self, event_type: str) -> bool:
        return self.event_types is None or event_type in self.event_types

    async def on_event(self, event: dict):
        raise NotImplementedError


class EventBus:
    """Central event dispatcher with SQLite persistence and async subscriber dispatch.

    Events are persisted to the studio SQLite database (db/studio.db).
    The in-memory ring buffer is kept for fast access by the WebSocket
    pusher and activity panel.
    """

    def __init__(self, max_log: int = 1000):
        self._log: list[dict] = []
        self._max_log = max_log
        self._queue: queue.Queue = queue.Queue()
        self._subscribers: list[EventSubscriber] = []
        self._db_ready = False

    def init_from_db(self):
        """Load recent events from SQLite into memory. Called after DB init."""
        try:
            import db as _db
            self._log = _db.list_events(limit=self._max_log)
            self._db_ready = True
        except Exception:
            pass

    def subscribe(self, subscriber: EventSubscriber):
        self._subscribers.append(subscriber)

    def emit(self, event_type: str, message: str, severity: str = "info", data: dict = None):
        """Emit an event. Thread-safe, non-blocking."""
        from datetime import datetime, timezone, timedelta
        event = {
            "id": f"evt_{uuid.uuid4().hex[:8]}",
            "type": event_type,
            "timestamp": _now_rome().strftime("%Y-%m-%dT%H:%M:%S"),
            "severity": severity,
            "message": message,
            "data": data or {},
        }
        # Ring buffer (in-memory, for fast WS push)
        self._log.append(event)
        if len(self._log) > self._max_log:
            self._log = self._log[-self._max_log:]
        # Persist to SQLite
        if self._db_ready:
            try:
                import db as _db
                _db.save_event(event)
            except Exception:
                pass
        # Queue for async dispatch to WS subscribers
        self._queue.put(event)

    def get_log(self, limit: int = 100, types: list[str] = None, severity: str = None) -> list[dict]:
        # Read from DB if available (more complete than in-memory)
        if self._db_ready:
            try:
                import db as _db
                return _db.list_events(limit=limit, types=types, severity=severity)
            except Exception:
                pass
        # Fallback to in-memory
        log = self._log
        if types:
            type_set = set(types)
            log = [e for e in log if e["type"] in type_set]
        if severity:
            log = [e for e in log if e["severity"] == severity]
        return log[-limit:]


_events = EventBus(max_log=1000)


class _WebSocketPusher(EventSubscriber):
    """Pushes events to connected WS clients."""
    event_types = None  # all events

    def __init__(self):
        self._clients: list[WebSocket] = []

    def add_client(self, ws: WebSocket):
        self._clients.append(ws)

    def remove_client(self, ws: WebSocket):
        self._clients = [c for c in self._clients if c is not ws]

    async def on_event(self, event: dict):
        dead = []
        for ws in self._clients:
            try:
                await ws.send_text(json.dumps(event, default=str))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.remove_client(ws)


_ws_pusher = _WebSocketPusher()
_events.subscribe(_ws_pusher)


@app.on_event("startup")
async def _start_event_consumer():
    """Background task: consumes events from the thread-safe queue and dispatches to async subscribers."""
    from catalogs import _load_version

    async def _consumer():
        loop = asyncio.get_event_loop()
        while True:
            try:
                event = await loop.run_in_executor(None, _events._queue.get)
                for sub in _events._subscribers:
                    if sub.accepts(event["type"]):
                        try:
                            await sub.on_event(event)
                        except Exception:
                            pass
            except Exception:
                await asyncio.sleep(0.1)

    asyncio.create_task(_consumer())

    # Clean up .old directories left by atomic swap update
    for old_name in ("backend.old", "www.old"):
        old_path = STUDIO_DIR / old_name
        if old_path.exists():
            import shutil
            shutil.rmtree(old_path)

    # Migration: copy working dirs from .repo/ if missing (first run after architecture change)
    from config import REPO_DIR, WWW_ROOT, BACKEND_DIR
    import shutil
    for src_name, dst_path in [("frontend", WWW_ROOT), ("backend", BACKEND_DIR)]:
        src = REPO_DIR / src_name
        if not dst_path.exists() and src.exists():
            shutil.copytree(str(src), str(dst_path))
            _events.emit("system.migration", f"Copied {src_name} from .repo/ to working dir",
                         severity="info")

    import db as _db

    # Load persisted events from SQLite into memory, trim old ones
    _events.init_from_db()
    _db.trim_events(1000)

    # Remove legacy files/dirs from pre-SQLite era
    import shutil as _shutil
    for legacy in ["events.jsonl"]:
        p = STUDIO_DIR / legacy
        if p.exists():
            p.unlink()
    for legacy_dir in ["jobs", "jobs_old"]:
        p = STUDIO_DIR / legacy_dir
        if p.is_symlink():
            p.unlink()
        elif p.is_dir():
            _shutil.rmtree(p)

    # Initialize gallery image store (SQLite)
    import gallery_db as _gdb
    _gdb.init_gallery_db()

    # Background sync CivitAI tags — non-blocking, runs after startup completes.
    # Resolves tag IDs from downloaded gallery metadata into human-readable names.
    import threading as _threading
    def _bg_tag_sync():
        import time; time.sleep(5)  # wait for server to fully start
        try:
            from loras_api import _sync_civitai_tags_bg
            count = _sync_civitai_tags_bg()
            if count > 0:
                _events.emit("system.startup", f"Synced {count} CivitAI tags", severity="info")
        except Exception as e:
            print(f"[startup] Tag sync failed: {e}", flush=True)
    _threading.Thread(target=_bg_tag_sync, daemon=True).start()

    # Restore persisted settings from DB into os.environ (DB always wins)
    import os as _os
    for _sk, _sv in _db.get_all_settings().items():
        if _sv:
            _os.environ[_sk] = _sv

    # Mark any jobs that were running/queued as stalled
    stalled = _db.mark_stalled_jobs()
    if stalled > 0:
        _events.emit("system.startup", f"Marked {stalled} stalled jobs", severity="warning")

    # Mark any downloads that were in-progress as failed (process died mid-download)
    stale_dl = _db.cleanup_stale_downloads()
    if stale_dl > 0:
        _events.emit("system.startup", f"Marked {stale_dl} stale downloads as failed", severity="warning")

    # Sync workflow index from manifest files on disk
    wf_count = _db.sync_workflows_from_disk()
    _events.emit("system.startup", f"Synced {wf_count} workflows from disk", severity="info")

    # Auto-start Telegram bot if configured
    try:
        from telegram_bot import auto_start as _bot_auto_start
        _bot_auto_start()
    except Exception as _bot_err:
        print(f"[startup] Telegram bot auto-start failed: {_bot_err}", flush=True)

    # Register SIGTERM handler for graceful shutdown.
    # Docker sends SIGTERM before SIGKILL (10s grace period).
    # This flushes SQLite WAL files to prevent corruption.
    def _sigterm_handler(signum, frame):
        print("[shutdown] SIGTERM received, flushing databases...", flush=True)
        try:
            _gdb._get_conn().execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        try:
            _db._get_conn().execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        print("[shutdown] DB flush complete, exiting.", flush=True)
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, _sigterm_handler)

    _events.emit("system.backend.started", "Backend started", severity="info",
                 data={"version": _load_version().get("app_version", "?")})
