"""Database connection and lifecycle management.

Single entry point for all SQLite operations in app/.
Creates the DB file, sets PRAGMA, manages connections, runs schema init.

Every module that needs the DB calls get_conn() from here.
No module creates its own connection or touches the DB file directly.

Connection strategy: one connection per thread (thread-local storage).
WAL mode allows concurrent readers with one writer.
"""

import sqlite3
import threading
from pathlib import Path

from app.settings import DB_DIR, DB_PATH

# ── Thread-local connection pool ─────────────────────────────────────────────

_local = threading.local()


def get_conn() -> sqlite3.Connection:
    """Get a SQLite connection for the current thread.

    Creates a new connection if one doesn't exist for this thread.
    All connections share the same PRAGMA settings.
    """
    if not hasattr(_local, "conn") or _local.conn is None:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        _local.conn = conn
    return _local.conn


def close_conn():
    """Close the connection for the current thread, if open."""
    if hasattr(_local, "conn") and _local.conn is not None:
        _local.conn.close()
        _local.conn = None


# ── Schema registry ──────────────────────────────────────────────────────────
# Modules register their schema init functions here.
# init_db() calls them all in order.

_schema_initializers: list[tuple[str, callable]] = []


def register_schema(name: str, init_func: callable):
    """Register a schema initializer.

    Modules call this at import time to register their CREATE TABLE statements.
    init_db() calls all registered initializers in order.

    Args:
        name: human-readable name for logging (e.g. "media_store")
        init_func: callable that takes a sqlite3.Connection and creates tables
    """
    _schema_initializers.append((name, init_func))


# ── Initialization ───────────────────────────────────────────────────────────

def init_db():
    """Create the database and all registered schemas.

    Safe to call multiple times — all CREATE TABLE use IF NOT EXISTS.
    Called once at application startup.

    Order:
    1. Create directory and DB file
    2. Set PRAGMA
    3. Run all registered schema initializers
    4. Commit
    """
    conn = get_conn()

    for name, init_func in _schema_initializers:
        try:
            init_func(conn)
        except Exception as e:
            print(f"[db] Schema init failed for '{name}': {e}", flush=True)
            raise

    conn.commit()
    print(f"[db] Initialized at {DB_PATH} ({len(_schema_initializers)} schemas)", flush=True)


# ── Utilities ────────────────────────────────────────────────────────────────

def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database."""
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    ).fetchone()
    return row is not None


def table_count(table_name: str) -> int:
    """Get row count for a table. Returns 0 if table doesn't exist."""
    if not table_exists(table_name):
        return 0
    conn = get_conn()
    return conn.execute(f"SELECT COUNT(*) FROM [{table_name}]").fetchone()[0]


def table_list() -> list[str]:
    """List all table names in the database."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def vacuum():
    """Reclaim unused space. May take a moment on large databases."""
    conn = get_conn()
    conn.execute("VACUUM")


def integrity_check() -> str:
    """Run SQLite integrity check. Returns 'ok' if healthy."""
    conn = get_conn()
    result = conn.execute("PRAGMA integrity_check").fetchone()
    return result[0] if result else "unknown"


def db_size_bytes() -> int:
    """Get total size of the DB file on disk (including WAL)."""
    total = 0
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(DB_PATH) + suffix)
        if p.exists():
            total += p.stat().st_size
    return total
