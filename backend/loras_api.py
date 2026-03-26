"""ComfyUI Studio — LoRA CivitAI integration: lookup, add, gallery, image serving."""

import json
import re
import threading
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel

from config import CATALOGS_DIR, LORAS_JSON, CIVITAI_API_KEY, MODELS_BASE
import catalogs
from download import _enqueue_download
from events import _events
from models_api import _clean_civitai_name

router = APIRouter()

IMAGES_DIR = CATALOGS_DIR / ".images"

# Gallery store: flat sharded media + SQLite index
# Imported here so download workers can use it.
# The actual DB init happens at startup via events.py.
import gallery_db as _gdb

_gallery_state: dict = {}


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
    if not image_id or not CIVITAI_API_KEY:
        return None
    try:
        params = json.dumps({"json": {"id": image_id, "authed": True}})
        r = httpx.get(f"https://civitai.com/api/trpc/image.getGenerationData?input={params}",
                      headers={"Authorization": f"Bearer {CIVITAI_API_KEY}",
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
    if not CIVITAI_API_KEY:
        raise HTTPException(403, "CIVITAI_API_KEY not configured")
    try:
        model_id, version_id = _parse_civitai_url(body.url)
    except ValueError as e:
        raise HTTPException(400, str(e))

    headers = {"Authorization": f"Bearer {CIVITAI_API_KEY}"}
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
        _enqueue_download(entry)

        for img in ver.get("images", []):
            url = img.get("url", "")
            if url:
                iid = img.get("id") or _url_to_id(url)
                meta = meta_lookup.get(img.get("id"), meta_lookup.get(iid, {}))
                images_to_dl.append((body.model_id, iid, url, meta))

    if added:
        loras_data["version"] = loras_data.get("version", 0) + 1
        from datetime import datetime, timezone, timedelta
        loras_data["date"] = datetime.now(timezone(timedelta(hours=1))).strftime("%Y-%m-%d %H:%M")
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
        dest = IMAGES_DIR / str(model_id) / "previews" / f"{image_id}.jpeg"
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
    if not CIVITAI_API_KEY:
        raise HTTPException(403, "CIVITAI_API_KEY not configured")

    st = _gallery_state.get(model_id)
    if st and st.get("status") == "downloading":
        return JSONResponse({"status": "downloading", "message": "Already running"})

    max_images = 200
    if body.action.startswith("start:"):
        try:
            max_images = int(body.action.split(":")[1])
        except (ValueError, IndexError):
            pass
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
    rel_thumb = _gdb.thumb_path_for(source, model_id, iid) if ext == ".mp4" else None
    rel_meta = _gdb.meta_path_for(source, model_id, iid)
    dest = _gdb.abs_path(rel_file)

    # Skip if file already on disk (e.g. previous download that wasn't in DB)
    if dest.exists() and dest.stat().st_size > 0:
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

    # Extract thumbnail from first video frame for gallery display.
    # Videos in the gallery are shown as static <img> thumbnails to avoid
    # loading heavy <video> elements in the DOM.
    has_thumb = False
    if ext == ".mp4":
        _extract_thumbnail(dest)
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
    headers = {"Authorization": f"Bearer {CIVITAI_API_KEY}"} if CIVITAI_API_KEY else {}
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
                meta["civitai_page"] = f"https://civitai.com/images/{img['id']}?token={CIVITAI_API_KEY}"
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
                "civitai_page": f"https://civitai.com/images/{img['id']}?token={CIVITAI_API_KEY}" if img.get("id") else None,
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
async def gallery_status(model_id: int, version_id: int | None = None):
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
        card_list = _gdb.list_images_by_model(model_id, source="original")
        comm_list = _gdb.list_images_by_version(version_id, source="community")
    else:
        card_list = _gdb.list_images_by_model(model_id, source="original")
        comm_list = _gdb.list_images_by_model(model_id, source="community")

    # Convert DB rows to the format the frontend expects.
    # Each item needs: id, ext, meta (light), createdAt, has_thumb
    def _format(row: dict) -> dict:
        return {
            "id": row["civitai_id"],
            "ext": row["ext"],
            "has_thumb": bool(row.get("thumb_path")),
            "createdAt": row.get("created_at", ""),
            "meta": {
                "civitai_id": row.get("civitai_id"),
                "civitai_page": f"https://civitai.com/images/{row['civitai_id']}?token={CIVITAI_API_KEY}" if row.get("civitai_id", "").isdigit() else None,
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
async def gallery_delete(model_id: int):
    """Delete all gallery images for a model.

    Removes DB records first (returns list of file paths), then deletes
    the actual files from the flat store. DB deletion cascades to
    image_versions automatically via ON DELETE CASCADE.
    """
    count, paths = _gdb.delete_by_model(model_id)
    # Delete actual files from disk
    for rel_path in paths:
        full = _gdb.abs_path(rel_path)
        if full.exists():
            full.unlink()
    if model_id in _gallery_state:
        del _gallery_state[model_id]
    return JSONResponse({"deleted": count})



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
    if not path.exists():
        raise HTTPException(404, "File missing from disk")
    media = "video/mp4" if row["ext"] == ".mp4" else "image/jpeg"
    return FileResponse(path, media_type=media)


@router.get("/api/admin/loras/gallery/thumb/{item_id}")
async def serve_gallery_thumb(item_id: str):
    """Serve a video thumbnail from the flat store.

    Returns the .thumb.jpg extracted by ffmpeg during download.
    If no thumbnail exists, returns 404 (frontend shows a grey placeholder).
    """
    clean_id = item_id.rsplit(".", 1)[0] if "." in item_id else item_id
    if ".." in clean_id or "/" in clean_id:
        raise HTTPException(400, "Invalid id")
    row = _gdb.get_image(clean_id)
    if not row or not row.get("thumb_path"):
        raise HTTPException(404, "Thumbnail not found")
    path = _gdb.abs_path(row["thumb_path"])
    if not path.exists():
        raise HTTPException(404, "Thumbnail file missing")
    return FileResponse(path, media_type="image/jpeg")


# Legacy route: serves preview images (model card thumbnails in catalog list).
# These are NOT part of the gallery store — they stay in the old per-model directory.
@router.get("/api/admin/loras/images/{model_id}/previews/{filename}")
async def serve_preview(model_id: str, filename: str):
    """Serve a preview image (used by the LoRA catalog cards, not gallery)."""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "Invalid path")
    path = IMAGES_DIR / model_id / "previews" / filename
    if not path.exists():
        raise HTTPException(404, "Preview not found")
    media = "video/mp4" if filename.endswith(".mp4") else "image/jpeg"
    return FileResponse(path, media_type=media)
