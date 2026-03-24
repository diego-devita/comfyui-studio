"""ComfyUI Studio — Runner API: upload, build, execute, WS, status, result, ComfyUI view proxy."""

import asyncio
import json
import threading
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.responses import Response

from config import app, COMFY_URL
from auth import COOKIE_NAME, _verify_cookie
from events import _events
from runner import (
    _exec_progress, _pick_best_output, _start_ws_listener, _save_job, _build_workflow,
)
from workflows import _load_workflows_index, _load_manifest, _make_input_filename, _api_to_workflow_format

router = APIRouter()


@router.get("/api/run/{workflow_id}")
async def get_runner_manifest(workflow_id: str):
    index = _load_workflows_index()
    entry = next((e for e in index if e["id"] == workflow_id), None)
    if not entry:
        raise HTTPException(404)
    manifest = _load_manifest(entry["id"])
    if not manifest:
        raise HTTPException(404)
    return manifest


@router.post("/api/run/upload-image")
async def upload_input_image(file: UploadFile = File(...)):
    """Upload an image to ComfyUI input directory. Returns the filename for later use."""
    image_bytes = await file.read()
    unique_name = _make_input_filename(file.filename)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{COMFY_URL}/upload/image",
                files={"image": (unique_name, image_bytes, file.content_type or "image/png")},
                data={"overwrite": "true"},
            )
            r.raise_for_status()
            uploaded_name = r.json()["name"]
        return {"filename": uploaded_name}
    except Exception as e:
        raise HTTPException(500, f"Upload failed: {str(e)}")


@router.post("/api/run/{workflow_id}/build")
async def build_workflow(
    workflow_id: str,
    input_image: Optional[UploadFile] = File(None),
    params: str = Form("{}"),
    format: str = Query("api"),
):
    """Build a workflow with params applied and return it without executing."""
    form_params = json.loads(params)
    workflow, manifest, used_seeds, output_dir = await _build_workflow(
        workflow_id, form_params, input_image,
    )

    if format == "workflow":
        return await _api_to_workflow_format(workflow, manifest)
    else:
        return workflow


@router.post("/api/run/{workflow_id}/execute")
async def execute_workflow(
    workflow_id: str,
    input_image: Optional[UploadFile] = File(None),
    params: str = Form("{}"),
):
    form_params = json.loads(params)
    workflow, manifest, used_seeds, output_dir = await _build_workflow(
        workflow_id, form_params, input_image,
    )

    # Send to ComfyUI
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
        node_errors = data.get("node_errors", {})
        detail = str(data["error"])
        if node_errors:
            for nid, nerr in node_errors.items():
                title = workflow.get(nid, {}).get("_meta", {}).get("title", nid)
                msgs = nerr.get("errors", [])
                for m in msgs:
                    detail += f" | {title}: {m.get('message', str(m))}"
        raise HTTPException(400, detail)

    prompt_id = data["prompt_id"]

    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=1)))
    is_dynamic = manifest.get("type") == "dynamic"
    input_image_name = None
    if is_dynamic:
        input_image_name = form_params.get("_uploaded_image")
    else:
        for inp in manifest.get("inputs", []):
            if inp["type"] == "image":
                node_id = str(inp["node_id"])
                field = inp["field"]
                if node_id in workflow:
                    input_image_name = workflow[node_id]["inputs"].get(field)

    save_params = {k: v for k, v in form_params.items() if not k.startswith("_")}

    job_record = {
        "prompt_id": prompt_id,
        "workflow_id": workflow_id,
        "workflow_name": manifest.get("name", workflow_id),
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
    }
    _save_job(job_record)

    _exec_progress[prompt_id] = {
        "status": "queued", "node_title": "", "node_id": "", "node_type": "",
        "workflow_name": manifest.get("name", workflow_id), "workflow_id": workflow_id,
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

    _events.emit("job.queued", f"Job queued: {manifest.get('name', workflow_id)}", data={"prompt_id": prompt_id, "workflow_id": workflow_id})
    return {"prompt_id": prompt_id, "client_id": client_id, "seeds": used_seeds}


# WebSocket endpoint must be on app directly
@app.websocket("/api/run/ws")
async def run_ws(websocket: WebSocket):
    """WebSocket endpoint for real-time job progress + preview frames + events."""
    cookie = websocket.cookies.get(COOKIE_NAME, "")
    if not cookie or not _verify_cookie(cookie):
        await websocket.close(code=4001, reason="Not authenticated")
        return
    await websocket.accept()
    last_state_hash = None
    last_preview_seq = {}
    last_event_idx = len(_events._log)

    try:
        while True:
            current_log = _events._log
            if len(current_log) > last_event_idx:
                for evt in current_log[last_event_idx:]:
                    await websocket.send_text(json.dumps(evt, default=str))
                last_event_idx = len(current_log)

            for pid, state in list(_exec_progress.items()):
                if state.get("status") not in ("queued", "running"):
                    continue

                json_state = {k: v for k, v in state.items()
                              if k not in ("preview_bytes",)}
                json_state["prompt_id"] = pid

                state_str = json.dumps(json_state, default=str)
                h = hash(state_str)
                if h != last_state_hash:
                    await websocket.send_text(state_str)
                    last_state_hash = h

                seq = state.get("preview_seq", 0)
                prev_seq = last_preview_seq.get(pid, 0)
                if seq > prev_seq and state.get("preview_bytes"):
                    await websocket.send_bytes(state["preview_bytes"])
                    last_preview_seq[pid] = seq

            await asyncio.sleep(0.15)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


@router.get("/api/run/status/{prompt_id}")
async def run_status(prompt_id: str):
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{COMFY_URL}/history/{prompt_id}")
        r.raise_for_status()
        history = r.json()

    if prompt_id not in history:
        ws_state = _exec_progress.get(prompt_id)
        if ws_state:
            return {
                "status": ws_state.get("status", "running"),
                "node_title": ws_state.get("node_title", ""),
                "node_type": ws_state.get("node_type", ""),
                "step": ws_state.get("step", 0),
                "total_steps": ws_state.get("total_steps", 0),
                "percent": ws_state.get("percent", 0),
                "nodes_done": ws_state.get("nodes_done", 0),
                "total_nodes": ws_state.get("total_nodes", 0),
                "effective_total": ws_state.get("effective_total", ws_state.get("total_nodes", 0)),
                "cached_count": ws_state.get("cached_count", 0),
                "eta_seconds": ws_state.get("eta_seconds"),
                "step_rate": ws_state.get("step_rate"),
                "node_outputs": ws_state.get("node_outputs", {}),
            }

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                qr = await client.get(f"{COMFY_URL}/queue")
                qr.raise_for_status()
                queue_data = qr.json()
                running = queue_data.get("queue_running", [])
                pending = queue_data.get("queue_pending", [])

                for item in running:
                    if len(item) > 1 and item[1] == prompt_id:
                        return {"status": "running", "step": 0, "total_steps": 0}
                for item in pending:
                    if len(item) > 1 and item[1] == prompt_id:
                        return {"status": "pending", "step": 0, "total_steps": 0}
        except Exception:
            pass
        return {"status": "pending", "step": 0, "total_steps": 0}

    job = history[prompt_id]
    status_str = job.get("status", {}).get("status_str", "")

    if status_str == "error":
        messages = job.get("status", {}).get("messages", [])
        return {"status": "error", "error": str(messages)}

    outputs = job.get("outputs", {})
    best_video, best_images = _pick_best_output(outputs)
    result_outputs = {}
    if best_video:
        result_outputs["video"] = {
            "filename": best_video["filename"],
            "subfolder": best_video.get("subfolder", ""),
            "type": best_video.get("type", "output"),
        }
    if best_images:
        info = best_images[0]
        result_outputs["image"] = {
            "filename": info["filename"],
            "subfolder": info.get("subfolder", ""),
            "type": info.get("type", "output"),
        }

    return {
        "status": "completed",
        "outputs": result_outputs,
    }


@router.get("/api/comfyui/view")
async def comfyui_view(filename: str, type: str = "input", subfolder: str = ""):
    """Proxy to ComfyUI /view endpoint for serving images."""
    params = {"filename": filename, "type": type}
    if subfolder:
        params["subfolder"] = subfolder
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{COMFY_URL}/view", params=params)
            if r.status_code != 200:
                raise HTTPException(r.status_code, "Image not found")
            ct = r.headers.get("content-type", "image/png")
            return Response(content=r.content, media_type=ct)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(404, "ComfyUI unreachable")


@router.get("/api/run/result/{prompt_id}")
async def run_result(prompt_id: str, output_type: str = "video"):
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{COMFY_URL}/history/{prompt_id}")
        r.raise_for_status()
        history = r.json()

    if prompt_id not in history:
        raise HTTPException(404, "Result not ready")

    outputs = history[prompt_id].get("outputs", {})
    best_video, best_images = _pick_best_output(outputs)
    file_info = best_video or (best_images[0] if best_images else None)

    if not file_info:
        raise HTTPException(404, "No output found")

    params = {"filename": file_info["filename"], "type": file_info.get("type", "output")}
    if file_info.get("subfolder"):
        params["subfolder"] = file_info["subfolder"]

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.get(f"{COMFY_URL}/view", params=params)
        r.raise_for_status()
        content = r.content

    fname = file_info["filename"]
    if fname.endswith(".mp4"):
        media_type = "video/mp4"
    elif fname.endswith(".webm"):
        media_type = "video/webm"
    elif fname.endswith(".png"):
        media_type = "image/png"
    elif fname.endswith(".jpg") or fname.endswith(".jpeg"):
        media_type = "image/jpeg"
    else:
        media_type = "application/octet-stream"

    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )
