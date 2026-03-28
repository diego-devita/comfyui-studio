"""ComfyUI Studio — Model + LoRA endpoints (list, download, delete, batch, sync, import, metadata)."""

import asyncio
import json
import os
import re
import threading
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from config import MODELS_BASE, MODELS_JSON, REPO_DIR
import catalogs as _catalogs
from catalogs import (
    _reload_models,
    _find_model, _all_categories, _build_catalog_response,
)
from download import (
    _download_state, _enqueue_download, _clean_state, _get_download_url,
)
from events import _events

router = APIRouter()


# ── Request schemas ──────────────────────────────────────────────────────────


class BatchDownloadRequest(BaseModel):
    filenames: list[str]


# ── Disk usage helpers ───────────────────────────────────────────────────────

async def _get_disk_free_bytes() -> int:
    """Get free disk space in bytes. Uses system_api's centralized disk stats."""
    from system_api import _get_disk_stats
    _total, _used, free = await _get_disk_stats()
    return free


# ── Civitai Metadata Fetcher ──────────────────────────────────────────────────

_metadata_state: dict = {}
_activity_log: list = []


def _log_activity(message: str, level: str = "info"):
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=1)))
    _activity_log.append({"time": now.strftime("%H:%M:%S"), "message": message, "level": level})


def _extract_civitai_version_id(url: str) -> str:
    match = re.search(r'civitai\.com/api/download/models/(\d+)', url)
    return match.group(1) if match else ""


def _clean_civitai_name(model_name: str, version_name: str, base_model: str, fp: str = "") -> str:
    """Build clean display name from Civitai metadata."""
    # Strip CJK characters
    model_name = re.sub(r'[\u4e00-\u9fff\u3000-\u303f]+', '', model_name).strip()
    version_name = re.sub(r'[\u4e00-\u9fff\u3000-\u303f]+', '', version_name).strip()

    # Strip emojis
    _emoji_re = re.compile(r'[\U0001f000-\U0001ffff\u2600-\u27bf\ufe00-\ufeff]+')
    model_name = _emoji_re.sub('', model_name).strip()
    version_name = _emoji_re.sub('', version_name).strip()

    version_name = re.sub(r'\([^)]{12,}\)', '', version_name).strip()
    version_name = version_name.replace('(', '').replace(')', '').strip()

    ver_num_m = re.match(r'v?(\d+(?:\.\d+)*)', version_name, re.IGNORECASE)
    if ver_num_m:
        full_match = ver_num_m.group(0)
        bare_number = ver_num_m.group(1)
        mn_stripped = model_name.rstrip()
        for pat in [full_match, bare_number]:
            if mn_stripped.lower().endswith(pat.lower()):
                model_name = mn_stripped[:len(mn_stripped) - len(pat)].rstrip(' -_')
                break

    ver_lower = version_name.lower().replace('_', ' ')
    mn_lower = model_name.lower().replace('_', ' ')
    if ver_lower.startswith(mn_lower):
        version_name = version_name[len(model_name):].lstrip(' _-')
    else:
        model_words = set(mn_lower.split())
        ver_tokens = version_name.split()
        deduped = []
        for t in ver_tokens:
            t_low = t.lower()
            t_stripped = t_low.lstrip('v')
            skip = t_low in model_words or (t_stripped and t_stripped in model_words)
            if not skip and len(t_low) >= 5:
                for mw in model_words:
                    if len(mw) >= 5 and (mw.startswith(t_low) or t_low.startswith(mw)):
                        skip = True
                        break
            if not skip:
                deduped.append(t)
        version_name = ' '.join(deduped)

    name = model_name
    if version_name:
        name = f"{name} {version_name}"

    bracket_parts = []
    if base_model:
        bracket_parts.append(base_model)
    if fp and fp.upper() not in ('NONE', ''):
        bracket_parts.append(fp.upper())
    if bracket_parts:
        name = f"{name} [{' '.join(bracket_parts)}]"

    name = re.sub(r'\s+', ' ', name).strip()
    return name


def _fetch_metadata_batch(items: list):
    """Background thread: fetch metadata for all Civitai models sequentially."""
    import httpx as _hx

    _reload_models()
    any_updated = False

    for fname, vid in items:
        if not vid or vid == "None":
            _metadata_state[fname] = {"status": "done"}
            continue
        _metadata_state[fname] = {"status": "fetching_metadata"}
        _log_activity(f"Fetching metadata for {fname}...")

        try:
            r1 = _hx.get(f"https://civitai.com/api/v1/model-versions/{vid}", timeout=15)
            r1.raise_for_status()
            ver_data = r1.json()

            base_model_civitai = ver_data.get("baseModel", "")
            trained_words = ver_data.get("trainedWords", [])
            model_info = ver_data.get("model", {})
            model_id = ver_data.get("modelId")
            nsfw = model_info.get("nsfw", False)
            model_type = model_info.get("type", "")
            version_name = ver_data.get("name", "")
            updated_at = ver_data.get("updatedAt", "")
            file_id = None
            file_fp = ""
            matched_file = None
            for vf in ver_data.get("files", []):
                if vf.get("name") == fname:
                    matched_file = vf
                    break
            if not matched_file and ver_data.get("files"):
                matched_file = ver_data["files"][0]
            if matched_file:
                file_id = matched_file.get("id")
                file_fp = (matched_file.get("metadata") or {}).get("fp", "")

            civitai_tags = []
            if model_id:
                try:
                    r2 = _hx.get(f"https://civitai.com/api/v1/models/{model_id}", timeout=15)
                    if r2.status_code == 200:
                        civitai_tags = r2.json().get("tags", [])
                except Exception:
                    pass

            changes = []
            for cat in _catalogs._models_data.get("categories", []):
                for m in cat.get("models", []):
                    if m.get("file") == fname:
                        if base_model_civitai:
                            if base_model_civitai != m.get("civitai_base_model"):
                                m["civitai_base_model"] = base_model_civitai
                                changes.append(f"civitai_base_model={base_model_civitai}")
                            if not m.get("base_model"):
                                m["base_model"] = base_model_civitai
                                changes.append(f"base_model={base_model_civitai}")
                        if civitai_tags and civitai_tags != m.get("civitai_tags"):
                            m["civitai_tags"] = civitai_tags
                            changes.append(f"+{len(civitai_tags)} civitai_tags")
                        if trained_words and trained_words != m.get("trainedWords"):
                            m["trainedWords"] = trained_words
                            changes.append(f"+{len(trained_words)} trainedWords")
                        if version_name and version_name != m.get("civitai_version"):
                            m["civitai_version"] = version_name
                            changes.append(f"version={version_name}")
                        if model_id:
                            m["civitai_model_id"] = model_id
                        if file_id:
                            m["civitai_file_id"] = file_id
                        if model_type:
                            m["civitai_type"] = model_type
                        if file_fp:
                            m["civitai_fp"] = file_fp
                        if updated_at:
                            m["lastModified"] = updated_at

                        civitai_model_name = model_info.get("name", "")
                        if civitai_model_name and not m.get("name_locked"):
                            new_name = _clean_civitai_name(
                                civitai_model_name, version_name,
                                base_model_civitai, file_fp
                            )
                            old_name = m.get("name", "")
                            if new_name != old_name:
                                m["name"] = new_name
                                changes.append(f"name={new_name}")

                        tags = m.get("tags", [])
                        if nsfw and "nsfw" not in tags:
                            tags.append("nsfw")
                            changes.append("+nsfw")
                        elif not nsfw and "nsfw" in tags:
                            tags.remove("nsfw")
                            changes.append("-nsfw")
                        m["tags"] = tags

                        any_updated = True
                        break

            _metadata_state[fname] = {"status": "done"}
            summary = ", ".join(changes) if changes else "no changes"
            _log_activity(f"OK \u2014 {fname}: {summary}", "ok")
            _events.emit("model.metadata.fetched", f"Metadata: {fname} ({summary})",
                         severity="success" if changes else "info",
                         data={"filename": fname, "changes": changes})

        except Exception as e:
            _metadata_state[fname] = {"status": "error", "error": str(e)}
            _log_activity(f"ERROR \u2014 {fname}: {str(e)}", "error")
            _events.emit("model.metadata.failed", f"Metadata failed: {fname}",
                         severity="error", data={"filename": fname, "error": str(e)})

    # Fetch HuggingFace dates
    for cat in _catalogs._models_data.get("categories", []):
        for m in cat.get("models", []):
            if m.get("source") != "huggingface" or not m.get("hf_repo"):
                continue
            if m.get("lastModified"):
                continue
            fname = m.get("file", "")
            _metadata_state[fname] = {"status": "fetching_metadata"}
            _log_activity(f"Fetching HF date for {fname}...")
            try:
                r = _hx.get(f"https://huggingface.co/api/models/{m['hf_repo']}", timeout=15)
                if r.status_code == 200:
                    hf_data = r.json()
                    last_modified = hf_data.get("lastModified", "")
                    if last_modified:
                        m["lastModified"] = last_modified
                        any_updated = True
                        _log_activity(f"OK \u2014 {fname}: lastModified={last_modified}", "ok")
                    else:
                        _log_activity(f"OK \u2014 {fname}: no date found", "ok")
                _metadata_state[fname] = {"status": "done"}
            except Exception as e:
                _metadata_state[fname] = {"status": "error", "error": str(e)}
                _log_activity(f"ERROR \u2014 {fname}: {str(e)}", "error")

    if any_updated:
        MODELS_JSON.parent.mkdir(parents=True, exist_ok=True)
        MODELS_JSON.write_text(json.dumps(_catalogs._models_data, indent=2, ensure_ascii=False))
        _log_activity("Saved models.json", "ok")

    total = len(items)
    done = sum(1 for fname, _ in items if _metadata_state.get(fname, {}).get("status") == "done")
    failed = sum(1 for fname, _ in items if _metadata_state.get(fname, {}).get("status") == "error")
    _events.emit("model.metadata.batch.completed",
                 f"Metadata fetch completed: {done}/{total} ok" + (f", {failed} failed" if failed else ""),
                 severity="success" if not failed else "warning",
                 data={"total": total, "done": done, "failed": failed})


# ── Model management endpoints ───────────────────────────────────────────────


@router.get("/api/admin/models")
async def models_list():
    result_categories = _build_catalog_response(_catalogs._models_data, MODELS_BASE, _download_state)

    # Compute stats
    queued_count = sum(1 for s in _download_state.values() if s.get("status") == "queued")
    downloading_count = sum(1 for s in _download_state.values() if s.get("status") == "downloading")
    fetching_count = sum(1 for s in _metadata_state.values() if s.get("status") in ("queued_metadata", "fetching_metadata"))
    global_speed = sum(s.get("speed", 0) for s in _download_state.values() if s.get("status") == "downloading")

    try:
        models_bytes = sum(m.get("on_disk_bytes", 0) for cat in result_categories for m in cat["models"])
        free_bytes = await _get_disk_free_bytes()
    except Exception:
        models_bytes = 0
        free_bytes = 0

    present_count = sum(1 for cat in result_categories for m in cat["models"] if m["status"] == "present")
    total_count = sum(len(cat["models"]) for cat in result_categories)

    return JSONResponse({
        "version": _catalogs._models_data.get("version", 0),
        "date": _catalogs._models_data.get("date", ""),
        "stats": {
            "queued_count": queued_count,
            "downloading_count": downloading_count,
            "fetching_count": fetching_count,
            "present_count": present_count,
            "total_count": total_count,
            "global_speed": global_speed,
            "models_bytes": models_bytes,
            "free_bytes": free_bytes,
        },
        "categories": result_categories,
    })


@router.get("/api/admin/loras")
async def loras_list():
    """List LoRAs catalog with download/presence status."""
    ld = _catalogs._loras_data
    result_categories = _build_catalog_response(ld, MODELS_BASE, _download_state)

    present_count = sum(1 for cat in result_categories for m in cat["models"] if m["status"] == "present")
    total_count = sum(len(cat["models"]) for cat in result_categories)

    lora_filenames = {m["file"] for cat in ld.get("categories", []) for m in cat.get("models", [])}
    queued_count = sum(1 for fn, s in _download_state.items() if fn in lora_filenames and s.get("status") == "queued")
    downloading_count = sum(1 for fn, s in _download_state.items() if fn in lora_filenames and s.get("status") == "downloading")
    global_speed = sum(s.get("speed", 0) for fn, s in _download_state.items() if fn in lora_filenames and s.get("status") == "downloading")

    try:
        models_bytes = sum(m.get("on_disk_bytes", 0) for cat in result_categories for m in cat["models"])
        free_bytes = await _get_disk_free_bytes()
    except Exception:
        models_bytes = 0
        free_bytes = 0

    return JSONResponse({
        "version": ld.get("version", 0),
        "date": ld.get("date", ""),
        "stats": {
            "queued_count": queued_count,
            "downloading_count": downloading_count,
            "present_count": present_count,
            "total_count": total_count,
            "global_speed": global_speed,
            "models_bytes": models_bytes,
            "free_bytes": free_bytes,
        },
        "categories": result_categories,
    })


@router.post("/api/admin/models/download/{filename}")
async def models_download(filename: str):
    model = _find_model(filename)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{filename}' not found in catalog")

    state = _download_state.get(filename, {})
    if state.get("status") in ("downloading", "queued"):
        return JSONResponse({"status": state["status"], "file": filename})

    _enqueue_download(model, source="manual")
    return JSONResponse({"status": "queued", "file": filename})


@router.post("/api/admin/models/download-batch")
async def models_download_batch(body: BatchDownloadRequest):
    queued = []
    skipped = []

    for filename in body.filenames:
        model = _find_model(filename)
        if not model:
            skipped.append(filename)
            continue

        state = _download_state.get(filename, {})
        if state.get("status") in ("downloading", "queued"):
            skipped.append(filename)
            continue

        _enqueue_download(model, source="batch")
        queued.append(filename)

    return JSONResponse({"queued": queued, "skipped": skipped})


@router.get("/api/admin/models/status")
async def models_status():
    async def event_stream():
        while True:
            downloads = {}
            for filename, state in _download_state.items():
                downloads[filename] = _clean_state(state)
            payload = json.dumps({"downloads": downloads, "timestamp": time.time()})
            yield f"data: {payload}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/api/admin/models/{filename}")
async def models_delete(filename: str):
    _reload_models()
    model = _find_model(filename)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{filename}' not found in catalog")

    dest_path = Path(MODELS_BASE) / model["dest"] / filename

    if dest_path.exists():
        dest_path.unlink()

    if filename in _download_state:
        state = _download_state[filename]
        if state.get("status") in ("error", "done"):
            del _download_state[filename]

    _events.emit("model.deleted", f"Model deleted: {filename}", data={"filename": filename})
    return JSONResponse({"status": "deleted", "file": filename})


@router.post("/api/admin/models/import")
async def import_models(file: UploadFile = File(...)):
    """Import models from a JSON file. Adds new models with 'imported' tag."""
    try:
        content = await file.read()
        imported_data = json.loads(content)
    except Exception as e:
        raise HTTPException(400, f"Invalid JSON: {str(e)}")

    _reload_models()

    existing_files = set()
    for cat in _catalogs._models_data.get("categories", []):
        for m in cat.get("models", []):
            existing_files.add(m.get("file", ""))

    cat_map = {cat["id"]: cat for cat in _catalogs._models_data.get("categories", [])}

    added = []
    skipped = []

    for imp_cat in imported_data.get("categories", []):
        cat_id = imp_cat.get("id", "")
        for m in imp_cat.get("models", []):
            fname = m.get("file", "")
            if not fname or fname in existing_files:
                skipped.append(fname)
                continue

            tags = m.get("tags", [])
            if "imported" not in tags:
                tags.append("imported")
            m["tags"] = tags

            if cat_id in cat_map:
                cat_map[cat_id]["models"].append(m)
            else:
                new_cat = {"id": cat_id, "name": imp_cat.get("name", cat_id), "models": [m]}
                _catalogs._models_data["categories"].append(new_cat)
                cat_map[cat_id] = new_cat

            existing_files.add(fname)
            added.append(fname)

    if added:
        _catalogs._models_data["version"] = _catalogs._models_data.get("version", 0) + 1
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone(timedelta(hours=1)))
        _catalogs._models_data["date"] = now.strftime("%Y-%m-%d %H:%M")

        MODELS_JSON.parent.mkdir(parents=True, exist_ok=True)
        MODELS_JSON.write_text(json.dumps(_catalogs._models_data, indent=2, ensure_ascii=False))

    return {"added": added, "skipped": skipped, "total_added": len(added)}


@router.post("/api/admin/models/fetch-metadata")
async def fetch_all_metadata():
    """Queue metadata fetch for all models (Civitai + HuggingFace)."""
    _reload_models()
    queued = []
    for cat in _all_categories():
        for m in cat.get("models", []):
            fname = m.get("file", "")
            if not fname:
                continue
            if fname in _metadata_state and _metadata_state[fname].get("status") in ("queued_metadata", "fetching_metadata"):
                continue
            vid = str(m.get("civitai_version_id", ""))
            hf_repo = m.get("hf_repo", "")
            if (vid and vid != "None") or hf_repo:
                _metadata_state[fname] = {"status": "queued_metadata"}
                queued.append((fname, vid))

    if queued:
        _log_activity(f"Queued {len(queued)} models for metadata fetch")
        threading.Thread(target=_fetch_metadata_batch, args=(queued,), daemon=True).start()

    return {"queued": len(queued), "files": [q[0] for q in queued]}


@router.get("/api/admin/models/metadata-status")
async def metadata_status():
    return _metadata_state


@router.get("/api/admin/activity-log")
async def get_activity_log():
    return _activity_log


@router.post("/api/admin/activity-log/clear")
async def clear_activity_log():
    _activity_log.clear()
    return {"status": "cleared"}


@router.post("/api/admin/models/sync")
async def sync_models():
    """Sync models.json from the local git repo clone."""
    try:
        src = REPO_DIR / "catalogs" / "models.json"
        if not src.exists():
            raise HTTPException(500, "Repo clone not found — run Check for Updates first")

        remote = json.loads(src.read_text())
        remote_version = remote.get("version", 0)
        local_version = _catalogs._models_data.get("version", 0)

        if type(remote_version) != type(local_version) or remote_version > local_version:
            MODELS_JSON.parent.mkdir(parents=True, exist_ok=True)
            MODELS_JSON.write_text(json.dumps(remote, indent=2, ensure_ascii=False))
            _reload_models()
            return {
                "status": "updated",
                "old_version": local_version,
                "new_version": remote_version,
                "new_date": remote.get("date", ""),
            }
        else:
            return {
                "status": "up_to_date",
                "version": local_version,
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Sync failed: {str(e)}")


@router.get("/api/admin/loras/compatible/{base_model}")
async def list_compatible_loras(base_model: str):
    """List LoRA pairs compatible with a given base model."""
    pairs = {}
    for cat in _all_categories():
        for m in cat.get("models", []):
            if m.get("pair_id") and (base_model == "all" or m.get("base_model") == base_model):
                pid = m["pair_id"]
                if pid not in pairs:
                    pairs[pid] = {"pair_id": pid, "name": "", "high": None, "low": None, "both": None}
                role = m.get("pair_role", "both")
                pairs[pid][role] = m["file"]
                if not pairs[pid]["name"]:
                    name = m["name"]
                    for suffix in [" High Noise", " Low Noise", " LoRA", " (Kijai)", " (WAN 2.1 I2V 14B)"]:
                        name = name.replace(suffix, "")
                    pairs[pid]["name"] = name.strip()
    return list(pairs.values())
