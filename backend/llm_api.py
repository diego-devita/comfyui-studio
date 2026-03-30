"""ComfyUI Studio — LLM endpoints (model list, download, delete, multi-instance server control, chat)."""

import json

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from config import LLM_MODELS_DIR, LLAMA_SERVER_PATH, DEV_MODE
import catalogs as _catalogs
from catalogs import _find_llm_model, _build_catalog_response
from download import _download_state, _enqueue_download
from events import _events
from llm_server import (
    _load_llm_config, _save_llm_config,
    _start_llama_server, _stop_llama_server, _stop_all,
    _get_running_instances, _get_instance_log, _get_instance_port,
    _is_running, _has_running_instances,
)

router = APIRouter()


@router.get("/api/admin/llm/models")
async def llm_models_list():
    """List LLM models catalog with download/presence status."""
    result_categories = _build_catalog_response(_catalogs._llm_models_data, LLM_MODELS_DIR, _download_state)

    present_count = sum(1 for cat in result_categories for m in cat["models"] if m["status"] == "present")
    total_count = sum(len(cat["models"]) for cat in result_categories)

    return JSONResponse({
        "version": _catalogs._llm_models_data.get("version", 0),
        "date": _catalogs._llm_models_data.get("date", ""),
        "categories": result_categories,
        "summary": {
            "total": total_count,
            "present": present_count,
        },
    })


@router.post("/api/admin/llm/models/download/{filename}")
async def llm_model_download(filename: str):
    """Download an LLM model file."""
    model = _find_llm_model(filename)
    if not model:
        raise HTTPException(status_code=404, detail=f"LLM model '{filename}' not found in catalog")

    state = _download_state.get(filename, {})
    if state.get("status") in ("downloading", "queued"):
        return JSONResponse({"status": state["status"], "file": filename})

    item = dict(model)
    item["_base_dir"] = str(LLM_MODELS_DIR)
    _enqueue_download(item, source="manual")
    return JSONResponse({"status": "queued", "file": filename})


@router.delete("/api/admin/llm/models/{filename}")
async def llm_model_delete(filename: str):
    """Delete an LLM model file from disk. Refuses if any instance is running."""
    model = _find_llm_model(filename)
    if not model:
        raise HTTPException(status_code=404, detail=f"LLM model '{filename}' not found in catalog")

    # Refuse deletion if any instance of this model is running
    if _has_running_instances(filename):
        raise HTTPException(status_code=409, detail=f"Cannot delete '{filename}': it has running instances. Stop them first.")

    dest_path = LLM_MODELS_DIR / filename
    if dest_path.exists():
        dest_path.unlink()

    if filename in _download_state:
        state = _download_state[filename]
        if state.get("status") in ("error", "done"):
            del _download_state[filename]

    _events.emit("llm.model.deleted", f"LLM model deleted: {filename}", data={"filename": filename})
    return JSONResponse({"status": "deleted", "file": filename})


@router.get("/api/admin/llm/status")
async def llm_status():
    """Get all running LLM instances and config."""
    config = _load_llm_config()
    instances = _get_running_instances()

    # Check health for each instance
    for inst in instances:
        inst["proxy_base_path"] = f"/api/admin/llm/{inst['instance_id']}/api/"
        if DEV_MODE:
            inst["health"] = "ok"
        else:
            try:
                async with httpx.AsyncClient(timeout=3) as client:
                    r = await client.get(f"http://127.0.0.1:{inst['port']}/health")
                    inst["health"] = "ok" if r.status_code == 200 else "loading"
            except Exception:
                inst["health"] = "unreachable"

    return JSONResponse({
        "instances": instances,
        "config": {k: v for k, v in config.items() if not k.startswith("_")},
        "binary_exists": LLAMA_SERVER_PATH.exists(),
    })


@router.post("/api/admin/llm/start")
async def llm_start(request: Request):
    """Start an LLM server instance for a model. Returns instance_id + port."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    model_file = body.get("model")
    if not model_file:
        raise HTTPException(400, "Missing 'model' field")

    config = _load_llm_config()
    for key in ("n_gpu_layers", "ctx_size", "threads", "temp", "top_p", "top_k", "repeat_penalty"):
        if key in body:
            config[key] = body[key]

    try:
        instance_id, port = _start_llama_server(model_file, config)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(500, f"Failed to start LLM server: {str(e)}")

    return JSONResponse({"status": "started", "model": model_file, "instance_id": instance_id, "port": port})


@router.post("/api/admin/llm/stop")
async def llm_stop(request: Request):
    """Stop a specific LLM server instance by instance_id."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    instance_id = body.get("instance_id")
    if not instance_id:
        raise HTTPException(400, "Missing 'instance_id' field")

    if not _is_running(instance_id):
        return JSONResponse({"status": "already_stopped", "instance_id": instance_id})

    _stop_llama_server(instance_id)
    return JSONResponse({"status": "stopped", "instance_id": instance_id})


@router.post("/api/admin/llm/stop-all")
async def llm_stop_all():
    """Stop all running LLM server instances."""
    _stop_all()
    return JSONResponse({"status": "stopped_all"})


@router.get("/api/admin/llm/log/{instance_id:path}")
async def llm_instance_log(instance_id: str, tail: int = 100):
    """Get the last N lines of an instance's log."""
    log = _get_instance_log(instance_id, tail=tail)
    return JSONResponse({"instance_id": instance_id, "log": log})


@router.post("/api/admin/llm/config")
async def llm_config_update(request: Request):
    """Update LLM server config."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    config = _load_llm_config()
    for key in ("n_gpu_layers", "ctx_size", "threads", "temp", "top_p", "top_k", "repeat_penalty"):
        if key in body:
            config[key] = body[key]
    _save_llm_config(config)

    return JSONResponse({"status": "saved", "config": {k: v for k, v in config.items() if not k.startswith("_")}})


@router.post("/api/admin/llm/chat")
async def llm_chat(request: Request):
    """Proxy chat completions to the correct llama-server instance."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    instance_id = body.get("instance_id")
    if not instance_id:
        raise HTTPException(400, "Missing 'instance_id' field — specify which running instance to chat with")

    if not _is_running(instance_id):
        raise HTTPException(503, f"Instance '{instance_id}' is not running")

    port = _get_instance_port(instance_id)
    if port is None:
        raise HTTPException(503, f"Cannot find port for instance '{instance_id}'")

    # DEV_MODE: return a fake streaming or non-streaming response
    if DEV_MODE:
        if body.get("stream"):
            async def _dev_stream():
                words = "[DEV MODE] This is a stub streaming response from the simulated LLM server.".split()
                for i, word in enumerate(words):
                    token = (" " if i > 0 else "") + word
                    chunk = {
                        "id": "dev-stub",
                        "object": "chat.completion.chunk",
                        "choices": [{"index": 0, "delta": {"content": token}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"
                # Final chunk
                done_chunk = {
                    "id": "dev-stub",
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
                yield f"data: {json.dumps(done_chunk)}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(_dev_stream(), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        return JSONResponse({
            "id": "dev-stub",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": f"[DEV MODE] Stub response from instance {instance_id}.",
                },
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })

    config = _load_llm_config()
    payload = {
        "messages": body.get("messages", []),
        "temperature": body.get("temperature", config.get("temp", 0.7)),
        "top_p": body.get("top_p", config.get("top_p", 0.9)),
        "top_k": body.get("top_k", config.get("top_k", 40)),
        "repeat_penalty": body.get("repeat_penalty", config.get("repeat_penalty", 1.1)),
        "stream": body.get("stream", False),
    }
    if "max_tokens" in body:
        payload["max_tokens"] = body["max_tokens"]

    try:
        if payload.get("stream"):
            async def _stream():
                async with httpx.AsyncClient(timeout=300) as client:
                    async with client.stream("POST", f"http://127.0.0.1:{port}/v1/chat/completions", json=payload) as resp:
                        async for line in resp.aiter_lines():
                            yield line + "\n"
            return StreamingResponse(_stream(), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        else:
            async with httpx.AsyncClient(timeout=300) as client:
                r = await client.post(f"http://127.0.0.1:{port}/v1/chat/completions", json=payload)
                return JSONResponse(r.json(), status_code=r.status_code)
    except httpx.ConnectError:
        raise HTTPException(503, f"LLM instance '{instance_id}' on port {port} is not reachable")
    except Exception as e:
        raise HTTPException(500, f"LLM chat error: {str(e)}")


@router.api_route("/api/admin/llm/{instance_id:path}/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def llm_proxy(instance_id: str, path: str, request: Request):
    """Generic proxy to a running llama-server instance.

    Routes /api/admin/llm/{instance_id}/api/{anything} to localhost:{port}/{anything}.
    Only works for instances registered in the instance registry.
    """
    if not _is_running(instance_id):
        raise HTTPException(503, f"Instance '{instance_id}' is not running")

    port = _get_instance_port(instance_id)
    if port is None:
        raise HTTPException(503, f"Cannot find port for instance '{instance_id}'")

    target_url = f"http://127.0.0.1:{port}/{path}"

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            body = await request.body()
            headers = {k: v for k, v in request.headers.items()
                       if k.lower() not in ("host", "connection", "transfer-encoding")}

            if request.method == "GET":
                r = await client.get(target_url, headers=headers)
            elif request.method == "POST":
                # Check if streaming is requested
                content_type = request.headers.get("content-type", "")
                if body and "json" in content_type:
                    payload = json.loads(body)
                    if payload.get("stream"):
                        async def _stream():
                            async with client.stream("POST", target_url, json=payload, headers=headers) as resp:
                                async for line in resp.aiter_lines():
                                    yield line + "\n"
                        return StreamingResponse(_stream(), media_type="text/event-stream",
                                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
                r = await client.post(target_url, content=body, headers=headers)
            elif request.method == "PUT":
                r = await client.put(target_url, content=body, headers=headers)
            elif request.method == "DELETE":
                r = await client.delete(target_url, headers=headers)
            else:
                raise HTTPException(405, "Method not allowed")

            # Forward response
            response_headers = {k: v for k, v in r.headers.items()
                               if k.lower() not in ("transfer-encoding", "content-encoding", "connection")}
            return StreamingResponse(
                iter([r.content]),
                status_code=r.status_code,
                headers=response_headers,
                media_type=r.headers.get("content-type"),
            )
    except httpx.ConnectError:
        raise HTTPException(503, f"LLM instance on port {port} is not reachable")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Proxy error: {str(e)}")
