"""Gallery — orchestrates CivitAI image downloads into the media store.

Connects: civitai_client → download_scheduler → media_store → join tables.

Two types of gallery downloads:
  Card images   — author's showcase images, belong to the parent model
  Community     — user-uploaded images, belong to a specific version

Tracking:
  gallery_jobs tracks operations in progress. Completed jobs auto-delete.
  Interrupted jobs (from crash) stay for resume or cleanup.

Tables owned by this module:
  gallery_jobs       — download operations in progress
  civitai_image_meta — CivitAI generation metadata per media item
"""

import json
import sqlite3
import uuid as _uuid

from v2.app.db import get_conn, register_schema
from v2.app.settings import now_iso


# ══════════════════════════════════════════════════════════════════════════════
#  SCHEMA
# ══════════════════════════════════════════════════════════════════════════════

def _init_schema(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS gallery_jobs (
            id          TEXT PRIMARY KEY,
            model_id    TEXT NOT NULL,
            version_id  TEXT,
            image_type  TEXT NOT NULL CHECK (image_type IN ('card', 'community')),
            filters     TEXT DEFAULT '{}',
            total       INTEGER DEFAULT 0,
            completed   INTEGER DEFAULT 0,
            failed      INTEGER DEFAULT 0,
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
            resources       TEXT,
            tools           TEXT,
            techniques      TEXT,
            post_id         INTEGER,
            post_title      TEXT,
            username        TEXT,
            civitai_url     TEXT,
            reactions       INTEGER DEFAULT 0,
            comments        INTEGER DEFAULT 0,
            collected       INTEGER DEFAULT 0,
            raw_meta        TEXT,
            FOREIGN KEY (media_id) REFERENCES media(id) ON DELETE CASCADE
        );
    """)

register_schema("gallery", _init_schema)


# ══════════════════════════════════════════════════════════════════════════════
#  INTERNAL HELPERS — small pieces used by the callback and download functions
# ══════════════════════════════════════════════════════════════════════════════

def _store_and_link(file_path, args):
    """Store a downloaded file in media_store and create the join table relation.

    This is step 1+2 of the delivery callback:
      1. media_store.store() → file enters the media store, returns media_id
      2. INSERT into model_media (card) or version_media (community)

    Returns the media_id.
    """
    from v2.app.stores import media as media_store

    media_id = media_store.store(
        source_path=file_path,
        origin=args.get("origin", "civitai"),
        origin_id=args.get("origin_id"),
        origin_url=args.get("origin_url"),
        original_name=args.get("original_name"),
    )

    conn = get_conn()
    if args.get("image_type") == "card" and args.get("model_id"):
        conn.execute(
            "INSERT OR IGNORE INTO model_media (media_id, model_id, sort_order) VALUES (?, ?, 0)",
            (media_id, args["model_id"]),
        )
    elif args.get("version_id"):
        conn.execute(
            "INSERT OR IGNORE INTO version_media (media_id, version_id, source, sort_order) VALUES (?, ?, 'community', 0)",
            (media_id, args["version_id"]),
        )

    return media_id


def _store_civitai_meta(media_id, args, generation_data=None):
    """Store CivitAI metadata for a media item.

    Combines data from the listing (username, postId, stats) with
    generation data fetched per-image (prompt, resources, tools).

    Only inserts if there's any data to store. Skips silently if empty.
    """
    meta = (generation_data or {}).get("meta", {}) or {}
    resources = (generation_data or {}).get("resources", [])
    tools = (generation_data or {}).get("tools", [])
    techniques = (generation_data or {}).get("techniques", [])
    stats = args.get("stats", {})

    has_data = meta or resources or tools or techniques or args.get("post_id") or args.get("username")
    if not has_data:
        return

    conn = get_conn()
    conn.execute("""
        INSERT OR IGNORE INTO civitai_image_meta (
            media_id, prompt, negative_prompt, steps, cfg_scale,
            sampler, seed, clip_skip, resources, tools, techniques,
            post_id, post_title, username, civitai_url,
            reactions, comments, collected, raw_meta
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        media_id,
        meta.get("prompt"), meta.get("negativePrompt"),
        meta.get("steps"), meta.get("cfgScale"),
        meta.get("sampler"), meta.get("seed"), meta.get("clipSkip"),
        json.dumps(resources) if resources else None,
        json.dumps(tools) if tools else None,
        json.dumps(techniques) if techniques else None,
        args.get("post_id"), args.get("post_title"), args.get("username"),
        args.get("civitai_url"),
        stats.get("reactions", 0), stats.get("comments", 0), stats.get("collected", 0),
        json.dumps(generation_data) if generation_data else None,
    ))


def _update_job_progress(job_id, success=True):
    """Increment completed or failed counter on a gallery job.

    If the job reaches total (completed + failed >= total), auto-deletes
    on success or sets status='error' if all remaining failed.
    """
    conn = get_conn()
    field = "completed" if success else "failed"
    conn.execute(f"UPDATE gallery_jobs SET {field} = {field} + 1 WHERE id = ?", (job_id,))

    row = conn.execute(
        "SELECT total, completed, failed FROM gallery_jobs WHERE id = ?", (job_id,)
    ).fetchone()

    if row and (row["completed"] + row["failed"]) >= row["total"]:
        if row["failed"] > 0 and row["completed"] == 0:
            conn.execute("UPDATE gallery_jobs SET status = 'error' WHERE id = ?", (job_id,))
        else:
            # Success (possibly partial) — auto-cleanup
            conn.execute("DELETE FROM gallery_jobs WHERE id = ?", (job_id,))

    conn.commit()


def _fetch_generation_data(civitai_image_id, api_key):
    """Fetch generation data for a single image from CivitAI.

    Returns the data dict, or empty dict on failure. Non-fatal — the image
    is already stored, metadata is a bonus.
    """
    if not civitai_image_id or not api_key:
        return {}
    try:
        from v2.app.clients.civitai import CivitaiClient
        return CivitaiClient(api_key=api_key).get_image_generation_data(int(civitai_image_id))
    except Exception:
        return {}


def _build_callback_args(
    model_id, version_id, image_type,
    origin_id, origin_url, original_name,
    civitai_image_id, api_key, job_id,
    post_id=None, post_title=None, username=None, stats=None,
    fetch_generation_data=False,
):
    """Build the callback_args dict for download_scheduler.enqueue().

    Centralises the construction so download_card_images, download_community_images,
    and resume_job all produce identical args.
    """
    return {
        "origin": "civitai",
        "origin_id": origin_id,
        "origin_url": origin_url,
        "original_name": original_name,
        "model_id": model_id,
        "version_id": version_id,
        "image_type": image_type,
        "civitai_image_id": civitai_image_id,
        "fetch_generation_data": fetch_generation_data,
        "civitai_api_key": api_key,
        "gallery_job_id": job_id,
        "post_id": post_id,
        "post_title": post_title,
        "username": username,
        "stats": stats or {},
    }


def _enqueue_image(url, callback_args):
    """Enqueue a single image download via the download scheduler."""
    from v2.app.domain import download as scheduler
    scheduler.enqueue(url=url, callback="gallery_deliver", callback_args=callback_args)


def _is_already_downloaded(origin_id):
    """Check if a media with this origin_id already exists (dedup)."""
    from v2.app.stores import media as media_store
    return media_store.get_by_origin("civitai", origin_id) is not None


# ══════════════════════════════════════════════════════════════════════════════
#  CALLBACK — called by download_scheduler when a gallery download completes
# ══════════════════════════════════════════════════════════════════════════════

def _deliver_gallery_media(file_path, args):
    """Delivery callback: store file, create relation, fetch meta, update job.

    Called by download_scheduler when a gallery image download completes.
    All steps run in one transaction. If any step fails, the whole thing
    rolls back and the job's failed counter increments.

    Steps:
      1. Store file in media_store → get media_id
      2. Create relation in model_media or version_media
      3. Fetch generation data from CivitAI (community only, non-fatal)
      4. Store CivitAI metadata in civitai_image_meta
      5. Update gallery_job progress (auto-cleanup if done)
    """
    conn = get_conn()
    job_id = args.get("gallery_job_id")

    try:
        # Steps 1 + 2: store file and create relation
        media_id = _store_and_link(file_path, args)

        # Step 3: fetch generation data (community only, non-fatal)
        gen_data = {}
        if args.get("fetch_generation_data") and args.get("civitai_image_id"):
            gen_data = _fetch_generation_data(args["civitai_image_id"], args.get("civitai_api_key", ""))

        # Step 4: store CivitAI metadata
        _store_civitai_meta(media_id, args, gen_data)

        # Step 5: update job progress
        if job_id:
            _update_job_progress(job_id, success=True)

        conn.commit()

    except Exception:
        conn.rollback()
        if job_id:
            _update_job_progress(job_id, success=False)
        raise


# Register callback with download scheduler
from v2.app.domain import download as _dl
_dl.register_callback("gallery_deliver", _deliver_gallery_media)


# ══════════════════════════════════════════════════════════════════════════════
#  DOWNLOAD OPERATIONS — start gallery downloads
# ══════════════════════════════════════════════════════════════════════════════

def download_card_images(model_id: str, civitai_model_id: int, api_key: str) -> str:
    """Download card images for a model from CivitAI.

    Fetches all versions of the model, collects their card images,
    deduplicates, creates a gallery_job, and enqueues downloads.

    Args:
        model_id: Our internal model UUID.
        civitai_model_id: CivitAI parent model ID.
        api_key: CivitAI API key.

    Returns:
        Gallery job ID, or empty string if nothing to download.
    """
    from v2.app.clients.civitai import CivitaiClient, extract_cdn_id_from_url, build_cdn_url

    client = CivitaiClient(api_key=api_key)
    model_data = client.get_model(civitai_model_id)

    # Collect unique card images across all versions
    images = []
    seen = set()
    for version in model_data.get("modelVersions", []):
        for img in client.extract_card_images(version):
            cdn_id = img.get("cdn_id", "")
            if cdn_id and cdn_id not in seen and not _is_already_downloaded(cdn_id):
                seen.add(cdn_id)
                images.append(img)

    if not images:
        return ""

    # Create gallery job
    job_id = _uuid.uuid4().hex
    conn = get_conn()
    conn.execute(
        "INSERT INTO gallery_jobs (id, model_id, image_type, total, status, created_at) VALUES (?, ?, 'card', ?, 'running', ?)",
        (job_id, model_id, len(images), now_iso()),
    )
    conn.commit()

    # Enqueue each image
    for img in images:
        cdn_id = img["cdn_id"]
        media_type = img.get("type", "image")
        url = build_cdn_url(cdn_id, media_type)
        ext = ".mp4" if media_type == "video" else ".jpeg"

        _enqueue_image(url, _build_callback_args(
            model_id=model_id, version_id=None, image_type="card",
            origin_id=cdn_id, origin_url=url, original_name=f"{cdn_id}{ext}",
            civitai_image_id=None, api_key=api_key, job_id=job_id,
        ))

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
    """Download community images for a model version from CivitAI.

    Fetches images via tRPC, deduplicates against existing media,
    creates a gallery_job, and enqueues downloads.

    Args:
        model_id: Our internal model UUID (parent).
        version_id: Our internal version UUID.
        civitai_version_id: CivitAI version ID for the API query.
        api_key: CivitAI API key.
        sort, period, types, with_meta, from_platform: Search filters.
        max_images: Maximum images to download.
        fetch_generation_data: Whether to fetch per-image generation data.

    Returns:
        Gallery job ID, or empty string if nothing to download.
    """
    from v2.app.clients.civitai import CivitaiClient, build_cdn_url

    client = CivitaiClient(api_key=api_key)
    filters = {
        "sort": sort, "period": period, "types": types,
        "with_meta": with_meta, "from_platform": from_platform,
        "max_images": max_images, "fetch_generation_data": fetch_generation_data,
    }

    # Collect images via tRPC pagination
    images = []
    for item in client.iter_images_trpc(
        version_id=civitai_version_id, sort=sort, period=period,
        types=types, with_meta=with_meta, from_platform=from_platform,
        limit=min(max_images, 200),
    ):
        normalized = client.normalize_trpc_image(item)
        image_id = normalized.get("id")
        cdn_id = normalized.get("cdn_id", "")
        origin_key = str(image_id) if image_id else cdn_id

        if not _is_already_downloaded(origin_key):
            images.append(normalized)
        if len(images) >= max_images:
            break

    if not images:
        return ""

    # Create gallery job
    job_id = _uuid.uuid4().hex
    conn = get_conn()
    conn.execute(
        "INSERT INTO gallery_jobs (id, model_id, version_id, image_type, filters, total, status, created_at) VALUES (?, ?, ?, 'community', ?, ?, 'running', ?)",
        (job_id, model_id, version_id, json.dumps(filters), len(images), now_iso()),
    )
    conn.commit()

    # Enqueue each image
    for img in images:
        cdn_id = img.get("cdn_id", "")
        image_id = img.get("id")
        media_type = img.get("type", "image")
        url = img.get("full_url") or build_cdn_url(cdn_id, media_type)
        ext = ".mp4" if media_type == "video" else ".jpeg"
        stats = img.get("stats", {})

        _enqueue_image(url, _build_callback_args(
            model_id=model_id, version_id=version_id, image_type="community",
            origin_id=str(image_id) if image_id else cdn_id,
            origin_url=url, original_name=f"{image_id or cdn_id}{ext}",
            civitai_image_id=image_id, api_key=api_key, job_id=job_id,
            post_id=img.get("postId"), post_title=img.get("postTitle"),
            username=img.get("username"),
            stats={
                "reactions": (stats.get("heartCount", 0) or 0) + (stats.get("likeCount", 0) or 0),
                "comments": stats.get("commentCount", 0) or 0,
                "collected": stats.get("collectedCount", 0) or 0,
            },
            fetch_generation_data=fetch_generation_data,
        ))

    return job_id


def resume_job(job_id: str, api_key: str) -> int:
    """Resume an interrupted gallery job.

    Re-fetches the image list from CivitAI with the same filters,
    checks which images are already downloaded (dedup), and enqueues
    only the missing ones. Reuses the same gallery_job record.

    Args:
        job_id: Gallery job ID (must be status='interrupted').
        api_key: CivitAI API key.

    Returns:
        Number of new downloads enqueued.

    Raises:
        ValueError: If job not found, not interrupted, or missing source mapping.
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM gallery_jobs WHERE id = ? AND status = 'interrupted'", (job_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"Job not found or not interrupted: {job_id}")

    job = dict(row)
    conn.execute("UPDATE gallery_jobs SET status = 'running' WHERE id = ?", (job_id,))
    conn.commit()

    from v2.app.domain import catalog as cat
    from v2.app.clients.civitai import CivitaiClient, build_cdn_url

    client = CivitaiClient(api_key=api_key)
    enqueued = 0

    try:
        if job["image_type"] == "card":
            source = cat.get_by_source_entity("model", job["model_id"])
            if not source:
                raise ValueError("No CivitAI source for model")
            model_data = client.get_model(int(source["source_id"]))
            for version in model_data.get("modelVersions", []):
                for img in client.extract_card_images(version):
                    cdn_id = img.get("cdn_id", "")
                    if cdn_id and not _is_already_downloaded(cdn_id):
                        media_type = img.get("type", "image")
                        url = build_cdn_url(cdn_id, media_type)
                        ext = ".mp4" if media_type == "video" else ".jpeg"
                        _enqueue_image(url, _build_callback_args(
                            model_id=job["model_id"], version_id=None, image_type="card",
                            origin_id=cdn_id, origin_url=url, original_name=f"{cdn_id}{ext}",
                            civitai_image_id=None, api_key=api_key, job_id=job_id,
                        ))
                        enqueued += 1

        elif job["image_type"] == "community" and job.get("version_id"):
            source = cat.get_by_source_entity("version", job["version_id"])
            if not source:
                raise ValueError("No CivitAI source for version")
            filters = json.loads(job.get("filters") or "{}")
            max_images = filters.get("max_images", 200)
            completed = job.get("completed", 0)

            for item in client.iter_images_trpc(
                version_id=int(source["source_id"]),
                sort=filters.get("sort", "Most Reactions"),
                period=filters.get("period", "AllTime"),
                types=filters.get("types"),
                with_meta=filters.get("with_meta", False),
                from_platform=filters.get("from_platform", False),
                limit=min(max_images, 200),
            ):
                normalized = client.normalize_trpc_image(item)
                image_id = normalized.get("id")
                cdn_id = normalized.get("cdn_id", "")
                origin_key = str(image_id) if image_id else cdn_id

                if not _is_already_downloaded(origin_key):
                    media_type = normalized.get("type", "image")
                    url = normalized.get("full_url") or build_cdn_url(cdn_id, media_type)
                    ext = ".mp4" if media_type == "video" else ".jpeg"
                    stats = normalized.get("stats", {})
                    _enqueue_image(url, _build_callback_args(
                        model_id=job["model_id"], version_id=job["version_id"],
                        image_type="community",
                        origin_id=origin_key, origin_url=url,
                        original_name=f"{image_id or cdn_id}{ext}",
                        civitai_image_id=image_id, api_key=api_key, job_id=job_id,
                        post_id=normalized.get("postId"), post_title=normalized.get("postTitle"),
                        username=normalized.get("username"),
                        stats={
                            "reactions": (stats.get("heartCount", 0) or 0) + (stats.get("likeCount", 0) or 0),
                            "comments": stats.get("commentCount", 0) or 0,
                            "collected": stats.get("collectedCount", 0) or 0,
                        },
                        fetch_generation_data=filters.get("fetch_generation_data", True),
                    ))
                    enqueued += 1
                    if enqueued + completed >= max_images:
                        break

    except Exception:
        conn.execute("UPDATE gallery_jobs SET status = 'interrupted' WHERE id = ?", (job_id,))
        conn.commit()
        raise

    return enqueued


# ══════════════════════════════════════════════════════════════════════════════
#  JOB MANAGEMENT — track, stop, resume, cleanup gallery download jobs
# ══════════════════════════════════════════════════════════════════════════════

def stop_job(job_id: str):
    """Signal a running gallery job to stop.

    Downloads already enqueued will complete, but the job won't be
    considered successful — it stays until cleanup or resume.
    """
    conn = get_conn()
    conn.execute(
        "UPDATE gallery_jobs SET status = 'stopping' WHERE id = ? AND status = 'running'",
        (job_id,),
    )
    conn.commit()


def get_job_status(job_id: str) -> dict | None:
    """Get gallery job status. Returns None if completed (auto-deleted) or not found."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM gallery_jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_active_jobs() -> list[dict]:
    """List jobs that are running or stopping."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM gallery_jobs WHERE status IN ('running', 'stopping', 'interrupted') ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def list_stale_jobs() -> list[dict]:
    """List interrupted and error jobs (candidates for cleanup or resume)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM gallery_jobs WHERE status IN ('interrupted', 'error') ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def delete_stale_jobs() -> int:
    """Delete all interrupted and error jobs. Returns count deleted."""
    conn = get_conn()
    count = conn.execute(
        "DELETE FROM gallery_jobs WHERE status IN ('interrupted', 'error')"
    ).rowcount
    conn.commit()
    return count


def recover_interrupted():
    """Boot recovery: set all 'running' jobs to 'interrupted'.

    Called at application startup. Downloads already in the scheduler
    will continue (the scheduler has its own recovery), but the gallery
    job needs to know it was interrupted so resume can re-enqueue missing images.
    """
    conn = get_conn()
    count = conn.execute(
        "UPDATE gallery_jobs SET status = 'interrupted' WHERE status = 'running'"
    ).rowcount
    conn.commit()
    if count:
        print(f"[gallery] Recovered {count} interrupted job(s)", flush=True)
    return count


# ══════════════════════════════════════════════════════════════════════════════
#  QUERIES — read gallery data
# ══════════════════════════════════════════════════════════════════════════════

def get_model_gallery(model_id: str) -> dict:
    """Get gallery summary for a model: card images + community counts per version.

    Returns dict with card_count, card_bytes, versions (per-version community counts),
    community_count, community_bytes.
    """
    conn = get_conn()

    card_rows = conn.execute("""
        SELECT m.* FROM media m
        JOIN model_media mm ON m.id = mm.media_id
        WHERE mm.model_id = ? ORDER BY mm.sort_order ASC
    """, (model_id,)).fetchall()

    version_rows = conn.execute("""
        SELECT vm.version_id, COUNT(*) as count,
               COALESCE(SUM(m.file_size), 0) as total_bytes
        FROM version_media vm
        JOIN media m ON m.id = vm.media_id
        JOIN model_versions mv ON mv.id = vm.version_id
        WHERE mv.model_id = ? GROUP BY vm.version_id
    """, (model_id,)).fetchall()

    return {
        "card_images": [dict(r) for r in card_rows],
        "card_count": len(card_rows),
        "card_bytes": sum(r["file_size"] for r in card_rows),
        "versions": {r["version_id"]: {"count": r["count"], "bytes": r["total_bytes"]} for r in version_rows},
        "community_count": sum(r["count"] for r in version_rows),
        "community_bytes": sum(r["total_bytes"] for r in version_rows),
    }


def get_version_gallery(version_id: str) -> list[dict]:
    """Get community images for a specific version."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT m.* FROM media m
        JOIN version_media vm ON m.id = vm.media_id
        WHERE vm.version_id = ? ORDER BY vm.sort_order ASC
    """, (version_id,)).fetchall()
    return [dict(r) for r in rows]


def get_image_meta(media_id: str) -> dict | None:
    """Get CivitAI generation metadata for a media item."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM civitai_image_meta WHERE media_id = ?", (media_id,)
    ).fetchone()
    return dict(row) if row else None


def get_gallery_stats() -> dict:
    """Get aggregate gallery statistics: total card + community counts and bytes."""
    conn = get_conn()
    card = conn.execute(
        "SELECT COUNT(*) as count, COALESCE(SUM(m.file_size), 0) as bytes FROM media m JOIN model_media mm ON m.id = mm.media_id"
    ).fetchone()
    community = conn.execute(
        "SELECT COUNT(*) as count, COALESCE(SUM(m.file_size), 0) as bytes FROM media m JOIN version_media vm ON m.id = vm.media_id"
    ).fetchone()
    return {
        "card_count": card["count"], "card_bytes": card["bytes"],
        "community_count": community["count"], "community_bytes": community["bytes"],
        "total_count": card["count"] + community["count"],
        "total_bytes": card["bytes"] + community["bytes"],
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PREVIEW — choose which image represents a model
# ══════════════════════════════════════════════════════════════════════════════

def set_model_preview(model_id: str, media_id: str):
    """Set the preview image for a model. Uses catalog.update_model()."""
    from v2.app.domain import catalog
    catalog.update_model(model_id, preview_id=media_id)
