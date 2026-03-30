"""ComfyUI Studio — Telegram contacts database.

Stores contacts who have interacted with the bot.
DB file: STUDIO_DIR/database/telegram.db
"""

import sqlite3
import threading
from pathlib import Path

from config import STUDIO_DIR, _now_rome

DB_PATH = STUDIO_DIR / "database" / "telegram.db"
_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                chat_id       INTEGER PRIMARY KEY,
                user_id       INTEGER,
                username      TEXT DEFAULT '',
                first_name    TEXT DEFAULT '',
                last_name     TEXT DEFAULT '',
                language_code TEXT DEFAULT '',
                first_seen    TEXT NOT NULL,
                last_seen     TEXT NOT NULL,
                blocked       INTEGER DEFAULT 0,
                unsubscribed  INTEGER DEFAULT 0
            )
        """)
        conn.commit()
        _local.conn = conn
    return _local.conn


def upsert_contact(chat_id: int, user_id: int = None, username: str = "",
                    first_name: str = "", last_name: str = "",
                    language_code: str = ""):
    """Insert or update a contact. Resets blocked/unsubscribed on new message."""
    conn = _get_conn()
    now = _now_rome().strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute("""
        INSERT INTO contacts (chat_id, user_id, username, first_name, last_name, language_code, first_seen, last_seen, blocked, unsubscribed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
        ON CONFLICT(chat_id) DO UPDATE SET
            user_id = excluded.user_id,
            username = excluded.username,
            first_name = excluded.first_name,
            last_name = excluded.last_name,
            language_code = excluded.language_code,
            last_seen = excluded.last_seen,
            blocked = 0,
            unsubscribed = 0
    """, (chat_id, user_id, username, first_name, last_name, language_code, now, now))
    conn.commit()


def set_unsubscribed(chat_id: int):
    conn = _get_conn()
    conn.execute("UPDATE contacts SET unsubscribed = 1 WHERE chat_id = ?", (chat_id,))
    conn.commit()


def set_blocked(chat_id: int):
    conn = _get_conn()
    conn.execute("UPDATE contacts SET blocked = 1 WHERE chat_id = ?", (chat_id,))
    conn.commit()


def get_active_contacts() -> list[dict]:
    """Return all contacts that are not blocked and not unsubscribed."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM contacts WHERE blocked = 0 AND unsubscribed = 0"
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_contacts() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM contacts ORDER BY last_seen DESC").fetchall()
    return [dict(r) for r in rows]


def get_contact_count() -> dict:
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
    active = conn.execute("SELECT COUNT(*) FROM contacts WHERE blocked = 0 AND unsubscribed = 0").fetchone()[0]
    return {"total": total, "active": active}
