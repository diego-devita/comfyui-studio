"""ComfyUI Studio — Gallery image store backed by SQLite.

This module manages gallery images and videos from CivitAI with two storage
areas under a single SQLite index:

  assets/images/
  ├── gallery.db                 ← SQLite index (this module)
  ├── lookup/{model_id}/previews/ ← Add LoRA preview thumbnails
  ├── models/{model_id}/         ← original/card images, grouped by model
  │   ├── {id}.mp4               ← media file
  │   ├── {id}.thumb.jpg         ← ffmpeg thumbnail (video only)
  │   └── {id}.json              ← full metadata
  └── media/NNN/NNN/             ← community images, flat sharded
      ├── {id}.mp4
      ├── {id}.thumb.jpg
      └── {id}.json

Design decisions:
  - Two storage areas because original images belong to a model (few, stable)
    while community images are numerous and cross-version. Originals are
    grouped by model_id for easy browsing; community is sharded for scale.
  - All files (media + thumb + meta) live in the same directory for each item.
    This avoids a separate meta/ tree and keeps related files together.
  - Single DB table with `source` field ('original' vs 'community') to
    distinguish the two types. Both are queried the same way.
  - Sharding community images by first 3 + next 3 digits of civitai_id keeps
    directories under ~1000 files each, even with tens of thousands.
  - civitai_id is TEXT to support both numeric IDs and UUID fallbacks
    (CivitAI REST API returns id=null for some model version images).
  - file_uuid provides cross-endpoint dedup: same image may have different
    IDs in REST vs tRPC, but CDN URL UUID is always the same.
  - image_versions join table: one community image can appear in multiple
    model versions' galleries without duplicating files on disk.
  - Thread safety: WAL mode + busy_timeout, each thread gets its own
    connection via threading.local(). Proven pattern from db.py.
"""

import json
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

from config import IMAGES_DIR, _now_rome

# ── Paths ────────────────────────────────────────────────────────────────────

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
    """Create tables and indexes, recover from WAL corruption if needed.

    Called once at backend startup. If the DB is corrupted (e.g. pod was
    killed without WAL checkpoint), deletes and recreates it. The gallery
    DB is rebuilable — files on disk are the source of truth.
    """
    # Recovery: try to open and checkpoint. If it fails, delete and recreate.
    if GALLERY_DB_PATH.exists():
        try:
            conn = _get_conn()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        except Exception as e:
            print(f"[gallery_db] DB corrupted ({e}), recreating...", flush=True)
            _local.conn = None
            for p in (GALLERY_DB_PATH,
                      GALLERY_DB_PATH.parent / (GALLERY_DB_PATH.name + "-wal"),
                      GALLERY_DB_PATH.parent / (GALLERY_DB_PATH.name + "-shm")):
                if p.exists():
                    p.unlink()

    conn = _get_conn()
    conn.executescript("""
        -- Main image table: one row per unique media file on disk.
        -- source='original' → file in models/{model_id}/
        -- source='community' → file in media/NNN/NNN/
        CREATE TABLE IF NOT EXISTS gallery_images (
            civitai_id    TEXT PRIMARY KEY,
            file_uuid     TEXT,
            type          TEXT NOT NULL DEFAULT 'image',
            ext           TEXT NOT NULL DEFAULT '.jpeg',
            file_path     TEXT NOT NULL,
            thumb_path    TEXT,
            meta_path     TEXT,

            -- CivitAI coordinates
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

            -- Stats snapshot (at download time)
            reactions     INTEGER DEFAULT 0,
            comments      INTEGER DEFAULT 0,
            collected     INTEGER DEFAULT 0,

            -- Flags
            has_meta      INTEGER DEFAULT 0,
            has_gen_data  INTEGER DEFAULT 0,
            source        TEXT NOT NULL DEFAULT 'community',
            search_mode   TEXT DEFAULT 'fixed',

            -- User flags
            starred       INTEGER DEFAULT 0,

            -- Extracted prompt for full-text search
            prompt        TEXT DEFAULT ''
        );

        -- Join table: maps images to model versions.
        -- One image can belong to multiple versions (e.g. user used both
        -- HIGH and LOW LoRA). Avoids duplicating files on disk.
        CREATE TABLE IF NOT EXISTS image_versions (
            civitai_id    TEXT NOT NULL,
            version_id    INTEGER NOT NULL,
            PRIMARY KEY (civitai_id, version_id),
            FOREIGN KEY (civitai_id) REFERENCES gallery_images(civitai_id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_gi_model_id   ON gallery_images(model_id);
        CREATE INDEX IF NOT EXISTS idx_gi_source      ON gallery_images(source);
        CREATE INDEX IF NOT EXISTS idx_gi_created_at  ON gallery_images(created_at);
        CREATE INDEX IF NOT EXISTS idx_gi_file_uuid   ON gallery_images(file_uuid);
        CREATE INDEX IF NOT EXISTS idx_iv_version_id  ON image_versions(version_id);

        -- CivitAI tag dictionary: maps numeric tag IDs to human-readable names.
        -- Populated on-demand via POST /api/admin/civitai/tags/sync.
        -- type values: Moderation, UserGenerated, Label, Category
        CREATE TABLE IF NOT EXISTS civitai_tags (
            id            INTEGER PRIMARY KEY,
            name          TEXT NOT NULL DEFAULT '',
            type          TEXT DEFAULT '',
            synced_at     TEXT
        );

        -- User-chosen preview image per model (overrides default first-original).
        CREATE TABLE IF NOT EXISTS gallery_previews (
            model_id      INTEGER PRIMARY KEY,
            civitai_id    TEXT NOT NULL
        );
    """)
    conn.commit()


# ── Path helpers ─────────────────────────────────────────────────────────────

def _shard_prefix(civitai_id: str) -> tuple[str, str]:
    """Split an ID into two 3-character shard components.

    For numeric IDs: 117242376 → ('117', '242')
    For UUIDs: 745fa4bb-... → ('745', 'fa4')
    Creates a balanced directory tree — max ~1000 files per leaf.
    """
    s = str(civitai_id).replace("-", "")
    d1 = s[:3] if len(s) >= 3 else s.ljust(3, "0")
    d2 = s[3:6] if len(s) >= 6 else (s[3:] if len(s) > 3 else "000").ljust(3, "0")
    return d1, d2


def original_path(model_id: int, civitai_id: str, ext: str) -> str:
    """Path for an original/card image: models/{model_id}/{id}{ext}

    Originals are grouped by model_id (not sharded) because there are
    few per model and they logically belong to the model, not globally.
    """
    return f"models/{model_id}/{civitai_id}{ext}"


def community_path(civitai_id: str, ext: str) -> str:
    """Path for a community image: media/NNN/NNN/{id}{ext}

    Community images are sharded because there can be thousands.
    """
    d1, d2 = _shard_prefix(civitai_id)
    return f"media/{d1}/{d2}/{civitai_id}{ext}"


def file_path_for(source: str, model_id: int, civitai_id: str, ext: str) -> str:
    """Compute the relative file path based on source type."""
    if source == "original":
        return original_path(model_id, civitai_id, ext)
    return community_path(civitai_id, ext)


def thumb_path_for(source: str, model_id: int, civitai_id: str) -> str:
    """Compute thumbnail path — same directory as the media file."""
    if source == "original":
        return f"models/{model_id}/{civitai_id}.thumb.jpg"
    d1, d2 = _shard_prefix(civitai_id)
    return f"media/{d1}/{d2}/{civitai_id}.thumb.jpg"


def meta_path_for(source: str, model_id: int, civitai_id: str) -> str:
    """Compute metadata JSON path — same directory as the media file."""
    if source == "original":
        return f"models/{model_id}/{civitai_id}.json"
    d1, d2 = _shard_prefix(civitai_id)
    return f"media/{d1}/{d2}/{civitai_id}.json"


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

    Cross-endpoint dedup: same image may have different civitai_ids in
    REST vs tRPC, but CDN URL UUID is unique.
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

    Uses UPSERT so it's safe to call multiple times for the same image.
    On conflict, updates metadata fields but preserves original file paths
    and download timestamp.
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

    The same image can be linked to multiple versions without
    duplicating files on disk.
    """
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO image_versions (civitai_id, version_id) VALUES (?, ?)",
        (str(civitai_id), version_id)
    )
    conn.commit()


def toggle_starred(civitai_id: str) -> bool:
    """Toggle the starred flag on an image. Returns new starred state.

    Used by the UI star button — one click stars, another unstars.
    """
    conn = _get_conn()
    conn.execute(
        "UPDATE gallery_images SET starred = NOT starred WHERE civitai_id = ?",
        (str(civitai_id),)
    )
    conn.commit()
    row = conn.execute(
        "SELECT starred FROM gallery_images WHERE civitai_id = ?",
        (str(civitai_id),)
    ).fetchone()
    return bool(row["starred"]) if row else False


def get_image(civitai_id: str) -> dict | None:
    """Get a single image record by its ID."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM gallery_images WHERE civitai_id = ?", (str(civitai_id),)
    ).fetchone()
    return dict(row) if row else None


def list_images_by_version(version_id: int, source: str | None = None,
                           order_by: str = "created_at",
                           order_desc: bool = True,
                           starred_only: bool = False) -> list[dict]:
    """List all images associated with a specific model version.

    Primary query for the gallery UI: shows images linked to a version
    via the image_versions join table.
    """
    conn = _get_conn()
    allowed_order = {"created_at", "reactions", "comments", "collected", "downloaded_at"}
    if order_by not in allowed_order:
        order_by = "created_at"
    direction = "DESC" if order_desc else "ASC"

    wheres = ["iv.version_id = ?"]
    params: list = [version_id]
    if source:
        wheres.append("g.source = ?")
        params.append(source)
    if starred_only:
        wheres.append("g.starred = 1")

    sql = f"""
        SELECT g.* FROM gallery_images g
        JOIN image_versions iv ON g.civitai_id = iv.civitai_id
        WHERE {" AND ".join(wheres)}
        ORDER BY g.{order_by} {direction}
    """
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def list_images_by_model(model_id: int, source: str | None = None,
                         order_by: str = "created_at",
                         order_desc: bool = True,
                         starred_only: bool = False) -> list[dict]:
    """List all images for a model (across all versions).

    Used for original/card images which belong to the model, not a version.
    Also useful for seeing the full gallery across all versions.
    """
    conn = _get_conn()
    allowed_order = {"created_at", "reactions", "comments", "collected", "downloaded_at"}
    if order_by not in allowed_order:
        order_by = "created_at"
    direction = "DESC" if order_desc else "ASC"

    wheres = ["model_id = ?"]
    params: list = [model_id]
    if source:
        wheres.append("source = ?")
        params.append(source)
    if starred_only:
        wheres.append("starred = 1")

    sql = f"""
        SELECT * FROM gallery_images
        WHERE {" AND ".join(wheres)}
        ORDER BY {order_by} {direction}
    """
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def count_and_size(model_id: int | None = None,
                   version_id: int | None = None) -> dict:
    """Get counts and total file size by source type.

    Returns: original_count, community_count, original_bytes, community_bytes.
    """
    conn = _get_conn()
    if version_id:
        # For community images linked to this version + originals for the model
        sql = """
            SELECT g.source,
                   COUNT(*) as count,
                   COALESCE(SUM(g.file_size), 0) as bytes
            FROM gallery_images g
            LEFT JOIN image_versions iv ON g.civitai_id = iv.civitai_id
            WHERE (iv.version_id = ? OR (g.source = 'original' AND g.model_id = (
                SELECT model_id FROM gallery_images g2
                JOIN image_versions iv2 ON g2.civitai_id = iv2.civitai_id
                WHERE iv2.version_id = ? LIMIT 1
            )))
            GROUP BY g.source
        """
        rows = conn.execute(sql, (version_id, version_id)).fetchall()
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

    result = {"original_count": 0, "community_count": 0,
              "original_bytes": 0, "community_bytes": 0}
    for row in rows:
        src = row["source"]
        result[f"{src}_count"] = row["count"]
        result[f"{src}_bytes"] = row["bytes"]
    return result


def community_counts_by_model() -> dict[int, dict]:
    """Return {model_id: {count, first_id, custom_id}} for all models with community images.

    first_id: civitai_id of first original image (default thumbnail).
    custom_id: user-chosen preview (from gallery_previews table), or None.
    """
    conn = _get_conn()
    rows = conn.execute("""
        SELECT g.model_id, COUNT(*) as cnt,
               (SELECT civitai_id FROM gallery_images g2
                WHERE g2.model_id = g.model_id
                ORDER BY CASE g2.source WHEN 'original' THEN 0 ELSE 1 END,
                         g2.rowid ASC LIMIT 1) as first_id,
               p.civitai_id as custom_id
        FROM gallery_images g
        LEFT JOIN gallery_previews p ON g.model_id = p.model_id
        WHERE g.source = 'community'
        GROUP BY g.model_id
    """).fetchall()
    return {row[0]: {"count": row[1], "first_id": row[2], "custom_id": row[3]} for row in rows}


def set_preview(model_id: int, civitai_id: str):
    """Set user-chosen preview image for a model."""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO gallery_previews (model_id, civitai_id) VALUES (?, ?) "
        "ON CONFLICT(model_id) DO UPDATE SET civitai_id = excluded.civitai_id",
        (model_id, civitai_id)
    )
    conn.commit()


def get_preview(model_id: int) -> str | None:
    """Get user-chosen preview image for a model, or None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT civitai_id FROM gallery_previews WHERE model_id = ?", (model_id,)
    ).fetchone()
    return row[0] if row else None


def delete_by_model(model_id: int) -> tuple[int, list[str]]:
    """Delete all gallery images for a model.

    Returns (count, paths) — caller deletes files from disk.
    Cascade deletes image_versions automatically.
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
    """Remove version associations only (not the images themselves)."""
    conn = _get_conn()
    count = conn.execute(
        "DELETE FROM image_versions WHERE version_id = ?", (version_id,)
    ).rowcount
    conn.commit()
    return count


# ── Helpers ──────────────────────────────────────────────────────────────────

# ── CivitAI Tags ─────────────────────────────────────────────────────────────
# These functions manage a local cache of CivitAI's tag dictionary.
# Tags are synced on-demand — the user triggers a sync, and we resolve
# tag IDs to names via the tRPC batch API, storing results locally.

def upsert_tags(tags: list[dict]):
    """Insert or update multiple CivitAI tags.

    Each tag dict should have: id (int), name (str), type (str).
    Uses UPSERT so it's safe to call repeatedly — existing tags get
    their name/type updated if CivitAI changed them.
    """
    conn = _get_conn()
    now = _now_italian()
    for tag in tags:
        conn.execute("""
            INSERT INTO civitai_tags (id, name, type, synced_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                type = excluded.type,
                synced_at = excluded.synced_at
        """, (tag["id"], tag.get("name", ""), tag.get("type", ""), now))
    conn.commit()


def get_all_tags() -> list[dict]:
    """Return all cached CivitAI tags, sorted by name.

    Returns list of {id, name, type, synced_at}.
    """
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, name, type, synced_at FROM civitai_tags ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


def get_tags_by_ids(tag_ids: list[int]) -> list[dict]:
    """Look up specific tags by their IDs. Returns only known tags."""
    if not tag_ids:
        return []
    conn = _get_conn()
    placeholders = ",".join("?" * len(tag_ids))
    rows = conn.execute(
        f"SELECT id, name, type FROM civitai_tags WHERE id IN ({placeholders})",
        tag_ids
    ).fetchall()
    return [dict(r) for r in rows]


def get_unknown_tag_ids(tag_ids: list[int]) -> list[int]:
    """Return tag IDs that are NOT yet in our local cache.

    Used during sync to know which tags need resolving from CivitAI.
    """
    if not tag_ids:
        return []
    conn = _get_conn()
    placeholders = ",".join("?" * len(tag_ids))
    rows = conn.execute(
        f"SELECT id FROM civitai_tags WHERE id IN ({placeholders})",
        tag_ids
    ).fetchall()
    known = {r["id"] for r in rows}
    return [tid for tid in tag_ids if tid not in known]


def tag_count() -> int:
    """Return total number of cached tags."""
    conn = _get_conn()
    row = conn.execute("SELECT COUNT(*) as c FROM civitai_tags").fetchone()
    return row["c"] if row else 0


def _now_italian() -> str:
    """Current timestamp in Italian timezone, ISO format."""
    return _now_rome().strftime("%Y-%m-%dT%H:%M:%S")
