"""ComfyUI Studio — EventBus, WebSocketPusher, startup consumer + frontend repair."""

import asyncio
import json
import queue
import uuid
from pathlib import Path

import httpx
from fastapi import WebSocket

from config import app, REPO_BASE, STUDIO_DIR, WWW_ROOT, WWW_DEFAULT


# ── Event Bus ───────────────────────────────────────────────────────────


class EventSubscriber:
    """Base class for event subscribers."""
    event_types: set | None = None  # None = all events

    def accepts(self, event_type: str) -> bool:
        return self.event_types is None or event_type in self.event_types

    async def on_event(self, event: dict):
        raise NotImplementedError


class EventBus:
    """Central event dispatcher with in-memory log and async subscriber dispatch."""

    def __init__(self, max_log: int = 1000, log_file: str = None):
        self._log: list[dict] = []
        self._max_log = max_log
        self._queue: queue.Queue = queue.Queue()
        self._subscribers: list[EventSubscriber] = []
        self._log_file = Path(log_file) if log_file else None
        # Load persisted events on startup
        if self._log_file and self._log_file.exists():
            try:
                for line in self._log_file.read_text().strip().split("\n"):
                    if line:
                        self._log.append(json.loads(line))
                self._log = self._log[-self._max_log:]
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
            "timestamp": datetime.now(timezone(timedelta(hours=1))).strftime("%Y-%m-%dT%H:%M:%S"),
            "severity": severity,
            "message": message,
            "data": data or {},
        }
        # Ring buffer
        self._log.append(event)
        if len(self._log) > self._max_log:
            self._log = self._log[-self._max_log:]
        # Persist to disk
        if self._log_file:
            try:
                self._log_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self._log_file, "a") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
                # Rotate if too large (>5MB)
                if self._log_file.stat().st_size > 5_000_000:
                    lines = self._log_file.read_text().strip().split("\n")
                    self._log_file.write_text("\n".join(lines[-self._max_log:]) + "\n")
            except Exception:
                pass
        # Queue for async dispatch
        self._queue.put(event)

    def get_log(self, limit: int = 100, types: list[str] = None, severity: str = None) -> list[dict]:
        log = self._log
        if types:
            type_set = set(types)
            log = [e for e in log if e["type"] in type_set]
        if severity:
            log = [e for e in log if e["severity"] == severity]
        return log[-limit:]


_events = EventBus(
    max_log=1000,
    log_file=str(STUDIO_DIR / "events.jsonl"),
)


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
    from catalogs import _www, _load_version

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

    # Verify all frontend files exist -- download missing ones (fixes post-update gaps)
    _FRONTEND_FILES = [
        "styles.css", "home.html", "login.html", "models.html", "loras.html",
        "workflows.html", "nodes.html", "runner.html", "queue.html",
        "history.html", "assets.html", "settings.html", "llm.html",
    ]
    missing = [f for f in _FRONTEND_FILES if not _www(f).exists() or (
        not (WWW_ROOT / f).exists() and not (WWW_DEFAULT / f).exists()
    )]
    if missing:
        async def _download_missing():
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    for fname in missing:
                        r = await client.get(f"{REPO_BASE}/frontend/{fname}")
                        if r.status_code == 200:
                            dest = WWW_ROOT / fname
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            dest.write_text(r.text)
                    _events.emit("system.frontend.repaired",
                                 f"Downloaded {len(missing)} missing frontend file(s): {', '.join(missing)}",
                                 severity="warning", data={"files": missing})
            except Exception:
                pass
        asyncio.create_task(_download_missing())

    # Clean up .old directories left by atomic swap update
    for old_name in ("backend.old", "www.old"):
        old_path = STUDIO_DIR / old_name
        if old_path.exists():
            import shutil
            shutil.rmtree(old_path)

    _events.emit("system.backend.started", "Backend started", severity="info",
                 data={"version": _load_version().get("app_version", "?")})
