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
    """Scan assets/input/, register new files, dedup duplicates.

    For each file on disk:
    - If already in DB by filename → skip
    - If same hash+size exists under another name → it's a duplicate:
      rewrite all dependencies to point to the canonical name, then
      delete the duplicate from disk (assets/input/ + ComfyUI/input/)
    - Otherwise → register as new

    Returns summary with added/deduped counts and list of removed files.
    """
    if not ASSETS_INPUT_DIR.exists():
        return {"files_on_disk": 0, "records_in_db": 0, "added": 0, "deduped": 0, "removed": []}

    import json as _json
    from config import PRESETS_DIR, COMFYUI_DIR

    conn = _db._get_conn()
    comfyui_input = Path(COMFYUI_DIR) / "input"

    # Build hash index from DB records
    existing_by_name = {}  # filename → {sha256, size}
    hash_to_canonical = {}  # "sha256:size" → filename (first one wins = canonical)
    for row in conn.execute("SELECT filename, sha256, size FROM input_assets").fetchall():
        existing_by_name[row[0]] = {"sha256": row[1], "size": row[2]}
        hkey = f"{row[1]}:{row[2]}"
        if hkey not in hash_to_canonical:
            hash_to_canonical[hkey] = row[0]

    added = 0
    deduped = 0
    removed = []
    files_on_disk = 0
    now = _now_rome().strftime("%Y-%m-%d %H:%M")

    # Collect all media files first (so we can iterate safely while deleting)
    media_files = []
    for f in ASSETS_INPUT_DIR.iterdir():
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".mp4", ".webm"):
            media_files.append(f)

    for f in media_files:
        ext = f.suffix.lower()
        files_on_disk += 1

        # Calculate hash for every file (even if in DB — needed for dedup)
        data = f.read_bytes()
        sha256 = _hash_bytes(data)
        size = len(data)
        hkey = f"{sha256}:{size}"

        # Is there already a canonical file with this hash?
        canon_name = hash_to_canonical.get(hkey)

        if canon_name and canon_name != f.name:
            # This file is a duplicate of canon_name — rewrite deps and delete
            _rewrite_dependencies(conn, f.name, canon_name, PRESETS_DIR)
            # Remove DB record if exists
            conn.execute("DELETE FROM input_assets WHERE filename = ?", (f.name,))
            # Delete from disk
            f.unlink(missing_ok=True)
            comfy_dup = comfyui_input / f.name
            if comfy_dup.exists():
                comfy_dup.unlink(missing_ok=True)
            deduped += 1
            removed.append({"duplicate": f.name, "canonical": canon_name})
            files_on_disk -= 1
            continue

        # Not a duplicate — register if not in DB
        if f.name not in existing_by_name:
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
            hash_to_canonical[hkey] = f.name
        elif not existing_by_name[f.name].get("sha256"):
            # Record exists but has no hash — update it
            conn.execute("UPDATE input_assets SET sha256 = ?, size = ? WHERE filename = ?", (sha256, size, f.name))

        # Track canonical
        if hkey not in hash_to_canonical:
            hash_to_canonical[hkey] = f.name

    conn.commit()

    records_in_db = conn.execute("SELECT COUNT(*) FROM input_assets").fetchone()[0]

    return {
        "files_on_disk": files_on_disk,
        "records_in_db": records_in_db,
        "added": added,
        "deduped": deduped,
        "removed": removed,
    }


def _rewrite_dependencies(conn, old_name: str, new_name: str, presets_dir: Path):
    """Rewrite all references from old_name to new_name across jobs, saved_prompts, and presets."""
    import json as _json

    # 1. jobs.input_image (direct column)
    conn.execute("UPDATE jobs SET input_image = ? WHERE input_image = ?", (new_name, old_name))

    # 2. jobs.params (JSON text — search and replace)
    rows = conn.execute(
        "SELECT rowid, params FROM jobs WHERE params LIKE ?",
        (f"%{old_name}%",)
    ).fetchall()
    for rowid, params_str in rows:
        if params_str:
            updated = params_str.replace(old_name, new_name)
            if updated != params_str:
                conn.execute("UPDATE jobs SET params = ? WHERE rowid = ?", (updated, rowid))

    # 3. saved_prompts.params (JSON text)
    rows = conn.execute(
        "SELECT rowid, params FROM saved_prompts WHERE params LIKE ?",
        (f"%{old_name}%",)
    ).fetchall()
    for rowid, params_str in rows:
        if params_str:
            updated = params_str.replace(old_name, new_name)
            if updated != params_str:
                conn.execute("UPDATE saved_prompts SET params = ? WHERE rowid = ?", (updated, rowid))

    # 4. Preset JSON files on disk
    if presets_dir.exists():
        for pf in presets_dir.glob("*.json"):
            try:
                text = pf.read_text()
                if old_name in text:
                    pf.write_text(text.replace(old_name, new_name))
            except Exception:
                pass


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
