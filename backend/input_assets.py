"""ComfyUI Studio — Input asset management.

Centralizes all file uploads to assets/input/ with SHA256 dedup,
DB tracking, and ComfyUI sync.
"""

import hashlib
import os
from pathlib import Path

import httpx

from config import ASSETS_INPUT_DIR, COMFY_URL, DEV_MODE, _now_rome
import db as _db


# ── Schema ───────────────────────────────────────────────────────────────────

def init_input_assets():
    """Create input_assets table if missing."""
    conn = _db._get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS input_assets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            filename    TEXT NOT NULL UNIQUE,
            sha256      TEXT NOT NULL,
            size        INTEGER NOT NULL,
            original_name TEXT,
            source      TEXT,
            mime_type   TEXT,
            comfyui_synced INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_input_sha ON input_assets(sha256, size)")
    conn.commit()


# ── Core ─────────────────────────────────────────────────────────────────────

def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _find_by_hash(sha256: str, size: int) -> dict | None:
    """Find an existing input asset by hash+size."""
    conn = _db._get_conn()
    row = conn.execute(
        "SELECT * FROM input_assets WHERE sha256 = ? AND size = ?",
        (sha256, size),
    ).fetchone()
    return dict(row) if row else None


def register_input(file_bytes: bytes, original_name: str, source: str = "unknown", mime_type: str = None) -> str:
    """Register an input file. Dedup by sha256+size. Returns the filename to use.

    If a file with the same hash+size already exists, returns the existing filename
    without re-uploading. Otherwise saves the file, uploads to ComfyUI, and registers in DB.
    """
    sha256 = _hash_bytes(file_bytes)
    size = len(file_bytes)

    # Check for existing
    existing = _find_by_hash(sha256, size)
    if existing:
        # Verify file still exists on disk
        if (ASSETS_INPUT_DIR / existing["filename"]).exists():
            return existing["filename"]
        # File gone from disk — re-upload but keep the DB record's filename
        filename = existing["filename"]
    else:
        # Generate unique filename
        from workflows import _make_input_filename
        filename = _make_input_filename(original_name)

    now = _now_rome().strftime("%Y-%m-%d %H:%M")

    # Save to DB (or update if filename exists)
    conn = _db._get_conn()
    conn.execute("""
        INSERT INTO input_assets (filename, sha256, size, original_name, source, mime_type, comfyui_synced, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?)
        ON CONFLICT(filename) DO UPDATE SET comfyui_synced = 0
    """, (filename, sha256, size, original_name, source, mime_type or "image/png", now))
    conn.commit()

    # Upload to ComfyUI
    synced = False
    if DEV_MODE:
        # In dev mode, just write the file directly
        ASSETS_INPUT_DIR.mkdir(parents=True, exist_ok=True)
        (ASSETS_INPUT_DIR / filename).write_bytes(file_bytes)
        synced = True
    else:
        try:
            import httpx as _httpx
            with _httpx.Client(timeout=30) as client:
                r = client.post(
                    f"{COMFY_URL}/upload/image",
                    files={"image": (filename, file_bytes, mime_type or "image/png")},
                    data={"overwrite": "true"},
                )
                r.raise_for_status()
                synced = True
        except Exception:
            # Failed to upload to ComfyUI — file may still be usable if written directly
            ASSETS_INPUT_DIR.mkdir(parents=True, exist_ok=True)
            (ASSETS_INPUT_DIR / filename).write_bytes(file_bytes)

    if synced:
        conn.execute("UPDATE input_assets SET comfyui_synced = 1 WHERE filename = ?", (filename,))
        conn.commit()

    return filename


async def register_input_async(file_bytes: bytes, original_name: str, source: str = "unknown", mime_type: str = None) -> str:
    """Async version of register_input for use in async endpoints."""
    sha256 = _hash_bytes(file_bytes)
    size = len(file_bytes)

    existing = _find_by_hash(sha256, size)
    if existing:
        if (ASSETS_INPUT_DIR / existing["filename"]).exists():
            return existing["filename"]
        filename = existing["filename"]
    else:
        from workflows import _make_input_filename
        filename = _make_input_filename(original_name)

    now = _now_rome().strftime("%Y-%m-%d %H:%M")

    conn = _db._get_conn()
    conn.execute("""
        INSERT INTO input_assets (filename, sha256, size, original_name, source, mime_type, comfyui_synced, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?)
        ON CONFLICT(filename) DO UPDATE SET comfyui_synced = 0
    """, (filename, sha256, size, original_name, source, mime_type or "image/png", now))
    conn.commit()

    synced = False
    if DEV_MODE:
        ASSETS_INPUT_DIR.mkdir(parents=True, exist_ok=True)
        (ASSETS_INPUT_DIR / filename).write_bytes(file_bytes)
        synced = True
    else:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    f"{COMFY_URL}/upload/image",
                    files={"image": (filename, file_bytes, mime_type or "image/png")},
                    data={"overwrite": "true"},
                )
                r.raise_for_status()
                synced = True
        except Exception:
            ASSETS_INPUT_DIR.mkdir(parents=True, exist_ok=True)
            (ASSETS_INPUT_DIR / filename).write_bytes(file_bytes)

    if synced:
        conn.execute("UPDATE input_assets SET comfyui_synced = 1 WHERE filename = ?", (filename,))
        conn.commit()

    return filename


# ── Sync ─────────────────────────────────────────────────────────────────────

def sync_input_assets() -> dict:
    """Scan assets/input/ and add missing files to DB. Does not touch existing records."""
    if not ASSETS_INPUT_DIR.exists():
        return {"files_on_disk": 0, "records_in_db": 0, "added": 0}

    conn = _db._get_conn()

    # Get all filenames already in DB
    existing = set()
    for row in conn.execute("SELECT filename FROM input_assets").fetchall():
        existing.add(row[0])

    added = 0
    files_on_disk = 0
    now = _now_rome().strftime("%Y-%m-%d %H:%M")

    for f in ASSETS_INPUT_DIR.iterdir():
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".mp4", ".webm"):
            continue
        files_on_disk += 1

        if f.name in existing:
            continue

        # Calculate hash
        data = f.read_bytes()
        sha256 = _hash_bytes(data)
        size = len(data)

        # Check if same hash+size exists under different name
        dup = _find_by_hash(sha256, size)
        if dup:
            continue  # Same content already tracked under another name

        mime = "image/png"
        if ext in (".jpg", ".jpeg"):
            mime = "image/jpeg"
        elif ext == ".gif":
            mime = "image/gif"
        elif ext == ".webp":
            mime = "image/webp"
        elif ext in (".mp4", ".webm"):
            mime = "video/" + ext[1:]

        conn.execute("""
            INSERT INTO input_assets (filename, sha256, size, original_name, source, mime_type, comfyui_synced, created_at)
            VALUES (?, ?, ?, ?, 'scan', ?, 1, ?)
        """, (f.name, sha256, size, f.name, mime, now))
        added += 1

    conn.commit()

    records_in_db = conn.execute("SELECT COUNT(*) FROM input_assets").fetchone()[0]

    return {"files_on_disk": files_on_disk, "records_in_db": records_in_db, "added": added}


def get_stats() -> dict:
    """Get counts of files on disk vs records in DB."""
    conn = _db._get_conn()
    records = conn.execute("SELECT COUNT(*) FROM input_assets").fetchone()[0]
    files = 0
    if ASSETS_INPUT_DIR.exists():
        for f in ASSETS_INPUT_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".mp4", ".webm"):
                files += 1
    return {"files_on_disk": files, "records_in_db": records}
