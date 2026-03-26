"""ComfyUI Studio — Gallery image store backed by SQLite.

This module manages a flat, content-addressed media store for CivitAI gallery
images and videos. It replaces the old per-model directory structure with:

  catalogs/.images/
  ├── gallery.db         ← SQLite index (this module)
  ├── media/NNN/NNN/     ← sharded media files + thumbnails
  └── meta/NNN/NNN/      ← JSON metadata (full API response, generation data)

Design decisions:
  - Separate DB file (not in db/studio.db) because gallery data is ephemeral
    and rebuildable from CivitAI. Keeping it separate means gallery wipes
    don't risk critical data like jobs.
  - Sharding by first 3 + next 3 digits of civitai_id keeps directories
    under ~1000 files each, even with tens of thousands of images.
  - civitai_id is TEXT not INTEGER because card images may only have a UUID
    (CivitAI REST API returns id=null for model version images).
  - file_uuid provides cross-endpoint dedup: the same image may appear under
    different IDs in REST vs tRPC, but the CDN URL UUID is always the same.
  - image_versions join table supports the reality that one community image
    can belong to multiple model versions (user used both HIGH and LOW LoRA).
  - Thread safety via WAL mode + busy_timeout, matching the proven pattern
    in db.py. Each thread gets its own connection via threading.local().
"""

import json
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

from config import CATALOGS_DIR

# ── Paths ────────────────────────────────────────────────────────────────────
# Gallery DB and media live under the catalogs .images directory.
# This keeps everything together and separate from the main studio DB.

IMAGES_DIR = CATALOGS_DIR / ".images"
GALLERY_DB_PATH = IMAGES_DIR / "gallery.db"

_local = threading.local()


# ── Connection management ────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    """Get a thread-local SQLite connection.

    Each thread gets its own connection to avoid SQLite threading issues.
    WAL mode allows concurrent reads while one thread writes.
    busy_timeout prevents immediate SQLITE_BUSY errors under contention
    from the 6-20 parallel download workers.
    """
    if not hasattr(_local, "conn") or _local.conn is None:
        GALLERY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(GALLERY_DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        _local.conn = conn
    return _local.conn


# ── Schema ───────────────────────────────────────────────────────────────────

def init_gallery_db():
    """Create tables and indexes if they don't exist.

    Called once at backend startup. Idempotent — safe to call multiple times.
    """
    conn = _get_conn()
    conn.executescript("""
        -- Main image table: one row per unique media file on disk.
        -- civitai_id is the primary key (numeric ID as text, or UUID fallback).
        CREATE TABLE IF NOT EXISTS gallery_images (
            civitai_id    TEXT PRIMARY KEY,
            file_uuid     TEXT,
            type          TEXT NOT NULL DEFAULT 'image',
            ext           TEXT NOT NULL DEFAULT '.jpeg',
            file_path     TEXT NOT NULL,
            thumb_path    TEXT,
            meta_path     TEXT,

            -- CivitAI coordinates: where this image came from
            model_id      INTEGER NOT NULL,
            post_id       INTEGER,
            post_title    TEXT DEFAULT '',
            username      TEXT DEFAULT '',
            base_model    TEXT DEFAULT '',

            -- Media properties
            width         INTEGER,
            height        INTEGER,
            duration      REAL,
            audio         INTEGER DEFAULT 0,
            file_size     INTEGER DEFAULT 0,

            -- Timestamps
            created_at    TEXT,
            downloaded_at TEXT,

            -- Stats snapshot (captured at download time)
            reactions     INTEGER DEFAULT 0,
            comments      INTEGER DEFAULT 0,
            collected     INTEGER DEFAULT 0,

            -- Flags
            has_meta      INTEGER DEFAULT 0,
            has_gen_data  INTEGER DEFAULT 0,
            source        TEXT NOT NULL DEFAULT 'community',
            search_mode   TEXT DEFAULT 'fixed',

            -- Extracted prompt for full-text search
            prompt        TEXT DEFAULT ''
        );

        -- Join table: maps images to model versions.
        -- One image can belong to multiple versions (e.g. user used both
        -- HIGH and LOW LoRA). This avoids duplicating files on disk.
        CREATE TABLE IF NOT EXISTS image_versions (
            civitai_id    TEXT NOT NULL,
            version_id    INTEGER NOT NULL,
            PRIMARY KEY (civitai_id, version_id),
            FOREIGN KEY (civitai_id) REFERENCES gallery_images(civitai_id)
                ON DELETE CASCADE
        );

        -- Indexes for the queries we actually run:
        -- list by model, list by version, sort by date, dedup by uuid
        CREATE INDEX IF NOT EXISTS idx_gi_model_id   ON gallery_images(model_id);
        CREATE INDEX IF NOT EXISTS idx_gi_source      ON gallery_images(source);
        CREATE INDEX IF NOT EXISTS idx_gi_created_at  ON gallery_images(created_at);
        CREATE INDEX IF NOT EXISTS idx_gi_file_uuid   ON gallery_images(file_uuid);
        CREATE INDEX IF NOT EXISTS idx_iv_version_id  ON image_versions(version_id);
    """)
    conn.commit()


# ── Path helpers ─────────────────────────────────────────────────────────────
# These compute the sharded directory structure for a given civitai_id.
# The sharding ensures no single directory accumulates too many files,
# which would degrade filesystem performance on ext4.
#
# Numeric IDs:  117242376 → media/117/242/117242376.mp4
# UUID fallback: 745fa4bb-... → media/745/fa4/745fa4bb-....mp4

def _shard_prefix(civitai_id: str) -> tuple[str, str]:
    """Split an ID into two 3-character shard components.

    For numeric IDs (most common), this splits by digit position.
    For UUIDs, it splits by hex character position.
    Either way, it creates a balanced directory tree.
    """
    s = str(civitai_id).replace("-", "")  # strip UUID dashes for consistent sharding
    d1 = s[:3] if len(s) >= 3 else s.ljust(3, "0")
    d2 = s[3:6] if len(s) >= 6 else (s[3:] if len(s) > 3 else "000").ljust(3, "0")
    return d1, d2


def media_path(civitai_id: str, ext: str) -> str:
    """Compute relative path for a media file: media/NNN/NNN/{id}{ext}"""
    d1, d2 = _shard_prefix(civitai_id)
    return f"media/{d1}/{d2}/{civitai_id}{ext}"


def thumb_path(civitai_id: str) -> str:
    """Compute relative path for a video thumbnail."""
    d1, d2 = _shard_prefix(civitai_id)
    return f"media/{d1}/{d2}/{civitai_id}.thumb.jpg"


def meta_path(civitai_id: str) -> str:
    """Compute relative path for the JSON metadata file."""
    d1, d2 = _shard_prefix(civitai_id)
    return f"meta/{d1}/{d2}/{civitai_id}.json"


def abs_path(relative: str) -> Path:
    """Convert a relative store path to an absolute filesystem path."""
    return IMAGES_DIR / relative


# ── CRUD operations ──────────────────────────────────────────────────────────

def image_exists(civitai_id: str) -> bool:
    """Check if an image is already in the database.

    Used during download to skip already-downloaded images without
    hitting the filesystem. Faster than os.path.exists() for bulk checks.
    """
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM gallery_images WHERE civitai_id = ?", (str(civitai_id),)
    ).fetchone()
    return row is not None


def uuid_exists(file_uuid: str) -> bool:
    """Check if an image with this CDN UUID already exists.

    Used for cross-endpoint dedup: the same image may have different
    civitai_ids in REST vs tRPC responses, but the CDN URL UUID is unique.
    """
    if not file_uuid:
        return False
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM gallery_images WHERE file_uuid = ?", (file_uuid,)
    ).fetchone()
    return row is not None


def insert_image(data: dict):
    """Insert or update an image record.

    Uses UPSERT (ON CONFLICT) so it's safe to call multiple times for the
    same image. On conflict, updates metadata fields but preserves the
    original file paths and download timestamp.
    """
    conn = _get_conn()
    conn.execute("""
        INSERT INTO gallery_images (
            civitai_id, file_uuid, type, ext, file_path, thumb_path, meta_path,
            model_id, post_id, post_title, username, base_model,
            width, height, duration, audio, file_size,
            created_at, downloaded_at,
            reactions, comments, collected,
            has_meta, has_gen_data, source, search_mode, prompt
        ) VALUES (
            :civitai_id, :file_uuid, :type, :ext, :file_path, :thumb_path, :meta_path,
            :model_id, :post_id, :post_title, :username, :base_model,
            :width, :height, :duration, :audio, :file_size,
            :created_at, :downloaded_at,
            :reactions, :comments, :collected,
            :has_meta, :has_gen_data, :source, :search_mode, :prompt
        )
        ON CONFLICT(civitai_id) DO UPDATE SET
            has_meta = excluded.has_meta,
            has_gen_data = excluded.has_gen_data,
            reactions = excluded.reactions,
            comments = excluded.comments,
            collected = excluded.collected
    """, {
        "civitai_id": str(data.get("civitai_id", "")),
        "file_uuid": data.get("file_uuid"),
        "type": data.get("type", "image"),
        "ext": data.get("ext", ".jpeg"),
        "file_path": data.get("file_path", ""),
        "thumb_path": data.get("thumb_path"),
        "meta_path": data.get("meta_path"),
        "model_id": data.get("model_id"),
        "post_id": data.get("post_id"),
        "post_title": data.get("post_title", ""),
        "username": data.get("username", ""),
        "base_model": data.get("base_model", ""),
        "width": data.get("width"),
        "height": data.get("height"),
        "duration": data.get("duration"),
        "audio": 1 if data.get("audio") else 0,
        "file_size": data.get("file_size", 0),
        "created_at": data.get("created_at"),
        "downloaded_at": data.get("downloaded_at") or _now_italian(),
        "reactions": data.get("reactions", 0),
        "comments": data.get("comments", 0),
        "collected": data.get("collected", 0),
        "has_meta": 1 if data.get("has_meta") else 0,
        "has_gen_data": 1 if data.get("has_gen_data") else 0,
        "source": data.get("source", "community"),
        "search_mode": data.get("search_mode", "fixed"),
        "prompt": data.get("prompt", ""),
    })
    conn.commit()


def link_version(civitai_id: str, version_id: int):
    """Associate an image with a model version.

    Called after insert_image to record that this image was found via
    a specific version's gallery. The same image can be linked to
    multiple versions without duplicating files.
    """
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO image_versions (civitai_id, version_id) VALUES (?, ?)",
        (str(civitai_id), version_id)
    )
    conn.commit()


def get_image(civitai_id: str) -> dict | None:
    """Get a single image record by its ID."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM gallery_images WHERE civitai_id = ?", (str(civitai_id),)
    ).fetchone()
    return dict(row) if row else None


def list_images_by_version(version_id: int, source: str | None = None,
                           order_by: str = "created_at",
                           order_desc: bool = True) -> list[dict]:
    """List all images associated with a specific model version.

    This is the primary query for the gallery UI: when you open a LoRA's
    gallery, it shows images linked to that version via image_versions.

    Args:
        version_id: CivitAI model version ID
        source: Optional filter — 'card' or 'community' or None for all
        order_by: Column to sort by (created_at, reactions, etc.)
        order_desc: Sort descending (newest/most popular first)
    """
    conn = _get_conn()
    # Whitelist allowed order_by columns to prevent SQL injection
    allowed_order = {"created_at", "reactions", "comments", "collected", "downloaded_at"}
    if order_by not in allowed_order:
        order_by = "created_at"
    direction = "DESC" if order_desc else "ASC"

    sql = f"""
        SELECT g.* FROM gallery_images g
        JOIN image_versions iv ON g.civitai_id = iv.civitai_id
        WHERE iv.version_id = ?
        {"AND g.source = ?" if source else ""}
        ORDER BY g.{order_by} {direction}
    """
    params = [version_id]
    if source:
        params.append(source)
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def list_images_by_model(model_id: int, source: str | None = None,
                         order_by: str = "created_at",
                         order_desc: bool = True) -> list[dict]:
    """List all images for a model (across all versions).

    Used when the user wants to see the full gallery for a model,
    not filtered by a specific version.
    """
    conn = _get_conn()
    allowed_order = {"created_at", "reactions", "comments", "collected", "downloaded_at"}
    if order_by not in allowed_order:
        order_by = "created_at"
    direction = "DESC" if order_desc else "ASC"

    sql = f"""
        SELECT * FROM gallery_images
        WHERE model_id = ?
        {"AND source = ?" if source else ""}
        ORDER BY {order_by} {direction}
    """
    params = [model_id]
    if source:
        params.append(source)
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def count_and_size(model_id: int | None = None,
                   version_id: int | None = None) -> dict:
    """Get counts and total file size for a model or version.

    Returns dict with: card_count, community_count, card_bytes, community_bytes.
    Used by the gallery status endpoint.
    """
    conn = _get_conn()
    if version_id:
        sql = """
            SELECT g.source,
                   COUNT(*) as count,
                   COALESCE(SUM(g.file_size), 0) as bytes
            FROM gallery_images g
            JOIN image_versions iv ON g.civitai_id = iv.civitai_id
            WHERE iv.version_id = ?
            GROUP BY g.source
        """
        rows = conn.execute(sql, (version_id,)).fetchall()
    elif model_id:
        sql = """
            SELECT source,
                   COUNT(*) as count,
                   COALESCE(SUM(file_size), 0) as bytes
            FROM gallery_images
            WHERE model_id = ?
            GROUP BY source
        """
        rows = conn.execute(sql, (model_id,)).fetchall()
    else:
        return {}

    result = {"card_count": 0, "community_count": 0,
              "card_bytes": 0, "community_bytes": 0}
    for row in rows:
        src = row["source"]
        result[f"{src}_count"] = row["count"]
        result[f"{src}_bytes"] = row["bytes"]
    return result


def delete_by_model(model_id: int) -> int:
    """Delete all gallery images for a model.

    Removes DB records (cascade deletes image_versions) and returns
    the list of file paths to delete from disk. Caller is responsible
    for actually deleting the files — this keeps DB ops and filesystem
    ops separate for reliability.
    """
    conn = _get_conn()
    rows = conn.execute(
        "SELECT file_path, thumb_path, meta_path FROM gallery_images WHERE model_id = ?",
        (model_id,)
    ).fetchall()
    paths = []
    for row in rows:
        for field in ("file_path", "thumb_path", "meta_path"):
            if row[field]:
                paths.append(row[field])
    count = conn.execute(
        "DELETE FROM gallery_images WHERE model_id = ?", (model_id,)
    ).rowcount
    conn.commit()
    return count, paths


def delete_by_version(version_id: int) -> int:
    """Remove version associations. Images that have no remaining version
    links are orphans and can be cleaned up separately."""
    conn = _get_conn()
    count = conn.execute(
        "DELETE FROM image_versions WHERE version_id = ?", (version_id,)
    ).rowcount
    conn.commit()
    return count


# ── Migration ────────────────────────────────────────────────────────────────
# Migrates from old per-model directory structure to flat sharded store.
# Idempotent — safe to run multiple times. Files are moved, not copied,
# to avoid doubling disk usage during migration.

def migrate_from_directories(images_dir: Path) -> int:
    """Migrate old directory-based gallery to flat store + SQLite.

    Old structure: {model_id}/gallery/{card|community}/{id}.{ext}
    New structure: media/NNN/NNN/{id}.{ext}

    Returns count of migrated images.
    """
    import shutil

    count = 0
    # Find all model directories that have a gallery subdirectory
    for model_dir in images_dir.iterdir():
        if not model_dir.is_dir() or model_dir.name in ("media", "meta"):
            continue
        try:
            model_id = int(model_dir.name)
        except ValueError:
            continue

        gallery_dir = model_dir / "gallery"
        if not gallery_dir.is_dir():
            continue

        for source in ("card", "community"):
            source_dir = gallery_dir / source
            if not source_dir.is_dir():
                continue

            for f in source_dir.iterdir():
                # Only process media files, not metadata or thumbnails
                if f.suffix not in (".jpeg", ".mp4"):
                    continue
                if f.stat().st_size == 0:
                    continue

                civitai_id = f.stem
                ext = f.suffix

                # Skip if already in DB
                if image_exists(civitai_id):
                    # Just ensure the version link exists
                    # We don't know the version_id from the old structure,
                    # so we skip version linking during migration
                    continue

                # Compute new paths
                new_file = media_path(civitai_id, ext)
                new_thumb = thumb_path(civitai_id)
                new_meta = meta_path(civitai_id)

                # Move media file
                dest = abs_path(new_file)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(dest))

                # Move thumbnail if exists
                old_thumb = f.with_suffix(".thumb.jpg")
                if old_thumb.exists():
                    thumb_dest = abs_path(new_thumb)
                    thumb_dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(old_thumb), str(thumb_dest))

                # Move metadata JSON if exists
                old_meta = f.with_suffix(".json")
                meta_data = {}
                if old_meta.exists():
                    try:
                        meta_data = json.loads(old_meta.read_text())
                    except Exception:
                        pass
                    meta_dest = abs_path(new_meta)
                    meta_dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(old_meta), str(meta_dest))

                # Extract stats from metadata
                stats = meta_data.get("stats") or {}
                prompt = ""
                raw_meta = meta_data.get("raw_meta") or {}
                if isinstance(raw_meta, dict):
                    prompt = raw_meta.get("prompt", "")

                # Insert into DB
                insert_image({
                    "civitai_id": civitai_id,
                    "file_uuid": meta_data.get("url", "").split("/")[-2] if "/" in meta_data.get("url", "") else None,
                    "type": meta_data.get("type", "video" if ext == ".mp4" else "image"),
                    "ext": ext,
                    "file_path": new_file,
                    "thumb_path": new_thumb if old_thumb.exists() or abs_path(new_thumb).exists() else None,
                    "meta_path": new_meta if meta_data else None,
                    "model_id": model_id,
                    "post_id": meta_data.get("postId"),
                    "post_title": meta_data.get("postTitle", ""),
                    "username": meta_data.get("username", ""),
                    "base_model": meta_data.get("baseModel", ""),
                    "width": meta_data.get("width"),
                    "height": meta_data.get("height"),
                    "duration": meta_data.get("duration"),
                    "audio": meta_data.get("audio"),
                    "file_size": dest.stat().st_size if dest.exists() else 0,
                    "created_at": meta_data.get("createdAt"),
                    "has_meta": bool(meta_data),
                    "has_gen_data": bool(meta_data.get("generation_data")),
                    "source": source,
                    "prompt": prompt,
                })
                count += 1

        # Clean up empty directories after migration
        try:
            if gallery_dir.exists():
                shutil.rmtree(gallery_dir)
            # Remove model dir if empty (only had gallery)
            remaining = list(model_dir.iterdir())
            if not remaining:
                model_dir.rmdir()
        except Exception:
            pass

    return count


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now_italian() -> str:
    """Current timestamp in Italian timezone, ISO format.

    Matches the convention used throughout the project: all user-facing
    timestamps are in Europe/Rome timezone.
    """
    return datetime.now(timezone(timedelta(hours=1))).strftime("%Y-%m-%dT%H:%M:%S")
