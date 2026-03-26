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
    nsfw: str = "X"
    sort: str = "Newest"
    period: str = "AllTime"
    version_id: int | None = None


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
    api_params = {"nsfw": body.nsfw, "sort": body.sort, "period": body.period,
                   "version_id": body.version_id}
    _gallery_state[model_id] = {
        "status": "downloading", "downloaded": 0, "skipped": 0,
        "total": 0, "_stop": stop, "max_images": max_images,
    }
    threading.Thread(target=_gallery_thread, args=(model_id, stop, api_params),
                     daemon=True).start()
    return JSONResponse({"status": "downloading"})


_GALLERY_MAX_IMAGES = 1000


def _gallery_download_batch(items: list[tuple], dest_dir: Path,
                            state: dict, stop: threading.Event,
                            seen: set) -> bool:
    """Download a batch of (id, url, meta) items. Returns False if stopped.
    Deduplicates by URL-derived UUID (consistent across endpoints)."""
    for iid, url, meta in items:
        if stop.is_set():
            return False
        url_key = _url_to_id(url) or iid
        if url_key in seen:
            continue
        seen.add(url_key)
        ext = ".mp4" if ".mp4" in url else ".jpeg"
        dest = dest_dir / f"{iid}{ext}"
        if dest.exists():
            state["skipped"] += 1
            continue
        if _download_image(url, dest):
            state["downloaded"] += 1
            if meta:
                dest.with_suffix(".json").write_text(
                    json.dumps(meta, indent=2, ensure_ascii=False))
    return True


def _gallery_thread(model_id: int, stop: threading.Event, api_params: dict):
    """Download model card images + community images for a CivitAI model."""
    state = _gallery_state[model_id]
    base_dir = IMAGES_DIR / str(model_id) / "gallery"
    card_dir = base_dir / "card"
    community_dir = base_dir / "community"
    card_dir.mkdir(parents=True, exist_ok=True)
    community_dir.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {CIVITAI_API_KEY}"} if CIVITAI_API_KEY else {}
    max_community = state.get("max_images", 200)

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
                    "width": img.get("width"), "height": img.get("height")}
            if img.get("id"):
                meta["civitai_page"] = f"https://civitai.com/images/{img['id']}"
            card_imgs.append((str(iid), url, meta))

    state["total"] = len(card_imgs) + max_community
    seen: set[str] = set()

    if not _gallery_download_batch(card_imgs, card_dir, state, stop, seen):
        state["status"] = "stopped"
        return

    # ── Phase 2: community images (capped by max_community) ──
    community_downloaded = 0
    cursor = None
    state["pages_fetched"] = 0

    while community_downloaded < max_community:
        if stop.is_set():
            state["status"] = "stopped"
            return
        params: dict = {"modelId": model_id, "limit": 200,
                        "nsfw": api_params.get("nsfw", "X"),
                        "sort": api_params.get("sort", "Newest"),
                        "period": api_params.get("period", "AllTime")}
        if api_params.get("version_id"):
            params["modelVersionId"] = api_params["version_id"]
        if cursor:
            params["cursor"] = cursor
        try:
            r = httpx.get("https://civitai.com/api/v1/images",
                          params=params, timeout=30, headers=headers)
            if r.status_code != 200:
                break
            data = r.json()
        except Exception:
            break
        state["pages_fetched"] = state.get("pages_fetched", 0) + 1

        page_items = data.get("items", [])
        if not page_items:
            break

        batch = []
        for img in page_items:
            if community_downloaded >= max_community:
                break
            url = img.get("url", "")
            if not url:
                continue
            url_key = _url_to_id(url)
            if url_key and url_key in seen:
                continue
            iid = str(img.get("id") or url_key)
            if not iid:
                continue
            meta = {
                "civitai_id": img.get("id"),
                "civitai_page": f"https://civitai.com/images/{img['id']}" if img.get("id") else None,
                "url": url,
                "type": img.get("type", "image"),
                "width": img.get("width"), "height": img.get("height"),
                "username": img.get("username"),
                "createdAt": img.get("createdAt"),
                "stats": img.get("stats"),
                "raw_meta": img.get("meta"),
            }
            batch.append((iid, url, meta))
            community_downloaded += 1

        if not _gallery_download_batch(batch, community_dir, state, stop, seen):
            state["status"] = "stopped"
            return

        cursor = (data.get("metadata") or {}).get("nextCursor")
        if not cursor:
            break

    # Adjust total to actual count
    state["total"] = len(seen)
    state["status"] = "done"
    _events.emit("lora.gallery.done",
                 f"Gallery done for {model_id}: {state['downloaded']} new, {state['skipped']} skipped",
                 severity="success", data={"model_id": model_id})


@router.get("/api/admin/loras/{model_id}/gallery")
async def gallery_status(model_id: int):
    """Get gallery download status and list of images."""
    state = _gallery_state.get(model_id, {})

    def _list_images(dirpath: Path) -> list:
        if not dirpath.is_dir():
            return []
        result = []
        for f in sorted(dirpath.iterdir()):
            if f.suffix not in (".jpeg", ".mp4"):
                continue
            meta = {}
            mf = f.with_suffix(".json")
            if mf.exists():
                try:
                    meta = json.loads(mf.read_text())
                except Exception:
                    pass
            result.append({"id": f.stem, "ext": f.suffix, "meta": meta})
        return result

    base = IMAGES_DIR / str(model_id)
    return JSONResponse({
        "status": state.get("status", "idle"),
        "downloaded": state.get("downloaded", 0),
        "skipped": state.get("skipped", 0),
        "total": state.get("total"),
        "pages_fetched": state.get("pages_fetched", 0),
        "counted": state.get("counted", 0),
        "previews": _list_images(base / "previews"),
        "gallery_card": _list_images(base / "gallery" / "card"),
        "gallery_community": _list_images(base / "gallery" / "community"),
    })


@router.delete("/api/admin/loras/{model_id}/gallery")
async def gallery_delete(model_id: int):
    """Delete all gallery images for a model."""
    import shutil
    gallery_dir = IMAGES_DIR / str(model_id) / "gallery"
    count = 0
    if gallery_dir.is_dir():
        count = sum(1 for f in gallery_dir.rglob("*") if f.suffix in (".jpeg", ".mp4"))
        shutil.rmtree(gallery_dir)
    if model_id in _gallery_state:
        del _gallery_state[model_id]
    return JSONResponse({"deleted": count})


@router.get("/api/admin/loras/images/{model_id}/{img_type}/{filename}")
async def serve_image(model_id: str, img_type: str, filename: str):
    """Serve a preview or gallery image with path traversal protection."""
    _type_dirs = {
        "previews": "previews",
        "gallery-card": "gallery/card",
        "gallery-community": "gallery/community",
    }
    if img_type not in _type_dirs:
        raise HTTPException(400, "Invalid image type")
    for part in (model_id, filename):
        if ".." in part or "/" in part or "\\" in part:
            raise HTTPException(400, "Invalid path")
    path = IMAGES_DIR / model_id / _type_dirs[img_type] / filename
    if not path.exists():
        raise HTTPException(404, "Image not found")
    media = "video/mp4" if filename.endswith(".mp4") else "image/jpeg"
    return FileResponse(path, media_type=media)
