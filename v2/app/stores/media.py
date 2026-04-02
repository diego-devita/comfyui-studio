"""Media Store — centralised file store with metadata extraction.

Every media file (image or video) enters the system through this module.
Files are stored in a sharded flat directory, validated, analysed, and
registered in SQLite.  Nothing else writes to the store directory.

Store layout
────────────
  MEDIA_STORE_DIR/
    ab/cd/<uuid>.ext          ← original file
    ab/cd/<uuid>.thumb.xs.jpg ← 100px thumb
    ab/cd/<uuid>.thumb.sm.jpg ← 200px thumb
    ab/cd/<uuid>.thumb.md.jpg ← 400px thumb

Tables (inside studio.db)
─────────────────────────
  media         ← one row per physical file
  media_thumbs  ← 0-3 rows per media (xs, sm, md)
"""

import hashlib
import json
import sqlite3
import subprocess
import uuid
from pathlib import Path

import os
from datetime import datetime, timezone

from v2.app.core.settings import MEDIA_STORE_DIR, now_iso
from v2.app.core.db import get_conn, register_schema

# ══════════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════
# ────────────────────────────────────────────────────────────────

ALLOWED_IMAGE = {
    ".jpeg", ".jpg", ".png", ".webp", ".gif", ".bmp",
    ".tiff", ".tif", ".avif", ".jxl", ".apng", ".ico", ".svg",
}
ALLOWED_VIDEO = {
    ".mp4", ".webm", ".mov", ".avi", ".mkv",
}
ALLOWED = ALLOWED_IMAGE | ALLOWED_VIDEO

THUMB_SIZES = {
    "xs": 100,
    "sm": 200,
    "md": 400,
}

THUMB_QUALITY = 70

SCHEMA_VERSION = 1

# ══════════════════════════════════════════════════════════════════════════════
#  SCHEMA
# ══════════════════════════════════════════════════════════════════════════════

def _init_schema(conn: sqlite3.Connection):
    """Create media tables and indexes.  Called by db.init_db()."""
    MEDIA_STORE_DIR.mkdir(parents=True, exist_ok=True)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS media (
            id              TEXT PRIMARY KEY,
            file_path       TEXT NOT NULL,
            thumb_path      TEXT,

            -- Type and format
            type            TEXT NOT NULL CHECK (type IN ('image', 'video')),
            ext             TEXT NOT NULL,
            mime            TEXT,
            original_name   TEXT,

            -- Physical dimensions
            width           INTEGER,
            height          INTEGER,

            -- Video properties
            duration        REAL,
            audio           INTEGER DEFAULT 0 CHECK (audio IN (0, 1)),
            fps             REAL,
            codec           TEXT,

            -- Colour properties
            color_space     TEXT,
            bit_depth       INTEGER,
            has_alpha       INTEGER DEFAULT 0 CHECK (has_alpha IN (0, 1)),

            -- File weight
            file_size       INTEGER NOT NULL DEFAULT 0,
            thumb_size      INTEGER DEFAULT 0,

            -- Integrity and dedup
            hash            TEXT,
            schema_version  INTEGER DEFAULT 1,

            -- Embedded metadata (JSON or NULL)
            exif            TEXT,

            -- Provenance
            origin          TEXT NOT NULL CHECK (origin IN ('civitai', 'comfyui', 'upload', 'generated')),
            origin_id       TEXT,
            origin_url      TEXT,

            -- Timestamp
            created_at      TEXT NOT NULL        -- ISO 8601 UTC (YYYY-MM-DDTHH:MM:SSZ)
        );

        CREATE INDEX IF NOT EXISTS idx_media_hash   ON media(hash);
        CREATE INDEX IF NOT EXISTS idx_media_type   ON media(type);
        CREATE INDEX IF NOT EXISTS idx_media_origin ON media(origin, origin_id);

        CREATE TABLE IF NOT EXISTS media_thumbs (
            media_id    TEXT NOT NULL,
            size        TEXT NOT NULL CHECK (size IN ('xs', 'sm', 'md')),
            file_path   TEXT NOT NULL,
            file_size   INTEGER DEFAULT 0,
            width       INTEGER,
            height      INTEGER,
            PRIMARY KEY (media_id, size),
            FOREIGN KEY (media_id) REFERENCES media(id) ON DELETE CASCADE
        );
    """)


# Register with db.py — called when db.init_db() runs
register_schema("media_store", _init_schema)


# ══════════════════════════════════════════════════════════════════════════════
#  PATH HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _shard_dir(media_id: str) -> str:
    """Return shard path: first 2 + next 2 chars of UUID → 'ab/cd'."""
    return f"{media_id[:2]}/{media_id[2:4]}"


def _rel_path(media_id: str, ext: str) -> str:
    """Relative path inside the store: ab/cd/uuid.ext"""
    return f"{_shard_dir(media_id)}/{media_id}{ext}"


def _abs_path(rel: str) -> Path:
    """Absolute path from relative store path."""
    return MEDIA_STORE_DIR / rel


def _ensure_dir(rel: str):
    """Create parent directory for a relative path."""
    _abs_path(rel).parent.mkdir(parents=True, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
#  VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

def validate(path: Path) -> tuple[str, str]:
    """Validate file: extension must be allowed and content must match.

    Returns (type, mime).
    Raises ValueError if invalid.
    """
    ext = path.suffix.lower()
    if ext not in ALLOWED:
        raise ValueError(f"Extension '{ext}' not allowed")

    if ext in ALLOWED_IMAGE:
        if ext == ".svg":
            # SVG is text/xml — don't try to open with Pillow
            return "image", "image/svg+xml"
        try:
            from PIL import Image
            img = Image.open(path)
            img.verify()
            # Re-open after verify (verify closes the fp)
            img = Image.open(path)
            mime = Image.MIME.get(img.format, "application/octet-stream")
            img.close()
            return "image", mime
        except Exception as e:
            raise ValueError(f"Not a valid image ({ext}): {e}")

    if ext in ALLOWED_VIDEO:
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries",
                 "format=format_name", "-of", "csv=p=0", str(path)],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode != 0 or not r.stdout.strip():
                raise ValueError(f"ffprobe failed for {ext}")
            fmt = r.stdout.strip().split(",")[0]
            mime = f"video/{fmt}" if fmt else f"video/{ext.lstrip('.')}"
            return "video", mime
        except subprocess.TimeoutExpired:
            raise ValueError(f"ffprobe timeout for {ext}")
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Not a valid video ({ext}): {e}")

    raise ValueError(f"Unhandled extension '{ext}'")


# ══════════════════════════════════════════════════════════════════════════════
#  PROPERTY EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def _extract_image_properties(path: Path) -> dict:
    """Extract properties from an image file using Pillow."""
    from PIL import Image
    props = {}
    try:
        img = Image.open(path)
        props["width"] = img.width
        props["height"] = img.height
        props["codec"] = (img.format or "").lower()
        props["color_space"] = img.mode
        props["has_alpha"] = 1 if img.mode in ("RGBA", "LA", "PA", "RGBa") else 0

        # Bit depth from mode
        mode_bits = {
            "1": 1, "L": 8, "P": 8, "RGB": 8, "RGBA": 8,
            "CMYK": 8, "YCbCr": 8, "LAB": 8, "HSV": 8,
            "I": 32, "F": 32, "LA": 8, "PA": 8, "RGBa": 8,
            "I;16": 16, "I;16L": 16, "I;16B": 16,
        }
        props["bit_depth"] = mode_bits.get(img.mode, 8)

        # Override from image info if available
        if img.info.get("bits"):
            props["bit_depth"] = img.info["bits"]

        img.close()
    except Exception:
        pass
    return props


def _extract_video_properties(path: Path) -> dict:
    """Extract properties from a video file using ffprobe."""
    props = {}
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return props

        data = json.loads(r.stdout)
        streams = data.get("streams", [])

        # Video stream
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        if video:
            props["width"] = video.get("width")
            props["height"] = video.get("height")
            props["codec"] = video.get("codec_name", "")
            props["color_space"] = video.get("pix_fmt", "")
            props["bit_depth"] = video.get("bits_per_raw_sample")
            if props["bit_depth"]:
                props["bit_depth"] = int(props["bit_depth"])
            # FPS from r_frame_rate ("30/1" or "24000/1001")
            rfr = video.get("r_frame_rate", "")
            if "/" in rfr:
                num, den = rfr.split("/")
                try:
                    props["fps"] = round(int(num) / int(den), 3)
                except (ValueError, ZeroDivisionError):
                    pass

        # Audio stream presence
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        props["audio"] = 1 if audio else 0

        # Duration
        fmt = data.get("format", {})
        dur = fmt.get("duration") or (video or {}).get("duration")
        if dur:
            try:
                props["duration"] = round(float(dur), 3)
            except (ValueError, TypeError):
                pass

    except Exception:
        pass
    return props


def extract_properties(path: Path, media_type: str) -> dict:
    """Extract all intrinsic properties from a media file."""
    if media_type == "image":
        return _extract_image_properties(path)
    elif media_type == "video":
        return _extract_video_properties(path)
    return {}


# ══════════════════════════════════════════════════════════════════════════════
#  EXIF / METADATA EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def _extract_image_exif(path: Path) -> dict | None:
    """Extract embedded metadata from an image file."""
    from PIL import Image, ExifTags
    meta = {}
    try:
        img = Image.open(path)

        # PNG text chunks / info dict (parameters, prompt, workflow, etc.)
        for k, v in img.info.items():
            if k in ("exif",):  # skip raw EXIF bytes
                continue
            if isinstance(v, bytes):
                try:
                    v = v.decode("utf-8", errors="replace")
                except Exception:
                    continue
            if isinstance(v, (str, int, float, bool)):
                meta[k] = v

        # EXIF tags (JPEG, WebP, TIFF) — numeric IDs → human names
        exif = img.getexif()
        if exif:
            for tag_id, value in exif.items():
                name = ExifTags.TAGS.get(tag_id, str(tag_id))
                if isinstance(value, bytes):
                    try:
                        value = value.decode("utf-8", errors="replace")
                    except Exception:
                        continue
                if isinstance(value, (str, int, float, bool)):
                    meta[name] = value

        img.close()
    except Exception:
        pass

    if not meta:
        return None

    meta["_source"] = "pillow"
    return meta


def _extract_video_exif(path: Path) -> dict | None:
    """Extract embedded metadata from a video file."""
    meta = {}
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_entries", "format_tags", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            data = json.loads(r.stdout)
            tags = data.get("format", {}).get("tags", {})
            for k, v in tags.items():
                if isinstance(v, (str, int, float, bool)):
                    meta[k] = v
    except Exception:
        pass

    if not meta:
        return None

    meta["_source"] = "ffprobe"
    return meta


def extract_exif(path: Path, media_type: str) -> dict | None:
    """Extract all embedded metadata from a file."""
    if media_type == "image":
        return _extract_image_exif(path)
    elif media_type == "video":
        return _extract_video_exif(path)
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  HASH
# ══════════════════════════════════════════════════════════════════════════════

def compute_hash(path: Path) -> str:
    """Compute SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ══════════════════════════════════════════════════════════════════════════════
#  THUMBNAIL GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def _generate_image_thumb(source: Path, dest: Path, max_side: int) -> bool:
    """Resize image so longest side = max_side.  Skip if source is smaller."""
    try:
        from PIL import Image
        img = Image.open(source)
        longest = max(img.width, img.height)
        if longest <= max_side:
            img.close()
            return False  # original is smaller, skip
        ratio = max_side / longest
        new_w = int(img.width * ratio)
        new_h = int(img.height * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        img = img.convert("RGB")
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, "JPEG", quality=THUMB_QUALITY)
        img.close()
        return dest.exists() and dest.stat().st_size > 0
    except Exception:
        return False


def _generate_video_thumb(source: Path, dest: Path, max_side: int) -> bool:
    """Extract first frame from video and resize."""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(source),
             "-vframes", "1",
             "-vf", f"scale='if(gt(iw,ih),{max_side},-2)':'if(gt(iw,ih),-2,{max_side})'",
             "-q:v", "5", "-f", "image2", str(dest)],
            capture_output=True, timeout=15,
        )
        return dest.exists() and dest.stat().st_size > 0
    except Exception:
        return False


def generate_thumbs(media_id: str, source_path: Path, media_type: str) -> list[dict]:
    """Generate all applicable thumbnails.  Returns list of {size, file_path, file_size, width, height}."""
    results = []

    for size_name, max_side in THUMB_SIZES.items():
        rel = f"{_shard_dir(media_id)}/{media_id}.thumb.{size_name}.jpg"
        dest = _abs_path(rel)

        if media_type == "image":
            ok = _generate_image_thumb(source_path, dest, max_side)
        elif media_type == "video":
            ok = _generate_video_thumb(source_path, dest, max_side)
        else:
            continue

        if ok:
            # Read actual dimensions of generated thumb
            w, h = None, None
            try:
                from PIL import Image
                img = Image.open(dest)
                w, h = img.width, img.height
                img.close()
            except Exception:
                pass

            results.append({
                "size": size_name,
                "file_path": rel,
                "file_size": dest.stat().st_size,
                "width": w,
                "height": h,
            })

    return results


# ══════════════════════════════════════════════════════════════════════════════
#  CORE OPERATIONS
# ══════════════════════════════════════════════════════════════════════════════

def store(
    source_path: Path,
    origin: str,
    origin_id: str | None = None,
    origin_url: str | None = None,
    original_name: str | None = None,
) -> str:
    """Validate, analyse, and store a media file.

    The file at source_path is MOVED into the store (not copied).
    Returns the media ID (UUID).
    Raises ValueError if validation fails.
    """
    # 1. Validate
    media_type, mime = validate(source_path)
    ext = source_path.suffix.lower()
    if original_name is None:
        original_name = source_path.name

    # 2. Hash and dedup
    file_hash = compute_hash(source_path)
    existing = get_by_hash(file_hash)
    if existing:
        # File already in store — don't duplicate
        source_path.unlink()
        return existing["id"]

    # 3. Generate ID and move file
    media_id = uuid.uuid4().hex
    rel = _rel_path(media_id, ext)
    _ensure_dir(rel)
    dest = _abs_path(rel)
    source_path.rename(dest)

    # 4. Extract properties
    props = extract_properties(dest, media_type)

    # 5. Extract EXIF
    exif = extract_exif(dest, media_type)

    # 6. Generate thumbnails
    thumbs = generate_thumbs(media_id, dest, media_type)

    # 7. Pick the smallest thumb as the default thumb_path
    thumb_path = None
    thumb_size_bytes = 0
    if thumbs:
        smallest = thumbs[0]  # xs is first (100px)
        thumb_path = smallest["file_path"]
        thumb_size_bytes = smallest["file_size"]

    # 8. Insert into DB
    now = now_iso()
    conn = get_conn()
    conn.execute("""
        INSERT INTO media (
            id, file_path, thumb_path,
            type, ext, mime, original_name,
            width, height,
            duration, audio, fps, codec,
            color_space, bit_depth, has_alpha,
            file_size, thumb_size,
            hash, schema_version, exif,
            origin, origin_id, origin_url,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        media_id, rel, thumb_path,
        media_type, ext, mime, original_name,
        props.get("width"), props.get("height"),
        props.get("duration"), props.get("audio", 0), props.get("fps"), props.get("codec"),
        props.get("color_space"), props.get("bit_depth"), props.get("has_alpha", 0),
        dest.stat().st_size, thumb_size_bytes,
        file_hash, SCHEMA_VERSION, json.dumps(exif) if exif else None,
        origin, origin_id, origin_url,
        now,
    ))

    # Insert thumbs
    for t in thumbs:
        conn.execute("""
            INSERT INTO media_thumbs (media_id, size, file_path, file_size, width, height)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (media_id, t["size"], t["file_path"], t["file_size"], t["width"], t["height"]))

    conn.commit()
    return media_id


def store_from_bytes(
    data: bytes,
    ext: str,
    origin: str,
    origin_id: str | None = None,
    origin_url: str | None = None,
    original_name: str | None = None,
) -> str:
    """Store media from raw bytes.  Writes to a temp file, then calls store()."""
    import tempfile
    ext = ext if ext.startswith(".") else f".{ext}"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        return store(tmp_path, origin, origin_id, origin_url, original_name)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


# ══════════════════════════════════════════════════════════════════════════════
#  QUERIES
# ══════════════════════════════════════════════════════════════════════════════

def get(media_id: str) -> dict | None:
    """Get media record by ID."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
    return dict(row) if row else None


def get_by_hash(file_hash: str) -> dict | None:
    """Find media by SHA-256 hash (for dedup)."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM media WHERE hash = ?", (file_hash,)).fetchone()
    return dict(row) if row else None


def get_by_origin(origin: str, origin_id: str) -> dict | None:
    """Find media by origin + origin_id."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM media WHERE origin = ? AND origin_id = ?",
        (origin, origin_id),
    ).fetchone()
    return dict(row) if row else None


def get_thumbs(media_id: str) -> list[dict]:
    """Get all thumbnails for a media."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM media_thumbs WHERE media_id = ? ORDER BY file_size ASC",
        (media_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_thumb(media_id: str, size: str = "sm") -> dict | None:
    """Get a specific thumbnail.  Falls back to nearest available size."""
    conn = get_conn()
    # Try exact size
    row = conn.execute(
        "SELECT * FROM media_thumbs WHERE media_id = ? AND size = ?",
        (media_id, size),
    ).fetchone()
    if row:
        return dict(row)
    # Fallback: smallest available
    row = conn.execute(
        "SELECT * FROM media_thumbs WHERE media_id = ? ORDER BY file_size ASC LIMIT 1",
        (media_id,),
    ).fetchone()
    return dict(row) if row else None


def exists(media_id: str) -> bool:
    """Check if a media record exists in DB."""
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM media WHERE id = ?", (media_id,)).fetchone()
    return row is not None


def hash_exists(file_hash: str) -> bool:
    """Check if a file with this hash is already in the store."""
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM media WHERE hash = ?", (file_hash,)).fetchone()
    return row is not None


# ══════════════════════════════════════════════════════════════════════════════
#  SERVE
# ══════════════════════════════════════════════════════════════════════════════

def serve_path(media_id: str) -> Path | None:
    """Get absolute path of the original file for serving."""
    m = get(media_id)
    if not m:
        return None
    p = _abs_path(m["file_path"])
    return p if p.exists() else None


def serve_thumb_path(media_id: str, size: str = "sm") -> Path | None:
    """Get absolute path of a thumbnail for serving.  Falls back to original."""
    t = get_thumb(media_id, size)
    if t:
        p = _abs_path(t["file_path"])
        if p.exists():
            return p
    # Fallback to original
    return serve_path(media_id)


# ══════════════════════════════════════════════════════════════════════════════
#  DELETE
# ══════════════════════════════════════════════════════════════════════════════

def delete(media_id: str) -> bool:
    """Delete media: remove files from disk and record from DB."""
    m = get(media_id)
    if not m:
        return False

    # Delete original file
    p = _abs_path(m["file_path"])
    if p.exists():
        p.unlink()

    # Delete thumbs
    thumbs = get_thumbs(media_id)
    for t in thumbs:
        tp = _abs_path(t["file_path"])
        if tp.exists():
            tp.unlink()

    # Delete from DB (CASCADE deletes media_thumbs)
    conn = get_conn()
    conn.execute("DELETE FROM media WHERE id = ?", (media_id,))
    conn.commit()

    # Try to remove empty shard dirs
    shard = _abs_path(_shard_dir(media_id))
    try:
        shard.rmdir()  # only succeeds if empty
        shard.parent.rmdir()
    except OSError:
        pass

    return True


# ══════════════════════════════════════════════════════════════════════════════
#  STATS
# ══════════════════════════════════════════════════════════════════════════════

def total_size() -> int:
    """Total bytes of all media files (originals only, no thumbs)."""
    conn = get_conn()
    row = conn.execute("SELECT COALESCE(SUM(file_size), 0) FROM media").fetchone()
    return row[0]


def total_size_with_thumbs() -> int:
    """Total bytes including thumbnails."""
    conn = get_conn()
    media = conn.execute("SELECT COALESCE(SUM(file_size), 0) FROM media").fetchone()[0]
    thumbs = conn.execute("SELECT COALESCE(SUM(file_size), 0) FROM media_thumbs").fetchone()[0]
    return media + thumbs


def count() -> int:
    """Total number of media files."""
    conn = get_conn()
    row = conn.execute("SELECT COUNT(*) FROM media").fetchone()
    return row[0]


def count_by_type() -> dict:
    """Count media grouped by type (image/video)."""
    conn = get_conn()
    rows = conn.execute("SELECT type, COUNT(*) FROM media GROUP BY type").fetchall()
    return {r[0]: r[1] for r in rows}


def stats() -> dict:
    """Comprehensive statistics for the media store."""
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*), COALESCE(SUM(file_size), 0) FROM media").fetchone()
    thumb_stats = conn.execute(
        "SELECT size, COUNT(*), COALESCE(SUM(file_size), 0) FROM media_thumbs GROUP BY size ORDER BY size"
    ).fetchall()
    by_type = conn.execute(
        "SELECT type, COUNT(*), COALESCE(SUM(file_size), 0) FROM media GROUP BY type ORDER BY COUNT(*) DESC"
    ).fetchall()
    by_origin = conn.execute(
        "SELECT origin, COUNT(*), COALESCE(SUM(file_size), 0) FROM media GROUP BY origin ORDER BY COUNT(*) DESC"
    ).fetchall()
    by_format = conn.execute(
        "SELECT ext, COUNT(*), COALESCE(SUM(file_size), 0) FROM media GROUP BY ext ORDER BY COUNT(*) DESC"
    ).fetchall()
    by_schema = conn.execute(
        "SELECT schema_version, COUNT(*) FROM media GROUP BY schema_version ORDER BY schema_version"
    ).fetchall()
    media_with_thumbs = conn.execute(
        "SELECT COUNT(DISTINCT media_id) FROM media_thumbs"
    ).fetchone()[0]
    return {
        "total_count": total[0], "total_bytes": total[1],
        "total_thumb_bytes": sum(r[2] for r in thumb_stats),
        "by_type": {r[0]: {"count": r[1], "bytes": r[2]} for r in by_type},
        "by_origin": {r[0]: {"count": r[1], "bytes": r[2]} for r in by_origin},
        "by_format": {r[0]: {"count": r[1], "bytes": r[2]} for r in by_format},
        "by_schema": {r[0]: r[1] for r in by_schema},
        "thumb_coverage": media_with_thumbs,
        "thumbs": {r[0]: {"count": r[1], "bytes": r[2]} for r in thumb_stats},
    }


# ── Queries: search and filter ────────────────────────────────────────────────

def get_by_prefix(prefix: str) -> dict | None:
    """Find media by ID prefix (min 8 chars)."""
    conn = get_conn()
    if len(prefix) >= 32:
        row = conn.execute("SELECT * FROM media WHERE id = ?", (prefix,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM media WHERE id LIKE ?", (prefix + "%",)).fetchone()
    return dict(row) if row else None


def find(
    type: str | None = None,
    origin: str | None = None,
    ext: str | None = None,
    search: str | None = None,
    sort: str = "created_at",
    desc: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Search media with filters. Returns (rows, total_count)."""
    conn = get_conn()
    clauses, params = [], []
    if type:
        clauses.append("type = ?"); params.append(type)
    if origin:
        clauses.append("origin = ?"); params.append(origin)
    if ext:
        e = ext if ext.startswith(".") else f".{ext}"
        clauses.append("ext = ?"); params.append(e)
    if search:
        clauses.append("(original_name LIKE ? OR origin_id LIKE ? OR id LIKE ?)")
        pat = f"%{search}%"; params.extend([pat, pat, pat])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order = "DESC" if desc else "ASC"
    rows = conn.execute(
        f"SELECT * FROM media {where} ORDER BY {sort} {order} LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    total = conn.execute(f"SELECT COUNT(*) FROM media {where}", params).fetchone()[0]
    return [dict(r) for r in rows], total


def find_by_name(name: str) -> list[dict]:
    """Find media by original_name substring."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM media WHERE original_name LIKE ?", (f"%{name}%",)).fetchall()
    return [dict(r) for r in rows]


# ── Diagnostics: dedup, orphans, schema ───────────────────────────────────────

def find_duplicates() -> list[dict]:
    """Find media with duplicate hashes."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT hash, COUNT(*) as cnt, GROUP_CONCAT(id, ',') as ids
        FROM media WHERE hash IS NOT NULL
        GROUP BY hash HAVING cnt > 1 ORDER BY cnt DESC
    """).fetchall()
    return [dict(r) for r in rows]


def all_file_paths() -> tuple[set, set]:
    """Return (media_paths, thumb_paths) — all relative paths tracked in DB."""
    conn = get_conn()
    media_paths = {r[0] for r in conn.execute("SELECT file_path FROM media").fetchall()}
    thumb_paths = {r[0] for r in conn.execute("SELECT file_path FROM media_thumbs").fetchall()}
    return media_paths, thumb_paths


def outdated_schema_count(current_version: int) -> int:
    """Count media with schema_version below current."""
    conn = get_conn()
    return conn.execute(
        "SELECT COUNT(*) FROM media WHERE schema_version < ?", (current_version,)
    ).fetchone()[0]


def find_for_reindex(force: bool = False) -> list[dict]:
    """Get media records that need reindexing."""
    conn = get_conn()
    if force:
        return [dict(r) for r in conn.execute("SELECT id, file_path, type, ext FROM media").fetchall()]
    return [dict(r) for r in conn.execute(
        "SELECT id, file_path, type, ext FROM media WHERE schema_version < ?", (SCHEMA_VERSION,)
    ).fetchall()]


# ── Mutations: update, delete thumbs, insert thumbs ──────────────────────────

def update_fields(media_id: str, **kwargs):
    """Update specific fields on a media record."""
    if not kwargs:
        return
    conn = get_conn()
    set_clause = ", ".join(f"{k} = ?" for k in kwargs)
    conn.execute(f"UPDATE media SET {set_clause} WHERE id = ?", list(kwargs.values()) + [media_id])
    conn.commit()


def delete_thumbs(media_id: str):
    """Delete all thumbnails for a media (DB + files)."""
    conn = get_conn()
    rows = conn.execute("SELECT file_path FROM media_thumbs WHERE media_id = ?", (media_id,)).fetchall()
    for r in rows:
        p = _abs_path(r["file_path"])
        if p.exists():
            p.unlink()
    conn.execute("DELETE FROM media_thumbs WHERE media_id = ?", (media_id,))
    conn.commit()


def insert_thumbs(media_id: str, thumbs: list[dict]):
    """Insert thumbnail records and update media.thumb_path."""
    conn = get_conn()
    for t in thumbs:
        conn.execute("""
            INSERT INTO media_thumbs (media_id, size, file_path, file_size, width, height)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (media_id, t["size"], t["file_path"], t["file_size"], t["width"], t["height"]))
    if thumbs:
        conn.execute("UPDATE media SET thumb_path = ?, thumb_size = ? WHERE id = ?",
                     (thumbs[0]["file_path"], thumbs[0]["file_size"], media_id))
    conn.commit()
