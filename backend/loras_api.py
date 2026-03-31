"""ComfyUI Studio — LoRA CivitAI integration: lookup, add, gallery, image serving."""

import json
import os
import re
import threading
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from pydantic import BaseModel

from config import CATALOGS_DIR, LORAS_JSON, MODELS_BASE, IMAGES_DIR, _now_rome

def _civitai_key():
    return os.environ.get("CIVITAI_API_KEY", "")
import catalogs
from download import _enqueue_download
from events import _events
from models_api import _clean_civitai_name

router = APIRouter()


# Gallery store: flat sharded media + SQLite index
# Imported here so download workers can use it.
# The actual DB init happens at startup via events.py.
import gallery_db as _gdb

_gallery_state: dict = {}


def get_active_gallery_downloads() -> dict[int, dict]:
    """Return {model_id: {status, downloaded, total}} for active gallery downloads."""
    result = {}
    for mid, st in _gallery_state.items():
        status = st.get("status", "idle")
        if status in ("downloading", "stopping"):
            result[mid] = {
                "status": status,
                "downloaded": st.get("downloaded", 0),
                "skipped": st.get("skipped", 0),
                "total": st.get("total", 0),
            }
    return result



# ── Request schemas ──────────────────────────────────────────────────────────


class LookupRequest(BaseModel):
    url: str


class AddCivitaiRequest(BaseModel):
    model_id: int
    model_name: str
    author: str
    description: str = ""
    tags: list[str] = []
    rating: float = 0
    downloads: int = 0
    versions: list[dict]
    preview_images: list[dict] = []


class GalleryActionRequest(BaseModel):
    action: str
    mode: str = "fixed"  # fixed | trpc | rest
    # REST filters
    nsfw: str = "X"
    # Shared
    sort: str = "Newest"
    period: str = "AllTime"
    version_id: int | None = None
    # tRPC filters
    types: list[str] | None = None  # ["image"], ["video"], or None=all
    with_meta: bool = False
    from_platform: bool = False
    is_remix: bool | None = None  # None=all, False=originals, True=remixes
    workers: int = 6


# ── Helpers ──────────────────────────────────────────────────────────────────

_BASE_MODEL_MAP = {
    "SD 1.4": ("sd15_loras", "SD 1.5 LoRAs"),
    "SD 1.5": ("sd15_loras", "SD 1.5 LoRAs"),
    "SD 1.5 LCM": ("sd15_loras", "SD 1.5 LoRAs"),
    "SDXL 0.9": ("sdxl_loras", "SDXL LoRAs"),
    "SDXL 1.0": ("sdxl_loras", "SDXL LoRAs"),
    "SDXL 1.0 LCM": ("sdxl_loras", "SDXL LoRAs"),
    "SDXL Turbo": ("sdxl_loras", "SDXL LoRAs"),
    "SDXL Lightning": ("sdxl_loras", "SDXL LoRAs"),
    "SDXL Hyper": ("sdxl_loras", "SDXL LoRAs"),
    "Pony": ("pony_loras", "Pony LoRAs"),
    "FLUX.1 D": ("flux_loras", "FLUX LoRAs"),
    "FLUX.1 S": ("flux_loras", "FLUX LoRAs"),
}


def _nsfw_level(val) -> bool:
    try:
        return int(val) > 1
    except (TypeError, ValueError):
        return False


def _category_for_base_model(bm: str) -> tuple[str, str]:
    if bm in _BASE_MODEL_MAP:
        return _BASE_MODEL_MAP[bm]
    bl = bm.lower()
    if "flux" in bl: return ("flux_loras", "FLUX LoRAs")
    if "pony" in bl: return ("pony_loras", "Pony LoRAs")
    if "sdxl" in bl: return ("sdxl_loras", "SDXL LoRAs")
    if "sd 1" in bl or "sd1" in bl: return ("sd15_loras", "SD 1.5 LoRAs")
    if "illustrious" in bl: return ("illustrious_loras", "Illustrious LoRAs")
    return ("other_loras", "Other LoRAs")


def _url_to_id(url: str) -> str:
    """Extract UUID from CivitAI CDN URL as fallback when id is null."""
    m = re.search(r'/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/', url)
    return m.group(1) if m else ""


def _parse_civitai_url(url: str) -> tuple[int, int | None]:
    m = re.search(r'civitai\.com/models/(\d+)', url)
    if not m:
        raise ValueError("Not a valid CivitAI model URL. Expected: https://civitai.com/models/12345")
    model_id = int(m.group(1))
    vm = re.search(r'modelVersionId=(\d+)', url)
    return model_id, int(vm.group(1)) if vm else None


def _extract_image_meta(meta: dict | None) -> dict:
    if not meta:
        return {}
    r = {}
    for k in ("prompt", "negativePrompt"):
        if meta.get(k):
            r[k] = meta[k]
    if meta.get("Model"):
        r["model"] = meta["Model"]
    loras = []
    for res in (meta.get("resources") or []):
        if res.get("type", "").lower() == "lora":
            entry = {"name": res.get("name", "")}
            if res.get("hash"):
                entry["hash"] = res["hash"]
            if res.get("weight") is not None:
                entry["weight"] = res["weight"]
            loras.append(entry)
    if loras:
        r["loras"] = loras
    for k in ("seed", "steps", "cfgScale", "sampler", "clipSkip"):
        if meta.get(k) is not None:
            r[k] = meta[k]
    if meta.get("Size"):
        r["size"] = meta["Size"]
        parts = meta["Size"].split("x")
        if len(parts) == 2:
            try:
                r["width"], r["height"] = int(parts[0]), int(parts[1])
            except ValueError:
                pass
    return r


def _fetch_generation_data(image_id: int) -> dict | None:
    """Fetch generation data from CivitAI tRPC endpoint."""
    if not image_id or not _civitai_key():
        return None
    try:
        params = json.dumps({"json": {"id": image_id, "authed": True}})
        r = httpx.get(f"https://civitai.com/api/trpc/image.getGenerationData?input={params}",
                      headers={"Authorization": f"Bearer {_civitai_key()}",
                               "Content-Type": "application/json"},
                      timeout=15)
        if r.status_code == 200:
            return r.json().get("result", {}).get("data", {}).get("json", {})
    except Exception:
        pass
    return None


def _extract_thumbnail(video_path: Path) -> bool:
    """Extract first frame from video as thumbnail using ffmpeg."""
    thumb = video_path.with_suffix(".thumb.jpg")
    if thumb.exists():
        return True
    try:
        import subprocess
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_path), "-vframes", "1",
             "-vf", "scale=300:-1", "-q:v", "5", "-f", "image2", str(thumb)],
            capture_output=True, timeout=15)
        return thumb.exists() and thumb.stat().st_size > 0
    except Exception:
        return False


def _generate_image_thumb(image_path: Path, max_width: int = 300) -> bool:
    """Generate a thumbnail for an image using Pillow. Returns True on success."""
    thumb = image_path.with_suffix(".thumb.jpg")
    if thumb.exists() and thumb.stat().st_size > 0:
        return True
    try:
        from PIL import Image
        with Image.open(image_path) as img:
            if img.width > max_width:
                ratio = max_width / img.width
                new_size = (max_width, int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)
            img = img.convert("RGB")
            img.save(thumb, "JPEG", quality=70)
        return thumb.exists() and thumb.stat().st_size > 0
    except Exception:
        return False


def _download_image(url: str, dest: Path, timeout: int = 30) -> bool:
    try:
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as resp:
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                for chunk in resp.iter_bytes(65536):
                    f.write(chunk)
        return True
    except Exception:
        if dest.exists():
            dest.unlink()
        return False


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/api/admin/loras/lookup-civitai")
async def lookup_civitai(body: LookupRequest):
    """Lookup a CivitAI model by URL and return structured data."""
    if not _civitai_key():
        raise HTTPException(400, "CIVITAI_API_KEY not configured — set it in Settings")
    try:
        model_id, version_id = _parse_civitai_url(body.url)
    except ValueError as e:
        raise HTTPException(400, str(e))

    headers = {"Authorization": f"Bearer {_civitai_key()}"}
    async with httpx.AsyncClient(timeout=20, headers=headers) as client:
        try:
            r = await client.get(f"https://civitai.com/api/v1/models/{model_id}")
        except httpx.RequestError:
            raise HTTPException(502, "Could not reach CivitAI")
        if r.status_code == 404:
            raise HTTPException(404, "Model not found on CivitAI")
        r.raise_for_status()
        model = r.json()

        try:
            r2 = await client.get("https://civitai.com/api/v1/images",
                                  params={"modelId": model_id, "limit": 20})
            imgs_data = r2.json() if r2.status_code == 200 else {"items": []}
        except Exception:
            imgs_data = {"items": []}

    versions = []
    for v in model.get("modelVersions", []):
        files = [
            {"id": f.get("id"), "name": f.get("name", ""),
             "size_kb": f.get("sizeKB", 0),
             "fp": (f.get("metadata") or {}).get("fp", ""),
             "format": (f.get("metadata") or {}).get("format", "")}
            for f in v.get("files", [])
        ]
        v_images = [
            {"id": img.get("id") or _url_to_id(img.get("url", "")),
             "url": img.get("url", ""),
             "width": img.get("width"), "height": img.get("height"),
             "type": img.get("type", "image"),
             "nsfw": _nsfw_level(img.get("nsfwLevel"))}
            for img in v.get("images", []) if img.get("url")
        ]
        versions.append({
            "version_id": v.get("id"),
            "name": v.get("name", ""),
            "base_model": v.get("baseModel", ""),
            "trigger_words": v.get("trainedWords", []),
            "files": files,
            "images": v_images,
            "created_at": v.get("createdAt", ""),
            "download_count": v.get("stats", {}).get("downloadCount", 0),
        })

    preview_images = [
        {"id": img.get("id"), "url": img.get("url", ""),
         "width": img.get("width"), "height": img.get("height"),
         "nsfw": _nsfw_level(img.get("nsfwLevel")),
         "meta": _extract_image_meta(img.get("meta"))}
        for img in imgs_data.get("items", [])
    ]

    stats = model.get("stats", {})
    return JSONResponse({
        "model_id": model.get("id"),
        "name": model.get("name", ""),
        "author": (model.get("creator") or {}).get("username", ""),
        "description": model.get("description", ""),
        "type": model.get("type", ""),
        "tags": model.get("tags", []),
        "nsfw": model.get("nsfw", False),
        "stats": {
            "rating": stats.get("rating", 0),
            "rating_count": stats.get("ratingCount", 0),
            "download_count": stats.get("downloadCount", 0),
            "favorite_count": stats.get("favoriteCount", 0),
        },
        "versions": versions,
        "preview_images": preview_images,
        "selected_version_id": version_id,
    })


@router.post("/api/admin/loras/add-civitai")
async def add_civitai(body: AddCivitaiRequest):
    """Add selected CivitAI LoRA versions to the catalog and queue downloads."""
    catalogs._reload_models()
    loras_data = catalogs._loras_data

    existing = {m.get("file", "") for cat in loras_data.get("categories", [])
                for m in cat.get("models", [])}
    cat_map = {cat["id"]: cat for cat in loras_data.get("categories", [])}

    # Build meta lookup from preview images
    meta_lookup = {}
    for img in body.preview_images:
        if img.get("id") and img.get("meta"):
            meta_lookup[img["id"]] = img["meta"]

    added, skipped = [], []
    images_to_dl = []

    for ver in body.versions:
        files = ver.get("files", [])
        if not files:
            continue
        f = files[0]
        filename = f.get("name", "")
        if not filename or filename in existing:
            if filename:
                skipped.append(filename)
            continue

        base_model = ver.get("base_model", "")
        fp = f.get("fp", "")
        size_gb = round(f.get("size_kb", 0) / 1_000_000, 3)
        name = _clean_civitai_name(body.model_name, ver.get("name", ""), base_model, fp)

        img_ids = [str(img.get("id") or _url_to_id(img.get("url", ""))) + ".jpeg"
                   for img in ver.get("images", []) if img.get("url")]

        entry = {
            "name": name,
            "file": filename,
            "dest": "loras",
            "source": "civitai",
            "civitai_version_id": ver.get("version_id"),
            "civitai_model_id": body.model_id,
            "size_gb": size_gb,
            "base_model": base_model,
            "tags": list(body.tags),
            "trigger_words": ver.get("trigger_words", []),
            "description": (body.description or "")[:500],
            "author": body.author,
            "rating": body.rating,
            "downloads": body.downloads,
            "images": img_ids,
        }

        cat_id, cat_name = _category_for_base_model(base_model)
        if cat_id not in cat_map:
            new_cat = {"id": cat_id, "name": cat_name, "models": []}
            loras_data.setdefault("categories", []).append(new_cat)
            cat_map[cat_id] = new_cat
        cat_map[cat_id]["models"].append(entry)
        existing.add(filename)
        added.append(filename)
        _enqueue_download(entry, source="civitai-add")

        for img in ver.get("images", []):
            url = img.get("url", "")
            if url:
                iid = img.get("id") or _url_to_id(url)
                meta = meta_lookup.get(img.get("id"), meta_lookup.get(iid, {}))
                images_to_dl.append((body.model_id, iid, url, meta))

    if added:
        loras_data["version"] = loras_data.get("version", 0) + 1
        from datetime import datetime, timezone, timedelta
        loras_data["date"] = _now_rome().strftime("%Y-%m-%d %H:%M")
        LORAS_JSON.parent.mkdir(parents=True, exist_ok=True)
        LORAS_JSON.write_text(json.dumps(loras_data, indent=2, ensure_ascii=False))
        if images_to_dl:
            threading.Thread(target=_download_preview_images, args=(images_to_dl,),
                             daemon=True).start()
        _events.emit("lora.added", f"Added {len(added)} LoRA(s) from CivitAI",
                     severity="success", data={"added": added, "model_id": body.model_id})

    return JSONResponse({"added": added, "skipped": skipped})


def _download_preview_images(items: list):
    """Background: download preview images and save metadata."""
    for model_id, image_id, url, meta in items:
        dest = IMAGES_DIR / "lookup" / str(model_id) / "previews" / f"{image_id}.jpeg"
        if dest.exists():
            continue
        if _download_image(url, dest) and meta:
            dest.with_suffix(".json").write_text(
                json.dumps(meta, indent=2, ensure_ascii=False))


# ── Gallery ──────────────────────────────────────────────────────────────────


@router.post("/api/admin/loras/{model_id}/gallery")
async def gallery_action(model_id: int, body: GalleryActionRequest):
    """Start or stop gallery image download for a model."""
    if body.action == "stop":
        st = _gallery_state.get(model_id)
        if st and st.get("_stop"):
            st["_stop"].set()
            st["status"] = "stopping"
        return JSONResponse({"status": "stopping"})

    if not body.action.startswith("start"):
        raise HTTPException(400, "action must be 'start' or 'stop'")
    if not _civitai_key():
        raise HTTPException(400, "CIVITAI_API_KEY not configured — set it in Settings")

    st = _gallery_state.get(model_id)
    if st and st.get("status") == "downloading":
        return JSONResponse({"status": "downloading", "message": "Already running"})

    max_images = 200
    cards_only = body.action == "start:cards"
    if not cards_only and body.action.startswith("start:"):
        try:
            max_images = int(body.action.split(":")[1])
        except (ValueError, IndexError):
            pass
    if cards_only:
        max_images = 0
    else:
        max_images = max(1, min(max_images, _GALLERY_MAX_IMAGES))

    stop = threading.Event()
    api_params = {
        "mode": body.mode, "nsfw": body.nsfw, "sort": body.sort, "period": body.period,
        "version_id": body.version_id, "types": body.types,
        "with_meta": body.with_meta, "from_platform": body.from_platform,
        "is_remix": body.is_remix, "workers": max(1, min(body.workers, 20)),
    }
    _gallery_state[model_id] = {
        "status": "downloading", "downloaded": 0, "skipped": 0,
        "total": 0, "_stop": stop, "max_images": max_images,
    }
    threading.Thread(target=_gallery_thread, args=(model_id, stop, api_params),
                     daemon=True).start()
    return JSONResponse({"status": "downloading"})


_GALLERY_MAX_IMAGES = 1000


def _gallery_download_one(iid: str, url: str, meta: dict,
                          model_id: int, version_id: int | None,
                          fetch_gen_data: bool, stop: threading.Event,
                          search_mode: str = "fixed") -> str:
    """Download a single gallery image/video to the flat store.

    This is the per-item worker function called by the ThreadPoolExecutor.
    Each call is independent and thread-safe:
    1. Check if already downloaded (DB lookup, faster than filesystem)
    2. Download with retry (5 attempts, 200ms stop-checks)
    3. Extract thumbnail for videos (ffmpeg)
    4. Fetch generation data from CivitAI tRPC
    5. Save metadata JSON to sharded meta/ directory
    6. Insert into SQLite gallery_images + link to version

    Returns 'ok', 'skipped', or 'failed'.
    """
    ext = ".mp4" if ".mp4" in url else ".jpeg"

    # Skip if already in the database — faster than checking filesystem
    if _gdb.image_exists(iid):
        # Still link to this version (image may exist from another version's download)
        if version_id:
            _gdb.link_version(iid, version_id)
        return "skipped"

    # Compute file paths based on source type:
    # 'original' → models/{model_id}/{id}.ext (grouped by model)
    # 'community' → media/NNN/NNN/{id}.ext (sharded flat store)
    source = meta.get("_source", "community")
    rel_file = _gdb.file_path_for(source, model_id, iid, ext)
    rel_thumb = _gdb.thumb_path_for(source, model_id, iid)
    rel_meta = _gdb.meta_path_for(source, model_id, iid)
    dest = _gdb.abs_path(rel_file)

    # File on disk but not in DB — register it and skip download.
    # This happens when files exist from a previous session.
    if dest.exists() and dest.stat().st_size > 0:
        has_thumb = _gdb.abs_path(rel_thumb).exists() if rel_thumb else False
        stats = meta.get("stats") or {}
        raw_meta = meta.get("raw_meta") or {}
        prompt = raw_meta.get("prompt", "") if isinstance(raw_meta, dict) else ""
        try:
            _gdb.insert_image({
                "civitai_id": iid, "file_uuid": _url_to_id(url),
                "type": meta.get("type", "video" if ext == ".mp4" else "image"),
                "ext": ext, "file_path": rel_file,
                "thumb_path": rel_thumb if has_thumb else None,
                "meta_path": rel_meta if _gdb.abs_path(rel_meta).exists() else None,
                "model_id": model_id, "source": source,
                "post_id": meta.get("postId"), "post_title": meta.get("postTitle", ""),
                "username": meta.get("username", ""), "base_model": meta.get("baseModel", ""),
                "width": meta.get("width"), "height": meta.get("height"),
                "duration": meta.get("duration"), "audio": meta.get("audio"),
                "file_size": dest.stat().st_size, "created_at": meta.get("createdAt"),
                "reactions": stats.get("heartCount", 0) + stats.get("likeCount", 0),
                "has_meta": _gdb.abs_path(rel_meta).exists() if rel_meta else False,
                "search_mode": search_mode, "prompt": prompt,
            })
            if version_id:
                _gdb.link_version(iid, version_id)
        except Exception as e:
            print(f"[gallery] DB insert (existing file) failed for {iid}: {e}", flush=True)
        return "skipped"

    # Retry up to 5 times with 2s delay between attempts.
    # Check stop event every 200ms to allow fast cancellation
    # instead of blocking for the full 2s sleep.
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(5):
        if stop.is_set():
            return "failed"
        if _download_image(url, dest):
            break
        for _ in range(10):
            if stop.is_set():
                return "failed"
            time.sleep(0.2)
    else:
        return "failed"

    # Generate thumbnail: ffmpeg for videos, Pillow resize for images.
    has_thumb = False
    if ext == ".mp4":
        _extract_thumbnail(dest)
    else:
        _generate_image_thumb(dest)
    has_thumb = _gdb.abs_path(rel_thumb).exists() if rel_thumb else False

    # Fetch generation data (resources, tools, techniques) from CivitAI tRPC.
    # This gives us the list of LoRAs/checkpoints used, which the REST API
    # doesn't include in the meta field.
    if fetch_gen_data and meta.get("civitai_id"):
        gen = _fetch_generation_data(meta["civitai_id"])
        if gen:
            meta["generation_data"] = gen

    # Save full metadata JSON to the sharded meta/ directory.
    # This includes raw_item, generation_data, and everything else.
    # The DB only stores light fields; heavy data lives in JSON on disk.
    meta_dest = _gdb.abs_path(rel_meta)
    meta_dest.parent.mkdir(parents=True, exist_ok=True)
    if meta:
        meta_dest.write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    # Extract stats for DB storage
    stats = meta.get("stats") or {}
    raw_meta = meta.get("raw_meta") or {}
    prompt = raw_meta.get("prompt", "") if isinstance(raw_meta, dict) else ""

    # Insert into gallery database
    try:
        _gdb.insert_image({
        "civitai_id": iid,
        "file_uuid": _url_to_id(url),
        "type": meta.get("type", "video" if ext == ".mp4" else "image"),
        "ext": ext,
        "file_path": rel_file,
        "thumb_path": rel_thumb if has_thumb else None,
        "meta_path": rel_meta if meta else None,
        "model_id": model_id,
        "post_id": meta.get("postId"),
        "post_title": meta.get("postTitle", ""),
        "username": meta.get("username", ""),
        "base_model": meta.get("baseModel", ""),
        "width": meta.get("width"),
        "height": meta.get("height"),
        "duration": meta.get("duration"),
        "audio": meta.get("audio"),
        "file_size": dest.stat().st_size if dest.exists() else 0,
        "created_at": meta.get("createdAt"),
        "reactions": stats.get("heartCount", 0) + stats.get("likeCount", 0),
        "comments": stats.get("commentCount", 0),
        "collected": stats.get("collectedCount", 0) if "collectedCount" in stats else 0,
        "has_meta": bool(meta),
        "has_gen_data": bool(meta.get("generation_data")),
        "source": meta.get("_source", "community"),
        "search_mode": search_mode,
        "prompt": prompt,
    })
    except Exception as e:
        print(f"[gallery] DB insert failed for {iid}: {e}", flush=True)

    # Link this image to the specific version it was found under.
    # The same image can be linked to multiple versions.
    if version_id:
        try:
            _gdb.link_version(iid, version_id)
        except Exception as e:
            print(f"[gallery] DB link_version failed for {iid}: {e}", flush=True)

    return "ok"


def _gallery_download_batch(items: list[tuple],
                            model_id: int, version_id: int | None,
                            state: dict, stop: threading.Event,
                            seen: set, fetch_gen_data: bool = False,
                            workers: int = 6,
                            search_mode: str = "fixed") -> bool:
    """Download a batch of (id, url, meta) items with parallel workers.

    Orchestrates the download of multiple gallery items concurrently.
    Deduplicates by URL-derived UUID within the current download session
    (the 'seen' set). Cross-session dedup happens in _gallery_download_one
    via the SQLite database.

    Returns False if stopped (so the caller can break out of the pagination loop).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Filter duplicates within this session using URL UUIDs.
    # This prevents downloading the same image twice if it appears
    # in both card and community results, or across paginated pages.
    todo = []
    for iid, url, meta in items:
        url_key = _url_to_id(url) or iid
        if url_key in seen:
            continue
        seen.add(url_key)
        todo.append((iid, url, meta))

    if not todo:
        return True

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_gallery_download_one, iid, url, meta,
                        model_id, version_id, fetch_gen_data, stop,
                        search_mode): iid
            for iid, url, meta in todo
        }
        for fut in as_completed(futures):
            if stop.is_set():
                pool.shutdown(wait=False, cancel_futures=True)
                return False
            result = fut.result()
            if result == "ok":
                state["downloaded"] += 1
            elif result == "skipped":
                state["skipped"] += 1
    return True


def _gallery_thread(model_id: int, stop: threading.Event, api_params: dict):
    """Download model card images + community images for a CivitAI model."""
    state = _gallery_state[model_id]
    headers = {"Authorization": f"Bearer {_civitai_key()}"} if _civitai_key() else {}
    max_community = state.get("max_images", 200)
    num_workers = api_params.get("workers", 6)
    mode = api_params.get("mode", "fixed")
    version_id = api_params.get("version_id")

    # ── Phase 1: model card images (always all of them) ──
    try:
        r = httpx.get(f"https://civitai.com/api/v1/models/{model_id}",
                      timeout=30, headers=headers)
        if r.status_code != 200:
            state["status"] = "done"
            return
        model_data = r.json()
    except Exception:
        state["status"] = "done"
        return

    card_imgs = []
    for v in model_data.get("modelVersions", []):
        for img in v.get("images", []):
            url = img.get("url", "")
            if not url:
                continue
            iid = img.get("id") or _url_to_id(url)
            if not iid:
                continue
            meta = {"civitai_id": img.get("id"), "url": url,
                    "type": img.get("type", "image"),
                    "width": img.get("width"), "height": img.get("height"),
                    "_source": "original"}
            if img.get("id"):
                meta["civitai_page"] = f"https://civitai.com/images/{img['id']}?token={_civitai_key()}"
            card_imgs.append((str(iid), url, meta))

    state["total"] = len(card_imgs) + max_community
    seen: set[str] = set()

    if not _gallery_download_batch(card_imgs, model_id, version_id, state, stop, seen,
                                   workers=num_workers, search_mode=mode):
        state["status"] = "stopped"
        return

    # ── Resolve creator ID for tRPC prioritizedUserIds ──
    creator_id = None
    creator_username = (model_data.get("creator") or {}).get("username")
    if creator_username:
        try:
            inp = json.dumps({"json": {"username": creator_username}})
            cr = httpx.get(f"https://civitai.com/api/trpc/user.getCreator?input={inp}",
                           headers=headers, timeout=10)
            if cr.status_code == 200:
                creator_id = cr.json().get("result", {}).get("data", {}).get("json", {}).get("id")
        except Exception:
            pass

    # ── Phase 2: community images (capped by max_community) ──
    community_downloaded = 0
    cursor = None
    state["pages_fetched"] = 0
    print(f"[gallery] {model_id}: mode={mode}, max={max_community}, seen={len(seen)}, creator={creator_id}", flush=True)

    while community_downloaded < max_community:
        if stop.is_set():
            state["status"] = "stopped"
            return

        # Fetch page
        try:
            if mode in ("fixed", "trpc"):
                # Build tRPC input — base matches CivitAI site call
                inp = {
                    "modelVersionId": api_params.get("version_id") or model_id,
                    "period": "AllTime",
                    "sort": "Most Reactions",
                    "limit": 200,
                    "pending": True,
                    "include": [],
                    "withMeta": False,
                    "excludedTagIds": [],
                    "disablePoi": True,
                    "disableMinor": True,
                    "cursor": cursor,
                    "authed": True,
                }
                # In tRPC mode, apply user filters
                if mode == "trpc":
                    inp["sort"] = api_params.get("sort", "Newest")
                    inp["period"] = api_params.get("period", "AllTime")
                    if api_params.get("types"):
                        inp["types"] = api_params["types"]
                    if api_params.get("with_meta"):
                        inp["withMeta"] = True
                    if api_params.get("from_platform"):
                        inp["fromPlatform"] = True
                    if api_params.get("is_remix") is not None:
                        inp["isRemix"] = api_params["is_remix"]

                trpc_input = json.dumps({"json": inp, "meta": {"values": {"cursor": ["undefined"]}}})
                print(f"[gallery] tRPC input: {trpc_input[:300]}", flush=True)
                # Use params= so httpx URL-encodes the input properly.
                # Passing raw JSON in f-string URL breaks on special chars.
                r = httpx.get("https://civitai.com/api/trpc/image.getInfinite",
                              params={"input": trpc_input},
                              headers=headers, timeout=30)
                print(f"[gallery] tRPC status: {r.status_code}, body size: {len(r.content)}", flush=True)
                if r.status_code != 200:
                    break
                rdata = r.json().get("result", {}).get("data", {}).get("json", {})
                page_items = rdata.get("items", [])
                next_cursor = rdata.get("nextCursor")
            else:
                # REST mode
                params: dict = {"modelId": model_id, "limit": 200,
                                "nsfw": api_params.get("nsfw", "X"),
                                "sort": api_params.get("sort", "Newest"),
                                "period": api_params.get("period", "AllTime")}
                if api_params.get("version_id"):
                    params["modelVersionId"] = api_params["version_id"]
                if cursor:
                    params["cursor"] = cursor
                r = httpx.get("https://civitai.com/api/v1/images",
                              params=params, timeout=30, headers=headers)
                if r.status_code != 200:
                    break
                data = r.json()
                page_items = data.get("items", [])
                next_cursor = (data.get("metadata") or {}).get("nextCursor")
        except Exception:
            break
        state["pages_fetched"] = state.get("pages_fetched", 0) + 1

        print(f"[gallery] {model_id}: page {state['pages_fetched']}, items={len(page_items)}, cd={community_downloaded}", flush=True)
        if not page_items:
            break

        # Build batch from page items
        _CDN = "https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/"
        batch = []
        for img in page_items:
            if community_downloaded >= max_community:
                break
            # tRPC returns short url (UUID only), REST returns full URL
            raw_url = img.get("url", "")
            if mode in ("fixed", "trpc") and raw_url and not raw_url.startswith("http"):
                ext_hint = ".mp4" if img.get("type") == "video" else ".jpeg"
                full_url = f"{_CDN}{raw_url}/original=true/{raw_url}{ext_hint}"
            else:
                full_url = raw_url
            if not full_url:
                continue
            url_key = _url_to_id(full_url) or raw_url
            if url_key and url_key in seen:
                continue
            iid = str(img.get("id") or url_key)
            if not iid:
                continue
            meta = {
                "civitai_id": img.get("id"),
                "civitai_page": f"https://civitai.com/images/{img['id']}?token={_civitai_key()}" if img.get("id") else None,
                "url": full_url,
                "type": img.get("type", "image"),
                "width": img.get("width"), "height": img.get("height"),
                "username": (img.get("user") or {}).get("username") if mode in ("fixed", "trpc") else img.get("username"),
                "postId": img.get("postId"),
                "postTitle": img.get("postTitle", ""),
                "duration": (img.get("metadata") or {}).get("duration"),
                "audio": (img.get("metadata") or {}).get("audio"),
                "baseModel": img.get("baseModel"),
                "createdAt": img.get("createdAt"),
                "stats": img.get("stats"),
                "raw_meta": img.get("meta"),
                "raw_item": img,
                "_source": "community",
            }
            batch.append((iid, full_url, meta))
            community_downloaded += 1

        if not _gallery_download_batch(batch, model_id, version_id, state, stop, seen,
                                              fetch_gen_data=True, workers=num_workers,
                                              search_mode=mode):
            state["status"] = "stopped"
            return

        print(f"[gallery] {model_id}: batch done, cd={community_downloaded}, dl={state['downloaded']} skip={state['skipped']}", flush=True)
        cursor = next_cursor
        print(f"[gallery] {model_id}: nextCursor={'yes' if cursor else 'NO'}", flush=True)
        if not cursor:
            break

    # Mark as done, then clear state after a short delay so the frontend
    # can show the "Completed" message before it disappears.
    state["total"] = len(seen)
    state["status"] = "done"
    # Clean up state after 10s so reopening gallery doesn't show stale progress
    def _cleanup():
        time.sleep(10)
        if _gallery_state.get(model_id, {}).get("status") == "done":
            _gallery_state.pop(model_id, None)
    threading.Thread(target=_cleanup, daemon=True).start()
    _events.emit("lora.gallery.done",
                 f"Gallery done for {model_id}: {state['downloaded']} new, {state['skipped']} skipped",
                 severity="success", data={"model_id": model_id})


@router.get("/api/admin/loras/{model_id}/gallery")
async def gallery_status(model_id: int, version_id: int | None = None,
                         starred: bool = False):
    """Get gallery download status and image listing from SQLite.

    This replaces the old filesystem-scanning approach. The DB query is
    instant regardless of how many images exist — no more reading hundreds
    of JSON files on every poll request.

    The version_id query param is optional. If provided, only images linked
    to that version are returned. Otherwise, all images for the model.
    """
    state = _gallery_state.get(model_id, {})

    # Query images from SQLite, split by source (card vs community)
    if version_id:
        # Original images belong to model, not version — always query by model_id
        card_list = _gdb.list_images_by_model(model_id, source="original", starred_only=starred)
        comm_list = _gdb.list_images_by_version(version_id, source="community", starred_only=starred)
    else:
        card_list = _gdb.list_images_by_model(model_id, source="original", starred_only=starred)
        comm_list = _gdb.list_images_by_model(model_id, source="community", starred_only=starred)

    # Convert DB rows to the format the frontend expects.
    # Each item needs: id, ext, meta (light), createdAt, has_thumb
    def _format(row: dict) -> dict:
        return {
            "id": row["civitai_id"],
            "ext": row["ext"],
            "has_thumb": bool(row.get("thumb_path")),
            "starred": bool(row.get("starred")),
            "createdAt": row.get("created_at", ""),
            "meta": {
                "civitai_id": row.get("civitai_id"),
                "civitai_page": f"https://civitai.com/images/{row['civitai_id']}?token={_civitai_key()}" if row.get("civitai_id", "").isdigit() else None,
                "url": None,  # not needed for listing — loaded on detail view
                "type": row.get("type", "image"),
                "width": row.get("width"),
                "height": row.get("height"),
                "username": row.get("username", ""),
                "postId": row.get("post_id"),
                "postTitle": row.get("post_title", ""),
                "duration": row.get("duration"),
                "audio": bool(row.get("audio")),
                "baseModel": row.get("base_model", ""),
                "createdAt": row.get("created_at", ""),
            },
        }

    formatted_card = [_format(r) for r in card_list]
    formatted_comm = [_format(r) for r in comm_list]

    # Get aggregate sizes from DB
    stats = _gdb.count_and_size(model_id=model_id, version_id=version_id)

    # Preview info: default (first original) + user custom choice
    default_preview = formatted_card[0]["id"] if formatted_card else (formatted_comm[0]["id"] if formatted_comm else None)
    custom_preview = _gdb.get_preview(model_id)

    return JSONResponse({
        "status": state.get("status", "idle"),
        "downloaded": state.get("downloaded", 0),
        "skipped": state.get("skipped", 0),
        "total": state.get("total"),
        "pages_fetched": state.get("pages_fetched", 0),
        "counted": state.get("counted", 0),
        "gallery_card": formatted_card,
        "gallery_card_bytes": stats.get("original_bytes", 0),
        "gallery_community": formatted_comm,
        "gallery_community_bytes": stats.get("community_bytes", 0),
        "default_preview": default_preview,
        "custom_preview": custom_preview,
    })


@router.get("/api/admin/loras/gallery/{item_id}/meta")
async def gallery_item_meta(item_id: str):
    """Get full metadata (including generation_data) for a single gallery item.

    Looks up the item in SQLite to find its meta_path, then reads the full
    JSON from disk. This is the on-demand detail endpoint — called when the
    user clicks 'Details' on a gallery item. The heavy fields (raw_item,
    generation_data) are only in the JSON file, not in the DB.
    """
    row = _gdb.get_image(item_id)
    if not row or not row.get("meta_path"):
        raise HTTPException(404, "Metadata not found")
    mf = _gdb.abs_path(row["meta_path"])
    if not mf.exists():
        raise HTTPException(404, "Metadata file missing")
    try:
        return JSONResponse(json.loads(mf.read_text()))
    except Exception:
        raise HTTPException(500, "Failed to read metadata")


@router.delete("/api/admin/loras/{model_id}/gallery")
async def gallery_delete(model_id: int, version_id: int | None = None):
    """Unlink gallery images from a version (or all versions of a model).

    Community images are GLOBAL — they are never deleted from disk or DB.
    This only removes the image_versions links so the images stop appearing
    in this version's gallery. The files and DB records stay for future use.
    Original/card images for this model ARE deleted (files + DB records)
    since they belong to the model, not the global store.
    """
    # Remove version links
    if version_id:
        count = _gdb.delete_by_version(version_id)
    else:
        # Remove all version links for all versions of this model
        # by finding all versions that have links
        conn = _gdb._get_conn()
        rows = conn.execute("""
            SELECT DISTINCT iv.version_id FROM image_versions iv
            JOIN gallery_images g ON iv.civitai_id = g.civitai_id
            WHERE g.model_id = ?
        """, (model_id,)).fetchall()
        count = 0
        for row in rows:
            count += _gdb.delete_by_version(row["version_id"])

    # Delete original/card images (these belong to the model)
    originals = _gdb.list_images_by_model(model_id, source="original")
    for img in originals:
        for field in ("file_path", "thumb_path", "meta_path"):
            if img.get(field):
                full = _gdb.abs_path(img[field])
                if full.exists():
                    full.unlink()
    if originals:
        conn = _gdb._get_conn()
        conn.execute("DELETE FROM gallery_images WHERE model_id = ? AND source = 'original'", (model_id,))
        conn.commit()

    if model_id in _gallery_state:
        del _gallery_state[model_id]
    return JSONResponse({"deleted": count + len(originals)})



@router.post("/api/admin/loras/gallery/{item_id}/set-preview")
async def set_gallery_preview(item_id: str):
    """Set a gallery image as the custom preview for its model."""
    img = _gdb.get_image(item_id)
    if not img:
        raise HTTPException(404, "Image not found")
    model_id = img["model_id"]
    _gdb.set_preview(model_id, item_id)
    return JSONResponse({"status": "ok", "model_id": model_id, "civitai_id": item_id})


@router.post("/api/admin/loras/gallery/{item_id}/star")
async def toggle_star(item_id: str):
    """Toggle the starred flag on a gallery image.

    Returns the new starred state. Used by the star button in the UI.
    """
    new_state = _gdb.toggle_starred(item_id)
    return JSONResponse({"starred": new_state})


# ── CivitAI Tags ────────────────────────────────────────────────────────────
# Endpoints for syncing and querying the local CivitAI tag dictionary.
# Tags are resolved from CivitAI's tRPC batch API and cached in SQLite.


def _sync_civitai_tags_bg() -> int:
    """Background (sync) version of tag sync. Called from startup thread.

    Collects tagIds from gallery metadata, resolves unknown ones via
    CivitAI tRPC batch, stores in DB. Returns count of newly resolved tags.
    """
    if not _civitai_key():
        return 0

    # Collect all unique tagIds from gallery images' raw metadata
    all_tag_ids = set()
    conn = _gdb._get_conn()
    rows = conn.execute("SELECT meta_path FROM gallery_images WHERE meta_path IS NOT NULL").fetchall()
    for row in rows:
        meta_file = _gdb.abs_path(row["meta_path"])
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text())
            raw_item = meta.get("raw_item") or {}
            tag_ids = raw_item.get("tagIds") or []
            all_tag_ids.update(tag_ids)
        except Exception:
            pass

    unknown = _gdb.get_unknown_tag_ids(list(all_tag_ids))
    if not unknown:
        return 0

    # Resolve via tRPC batch (sync httpx, not async)
    headers = {"Authorization": f"Bearer {_civitai_key()}",
               "Content-Type": "application/json"}
    resolved = []
    chunk_size = 50
    for i in range(0, len(unknown), chunk_size):
        chunk = unknown[i:i + chunk_size]
        batch_input = {str(j): {"json": {"id": tid}} for j, tid in enumerate(chunk)}
        procedure = ",".join(["tag.getById"] * len(chunk))
        try:
            r = httpx.get(f"https://civitai.com/api/trpc/{procedure}",
                          params={"batch": "1", "input": json.dumps(batch_input)},
                          headers=headers, timeout=15)
            if r.status_code == 200:
                results = r.json()
                if isinstance(results, list):
                    for item in results:
                        tag = item.get("result", {}).get("data", {}).get("json", {})
                        if tag.get("id"):
                            resolved.append(tag)
        except Exception:
            pass

    if resolved:
        _gdb.upsert_tags(resolved)
    return len(resolved)


@router.post("/api/admin/civitai/tags/sync")
async def sync_civitai_tags():
    """Sync CivitAI tags: collect all tag IDs from downloaded gallery images,
    resolve unknown ones via CivitAI tRPC batch API, store in local DB.

    Each call is incremental — only resolves tags not already cached.
    Safe to call repeatedly.
    """
    if not _civitai_key():
        raise HTTPException(400, "CIVITAI_API_KEY not configured — set it in Settings")

    # Collect all unique tagIds from gallery images' raw metadata
    all_tag_ids = set()
    conn = _gdb._get_conn()
    rows = conn.execute("SELECT meta_path FROM gallery_images WHERE meta_path IS NOT NULL").fetchall()
    for row in rows:
        meta_file = _gdb.abs_path(row["meta_path"])
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text())
            raw_item = meta.get("raw_item") or {}
            tag_ids = raw_item.get("tagIds") or []
            all_tag_ids.update(tag_ids)
        except Exception:
            pass

    # Find which ones we don't have yet
    unknown = _gdb.get_unknown_tag_ids(list(all_tag_ids))
    if not unknown:
        return JSONResponse({
            "synced": 0, "total_known": _gdb.tag_count(),
            "message": "All tags already cached"
        })

    # Resolve via tRPC batch API.
    # tRPC batch: repeat procedure name N times, input keyed by index.
    # Process in chunks of 50 to avoid URL length limits.
    headers = {"Authorization": f"Bearer {_civitai_key()}",
               "Content-Type": "application/json"}
    resolved = []
    chunk_size = 50
    for i in range(0, len(unknown), chunk_size):
        chunk = unknown[i:i + chunk_size]
        # Build batch input: {"0": {"json": {"id": N}}, "1": {"json": {"id": M}}, ...}
        batch_input = {str(j): {"json": {"id": tid}} for j, tid in enumerate(chunk)}
        procedure = ",".join(["tag.getById"] * len(chunk))
        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            try:
                r = await client.get(
                    f"https://civitai.com/api/trpc/{procedure}",
                    params={"batch": "1", "input": json.dumps(batch_input)})
                if r.status_code == 200:
                    results = r.json()
                    # Response is an array of {result: {data: {json: {id, name, type}}}}
                    if isinstance(results, list):
                        for item in results:
                            tag = item.get("result", {}).get("data", {}).get("json", {})
                            if tag.get("id"):
                                resolved.append(tag)
            except Exception:
                pass

    # Store resolved tags
    if resolved:
        _gdb.upsert_tags(resolved)

    return JSONResponse({
        "synced": len(resolved),
        "total_known": _gdb.tag_count(),
        "unknown_remaining": len(unknown) - len(resolved)
    })


@router.get("/api/admin/civitai/tags")
async def list_civitai_tags():
    """Return all cached CivitAI tags from local database.

    Returns list of {id, name, type, synced_at}, sorted by name.
    Call POST /api/admin/civitai/tags/sync first to populate.
    """
    tags = _gdb.get_all_tags()
    return JSONResponse({"tags": tags, "count": len(tags)})


@router.get("/api/admin/loras/gallery/media/{item_id}")
async def serve_gallery_media(item_id: str):
    """Serve a gallery media file (image or video) from the flat store.

    Looks up the item in SQLite to find its file_path, then serves it.
    The item_id can include an extension (e.g. '123456.mp4') which we strip,
    or it can be just the ID (e.g. '123456').
    """
    # Strip extension if present (frontend may append .mp4 or .jpeg)
    clean_id = item_id.rsplit(".", 1)[0] if "." in item_id else item_id
    if ".." in clean_id or "/" in clean_id:
        raise HTTPException(400, "Invalid id")
    row = _gdb.get_image(clean_id)
    if not row:
        raise HTTPException(404, "Image not found")
    path = _gdb.abs_path(row["file_path"])
    from media import serve_media
    return serve_media(path)


@router.get("/api/admin/loras/gallery/thumb/{item_id}")
async def serve_gallery_thumb(item_id: str):
    """Serve the thumbnail (.thumb.jpg) for a gallery item.

    Both images and videos have thumbnails (300px wide).
    Falls back to original file if thumb not yet generated.
    """
    clean_id = item_id.rsplit(".", 1)[0] if "." in item_id else item_id
    if ".." in clean_id or "/" in clean_id:
        raise HTTPException(400, "Invalid id")
    row = _gdb.get_image(clean_id)
    if not row:
        raise HTTPException(404, "Image not found")
    # Prefer video thumbnail, fall back to original file
    rel = row.get("thumb_path") or row.get("file_path")
    if not rel:
        raise HTTPException(404, "Thumbnail not found")
    path = _gdb.abs_path(rel)
    from media import serve_media
    return serve_media(path)


_CDN = "https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/"


# ── Thumbnail backfill ──────────────────────────────────────────────────────

_thumb_cancel = threading.Event()


def _backfill_thumbs_stream():
    """SSE generator: generate missing thumbnails and fix file sizes for all gallery images.

    Phase 1: Generate .thumb.jpg for images without thumb_path
    Phase 2: Fix file_size=0 and thumb_size=0 for all rows
    """
    import json as _json, time as _time

    _thumb_cancel.clear()
    conn = _gdb._get_conn()

    # Phase 1: missing thumbnails
    rows_no_thumb = conn.execute(
        "SELECT civitai_id, file_path, type FROM gallery_images WHERE thumb_path IS NULL"
    ).fetchall()

    # Phase 2: missing sizes (file_size or thumb_size is 0/NULL but file exists)
    rows_no_size = conn.execute(
        "SELECT civitai_id, file_path, thumb_path FROM gallery_images WHERE file_size = 0 OR file_size IS NULL OR thumb_size = 0 OR thumb_size IS NULL"
    ).fetchall()

    total_thumbs = len(rows_no_thumb)
    total_sizes = len(rows_no_size)
    total = total_thumbs + total_sizes

    if total == 0:
        yield f"event: log\ndata: {_json.dumps('Everything up to date')}\n\n"
        yield f"event: done\ndata: {_json.dumps({'total': 0, 'thumbs_generated': 0, 'sizes_fixed': 0, 'failed': 0})}\n\n"
        return

    yield f"event: log\ndata: {_json.dumps(f'{total_thumbs} missing thumbs, {total_sizes} missing sizes')}\n\n"
    yield f"event: progress\ndata: {_json.dumps({'current': 0, 'total': total, 'thumbs_generated': 0, 'sizes_fixed': 0, 'failed': 0, 'phase': 'thumbs'})}\n\n"

    thumbs_gen = 0
    sizes_fixed = 0
    failed = 0
    processed = 0
    start = _time.time()

    # Phase 1: generate thumbnails
    for row in rows_no_thumb:
        if _thumb_cancel.is_set():
            yield f"event: log\ndata: {_json.dumps('Cancelled by user')}\n\n"
            break

        cid = row["civitai_id"]
        fpath = row["file_path"]
        ftype = row["type"]
        abs_file = _gdb.abs_path(fpath)
        processed += 1

        if not abs_file.exists():
            failed += 1
        else:
            thumb_rel = str(Path(fpath).with_suffix(".thumb.jpg"))
            thumb_abs = _gdb.abs_path(thumb_rel)

            ok = _extract_thumbnail(abs_file) if ftype == "video" else _generate_image_thumb(abs_file)

            if ok and thumb_abs.exists():
                fs = abs_file.stat().st_size
                ts = thumb_abs.stat().st_size
                conn.execute(
                    "UPDATE gallery_images SET thumb_path = ?, thumb_size = ?, file_size = ? WHERE civitai_id = ?",
                    (thumb_rel, ts, fs, cid))
                if thumbs_gen % 20 == 0:
                    conn.commit()
                thumbs_gen += 1
            else:
                failed += 1

        elapsed = _time.time() - start
        rate = processed / elapsed if elapsed > 0 else 0
        eta = int((total - processed) / rate) if rate > 0 else 0
        yield f"event: progress\ndata: {_json.dumps({'current': processed, 'total': total, 'thumbs_generated': thumbs_gen, 'sizes_fixed': sizes_fixed, 'failed': failed, 'rate': round(rate, 1), 'eta_seconds': eta, 'phase': 'thumbs'})}\n\n"

    conn.commit()

    if not _thumb_cancel.is_set():
        yield f"event: log\ndata: {_json.dumps(f'Phase 2: fixing file sizes ({total_sizes} rows)')}\n\n"

    # Phase 2: fix sizes
    for row in rows_no_size:
        if _thumb_cancel.is_set():
            yield f"event: log\ndata: {_json.dumps('Cancelled by user')}\n\n"
            break

        cid = row["civitai_id"]
        fpath = row["file_path"]
        tpath = row["thumb_path"]
        processed += 1

        updates = []
        params = []
        abs_file = _gdb.abs_path(fpath) if fpath else None
        if abs_file and abs_file.exists():
            updates.append("file_size = ?")
            params.append(abs_file.stat().st_size)
        abs_thumb = _gdb.abs_path(tpath) if tpath else None
        if abs_thumb and abs_thumb.exists():
            updates.append("thumb_size = ?")
            params.append(abs_thumb.stat().st_size)

        if updates:
            params.append(cid)
            conn.execute(f"UPDATE gallery_images SET {', '.join(updates)} WHERE civitai_id = ?", params)
            sizes_fixed += 1

        if sizes_fixed % 50 == 0:
            conn.commit()

        elapsed = _time.time() - start
        rate = processed / elapsed if elapsed > 0 else 0
        eta = int((total - processed) / rate) if rate > 0 else 0
        yield f"event: progress\ndata: {_json.dumps({'current': processed, 'total': total, 'thumbs_generated': thumbs_gen, 'sizes_fixed': sizes_fixed, 'failed': failed, 'rate': round(rate, 1), 'eta_seconds': eta, 'phase': 'sizes'})}\n\n"

    conn.commit()

    summary = {'total': total, 'thumbs_generated': thumbs_gen, 'sizes_fixed': sizes_fixed, 'failed': failed, 'cancelled': _thumb_cancel.is_set()}
    yield f"event: log\ndata: {_json.dumps(f'Done: {thumbs_gen} thumbs, {sizes_fixed} sizes fixed, {failed} failed')}\n\n"
    yield f"event: done\ndata: {_json.dumps(summary)}\n\n"


@router.get("/api/admin/loras/gallery/backfill-thumbs")
async def backfill_thumbs_sse():
    """SSE stream: generate thumbnails for all gallery images that don't have one."""
    return StreamingResponse(_backfill_thumbs_stream(), media_type="text/event-stream")


@router.post("/api/admin/loras/gallery/backfill-thumbs/cancel")
async def backfill_thumbs_cancel():
    """Cancel an in-progress thumbnail backfill."""
    _thumb_cancel.set()
    return JSONResponse({"status": "cancelling"})


@router.post("/api/admin/loras/gallery/to-input/{image_id}")
async def gallery_to_input(image_id: str):
    """Copy a gallery image/thumb to ComfyUI input dir for use as workflow input.

    For videos: copies the .thumb.jpg (first frame).
    For images: copies the jpeg directly.
    Returns the filename in ComfyUI's input dir.
    """
    row = _gdb.get_image(image_id)
    if not row:
        raise HTTPException(404, "Image not found in gallery")

    if row.get("ext") == ".mp4" and row.get("thumb_path"):
        src = _gdb.abs_path(row["thumb_path"])
    elif row.get("file_path"):
        src = _gdb.abs_path(row["file_path"])
    else:
        raise HTTPException(404, "No file found for this image")

    if not src.exists():
        raise HTTPException(404, f"File not found on disk")

    from config import COMFY_URL
    filename = f"civitai_{image_id}.jpg"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            with open(src, "rb") as f:
                r = await client.post(
                    f"{COMFY_URL}/upload/image",
                    files={"image": (filename, f, "image/jpeg")},
                    data={"overwrite": "true"},
                )
                r.raise_for_status()
                uploaded = r.json()["name"]
        return {"filename": uploaded}
    except Exception as e:
        raise HTTPException(500, f"Upload to ComfyUI failed: {e}")


# Legacy route: serves preview images (model card thumbnails in catalog list).


def download_single_civitai_image(civitai_image_id: int) -> dict | None:
    """Download a single CivitAI image/video to the gallery store.

    Uses tRPC image.get to fetch metadata + URL, then calls _gallery_download_one
    which handles everything: download, ffmpeg thumbnail, metadata JSON, DB insert.

    Returns the full gallery_images record from DB, or None on failure.
    """
    iid = str(civitai_image_id)

    # Already downloaded?
    if _gdb.image_exists(iid):
        return _gdb.get_image(iid)

    # Fetch image info from tRPC
    key = _civitai_key()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        inp = json.dumps({"json": {"id": civitai_image_id}})
        r = httpx.get("https://civitai.com/api/trpc/image.get",
                       params={"input": inp}, headers=headers, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json().get("result", {}).get("data", {}).get("json", {})
    except Exception:
        return None

    if not data or not data.get("url"):
        return None

    # Build full URL from UUID
    uuid = data["url"]
    img_type = data.get("type", "image")
    ext_hint = ".mp4" if img_type == "video" else ".jpeg"
    if uuid.startswith("http"):
        full_url = uuid
    else:
        full_url = f"{_CDN}{uuid}/original=true/{uuid}{ext_hint}"

    # Build meta dict (same structure as _gallery_thread)
    meta_data = data.get("metadata") or {}
    meta = {
        "civitai_id": data.get("id"),
        "civitai_page": f"https://civitai.com/images/{civitai_image_id}",
        "url": full_url,
        "type": img_type,
        "width": data.get("width"),
        "height": data.get("height"),
        "username": (data.get("user") or {}).get("username", ""),
        "postId": data.get("postId"),
        "postTitle": data.get("postTitle", ""),
        "duration": meta_data.get("duration"),
        "audio": meta_data.get("audio"),
        "baseModel": data.get("baseModel"),
        "createdAt": data.get("createdAt"),
        "stats": data.get("stats"),
        "_source": "community",
    }

    # Download using the existing gallery pipeline
    stop = threading.Event()
    result = _gallery_download_one(iid, full_url, meta, 0, None, True, stop)

    if result == "ok" or result == "skipped":
        return _gdb.get_image(iid)
    return None


@router.post("/api/admin/loras/gallery/download-single/{image_id}")
async def gallery_download_single(image_id: int):
    """Download a single CivitAI image/video to the gallery store by ID."""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(download_single_civitai_image, image_id)
        record = future.result(timeout=120)

    if not record:
        raise HTTPException(502, "Failed to download image from CivitAI")

    return JSONResponse(dict(record))


# These are NOT part of the gallery store — they stay in the old per-model directory.
@router.get("/api/admin/loras/images/{model_id}/previews/{filename}")
async def serve_preview(model_id: str, filename: str):
    """Serve a preview image (used by the LoRA catalog cards, not gallery)."""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "Invalid path")
    # Try new location first, fallback to legacy
    path = IMAGES_DIR / "lookup" / model_id / "previews" / filename
    if not path.exists():
        path = IMAGES_DIR / model_id / "previews" / filename
    from media import serve_media
    return serve_media(path)
