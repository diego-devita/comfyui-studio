"""ComfyUI Studio — SQLite database layer.

Single DB file at STUDIO_DIR/database/studio.db.
Thread-safe via WAL mode + serialized access.
All timestamps stored as ISO 8601 strings (Italian timezone).
"""

import json
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

from config import STUDIO_DIR

DB_PATH = STUDIO_DIR / "database" / "studio.db"
_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """Get a thread-local connection (one per thread, reused)."""
    if not hasattr(_local, "conn") or _local.conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        _local.conn = conn
    return _local.conn


def init_db():
    """Create tables if they don't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            prompt_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            workflow_name TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'running', 'completed', 'failed', 'stalled')),
            params TEXT DEFAULT '{}',
            seeds TEXT DEFAULT '{}',
            output TEXT,
            outputs TEXT,
            output_dir TEXT,
            input_image TEXT,
            error TEXT,
            queued_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            duration INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
        CREATE INDEX IF NOT EXISTS idx_jobs_queued_at ON jobs(queued_at);
        CREATE INDEX IF NOT EXISTS idx_jobs_workflow_id ON jobs(workflow_id);

        -- Events log. Ring buffer behavior enforced by periodic cleanup, not DB constraint.
        CREATE TABLE IF NOT EXISTS events (
            id          TEXT PRIMARY KEY,
            type        TEXT NOT NULL,
            timestamp   TEXT NOT NULL,
            severity    TEXT NOT NULL DEFAULT 'info',
            message     TEXT NOT NULL DEFAULT '',
            data        TEXT DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
        CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
        CREATE INDEX IF NOT EXISTS idx_events_severity ON events(severity);

        -- Download tracking: persists lifecycle across page navigations and restarts.
        -- Real-time byte progress stays in memory (_download_state dict).
        CREATE TABLE IF NOT EXISTS downloads (
            filename     TEXT PRIMARY KEY,
            dest         TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'downloading', 'done', 'error')),
            total_bytes  INTEGER DEFAULT 0,
            error        TEXT,
            source       TEXT,
            queued_at    TEXT NOT NULL,
            started_at   TEXT,
            completed_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status);

        -- Workflow index: cache of manifest.yaml metadata.
        -- Source of truth is the manifest files on disk.
        -- Synced at boot and after OTA updates.
        CREATE TABLE IF NOT EXISTS workflows (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            category        TEXT DEFAULT '',
            type            TEXT DEFAULT 'static',
            version         INTEGER DEFAULT 0,
            date            TEXT DEFAULT '',
            description     TEXT DEFAULT '',
            author          TEXT DEFAULT '',
            inputs          TEXT DEFAULT '[]',
            outputs         TEXT DEFAULT '[]',
            required_models TEXT DEFAULT '[]',
            required_nodes  TEXT DEFAULT '[]',
            "group"         TEXT DEFAULT '',
            technical_notes TEXT DEFAULT '',
            synced_at       TEXT NOT NULL
        );
    """)
    # Migration: add columns if missing
    try:
        conn.execute("ALTER TABLE workflows ADD COLUMN \"group\" TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE workflows ADD COLUMN technical_notes TEXT DEFAULT ''")
    except Exception:
        pass  # already exists
    conn.commit()


# ── Job CRUD ─────────────────────────────────────────────────


def save_job(job: dict):
    """Insert or update a job record."""
    conn = _get_conn()
    conn.execute("""
        INSERT INTO jobs (prompt_id, workflow_id, workflow_name, status,
                          params, seeds, output, outputs, output_dir,
                          input_image, error, queued_at, started_at,
                          finished_at, duration)
        VALUES (:prompt_id, :workflow_id, :workflow_name, :status,
                :params, :seeds, :output, :outputs, :output_dir,
                :input_image, :error, :queued_at, :started_at,
                :finished_at, :duration)
        ON CONFLICT(prompt_id) DO UPDATE SET
            status=excluded.status,
            output=excluded.output,
            outputs=excluded.outputs,
            error=excluded.error,
            started_at=excluded.started_at,
            finished_at=excluded.finished_at,
            duration=excluded.duration
    """, {
        "prompt_id": job.get("prompt_id"),
        "workflow_id": job.get("workflow_id", ""),
        "workflow_name": job.get("workflow_name", ""),
        "status": job.get("status", "queued"),
        "params": json.dumps(job.get("params", {}), ensure_ascii=False),
        "seeds": json.dumps(job.get("seeds", {}), ensure_ascii=False),
        "output": json.dumps(job.get("output")) if isinstance(job.get("output"), (dict, list)) else job.get("output"),
        "outputs": json.dumps(job.get("outputs")) if job.get("outputs") else None,
        "output_dir": job.get("output_dir"),
        "input_image": job.get("input_image"),
        "error": job.get("error"),
        "queued_at": job.get("queued_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "duration": job.get("duration"),
    })
    conn.commit()


def get_job(prompt_id: str) -> dict | None:
    """Get a single job by prompt_id."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM jobs WHERE prompt_id = ?", (prompt_id,)).fetchone()
    return _row_to_job(row) if row else None


def list_jobs_by_status(statuses: list[str], order_desc: bool = True, limit: int = 0) -> list[dict]:
    """List jobs matching any of the given statuses."""
    conn = _get_conn()
    placeholders = ",".join("?" * len(statuses))
    order = "DESC" if order_desc else "ASC"
    sql = f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY queued_at {order}"
    if limit > 0:
        sql += f" LIMIT {limit}"
    rows = conn.execute(sql, statuses).fetchall()
    return [_row_to_job(r) for r in rows]


def list_active_jobs() -> list[dict]:
    """List queued + running jobs, running first, then by queued_at."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT * FROM jobs
        WHERE status IN ('queued', 'running')
        ORDER BY
            CASE status WHEN 'running' THEN 0 ELSE 1 END,
            queued_at ASC
    """).fetchall()
    return [_row_to_job(r) for r in rows]


def list_history(limit: int = 200, offset: int = 0) -> list[dict]:
    """List completed/failed/stalled jobs, newest first."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT * FROM jobs
        WHERE status IN ('completed', 'failed', 'stalled')
        ORDER BY queued_at DESC
        LIMIT ? OFFSET ?
    """, (limit, offset)).fetchall()
    return [_row_to_job(r) for r in rows]


def update_job_status(prompt_id: str, **fields):
    """Update specific fields of a job."""
    conn = _get_conn()
    sets = []
    values = []
    for key, val in fields.items():
        sets.append(f"{key} = ?")
        values.append(val)
    values.append(prompt_id)
    conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE prompt_id = ?", values)
    conn.commit()


def delete_jobs(prompt_ids: list[str]) -> list[str]:
    """Delete jobs by prompt_id. Returns list of deleted prompt_ids with their output_dirs."""
    conn = _get_conn()
    deleted = []
    for pid in prompt_ids:
        row = conn.execute("SELECT prompt_id, output_dir FROM jobs WHERE prompt_id = ?", (pid,)).fetchone()
        if row:
            conn.execute("DELETE FROM jobs WHERE prompt_id = ?", (pid,))
            deleted.append({"prompt_id": row["prompt_id"], "output_dir": row["output_dir"]})
    conn.commit()
    return deleted


def mark_stalled_jobs():
    """Mark any running/queued jobs as stalled (called at startup)."""
    conn = _get_conn()
    cursor = conn.execute("""
        UPDATE jobs SET status = 'stalled', error = 'Job was active when backend restarted'
        WHERE status IN ('queued', 'running')
    """)
    conn.commit()
    return cursor.rowcount


# ── Event CRUD ───────────────────────────────────────────────


def save_event(event: dict):
    """Insert an event into the database."""
    conn = _get_conn()
    conn.execute("""
        INSERT OR IGNORE INTO events (id, type, timestamp, severity, message, data)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        event.get("id"),
        event.get("type", ""),
        event.get("timestamp", ""),
        event.get("severity", "info"),
        event.get("message", ""),
        json.dumps(event.get("data", {}), ensure_ascii=False),
    ))
    conn.commit()


def list_events(limit: int = 100, types: list[str] = None,
                severity: str = None) -> list[dict]:
    """List events from DB, newest first."""
    conn = _get_conn()
    wheres = []
    params = []
    if types:
        placeholders = ",".join("?" * len(types))
        wheres.append(f"type IN ({placeholders})")
        params.extend(types)
    if severity:
        wheres.append("severity = ?")
        params.append(severity)
    where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
    rows = conn.execute(
        f"SELECT * FROM events {where_sql} ORDER BY timestamp DESC LIMIT ?",
        params + [limit]
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("data"):
            try:
                d["data"] = json.loads(d["data"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    # Return in chronological order (oldest first) for the UI
    result.reverse()
    return result


def trim_events(max_count: int = 1000):
    """Keep only the most recent max_count events. Called periodically."""
    conn = _get_conn()
    conn.execute("""
        DELETE FROM events WHERE id NOT IN (
            SELECT id FROM events ORDER BY timestamp DESC LIMIT ?
        )
    """, (max_count,))
    conn.commit()


def count_jobs_by_workflow() -> list[dict]:
    """Count jobs per workflow (for stats)."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT workflow_id, workflow_name, COUNT(*) as count,
               SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
               SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
        FROM jobs
        GROUP BY workflow_id
        ORDER BY count DESC
    """).fetchall()
    return [dict(r) for r in rows]


# ── Workflow index ───────────────────────────────────────────


def sync_workflows_from_disk():
    """Scan workflows dir, read each manifest.yaml, upsert into DB.
    Remove DB rows for workflows whose dir no longer exists."""
    import yaml
    from config import WORKFLOWS_DIR

    conn = _get_conn()
    now = _now_italian()
    found_ids = set()

    if WORKFLOWS_DIR.exists():
        for d in sorted(WORKFLOWS_DIR.iterdir()):
            manifest_path = d / "manifest.yaml"
            if not d.is_dir() or not manifest_path.exists():
                continue
            try:
                with open(manifest_path) as f:
                    m = yaml.safe_load(f)
                wf_id = m.get("id", d.name)
                found_ids.add(wf_id)
                conn.execute("""
                    INSERT INTO workflows (id, name, category, type, version, date,
                                           description, author, inputs, outputs,
                                           required_models, required_nodes, "group",
                                           technical_notes, synced_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name, category=excluded.category, type=excluded.type,
                        version=excluded.version, date=excluded.date,
                        description=excluded.description, author=excluded.author,
                        inputs=excluded.inputs, outputs=excluded.outputs,
                        required_models=excluded.required_models,
                        required_nodes=excluded.required_nodes,
                        "group"=excluded."group",
                        technical_notes=excluded.technical_notes,
                        synced_at=excluded.synced_at
                """, (
                    wf_id, m.get("name", wf_id), m.get("category", ""),
                    m.get("type", "static"), m.get("version", 0), m.get("date", ""),
                    m.get("description", ""), m.get("author", ""),
                    json.dumps(m.get("inputs", []), ensure_ascii=False),
                    json.dumps(m.get("outputs", []), ensure_ascii=False),
                    json.dumps(m.get("required_models", []), ensure_ascii=False),
                    json.dumps(m.get("required_nodes", []), ensure_ascii=False),
                    m.get("group", ""),
                    json.dumps(m.get("technical_notes", {}), ensure_ascii=False),
                    now,
                ))
            except Exception as e:
                print(f"[db] Failed to sync workflow {d.name}: {e}", flush=True)

    # Remove workflows no longer on disk
    existing = {r[0] for r in conn.execute("SELECT id FROM workflows").fetchall()}
    removed = existing - found_ids
    for wf_id in removed:
        conn.execute("DELETE FROM workflows WHERE id = ?", (wf_id,))

    conn.commit()
    return len(found_ids)


def list_workflows() -> list[dict]:
    """All workflows from DB, ordered by name."""
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM workflows ORDER BY name").fetchall()
    return [_row_to_workflow(r) for r in rows]


def get_workflow(workflow_id: str) -> dict | None:
    """Single workflow by id from DB."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
    return _row_to_workflow(row) if row else None


def _row_to_workflow(row: sqlite3.Row) -> dict:
    """Convert a DB row to workflow dict with parsed JSON fields."""
    d = dict(row)
    for field in ("inputs", "outputs", "required_models", "required_nodes", "technical_notes"):
        if d.get(field):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


# ── Helpers ──────────────────────────────────────────────────


# ── Download tracking ────────────────────────────────────────


def _now_italian() -> str:
    return datetime.now(timezone(timedelta(hours=1))).strftime("%Y-%m-%dT%H:%M:%S")


def upsert_download(filename: str, dest: str, status: str, source: str = None, error: str = None):
    """Insert or update a download record."""
    conn = _get_conn()
    now = _now_italian()
    conn.execute("""
        INSERT INTO downloads (filename, dest, status, source, error, queued_at, started_at, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(filename) DO UPDATE SET
            status=excluded.status,
            error=excluded.error,
            started_at=CASE WHEN excluded.status='downloading' THEN ? ELSE downloads.started_at END,
            completed_at=CASE WHEN excluded.status IN ('done','error') THEN ? ELSE downloads.completed_at END
    """, (filename, dest, status, source, error, now, None, None, now, now))
    conn.commit()


def complete_download(filename: str, total_bytes: int = 0):
    """Mark download as done."""
    conn = _get_conn()
    now = _now_italian()
    conn.execute("""
        UPDATE downloads SET status='done', total_bytes=?, completed_at=?, error=NULL
        WHERE filename=?
    """, (total_bytes, now, filename))
    conn.commit()


def fail_download(filename: str, error: str):
    """Mark download as error."""
    conn = _get_conn()
    now = _now_italian()
    conn.execute("""
        UPDATE downloads SET status='error', error=?, completed_at=?
        WHERE filename=?
    """, (error, now, filename))
    conn.commit()


def get_downloads_for_files(filenames: list[str]) -> dict:
    """Get download records for a list of filenames. Returns {filename: {status, ...}}."""
    if not filenames:
        return {}
    conn = _get_conn()
    placeholders = ",".join("?" * len(filenames))
    rows = conn.execute(
        f"SELECT * FROM downloads WHERE filename IN ({placeholders})", filenames
    ).fetchall()
    return {r["filename"]: dict(r) for r in rows}


def get_active_downloads() -> list[dict]:
    """Get all queued/downloading records."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM downloads WHERE status IN ('queued', 'downloading') ORDER BY queued_at"
    ).fetchall()
    return [dict(r) for r in rows]


def cleanup_stale_downloads() -> int:
    """On boot: mark 'downloading' records as 'error' (process died mid-download).
    Returns number of records cleaned up."""
    conn = _get_conn()
    now = _now_italian()
    cursor = conn.execute("""
        UPDATE downloads SET status='error', error='Process restarted during download', completed_at=?
        WHERE status='downloading'
    """, (now,))
    conn.commit()
    return cursor.rowcount


# ── Helpers ──────────────────────────────────────────────────


def _row_to_job(row: sqlite3.Row) -> dict:
    """Convert a DB row to the same dict format the API expects."""
    d = dict(row)
    # Parse JSON fields back to dicts/lists
    for field in ("params", "seeds"):
        if d.get(field):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                pass
    for field in ("output", "outputs"):
        if d.get(field) and isinstance(d[field], str) and d[field].startswith(("{", "[")):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return d
