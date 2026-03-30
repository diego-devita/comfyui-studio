"""ComfyUI Studio — LLM chat database (presets + conversations).

Stores chat presets (system prompts) and conversation history in
database/llm.db. Conversations are tied to a model filename (not
an instance), so they survive instance restarts.
"""

import json
import sqlite3
import threading
import uuid

from config import LLM_DB_PATH, _now_rome

_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        LLM_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(LLM_DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        _local.conn = conn
    return _local.conn


def _now() -> str:
    return _now_rome().strftime("%Y-%m-%d %H:%M")


def _gen_id() -> str:
    return uuid.uuid4().hex[:12]


# ── Schema ───────────────────────────────────────────────────────────────────

def init_llm_db():
    """Create tables and seed defaults."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS chat_presets (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            system_prompt TEXT NOT NULL DEFAULT '',
            temperature   REAL DEFAULT 0.7,
            created_at    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id               TEXT PRIMARY KEY,
            title            TEXT NOT NULL DEFAULT 'New Chat',
            preset_id        TEXT,
            model            TEXT NOT NULL,
            last_instance_id TEXT,
            messages         TEXT NOT NULL DEFAULT '[]',
            token_usage      TEXT NOT NULL DEFAULT '{}',
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL,
            FOREIGN KEY (preset_id) REFERENCES chat_presets(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_conv_model ON conversations(model);
        CREATE INDEX IF NOT EXISTS idx_conv_updated ON conversations(updated_at);
    """)
    _seed_defaults(conn)


def _seed_defaults(conn: sqlite3.Connection):
    """Insert default presets if table is empty."""
    count = conn.execute("SELECT COUNT(*) FROM chat_presets").fetchone()[0]
    if count > 0:
        return
    now = _now()
    conn.execute(
        "INSERT INTO chat_presets (id, name, system_prompt, temperature, created_at) VALUES (?, ?, ?, ?, ?)",
        ("prompt-engineer", "Prompt Engineer",
         "You are an expert Stable Diffusion prompt engineer. "
         "The user describes what they want in natural language (any language). "
         "You respond ONLY with the optimized prompt in English, using comma-separated tags. "
         "Include quality tags (masterpiece, best quality), subject description, style, lighting, composition. "
         "No explanations unless the user explicitly asks. "
         "When the user asks to modify, output the full updated prompt, not just the changes.",
         0.7, now),
    )
    conn.execute(
        "INSERT INTO chat_presets (id, name, system_prompt, temperature, created_at) VALUES (?, ?, ?, ?, ?)",
        ("general", "General Chat",
         "You are a helpful assistant. Answer concisely and clearly.",
         0.7, now),
    )
    conn.commit()


# ── Presets CRUD ─────────────────────────────────────────────────────────────

def list_presets() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM chat_presets ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def get_preset(preset_id: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM chat_presets WHERE id = ?", (preset_id,)).fetchone()
    return dict(row) if row else None


def upsert_preset(data: dict) -> dict:
    conn = _get_conn()
    pid = data.get("id") or _gen_id()
    now = _now()
    conn.execute("""
        INSERT INTO chat_presets (id, name, system_prompt, temperature, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            system_prompt = excluded.system_prompt,
            temperature = excluded.temperature
    """, (pid, data["name"], data.get("system_prompt", ""), data.get("temperature", 0.7), now))
    conn.commit()
    return get_preset(pid)


def delete_preset(preset_id: str) -> bool:
    conn = _get_conn()
    cur = conn.execute("DELETE FROM chat_presets WHERE id = ?", (preset_id,))
    conn.commit()
    return cur.rowcount > 0


# ── Conversations CRUD ───────────────────────────────────────────────────────

def _parse_conv(row) -> dict:
    """Convert a Row to dict, parsing JSON fields."""
    d = dict(row)
    d["messages"] = json.loads(d.get("messages") or "[]")
    d["token_usage"] = json.loads(d.get("token_usage") or "{}")
    return d


def list_conversations(model: str = None) -> list[dict]:
    conn = _get_conn()
    if model:
        rows = conn.execute(
            "SELECT id, title, model, preset_id, last_instance_id, token_usage, created_at, updated_at, "
            "json_array_length(messages) as message_count FROM conversations WHERE model = ? ORDER BY updated_at DESC",
            (model,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, title, model, preset_id, last_instance_id, token_usage, created_at, updated_at, "
            "json_array_length(messages) as message_count FROM conversations ORDER BY updated_at DESC",
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["token_usage"] = json.loads(d.get("token_usage") or "{}")
        result.append(d)
    return result


def get_conversation(conv_id: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
    return _parse_conv(row) if row else None


def create_conversation(model: str, preset_id: str = None, title: str = None) -> dict:
    conn = _get_conn()
    cid = _gen_id()
    now = _now()
    if not title and preset_id:
        preset = get_preset(preset_id)
        if preset:
            title = preset["name"]
    title = title or "New Chat"
    conn.execute(
        "INSERT INTO conversations (id, title, preset_id, model, messages, token_usage, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, '[]', '{}', ?, ?)",
        (cid, title, preset_id, model, now, now),
    )
    conn.commit()
    return get_conversation(cid)


def delete_conversation(conv_id: str) -> bool:
    conn = _get_conn()
    cur = conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    conn.commit()
    return cur.rowcount > 0


def reset_conversation(conv_id: str) -> bool:
    conn = _get_conn()
    now = _now()
    cur = conn.execute(
        "UPDATE conversations SET messages = '[]', token_usage = '{}', updated_at = ? WHERE id = ?",
        (now, conv_id),
    )
    conn.commit()
    return cur.rowcount > 0


def add_message(conv_id: str, role: str, content: str) -> dict:
    conn = _get_conn()
    row = conn.execute("SELECT messages FROM conversations WHERE id = ?", (conv_id,)).fetchone()
    if not row:
        return None
    messages = json.loads(row["messages"] or "[]")
    msg = {"role": role, "content": content, "timestamp": _now()}
    messages.append(msg)
    now = _now()
    conn.execute(
        "UPDATE conversations SET messages = ?, updated_at = ? WHERE id = ?",
        (json.dumps(messages), now, conv_id),
    )
    conn.commit()
    return msg


def update_conversation(conv_id: str, **fields) -> bool:
    conn = _get_conn()
    allowed = {"title", "last_instance_id", "token_usage", "preset_id"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    # Serialize dicts to JSON
    for k in ("token_usage",):
        if k in updates and isinstance(updates[k], dict):
            updates[k] = json.dumps(updates[k])
    updates["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [conv_id]
    cur = conn.execute(f"UPDATE conversations SET {set_clause} WHERE id = ?", values)
    conn.commit()
    return cur.rowcount > 0
