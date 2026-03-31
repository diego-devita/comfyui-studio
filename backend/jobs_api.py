"""ComfyUI Studio — Job queue/history, asset management, node list/install, output downloads."""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse

from config import COMFY_URL, COMFYUI_DIR, ASSETS_INPUT_DIR, ASSETS_OUTPUT_DIR, DEV_MODE, _now_rome
from events import _events
from runner import _exec_progress, _save_job, _pick_best_output, _start_ws_listener
from workflows import _make_input_filename
import db

router = APIRouter()


# ── Queue ────────────────────────────────────────────────────────────────────


@router.get("/api/admin/queue")
async def list_queue():
    """List active (running/queued) jobs with real-time progress."""
    jobs = db.list_active_jobs()

    # Enrich with in-memory progress
    for job in jobs:
        pid = job.get("prompt_id")
        prog = _exec_progress.get(pid, {})
        job["progress"] = {
            "status": prog.get("status") or job.get("status"),
            "node_title": prog.get("node_title", ""),
            "node_type": prog.get("node_type", ""),
            "step": prog.get("step", 0),
            "total_steps": prog.get("total_steps", 0),
            "nodes_done": prog.get("nodes_done", 0),
            "total_nodes": prog.get("total_nodes", 0),
            "effective_total": prog.get("effective_total", prog.get("total_nodes", 0)),
            "cached_count": prog.get("cached_count", 0),
            "percent": prog.get("percent", 0),
            "eta_seconds": prog.get("eta_seconds"),
            "step_rate": prog.get("step_rate"),
            "node_outputs": prog.get("node_outputs", {}),
        }

    return jobs


# ── History ──────────────────────────────────────────────────────────────────


@router.get("/api/admin/history")
async def list_history():
    """List completed/error/stalled job records, newest first."""
    return db.list_history()


@router.post("/api/admin/history/delete")
async def delete_history_jobs(request: Request):
    """Delete job records and their output files."""
    body = await request.json()
    prompt_ids = list(set(body.get("prompt_ids", [])))
    if not prompt_ids:
        return {"deleted": []}

    deleted_items = db.delete_jobs(prompt_ids)
    deleted_pids = []
    for item in deleted_items:
        pid = item["prompt_id"]
        output_dir_name = item.get("output_dir")
        if output_dir_name:
            out_dir = ASSETS_OUTPUT_DIR / output_dir_name
            if out_dir.exists() and out_dir.is_dir():
                shutil.rmtree(out_dir)
        deleted_pids.append(pid)
        _events.emit("job.deleted", f"Job deleted: {pid[:12]}", data={"prompt_id": pid})

    return {"deleted": deleted_pids}


@router.post("/api/admin/history/retry")
async def retry_job(request: Request):
    """Re-queue a stalled/error job with the same params and resolved seeds."""
    body = await request.json()
    source_pid = body.get("prompt_id")
    if not source_pid:
        raise HTTPException(400, "prompt_id required")

    source_job = db.get_job(source_pid)
    if not source_job:
        raise HTTPException(404, "Job not found")

    wf_id = source_job.get("workflow_id")
    if not wf_id:
        raise HTTPException(400, "Job has no workflow_id")

    params = dict(source_job.get("params", {}))
    seeds = source_job.get("seeds", {})
    for seed_key, seed_val in seeds.items():
        if seed_key in params:
            params[seed_key] = seed_val
        if seed_key.startswith("scene_") and "scenes" in params:
            try:
                idx = int(seed_key.split("_")[1]) - 1
                if 0 <= idx < len(params["scenes"]):
                    params["scenes"][idx]["seed"] = seed_val
            except (ValueError, IndexError):
                pass

    input_img = source_job.get("input_image")
    if input_img:
        params["_existing_input_image"] = input_img

    # Lazy import to avoid circular dependency
    from runner import _build_workflow

    form_params = params
    workflow, manifest, used_seeds, output_dir = await _build_workflow(
        wf_id, form_params, None,
    )

    from datetime import datetime, timezone, timedelta
    now = _now_rome()
    client_id = uuid.uuid4().hex
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{COMFY_URL}/prompt",
                json={"prompt": workflow, "client_id": client_id},
            )
            data = r.json()
    except Exception as e:
        raise HTTPException(500, f"ComfyUI unreachable: {str(e)}")

    if "error" in data:
        raise HTTPException(500, str(data["error"]))

    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise HTTPException(500, "No prompt_id returned")

    input_image_name = input_img

    save_params = {k: v for k, v in form_params.items() if not k.startswith("_")}
    job_record = {
        "prompt_id": prompt_id,
        "workflow_id": wf_id,
        "workflow_name": manifest.get("name", wf_id),
        "output_dir": output_dir,
        "status": "queued",
        "queued_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "started_at": None,
        "finished_at": None,
        "duration": None,
        "input_image": input_image_name,
        "params": save_params,
        "seeds": used_seeds,
        "output": None,
        "error": None,
        "retry_of": source_pid,
    }
    _save_job(job_record)

    _exec_progress[prompt_id] = {
        "status": "queued", "node_title": "", "node_id": "", "node_type": "",
        "workflow_name": manifest.get("name", wf_id), "workflow_id": wf_id,
        "step": 0, "total_steps": 0,
        "nodes_done": 0, "total_nodes": len(workflow),
        "effective_total": len(workflow), "cached_count": 0,
        "percent": 0, "eta_seconds": None, "step_rate": None,
        "preview_bytes": None, "preview_seq": 0,
        "node_outputs": {},
    }

    threading.Thread(
        target=_start_ws_listener,
        args=(client_id, prompt_id, workflow, job_record),
        daemon=True,
    ).start()

    _events.emit("job.retried", f"Job retried from {source_pid[:12]}", data={"prompt_id": prompt_id, "retry_of": source_pid, "workflow_id": wf_id})
    return {"prompt_id": prompt_id, "retry_of": source_pid}


@router.get("/api/admin/history/{prompt_id}/package")
async def download_job_package(prompt_id: str):
    """Download a ZIP with job.json, input image, and output files."""
    job_data = db.get_job(prompt_id)
    if not job_data:
        raise HTTPException(404, "Job not found")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp_path = tmp.name
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("job.json", json.dumps(job_data, indent=2, ensure_ascii=False))

            input_img = job_data.get("input_image")
            if input_img:
                input_path = ASSETS_INPUT_DIR / input_img
                if input_path.exists():
                    zf.write(input_path, f"input/{input_img}")

            output_dir_name = job_data.get("output_dir")
            if output_dir_name:
                out_dir = ASSETS_OUTPUT_DIR / output_dir_name
                if out_dir.exists():
                    for of in out_dir.iterdir():
                        if of.is_file():
                            zf.write(of, f"output/{of.name}")
            else:
                output = job_data.get("output", {})
                if output and output.get("filename"):
                    out_path = ASSETS_OUTPUT_DIR
                    if output.get("subfolder"):
                        out_path = out_path / output["subfolder"]
                    out_path = out_path / output["filename"]
                    if out_path.exists():
                        zf.write(out_path, f"output/{output['filename']}")

        tmp.close()

        def stream_and_cleanup():
            try:
                with open(tmp_path, "rb") as fh:
                    while chunk := fh.read(1024 * 1024):
                        yield chunk
            finally:
                os.unlink(tmp_path)

        job_name = output_dir_name or prompt_id[:12]
        return StreamingResponse(
            stream_and_cleanup(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="job_{job_name}.zip"'},
        )
    except Exception:
        tmp.close()
        os.unlink(tmp_path)
        raise


# ── Assets ───────────────────────────────────────────────────────────────────


@router.post("/api/admin/assets/upload-inputs")
async def upload_input_assets(files: list[UploadFile] = File(...)):
    """Upload one or more images to ComfyUI input directory."""
    from input_assets import register_input_async
    uploaded = []
    errors = []
    for f in files:
        try:
            image_bytes = await f.read()
            filename = await register_input_async(image_bytes, f.filename, source="assets", mime_type=f.content_type)
            uploaded.append(filename)
        except Exception as e:
            errors.append(f"{f.filename}: {str(e)}")
    if uploaded:
        _events.emit("assets.uploaded", f"Uploaded {len(uploaded)} file(s)", data={"files": uploaded})
    return {"uploaded": uploaded, "errors": errors}


@router.get("/api/admin/assets/input-stats")
async def input_asset_stats():
    """Get file count on disk vs DB records."""
    from input_assets import get_stats
    return get_stats()


@router.post("/api/admin/assets/sync-inputs")
async def sync_inputs():
    """Scan assets/input/ and register untracked files in DB."""
    from input_assets import sync_input_assets
    result = sync_input_assets()
    parts = []
    if result["added"] > 0:
        parts.append(f"{result['added']} added")
    if result.get("deduped", 0) > 0:
        parts.append(f"{result['deduped']} deduped")
    if parts:
        _events.emit("assets.synced", f"Input sync: {', '.join(parts)}")
    return result


@router.get("/api/admin/assets/{asset_type}")
async def list_assets(asset_type: str):
    """List files in ComfyUI input or output directory."""
    if asset_type == "inputs":
        base = ASSETS_INPUT_DIR
    elif asset_type == "outputs":
        base = ASSETS_OUTPUT_DIR
    else:
        raise HTTPException(400, "Invalid asset type. Use 'inputs' or 'outputs'.")

    if not base.exists():
        return {"files": [], "studio_jobs": [], "total_size": 0}

    files = []
    studio_jobs = []
    total_size = 0

    for f in sorted(base.rglob("*"), key=lambda p: p.stat().st_mtime, reverse=True):
        if not f.is_file():
            continue
        if f.name.startswith("."):
            continue
        rel = str(f.relative_to(base))
        stat = f.stat()
        ext = f.suffix.lower()
        is_video = ext in (".mp4", ".webm", ".mov", ".avi")
        is_image = ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
        if not is_video and not is_image:
            continue
        files.append({
            "filename": f.name,
            "path": rel,
            "subfolder": str(f.parent.relative_to(base)) if f.parent != base else "",
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "type": "video" if is_video else "image",
        })
        total_size += stat.st_size

    if asset_type == "outputs":
        if base.exists():
            for job_dir in sorted(base.iterdir(), key=lambda d: d.stat().st_mtime if d.is_dir() else 0, reverse=True):
                if not job_dir.is_dir():
                    continue
                video_files = []
                image_files = []
                preview_files = []
                intermediate_files = []
                folder_size = 0
                for child in sorted(job_dir.rglob("*")):
                    if not child.is_file():
                        continue
                    folder_size += child.stat().st_size
                    ext = child.suffix.lower()
                    is_video = ext in (".mp4", ".webm", ".mov", ".avi")
                    is_image = ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
                    if not is_video and not is_image:
                        continue
                    child_subfolder = str(child.parent.relative_to(base))
                    file_info = {"filename": child.name, "subfolder": child_subfolder}
                    rel_to_job = str(child.relative_to(job_dir))
                    if rel_to_job.startswith("preview"):
                        preview_files.append(file_info)
                    elif rel_to_job.startswith("intermediate"):
                        intermediate_files.append(file_info)
                    elif rel_to_job.startswith("final") or rel_to_job.startswith("video") or rel_to_job.startswith("image"):
                        # "final/" is the new prefix; "video/"/"image/" are legacy
                        if is_video:
                            video_files.append(file_info)
                        else:
                            image_files.append(file_info)
                    elif is_video:
                        video_files.append(file_info)
                    else:
                        image_files.append(file_info)

                if not video_files and not image_files and not preview_files:
                    continue

                subfolder = str(job_dir.relative_to(base))
                is_incomplete = (job_dir / ".incomplete").exists()
                job_entry = {
                    "folder": job_dir.name,
                    "folder_path": subfolder,
                    "total_size": folder_size,
                    "modified": job_dir.stat().st_mtime,
                    "incomplete": is_incomplete,
                    "video_count": len(video_files),
                    "image_count": len(image_files),
                    "preview_count": len(preview_files),
                    "intermediate_count": len(intermediate_files),
                }
                if video_files:
                    job_entry["type"] = "studio_job"
                    job_entry["video"] = video_files[0]
                    # For video jobs, png files are thumbnails not separate images
                    job_entry["image_count"] = 0
                    job_entry["thumbnail"] = (preview_files[0] if preview_files
                                              else image_files[0] if image_files
                                              else None)
                else:
                    job_entry["type"] = "studio_gallery"
                    job_entry["images"] = image_files
                    job_entry["thumbnail"] = image_files[0] if image_files else None

                if preview_files:
                    job_entry["previews"] = preview_files
                if intermediate_files:
                    job_entry["intermediates"] = intermediate_files

                studio_jobs.append(job_entry)
                total_size += folder_size

    if asset_type == "outputs":
        # For outputs, only return grouped studio_jobs — no loose files
        return {"files": [], "studio_jobs": studio_jobs, "total_size": total_size}
    return {"files": files, "studio_jobs": studio_jobs, "total_size": total_size}


@router.get("/api/admin/outputs-zip")
async def download_outputs():
    """Create a ZIP of the entire output directory and stream it."""
    output_dir = ASSETS_OUTPUT_DIR
    if not output_dir.exists():
        raise HTTPException(404, "Output directory not found")

    from datetime import datetime, timezone, timedelta
    now = _now_rome()
    filename = f"outputs_{now.strftime('%Y%m%d_%H%M%S')}.zip"

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp_path = tmp.name
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in output_dir.rglob("*"):
                if f.is_file():
                    zf.write(f, str(f.relative_to(output_dir)))
        tmp.close()

        def stream_and_cleanup():
            try:
                with open(tmp_path, "rb") as fh:
                    while chunk := fh.read(1024 * 1024):
                        yield chunk
            finally:
                os.unlink(tmp_path)

        return StreamingResponse(
            stream_and_cleanup(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception:
        tmp.close()
        os.unlink(tmp_path)
        raise


@router.post("/api/admin/assets/delete")
async def delete_assets(request: Request):
    """Delete one or more files from ComfyUI input or output directory."""
    body = await request.json()
    asset_type = body.get("type", "")
    files = body.get("files", [])

    if asset_type == "inputs":
        base = ASSETS_INPUT_DIR
    elif asset_type == "outputs":
        base = ASSETS_OUTPUT_DIR
    else:
        raise HTTPException(400, "Invalid type")

    deleted = []
    errors = []
    for rel_path in files:
        if ".." in rel_path or rel_path.startswith("/"):
            errors.append(f"{rel_path}: invalid path")
            continue
        target = base / rel_path
        if target.is_dir():
            if rel_path.count("/") > 0:
                errors.append(f"{rel_path}: directory deletion not allowed")
                continue
            try:
                shutil.rmtree(target)
                deleted.append(rel_path)
            except Exception as e:
                errors.append(f"{rel_path}: {str(e)}")
        elif target.is_file():
            try:
                target.unlink()
                deleted.append(rel_path)
            except Exception as e:
                errors.append(f"{rel_path}: {str(e)}")
        else:
            errors.append(f"{rel_path}: not found")

    if deleted:
        _events.emit("assets.deleted", f"Deleted {len(deleted)} asset(s)", data={"files": deleted, "type": asset_type})
    return {"deleted": deleted, "errors": errors}


# ── Nodes ────────────────────────────────────────────────────────────────────


@router.get("/api/admin/nodes")
async def list_nodes():
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{COMFY_URL}/object_info")
            r.raise_for_status()
            object_info = r.json()
    except Exception as e:
        raise HTTPException(503, f"ComfyUI unreachable: {str(e)}")

    packages = {}
    for node_name, node_info in object_info.items():
        pkg_name = "ComfyUI Core"
        if isinstance(node_info, dict):
            module = node_info.get("python_module", "")
            if "custom_nodes" in module:
                parts = module.split(".")
                idx = parts.index("custom_nodes") if "custom_nodes" in parts else -1
                if idx >= 0 and idx + 1 < len(parts):
                    pkg_name = parts[idx + 1]
            elif module.startswith("nodes"):
                pkg_name = "ComfyUI Core"

        if pkg_name not in packages:
            packages[pkg_name] = {"name": pkg_name, "nodes": [], "node_count": 0}
        packages[pkg_name]["nodes"].append(node_name)
        packages[pkg_name]["node_count"] += 1

    pkg_list = sorted(packages.values(), key=lambda p: p["name"])
    for pkg in pkg_list:
        pkg["nodes"].sort()

    return {
        "packages": pkg_list,
        "total_nodes": len(object_info),
        "total_packages": len(pkg_list),
    }


@router.post("/api/admin/nodes/install")
async def install_node(body: dict):
    repo_url = (body.get("repo_url") or body.get("url") or "").strip()
    if not repo_url or not repo_url.startswith("https://"):
        raise HTTPException(400, "Invalid repo URL")

    custom_nodes_dir = Path(COMFYUI_DIR) / "custom_nodes"
    custom_nodes_dir.mkdir(parents=True, exist_ok=True)

    name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
    dest = custom_nodes_dir / name

    if dest.exists():
        return {"status": "already_installed", "name": name}

    # DEV_MODE: create empty directory to simulate installed node
    if DEV_MODE:
        dest.mkdir(parents=True, exist_ok=True)
        return {"status": "installed", "name": name, "restart_required": True}

    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(dest)],
            check=True, capture_output=True, text=True, timeout=120
        )

        req = dest / "requirements.txt"
        if req.exists():
            subprocess.run(
                ["pip", "install", "-r", str(req)],
                check=True, capture_output=True, text=True, timeout=300
            )

        install_py = dest / "install.py"
        if install_py.exists():
            subprocess.run(
                ["python", str(install_py)],
                check=True, capture_output=True, text=True, timeout=300,
                cwd=str(dest)
            )

        return {"status": "installed", "name": name, "restart_required": True}
    except subprocess.CalledProcessError as e:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(500, f"Installation failed: {e.stderr[:500]}")
    except subprocess.TimeoutExpired:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(500, "Installation timed out")
