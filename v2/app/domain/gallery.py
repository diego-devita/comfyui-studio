"""Gallery — orchestrates CivitAI image downloads into the media store.

Connects civitai_client → download_scheduler → media_store → join tables.
This is the module that gives meaning to downloaded media: "this image
is a card image of model X" or "this is a community image of version Y".

Two types of gallery downloads:
  1. Card images — author's showcase images for a model (belong to parent)
  2. Community images — user-uploaded images for a specific version

The gallery_jobs table tracks operations in progress. When a job completes
successfully, its row is DELETED — no "done" status. If it's interrupted
(crash/restart), it stays with status='interrupted' and can be resumed.

Callback delivery:
  gallery.py registers a "gallery_deliver" callback with download_scheduler.
  When a download completes, the callback:
    1. Stores the file in media_store → gets media_id
    2. Creates the relation in model_media or version_media
    3. Fetches generation data from CivitAI (community images only)
    4. Stores CivitAI metadata in civitai_image_meta
    5. Updates the gallery_job progress counter
    6. If job is complete → deletes the gallery_job row (auto-cleanup)
  All steps in one transaction — if any fails, everything rolls back.
"""

import json
import sqlite3

from v2.app.db import get_conn, register_schema
from v2.app.settings import now_iso
from v2.app.stores import media as media_store
from v2.app.domain import download as download_scheduler
from v2.app.clients.civitai import (
    CivitaiClient,
    extract_cdn_id_from_url,
    build_cdn_url,
)


# ── Schema ───────────────────────────────────────────────────────────────────

def _init_schema(conn: sqlite3.Connection):
    """Create gallery tables. Called by db.init_db()."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS gallery_jobs (
            id          TEXT PRIMARY KEY,
            model_id    TEXT NOT NULL,           -- our model UUID (parent)
            version_id  TEXT,                    -- our version UUID (null = card images only)
            image_type  TEXT NOT NULL
                        CHECK (image_type IN ('card', 'community')),
            filters     TEXT DEFAULT '{}',       -- JSON, search filters used
            total       INTEGER DEFAULT 0,       -- images to download
            completed   INTEGER DEFAULT 0,       -- successfully stored + linked
            failed      INTEGER DEFAULT 0,       -- failed deliveries
            status      TEXT NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running', 'stopping', 'interrupted', 'error')),
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS civitai_image_meta (
            media_id        TEXT PRIMARY KEY,
            prompt          TEXT,
            negative_prompt TEXT,
            steps           INTEGER,
            cfg_scale       REAL,
            sampler         TEXT,
            seed            INTEGER,
            clip_skip       INTEGER,
            resources       TEXT,                -- JSON array
            tools           TEXT,                -- JSON array
            techniques      TEXT,                -- JSON array
            post_id         INTEGER,
            post_title      TEXT,
            username        TEXT,
            civitai_url     TEXT,
            reactions       INTEGER DEFAULT 0,
            comments        INTEGER DEFAULT 0,
            collected       INTEGER DEFAULT 0,
            raw_meta        TEXT,                -- full CivitAI meta JSON
            FOREIGN KEY (media_id) REFERENCES media(id) ON DELETE CASCADE
        );
    """)


register_schema("gallery", _init_schema)


# ── Callback delivery ────────────────────────────────────────────────────────
#
# Registered with download_scheduler. Called when a gallery download completes.
# Receives the downloaded file + args dict with all context.
# Does everything in one transaction.

def _deliver_gallery_media(file_path, args):
    """Callback: store file, create relation, fetch meta, update job.

    Called by download_scheduler when a gallery image download completes.
    Everything happens in one transaction for consistency.

    Args:
        file_path: Path to the downloaded file (in downloads/ temp dir).
        args: Dict with keys:
            origin, origin_id, origin_url, original_name — for media_store
            model_id — our model UUID for model_media relation
            version_id — our version UUID for version_media (null for card)
            image_type — 'card' or 'community'
            civitai_image_id — numeric CivitAI image ID (for generation data)
            fetch_generation_data — bool, whether to call getGenerationData
            civitai_api_key — needed for generation data fetch
            gallery_job_id — to update progress
            post_id, post_title, username — social context from listing
            stats — {reactions, comments, collected} from listing
    """
    conn = get_conn()

    try:
        # 1. Store file in media store → get media_id
        media_id = media_store.store(
            source_path=file_path,
            origin=args.get("origin", "civitai"),
            origin_id=args.get("origin_id"),
            origin_url=args.get("origin_url"),
            original_name=args.get("original_name"),
        )

        # 2. Create relation in join table
        image_type = args.get("image_type", "community")
        model_id = args.get("model_id")
        version_id = args.get("version_id")

        if image_type == "card" and model_id:
            conn.execute("""
                INSERT OR IGNORE INTO model_media (media_id, model_id, sort_order)
                VALUES (?, ?, 0)
            """, (media_id, model_id))

        elif version_id:
            conn.execute("""
                INSERT OR IGNORE INTO version_media (media_id, version_id, source, sort_order)
                VALUES (?, ?, 'community', 0)
            """, (media_id, version_id))

        # 3. Fetch and store CivitAI generation metadata (community only)
        civitai_image_id = args.get("civitai_image_id")
        api_key = args.get("civitai_api_key", "")

        meta_data = {}
        if args.get("fetch_generation_data") and civitai_image_id and api_key:
            try:
                client = CivitaiClient(api_key=api_key)
                gen = client.get_image_generation_data(int(civitai_image_id))
                if gen:
                    meta_data = gen
            except Exception:
                pass  # Non-fatal — we have the image, meta is a bonus

        # Build civitai_image_meta record
        meta = meta_data.get("meta", {}) or {}
        resources = meta_data.get("resources", [])
        tools = meta_data.get("tools", [])
        techniques = meta_data.get("techniques", [])
        stats = args.get("stats", {})

        # Always insert meta row if we have any data
        # (even card images get post_id/username from listing)
        has_any_meta = (
            meta or resources or tools or techniques
            or args.get("post_id") or args.get("username")
        )

        if has_any_meta:
            conn.execute("""
                INSERT OR IGNORE INTO civitai_image_meta (
                    media_id, prompt, negative_prompt, steps, cfg_scale,
                    sampler, seed, clip_skip,
                    resources, tools, techniques,
                    post_id, post_title, username, civitai_url,
                    reactions, comments, collected,
                    raw_meta
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                media_id,
                meta.get("prompt"),
                meta.get("negativePrompt"),
                meta.get("steps"),
                meta.get("cfgScale"),
                meta.get("sampler"),
                meta.get("seed"),
                meta.get("clipSkip"),
                json.dumps(resources) if resources else None,
                json.dumps(tools) if tools else None,
                json.dumps(techniques) if techniques else None,
                args.get("post_id"),
                args.get("post_title"),
                args.get("username"),
                args.get("civitai_url"),
                stats.get("reactions", 0),
                stats.get("comments", 0),
                stats.get("collected", 0),
                json.dumps(meta_data) if meta_data else None,
            ))

        # 4. Update gallery job progress
        job_id = args.get("gallery_job_id")
        if job_id:
            conn.execute("""
                UPDATE gallery_jobs SET completed = completed + 1 WHERE id = ?
            """, (job_id,))

            # Check if job is done → auto-cleanup
            row = conn.execute(
                "SELECT total, completed, failed FROM gallery_jobs WHERE id = ?",
                (job_id,)
            ).fetchone()
            if row and (row["completed"] + row["failed"]) >= row["total"]:
                conn.execute("DELETE FROM gallery_jobs WHERE id = ?", (job_id,))

        conn.commit()

    except Exception as e:
        conn.rollback()
        # Update job failure count
        job_id = args.get("gallery_job_id")
        if job_id:
            conn.execute("""
                UPDATE gallery_jobs SET failed = failed + 1 WHERE id = ?
            """, (job_id,))

            # Check if job is done (all failed) → keep for inspection, set error
            row = conn.execute(
                "SELECT total, completed, failed FROM gallery_jobs WHERE id = ?",
                (job_id,)
            ).fetchone()
            if row and (row["completed"] + row["failed"]) >= row["total"]:
                conn.execute(
                    "UPDATE gallery_jobs SET status = 'error' WHERE id = ?",
                    (job_id,),
                )
            conn.commit()
        raise


# Register callback with download scheduler
download_scheduler.register_callback("gallery_deliver", _deliver_gallery_media)


# ── Public API ───────────────────────────────────────────────────────────────

def download_card_images(
    model_id: str,
    civitai_model_id: int,
    api_key: str,
) -> str:
    """Start downloading card images for a model.

    Fetches the model from CivitAI, collects all card images from all
    versions, and enqueues them for download. Each downloaded image gets
    stored in the media store and linked to the model via model_media.

    Args:
        model_id: Our internal model UUID.
        civitai_model_id: CivitAI parent model ID.
        api_key: CivitAI API key.

    Returns:
        Gallery job ID.
    """
    import uuid

    client = CivitaiClient(api_key=api_key)
    model_data = client.get_model(civitai_model_id)

    # Collect all card images across all versions
    images = []
    seen_cdn_ids = set()
    for version in model_data.get("modelVersions", []):
        for img in client.extract_card_images(version):
            cdn_id = img.get("cdn_id", "")
            if cdn_id and cdn_id not in seen_cdn_ids:
                seen_cdn_ids.add(cdn_id)
                images.append(img)

    if not images:
        return ""

    # Create gallery job
    job_id = uuid.uuid4().hex
    conn = get_conn()
    conn.execute("""
        INSERT INTO gallery_jobs (id, model_id, version_id, image_type, total, status, created_at)
        VALUES (?, ?, NULL, 'card', ?, 'running', ?)
    """, (job_id, model_id, len(images), now_iso()))
    conn.commit()

    # Enqueue downloads
    for img in images:
        cdn_id = img["cdn_id"]
        media_type = img.get("type", "image")
        url = build_cdn_url(cdn_id, media_type)
        ext = ".mp4" if media_type == "video" else ".jpeg"

        download_scheduler.enqueue(
            url=url,
            callback="gallery_deliver",
            callback_args={
                "origin": "civitai",
                "origin_id": cdn_id,
                "origin_url": url,
                "original_name": f"{cdn_id}{ext}",
                "model_id": model_id,
                "version_id": None,
                "image_type": "card",
                "civitai_image_id": None,  # card images have no numeric ID
                "fetch_generation_data": False,
                "civitai_api_key": api_key,
                "gallery_job_id": job_id,
                "post_id": None,
                "post_title": None,
                "username": None,
                "stats": {},
            },
        )

    return job_id


def download_community_images(
    model_id: str,
    version_id: str,
    civitai_version_id: int,
    api_key: str,
    sort: str = "Most Reactions",
    period: str = "AllTime",
    types: list[str] | None = None,
    with_meta: bool = False,
    from_platform: bool = False,
    max_images: int = 200,
    fetch_generation_data: bool = True,
) -> str:
    """Start downloading community images for a model version.

    Fetches community images from CivitAI via tRPC, enqueues them for
    download. Each downloaded image gets stored, linked to the version
    via version_media, and enriched with CivitAI generation metadata.

    Args:
        model_id: Our internal model UUID (parent).
        version_id: Our internal version UUID.
        civitai_version_id: CivitAI version ID for the API query.
        api_key: CivitAI API key.
        sort: Sort order for the image search.
        period: Time period filter.
        types: Media type filter (['image'], ['video'], or None).
        with_meta: Only images with generation metadata.
        from_platform: Only images made on CivitAI.
        max_images: Maximum number of images to download.
        fetch_generation_data: Whether to fetch per-image generation data.

    Returns:
        Gallery job ID.
    """
    import uuid

    client = CivitaiClient(api_key=api_key)

    # Collect images from tRPC (paginated)
    images = []
    for item in client.iter_images_trpc(
        version_id=civitai_version_id,
        sort=sort,
        period=period,
        types=types,
        with_meta=with_meta,
        from_platform=from_platform,
        limit=min(max_images, 200),
    ):
        normalized = client.normalize_trpc_image(item)
        images.append(normalized)
        if len(images) >= max_images:
            break

    if not images:
        return ""

    # Create gallery job
    job_id = uuid.uuid4().hex
    filters = {
        "sort": sort, "period": period, "types": types,
        "with_meta": with_meta, "from_platform": from_platform,
        "max_images": max_images,
    }
    conn = get_conn()
    conn.execute("""
        INSERT INTO gallery_jobs (id, model_id, version_id, image_type, filters, total, status, created_at)
        VALUES (?, ?, ?, 'community', ?, ?, 'running', ?)
    """, (job_id, model_id, version_id, json.dumps(filters), len(images), now_iso()))
    conn.commit()

    # Enqueue downloads
    for img in images:
        cdn_id = img.get("cdn_id", "")
        media_type = img.get("type", "image")
        url = img.get("full_url") or build_cdn_url(cdn_id, media_type)
        ext = ".mp4" if media_type == "video" else ".jpeg"
        image_id = img.get("id")
        stats_data = img.get("stats", {})

        download_scheduler.enqueue(
            url=url,
            callback="gallery_deliver",
            callback_args={
                "origin": "civitai",
                "origin_id": str(image_id) if image_id else cdn_id,
                "origin_url": url,
                "original_name": f"{image_id or cdn_id}{ext}",
                "model_id": model_id,
                "version_id": version_id,
                "image_type": "community",
                "civitai_image_id": image_id,
                "fetch_generation_data": fetch_generation_data,
                "civitai_api_key": api_key,
                "gallery_job_id": job_id,
                "post_id": img.get("postId"),
                "post_title": img.get("postTitle"),
                "username": img.get("username"),
                "stats": {
                    "reactions": (stats_data.get("heartCount", 0) or 0)
                                + (stats_data.get("likeCount", 0) or 0),
                    "comments": stats_data.get("commentCount", 0) or 0,
                    "collected": stats_data.get("collectedCount", 0) or 0,
                },
                "civitai_url": f"https://civitai.com/images/{image_id}" if image_id else None,
            },
        )

    return job_id


def stop_job(job_id: str):
    """Signal a running gallery job to stop.

    Sets status to 'stopping'. Downloads already enqueued will complete
    but no new images are added. The job row remains until all pending
    downloads finish, then auto-cleans.

    Args:
        job_id: Gallery job ID.
    """
    conn = get_conn()
    conn.execute(
        "UPDATE gallery_jobs SET status = 'stopping' WHERE id = ? AND status = 'running'",
        (job_id,),
    )
    conn.commit()


def get_job_status(job_id: str) -> dict | None:
    """Get current status of a gallery job.

    Returns None if job completed successfully (row was deleted).

    Args:
        job_id: Gallery job ID.

    Returns:
        Job dict, or None if completed/not found.
    """
    conn = get_conn()
    row = conn.execute("SELECT * FROM gallery_jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_active_jobs() -> list[dict]:
    """List all active gallery jobs (running, stopping, interrupted).

    Returns:
        List of job dicts.
    """
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM gallery_jobs
        WHERE status IN ('running', 'stopping', 'interrupted')
        ORDER BY created_at DESC
    """).fetchall()
    return [dict(r) for r in rows]


def recover_interrupted():
    """Reset interrupted jobs for resume. Called at boot.

    Changes 'running' → 'interrupted'. The caller can then decide
    whether to resume or abandon each job.
    """
    conn = get_conn()
    count = conn.execute(
        "UPDATE gallery_jobs SET status = 'interrupted' WHERE status = 'running'"
    ).rowcount
    conn.commit()
    if count:
        print(f"[gallery] Recovered {count} interrupted job(s)", flush=True)
    return count


# ── Query functions ──────────────────────────────────────────────────────────

def get_model_gallery(model_id: str) -> dict:
    """Get all gallery data for a model.

    Returns card images (from model_media) and community image counts
    per version (from version_media).

    Args:
        model_id: Our internal model UUID.

    Returns:
        Dict with 'card_images' list and 'versions' dict of counts.
    """
    conn = get_conn()

    # Card images
    card_rows = conn.execute("""
        SELECT m.* FROM media m
        JOIN model_media mm ON m.id = mm.media_id
        WHERE mm.model_id = ?
        ORDER BY mm.sort_order ASC
    """, (model_id,)).fetchall()

    # Community counts per version
    version_rows = conn.execute("""
        SELECT vm.version_id, COUNT(*) as count,
               COALESCE(SUM(m.file_size), 0) as total_bytes
        FROM version_media vm
        JOIN media m ON m.id = vm.media_id
        JOIN model_versions mv ON mv.id = vm.version_id
        WHERE mv.model_id = ?
        GROUP BY vm.version_id
    """, (model_id,)).fetchall()

    return {
        "card_images": [dict(r) for r in card_rows],
        "card_count": len(card_rows),
        "card_bytes": sum(r["file_size"] for r in card_rows),
        "versions": {
            r["version_id"]: {"count": r["count"], "bytes": r["total_bytes"]}
            for r in version_rows
        },
        "community_count": sum(r["count"] for r in version_rows),
        "community_bytes": sum(r["total_bytes"] for r in version_rows),
    }


def get_version_gallery(version_id: str) -> list[dict]:
    """Get community images for a specific version.

    Args:
        version_id: Our internal version UUID.

    Returns:
        List of media dicts.
    """
    conn = get_conn()
    rows = conn.execute("""
        SELECT m.* FROM media m
        JOIN version_media vm ON m.id = vm.media_id
        WHERE vm.version_id = ?
        ORDER BY vm.sort_order ASC
    """, (version_id,)).fetchall()
    return [dict(r) for r in rows]


def get_image_meta(media_id: str) -> dict | None:
    """Get CivitAI generation metadata for a media item.

    Args:
        media_id: Media UUID.

    Returns:
        Meta dict, or None if no CivitAI meta exists.
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM civitai_image_meta WHERE media_id = ?", (media_id,)
    ).fetchone()
    return dict(row) if row else None


def set_model_preview(model_id: str, media_id: str):
    """Set the preview image for a model.

    Args:
        model_id: Our internal model UUID.
        media_id: Media UUID to use as preview.
    """
    conn = get_conn()
    conn.execute(
        "UPDATE models SET preview_id = ? WHERE id = ?",
        (media_id, model_id),
    )
    conn.commit()


def get_gallery_stats() -> dict:
    """Get aggregate gallery statistics.

    Returns:
        Dict with total counts and bytes for card + community images.
    """
    conn = get_conn()

    card = conn.execute("""
        SELECT COUNT(*) as count, COALESCE(SUM(m.file_size), 0) as bytes
        FROM media m JOIN model_media mm ON m.id = mm.media_id
    """).fetchone()

    community = conn.execute("""
        SELECT COUNT(*) as count, COALESCE(SUM(m.file_size), 0) as bytes
        FROM media m JOIN version_media vm ON m.id = vm.media_id
    """).fetchone()

    return {
        "card_count": card["count"],
        "card_bytes": card["bytes"],
        "community_count": community["count"],
        "community_bytes": community["bytes"],
        "total_count": card["count"] + community["count"],
        "total_bytes": card["bytes"] + community["bytes"],
    }
