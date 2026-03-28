"""ComfyUI Studio — Execution progress tracking, WS listener, workflow builder, job persistence."""

import json
import random
import uuid
from typing import Optional

import httpx
from fastapi import HTTPException, UploadFile

from config import COMFY_URL, ASSETS_OUTPUT_DIR
from catalogs import _reload_models
import db as _db
from workflows import (
    _load_manifest, _load_workflow_json,
    _make_input_filename,
    _assemble_dynamic_workflow,
)

# ── Execution progress tracking (via ComfyUI WebSocket) ──────────────────
# prompt_id -> {"status": "running"|"completed"|"error",
#               "node": str, "node_title": str,
#               "step": int, "total_steps": int}
_exec_progress: dict = {}


def _pick_best_output(hist_outputs: dict):
    """From ComfyUI history outputs, pick final video/images (skip intermediate)."""
    all_videos, all_images = [], []
    for _nout in hist_outputs.values():
        for _k in ("gifs", "videos"):
            if _k in _nout and _nout[_k]:
                all_videos.extend(_nout[_k])
        if "images" in _nout and _nout["images"]:
            all_images.extend(_nout["images"])
    _skip = lambda o: "/intermediate" in (o.get("subfolder") or "")
    best_video = next((v for v in all_videos if not _skip(v)), all_videos[-1]) if all_videos else None
    best_images = [i for i in all_images if not _skip(i)] or all_images
    return best_video, best_images


def _save_job(job_data: dict):
    """Save a job record to the database."""
    from db import save_job
    save_job(job_data)


def _start_ws_listener(client_id: str, prompt_id: str, workflow: dict, job_record: dict = None):
    """Background thread: listen to ComfyUI WebSocket for progress updates."""
    import time as _time
    from events import _events

    # Build node_id -> title map and class_type map
    node_titles = {}
    node_types = {}
    for nid, ndata in workflow.items():
        meta = ndata.get("_meta", {})
        node_titles[nid] = meta.get("title", ndata.get("class_type", nid))
        node_types[nid] = ndata.get("class_type", "")

    # Utility nodes that execute instantly -- exclude from effective total
    INSTANT_TYPES = {
        "Anything Everywhere", "Anything Everywhere3",
        "Prompts Everywhere", "Reroute", "Note", "PrimitiveNode",
        "PrimitiveInt", "Float", "SimpleMath+",
        "GetImageSize+", "ImageFromBatch+", "ImageListToImageBatch",
    }
    total_nodes = len(workflow)
    instant_count = sum(1 for ct in node_types.values() if ct in INSTANT_TYPES)
    cached_nodes = set()
    effective_total = max(total_nodes - instant_count, 1)
    nodes_done = 0

    # ETA tracking
    _step_times = []
    _exec_start = None

    comfy_ws = COMFY_URL.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{comfy_ws}/ws?clientId={client_id}"

    def _mark_stalled(reason="WebSocket listener terminated unexpectedly"):
        """Mark the job as stalled in DB if it never completed."""
        if job_record and job_record.get("status") in ("queued", "running"):
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone(timedelta(hours=1)))
            job_record["status"] = "stalled"
            job_record["error"] = reason
            job_record["finished_at"] = now.strftime("%Y-%m-%dT%H:%M:%S")
            _save_job(job_record)
            from events import _events
            _events.emit("job.failed", f"Job stalled: {reason[:100]}", severity="error",
                         data={"prompt_id": prompt_id})

    try:
        from websockets.sync.client import connect as ws_connect
        ws = ws_connect(ws_url)
    except ImportError:
        _exec_progress.pop(prompt_id, None)
        _mark_stalled("websockets library not available")
        return
    except Exception as e:
        _exec_progress.pop(prompt_id, None)
        _mark_stalled(f"WebSocket connection failed: {e}")
        return

    # Race condition guard: if ComfyUI already finished before WS connected,
    # the messages are lost. Check history immediately after connecting.
    _time.sleep(0.5)  # brief wait for ComfyUI to register the prompt
    try:
        import httpx as _hx
        _hist_r = _hx.get(f"{COMFY_URL}/history/{prompt_id}", timeout=5)
        if _hist_r.status_code == 200:
            _hist_data = _hist_r.json().get(prompt_id, {})
            _hist_status = _hist_data.get("status", {}).get("status_str", "")
            if _hist_status in ("error", "success"):
                # Job already finished — don't wait on WS
                if _hist_status == "error":
                    msgs = _hist_data.get("status", {}).get("messages", [])
                    err_msg = ""
                    for _m in msgs:
                        if isinstance(_m, (list, tuple)) and len(_m) >= 2 and _m[0] == "execution_error":
                            err_data = _m[1] if isinstance(_m[1], dict) else {}
                            err_msg = err_data.get("exception_message", str(_m))
                            break
                    _mark_stalled(f"ComfyUI error: {(err_msg or str(msgs))[:200]}")
                else:
                    from datetime import datetime, timezone, timedelta as _td
                    _now = datetime.now(timezone(_td(hours=1)))
                    if job_record:
                        job_record["status"] = "completed"
                        job_record["finished_at"] = _now.strftime("%Y-%m-%dT%H:%M:%S")
                        hist_outputs = _hist_data.get("outputs", {})
                        best_video, best_images = _pick_best_output(hist_outputs)
                        if best_video:
                            job_record["output"] = best_video
                        elif best_images:
                            job_record["output"] = best_images[0]
                        _save_job(job_record)
                _exec_progress.pop(prompt_id, None)
                try:
                    ws.close()
                except Exception:
                    pass
                return
    except Exception:
        pass  # history check failed, proceed with WS listener as normal

    _preview_seq = 0
    try:
        for raw in ws:
            if isinstance(raw, bytes):
                img_start = raw.find(b'\xff\xd8')
                img_type = "image/jpeg"
                if img_start < 0:
                    img_start = raw.find(b'\x89PNG')
                    img_type = "image/png"
                if img_start >= 0:
                    _preview_seq += 1
                    state = _exec_progress.get(prompt_id, {})
                    state["preview_bytes"] = raw[img_start:]
                    state["preview_seq"] = _preview_seq
                    state["preview_type"] = img_type
                    _exec_progress[prompt_id] = state
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            msg_type = msg.get("type")
            data = msg.get("data", {})

            if data.get("prompt_id") != prompt_id:
                continue

            state = _exec_progress.get(prompt_id, {})

            if msg_type == "execution_start":
                state["status"] = "running"
                _exec_start = _time.time()
                if job_record:
                    from datetime import datetime, timezone, timedelta
                    real_start = datetime.now(timezone(timedelta(hours=1)))
                    job_record["status"] = "running"
                    job_record["started_at"] = real_start.strftime("%Y-%m-%dT%H:%M:%S")
                    _save_job(job_record)
                    _events.emit("job.started", f"Job started: {prompt_id[:12]}", data={"prompt_id": prompt_id})
                    # Create output dir with .incomplete marker
                    _od = job_record.get("output_dir")
                    if _od:
                        _job_dir = ASSETS_OUTPUT_DIR / _od
                        _job_dir.mkdir(parents=True, exist_ok=True)
                        (_job_dir / ".incomplete").write_text("")

            elif msg_type == "execution_cached":
                cached_ids = data.get("nodes", [])
                for cn in cached_ids:
                    cached_nodes.add(str(cn))
                effective_total = max(total_nodes - instant_count - len(cached_nodes), 1)
                state["cached_count"] = len(cached_nodes)
                state["effective_total"] = effective_total

            elif msg_type == "executing":
                node = data.get("node")
                if node is None:
                    # Execution complete
                    state["status"] = "completed"
                    state["percent"] = 100
                    state["eta_seconds"] = 0
                    _exec_progress[prompt_id] = state
                    if job_record:
                        from datetime import datetime, timezone, timedelta
                        now = datetime.now(timezone(timedelta(hours=1)))
                        job_record["status"] = "completed"
                        job_record["finished_at"] = now.strftime("%Y-%m-%dT%H:%M:%S")
                        if not job_record.get("started_at"):
                            job_record["started_at"] = job_record.get("queued_at")
                        if job_record.get("started_at"):
                            try:
                                start = datetime.strptime(job_record["started_at"], "%Y-%m-%dT%H:%M:%S")
                                job_record["duration"] = round((now.replace(tzinfo=None) - start).total_seconds())
                            except Exception:
                                pass
                        try:
                            import httpx as _hx
                            r = _hx.get(f"{COMFY_URL}/history/{prompt_id}", timeout=5)
                            if r.status_code == 200:
                                hist = r.json().get(prompt_id, {}).get("outputs", {})
                                best_video, best_images = _pick_best_output(hist)
                                if best_video:
                                    job_record["output"] = best_video
                                elif best_images:
                                    job_record["output"] = best_images[0]
                                    if len(best_images) > 1:
                                        job_record["outputs"] = best_images
                        except Exception:
                            pass
                        _save_job(job_record)
                        _events.emit("job.completed", f"Job completed in {job_record.get('duration', '?')}s", severity="success", data={"prompt_id": prompt_id, "workflow_id": job_record.get("workflow_id"), "duration": job_record.get("duration")})
                        # Remove .incomplete marker
                        _od = job_record.get("output_dir")
                        if _od:
                            _marker = ASSETS_OUTPUT_DIR / _od / ".incomplete"
                            _marker.unlink(missing_ok=True)
                    _exec_progress.pop(prompt_id, None)
                    break

                # New node starting
                nodes_done += 1
                state["node_id"] = node
                state["node_title"] = node_titles.get(node, node)
                state["node_type"] = node_types.get(node, "")
                state["nodes_done"] = nodes_done
                state["effective_total"] = effective_total
                state["cached_count"] = len(cached_nodes)
                state["status"] = "running"
                state["step"] = 0
                state["total_steps"] = 0
                state["eta_seconds"] = None
                state["step_rate"] = None
                _step_times = []
                state["percent"] = min(round((nodes_done - 1) / effective_total * 100), 99)

            elif msg_type == "progress":
                step = data.get("value", 0)
                total = data.get("max", 0)
                prog_node = data.get("node")
                state["step"] = step
                state["total_steps"] = total
                if prog_node and prog_node in node_titles:
                    state["node_title"] = node_titles.get(prog_node, state.get("node_title", ""))

                now_t = _time.time()
                _step_times.append(now_t)
                if len(_step_times) > 11:
                    _step_times = _step_times[-11:]
                if len(_step_times) >= 2 and total > 0:
                    elapsed = _step_times[-1] - _step_times[0]
                    steps_measured = len(_step_times) - 1
                    rate = steps_measured / elapsed if elapsed > 0 else 0
                    remaining_steps = total - step
                    eta_current_node = round(remaining_steps / rate) if rate > 0 else None
                    eta_remaining_nodes = 0
                    remaining_nodes = effective_total - nodes_done
                    if remaining_nodes > 0 and _exec_start and nodes_done > 0:
                        avg_node_time = (now_t - _exec_start) / nodes_done
                        eta_remaining_nodes = round(remaining_nodes * avg_node_time)
                    state["eta_seconds"] = (eta_current_node or 0) + eta_remaining_nodes
                    state["step_rate"] = round(rate, 2)

                base = (nodes_done - 1) / effective_total * 100
                node_fraction = (step / total * (100 / effective_total)) if total > 0 else 0
                state["percent"] = min(round(base + node_fraction), 99)

            elif msg_type == "executed":
                exec_node = str(data.get("node", ""))
                output_data = data.get("output", {})
                if "node_outputs" not in state:
                    state["node_outputs"] = {}
                for key in ("images", "gifs", "videos"):
                    if key in output_data and output_data[key]:
                        items = []
                        for info in output_data[key]:
                            items.append({
                                "filename": info.get("filename"),
                                "subfolder": info.get("subfolder", ""),
                                "type": info.get("type", "output"),
                                "media": "video" if key in ("gifs", "videos") else "image",
                            })
                        state["node_outputs"][exec_node] = {
                            "node_title": node_titles.get(exec_node, exec_node),
                            "node_type": node_types.get(exec_node, ""),
                            "items": items,
                        }
                        break

            elif msg_type == "execution_error":
                err_msg = str(data.get("exception_message", ""))
                err_node = data.get("node")
                err_title = node_titles.get(str(err_node), str(err_node)) if err_node else ""
                full_err = f"[{err_title}] {err_msg}" if err_title else err_msg
                if job_record:
                    from datetime import datetime, timezone, timedelta
                    now = datetime.now(timezone(timedelta(hours=1)))
                    job_record["status"] = "error"
                    job_record["error"] = full_err
                    job_record["finished_at"] = now.strftime("%Y-%m-%dT%H:%M:%S")
                    _save_job(job_record)
                    _events.emit("job.failed", f"Job failed: {full_err[:100]}", severity="error", data={"prompt_id": prompt_id, "error": full_err})
                _exec_progress.pop(prompt_id, None)
                break

            _exec_progress[prompt_id] = state
    except Exception as _ws_err:
        _mark_stalled(f"WebSocket error: {_ws_err}")
    finally:
        _exec_progress.pop(prompt_id, None)
        try:
            ws.close()
        except Exception:
            pass
        # If job never completed/errored via WS, check ComfyUI history as fallback
        if job_record and job_record.get("status") in ("queued", "running"):
            try:
                import httpx as _hx
                r = _hx.get(f"{COMFY_URL}/history/{prompt_id}", timeout=5)
                if r.status_code == 200:
                    hist = r.json().get(prompt_id, {})
                    status_info = hist.get("status", {})
                    if status_info.get("status_str") == "error":
                        msgs = status_info.get("messages", [])
                        err_msg = ""
                        for m in msgs:
                            if isinstance(m, (list, tuple)) and len(m) >= 2 and m[0] == "execution_error":
                                err_data = m[1] if isinstance(m[1], dict) else {}
                                err_msg = err_data.get("exception_message", str(m))
                                break
                        if not err_msg:
                            err_msg = str(msgs)
                        _mark_stalled(f"ComfyUI error: {err_msg[:200]}")
                    elif status_info.get("status_str") == "success":
                        # Completed but WS missed it — mark completed
                        from datetime import datetime, timezone, timedelta
                        now = datetime.now(timezone(timedelta(hours=1)))
                        job_record["status"] = "completed"
                        job_record["finished_at"] = now.strftime("%Y-%m-%dT%H:%M:%S")
                        hist_outputs = hist.get("outputs", {})
                        best_video, best_images = _pick_best_output(hist_outputs)
                        if best_video:
                            job_record["output"] = best_video
                        elif best_images:
                            job_record["output"] = best_images[0]
                        _save_job(job_record)
                    else:
                        _mark_stalled("WS listener ended without completion")
                else:
                    _mark_stalled("WS listener ended, ComfyUI history unavailable")
            except Exception as _hist_err:
                _mark_stalled(f"WS listener ended: {_hist_err}")


async def _build_workflow(
    workflow_id: str, form_params: dict, input_image: Optional[UploadFile],
) -> tuple:
    """Build a workflow with params applied.

    Returns (workflow, manifest, used_seeds, output_dir).
    Handles static and dynamic workflows, image upload, param application,
    seed resolution, and output directory patching.
    """
    wf = _db.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404)

    manifest = _load_manifest(workflow_id)
    if not manifest:
        raise HTTPException(404)

    is_dynamic = manifest.get("type") == "dynamic"
    dynamic_seeds = {}

    # Generate output_dir early -- needed by assemblers
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=1)))
    output_dir = now.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]

    if is_dynamic:
        # Dynamic workflow: assemble from blocks
        uploaded_name = None
        existing_img = form_params.get("_existing_input_image")
        if existing_img:
            uploaded_name = existing_img
        elif input_image:
            image_bytes = await input_image.read()
            unique_name = _make_input_filename(input_image.filename)
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    f"{COMFY_URL}/upload/image",
                    files={"image": (unique_name, image_bytes, input_image.content_type or "image/png")},
                    data={"overwrite": "true"},
                )
                r.raise_for_status()
                uploaded_name = r.json()["name"]
            input_image = None

        form_params["_uploaded_image"] = uploaded_name or "input.png"
        form_params["_has_input_image"] = uploaded_name is not None
        if isinstance(form_params.get("scenes"), str):
            form_params["scenes"] = json.loads(form_params["scenes"])
        if isinstance(form_params.get("loras"), str):
            form_params["loras"] = json.loads(form_params["loras"])
        if isinstance(form_params.get("loras_high"), str):
            form_params["loras_high"] = json.loads(form_params["loras_high"])
        if isinstance(form_params.get("loras_low"), str):
            form_params["loras_low"] = json.loads(form_params["loras_low"])
        try:
            form_params["_output_dir"] = output_dir
            workflow, dynamic_seeds = _assemble_dynamic_workflow(manifest, form_params)
        except Exception as e:
            raise HTTPException(500, f"Workflow assembly failed: {str(e)}")
    else:
        workflow = _load_workflow_json(workflow_id)
        if not workflow:
            raise HTTPException(404, "Workflow JSON not found")

    # Static workflow: upload image or use existing
    if not is_dynamic:
        existing_img = form_params.get("_existing_input_image")
        if existing_img:
            for inp in manifest.get("inputs", []):
                if inp["type"] == "image":
                    node_id = str(inp["node_id"])
                    field = inp["field"]
                    if node_id in workflow:
                        workflow[node_id]["inputs"][field] = existing_img
        elif input_image:
            image_bytes = await input_image.read()
            unique_name = _make_input_filename(input_image.filename)

            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    f"{COMFY_URL}/upload/image",
                    files={"image": (unique_name, image_bytes, input_image.content_type or "image/png")},
                    data={"overwrite": "true"},
                )
                r.raise_for_status()
                uploaded_name = r.json()["name"]

            for inp in manifest.get("inputs", []):
                if inp["type"] == "image":
                    node_id = str(inp["node_id"])
                    field = inp["field"]
                    if node_id in workflow:
                        workflow[node_id]["inputs"][field] = uploaded_name

    if not is_dynamic:
        # Apply form parameters (static workflows only)
        for inp in manifest.get("inputs", []):
            if inp["id"] in form_params:
                node_id = str(inp["node_id"])
                field = inp["field"]
                value = form_params[inp["id"]]

                if node_id in workflow:
                    if inp["type"] == "int":
                        value = int(value)
                    elif inp["type"] == "float":
                        value = float(value)
                    elif inp["type"] == "select":
                        value = int(value) if isinstance(value, str) and value.isdigit() else value
                    elif inp["type"] == "seed":
                        value = int(value)
                        if value == -1:
                            value = random.randint(0, 2**53)

                    workflow[node_id]["inputs"][field] = value

        # Handle seed -1 for seed type inputs not in form_params
        for inp in manifest.get("inputs", []):
            if inp["type"] == "seed" and inp["id"] not in form_params:
                node_id = str(inp["node_id"])
                field = inp["field"]
                if node_id in workflow:
                    current = workflow[node_id]["inputs"].get(field, -1)
                    if current == -1:
                        workflow[node_id]["inputs"][field] = random.randint(0, 2**53)

    # Collect resolved seed values
    used_seeds = {}
    if is_dynamic:
        used_seeds = dynamic_seeds
    else:
        for inp in manifest.get("inputs", []):
            if inp["type"] == "seed" and inp.get("node_id"):
                node_id = str(inp["node_id"])
                field = inp["field"]
                if node_id in workflow:
                    used_seeds[inp["id"]] = workflow[node_id]["inputs"].get(field)

    # Set output directory per job
    for _nid, _node in workflow.items():
        ct = _node.get("class_type", "")
        if ct == "VHS_VideoCombine":
            inp = _node.get("inputs", {})
            if inp.get("save_output") is True:
                inp["filename_prefix"] = f"{output_dir}/final"
            else:
                inp["save_output"] = True
                inp["filename_prefix"] = f"{output_dir}/intermediate"
        elif ct == "SaveImage":
            _node["inputs"]["filename_prefix"] = f"{output_dir}/final"
        elif ct == "PreviewImage":
            _node["inputs"]["filename_prefix"] = f"{output_dir}/preview"

    return workflow, manifest, used_seeds, output_dir
