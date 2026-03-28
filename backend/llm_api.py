"""ComfyUI Studio — LLM endpoints (model list, download, delete, server control, chat)."""

import json

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from config import LLM_MODELS_DIR, LLAMA_SERVER_PORT, LLAMA_SERVER_PATH, DEV_MODE
import catalogs as _catalogs
from catalogs import _find_llm_model, _build_catalog_response
from download import _download_state, _enqueue_download
from events import _events
from llm_server import (
    _load_llm_config, _save_llm_config,
    _llama_server_running, _start_llama_server, _stop_llama_server,
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
    """Delete an LLM model file from disk."""
    model = _find_llm_model(filename)
    if not model:
        raise HTTPException(status_code=404, detail=f"LLM model '{filename}' not found in catalog")

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
    """Get LLM server status, config, and health."""
    config = _load_llm_config()
    running = _llama_server_running()
    active_model = config.get("_active_model", None)

    health = None
    if running:
        if DEV_MODE:
            health = {"status": "ok"}
        else:
            try:
                async with httpx.AsyncClient(timeout=3) as client:
                    r = await client.get(f"http://127.0.0.1:{LLAMA_SERVER_PORT}/health")
                    health = r.json() if r.status_code == 200 else {"status": "error", "code": r.status_code}
            except Exception:
                health = {"status": "unreachable"}

    return JSONResponse({
        "running": running,
        "active_model": active_model if running else None,
        "config": {k: v for k, v in config.items() if not k.startswith("_")},
        "health": health,
        "port": LLAMA_SERVER_PORT,
        "binary_exists": LLAMA_SERVER_PATH.exists(),
    })


@router.post("/api/admin/llm/start")
async def llm_start(request: Request):
    """Start the LLM server with a model and optional config overrides."""
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
        _start_llama_server(model_file, config)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"Failed to start LLM server: {str(e)}")

    return JSONResponse({"status": "started", "model": model_file, "port": LLAMA_SERVER_PORT})


@router.post("/api/admin/llm/stop")
async def llm_stop():
    """Stop the LLM server."""
    if not _llama_server_running():
        return JSONResponse({"status": "already_stopped"})

    _stop_llama_server()
    return JSONResponse({"status": "stopped"})


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
    """Proxy chat completions to llama-server /v1/chat/completions."""
    if not _llama_server_running():
        raise HTTPException(503, "LLM server is not running")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    # DEV_MODE: return a fake response without calling llama-server
    if DEV_MODE:
        return JSONResponse({
            "id": "dev-stub",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "[DEV MODE] This is a stub response. The LLM server is simulated in development mode.",
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
                    async with client.stream("POST", f"http://127.0.0.1:{LLAMA_SERVER_PORT}/v1/chat/completions", json=payload) as resp:
                        async for line in resp.aiter_lines():
                            yield line + "\n"
            return StreamingResponse(_stream(), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        else:
            async with httpx.AsyncClient(timeout=300) as client:
                r = await client.post(f"http://127.0.0.1:{LLAMA_SERVER_PORT}/v1/chat/completions", json=payload)
                return JSONResponse(r.json(), status_code=r.status_code)
    except httpx.ConnectError:
        raise HTTPException(503, "LLM server is not reachable")
    except Exception as e:
        raise HTTPException(500, f"LLM chat error: {str(e)}")
