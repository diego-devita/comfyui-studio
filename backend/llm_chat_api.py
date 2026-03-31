"""ComfyUI Studio — LLM chat API (presets + conversations)."""

import base64
import json
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse

from config import DEV_MODE, LLM_IMAGES_DIR
from llm_server import (
    _get_running_instances, _get_instance_port, _is_running, _load_llm_config,
)
import llm_db as db

router = APIRouter()

# ── Image helpers ────────────────────────────────────────────────────────────

_b64_cache: dict[str, str] = {}  # image_id -> base64 string (LRU-ish, max 20)


def _resolve_content_for_llm(content):
    """Resolve llm:// image references to base64 data URIs for llama-server."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return content
    resolved = []
    for part in content:
        if part.get("type") == "image_url":
            url = part.get("image_url", {}).get("url", "")
            if url.startswith("llm://"):
                image_id = url.replace("llm://", "")
                b64 = _get_image_b64(image_id)
                if b64:
                    resolved.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
                    continue
        resolved.append(part)
    return resolved


def _get_image_b64(image_id: str) -> str | None:
    """Get base64 of an image, with in-memory cache."""
    if image_id in _b64_cache:
        return _b64_cache[image_id]
    path = LLM_IMAGES_DIR / image_id
    if not path.exists():
        return None
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    # Keep cache small
    if len(_b64_cache) >= 20:
        _b64_cache.pop(next(iter(_b64_cache)))
    _b64_cache[image_id] = b64
    return b64


# ── Helpers ──────────────────────────────────────────────────────────────────

def _find_instance_for_model(model: str, preferred_id: str = None) -> dict | None:
    """Find a running instance for the given model. Tries preferred first."""
    instances = _get_running_instances()
    alive = [i for i in instances if i["model"] == model and i.get("alive")]
    if not alive:
        return None
    if preferred_id:
        for i in alive:
            if i["instance_id"] == preferred_id:
                return i
    return alive[0]


# ── Preset endpoints ─────────────────────────────────────────────────────────

@router.get("/api/admin/llm/chat-presets")
async def chat_presets_list():
    return JSONResponse(db.list_presets())


@router.post("/api/admin/llm/chat-presets")
async def chat_preset_upsert(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    if not body.get("name"):
        raise HTTPException(400, "Missing 'name' field")
    result = db.upsert_preset(body)
    return JSONResponse(result)


@router.delete("/api/admin/llm/chat-presets/{preset_id}")
async def chat_preset_delete(preset_id: str):
    if not db.delete_preset(preset_id):
        raise HTTPException(404, "Preset not found")
    return JSONResponse({"status": "deleted", "id": preset_id})


# ── Preset example endpoints ─────────────────────────────────────────────────

@router.post("/api/admin/llm/chat-presets/{preset_id}/examples")
async def preset_example_add(preset_id: str, request: Request):
    if not db.get_preset(preset_id):
        raise HTTPException(404, "Preset not found")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    text = body.get("text", "").strip()
    if not text:
        raise HTTPException(400, "Missing 'text' field")
    example = db.add_example(preset_id, text)
    return JSONResponse(example)


@router.patch("/api/admin/llm/chat-presets/examples/{example_id}")
async def preset_example_update(example_id: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    text = body.get("text", "").strip()
    if not text:
        raise HTTPException(400, "Missing 'text' field")
    if not db.update_example(example_id, text):
        raise HTTPException(404, "Example not found")
    return JSONResponse({"status": "updated", "id": example_id})


@router.delete("/api/admin/llm/chat-presets/examples/{example_id}")
async def preset_example_delete(example_id: str):
    if not db.delete_example(example_id):
        raise HTTPException(404, "Example not found")
    return JSONResponse({"status": "deleted", "id": example_id})


# ── Chat image endpoints ──────────────────────────────────────────────────────

@router.post("/api/admin/llm/chat-images")
async def chat_image_upload(file: UploadFile = File(...)):
    """Upload an image for use in chat. Resizes to max 1024px, saves as JPEG."""
    LLM_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    ext = "jpg"
    image_id = uuid.uuid4().hex[:12] + "." + ext
    dest = LLM_IMAGES_DIR / image_id

    data = await file.read()
    # Resize with Pillow if available
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(data))
        if img.mode == "RGBA":
            img = img.convert("RGB")
        max_dim = 1024
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        data = buf.getvalue()
    except ImportError:
        pass  # No Pillow — save raw

    dest.write_bytes(data)
    return JSONResponse({"image_id": image_id})


@router.get("/api/admin/llm/chat-images/{image_id}")
async def chat_image_serve(image_id: str):
    """Serve a chat image."""
    path = LLM_IMAGES_DIR / image_id
    from media import serve_media
    return serve_media(path)


# ── Conversation endpoints ───────────────────────────────────────────────────

@router.get("/api/admin/llm/conversations")
async def conversations_list(model: str = None):
    return JSONResponse(db.list_conversations(model))


@router.post("/api/admin/llm/conversations")
async def conversation_create(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    model = body.get("model")
    if not model:
        raise HTTPException(400, "Missing 'model' field")
    conv = db.create_conversation(
        model=model,
        preset_id=body.get("preset_id"),
        title=body.get("title"),
    )
    return JSONResponse(conv)


@router.get("/api/admin/llm/conversations/{conv_id}")
async def conversation_get(conv_id: str):
    conv = db.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return JSONResponse(conv)


@router.delete("/api/admin/llm/conversations/{conv_id}")
async def conversation_delete(conv_id: str):
    if not db.delete_conversation(conv_id):
        raise HTTPException(404, "Conversation not found")
    return JSONResponse({"status": "deleted", "id": conv_id})


@router.post("/api/admin/llm/conversations/{conv_id}/reset")
async def conversation_reset(conv_id: str):
    if not db.reset_conversation(conv_id):
        raise HTTPException(404, "Conversation not found")
    return JSONResponse({"status": "reset", "id": conv_id})


@router.patch("/api/admin/llm/conversations/{conv_id}")
async def conversation_update(conv_id: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    db.update_conversation(conv_id, **body)
    conv = db.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return JSONResponse(conv)


# ── Message endpoint ─────────────────────────────────────────────────────────

@router.post("/api/admin/llm/conversations/{conv_id}/message")
async def conversation_message(conv_id: str, request: Request):
    """Send a message in a conversation. Streams response from llama-server."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    text_content = body.get("content", "").strip()
    image_id = body.get("image_id")
    if not text_content and not image_id:
        raise HTTPException(400, "Missing 'content' or 'image_id' field")

    # Build the user message content (string or multimodal array)
    if image_id:
        user_content = []
        user_content.append({"type": "image_url", "image_url": {"url": f"llm://{image_id}"}})
        if text_content:
            user_content.append({"type": "text", "text": text_content})
        else:
            user_content.append({"type": "text", "text": "Describe this image."})
    else:
        user_content = text_content

    # Load conversation
    conv = db.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    # Find running instance
    inst = _find_instance_for_model(conv["model"], conv.get("last_instance_id"))
    if not inst:
        raise HTTPException(503, f"No running instance for model '{conv['model']}'. Start one first.")

    instance_id = inst["instance_id"]
    port = inst["port"]

    # Save user message (stores llm:// references, not base64)
    db.add_message(conv_id, "user", user_content)

    # Build messages array for llama-server
    llm_messages = []
    if conv.get("preset_id"):
        preset = db.get_preset(conv["preset_id"])
        if preset and preset.get("system_prompt"):
            llm_messages.append({"role": "system", "content": preset["system_prompt"]})

    for msg in conv["messages"]:
        if msg["role"] in ("user", "assistant"):
            llm_messages.append({"role": msg["role"], "content": _resolve_content_for_llm(msg["content"])})
    # Add the new user message (already saved but not in conv["messages"] snapshot)
    llm_messages.append({"role": "user", "content": _resolve_content_for_llm(user_content)})

    # Determine temperature
    config = _load_llm_config()
    temperature = body.get("temperature")
    if temperature is None and conv.get("preset_id"):
        preset = db.get_preset(conv["preset_id"])
        if preset:
            temperature = preset.get("temperature")
    if temperature is None:
        temperature = config.get("temp", 0.7)

    payload = {
        "messages": llm_messages,
        "temperature": temperature,
        "stream": body.get("stream", True),
    }
    if body.get("max_tokens"):
        payload["max_tokens"] = body["max_tokens"]

    # DEV_MODE stub
    if DEV_MODE:
        import random, asyncio
        _dev_responses = [
            f"masterpiece, best quality, 1girl, {content.replace(' ', ', ')}, detailed, cinematic lighting",
            f"[DEV] Echo: {content}\n\nThis is a dev stub response. Instance: {instance_id}.",
            f"[DEV] Conversation has {len(conv['messages'])} messages. Temperature: {temperature}.",
        ]
        resp_content = random.choice(_dev_responses)

        if payload.get("stream"):
            async def _dev_stream():
                words = resp_content.split()
                for i, word in enumerate(words):
                    token = (" " if i > 0 else "") + word
                    chunk = {"id": "dev", "object": "chat.completion.chunk",
                             "choices": [{"index": 0, "delta": {"content": token}, "finish_reason": None}]}
                    yield f"data: {json.dumps(chunk)}\n\n"
                    await asyncio.sleep(0.03)
                yield f"data: {json.dumps({'id': 'dev', 'object': 'chat.completion.chunk', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
                yield "data: [DONE]\n\n"
                # Save after stream
                db.add_message(conv_id, "assistant", resp_content)
                p_tok = sum(len(m["content"].split()) for m in llm_messages)
                c_tok = len(resp_content.split())
                db.update_conversation(conv_id, last_instance_id=instance_id,
                                       token_usage={"prompt_tokens": p_tok, "completion_tokens": c_tok,
                                                     "total_tokens": p_tok + c_tok, "ctx_size": config.get("ctx_size", 4096)})
            return StreamingResponse(_dev_stream(), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        # Non-streaming dev
        db.add_message(conv_id, "assistant", resp_content)
        db.update_conversation(conv_id, last_instance_id=instance_id)
        return JSONResponse({"id": "dev", "object": "chat.completion",
                             "choices": [{"index": 0, "message": {"role": "assistant", "content": resp_content}, "finish_reason": "stop"}],
                             "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})

    # Production: proxy to llama-server
    try:
        if payload.get("stream"):
            async def _stream_and_save():
                full_content = ""
                usage = {}
                async with httpx.AsyncClient(timeout=300) as client:
                    async with client.stream("POST", f"http://127.0.0.1:{port}/v1/chat/completions", json=payload) as resp:
                        async for line in resp.aiter_lines():
                            if line.strip():
                                yield line + "\n\n"
                            if line.startswith("data:"):
                                data_str = line[5:].strip()
                                if data_str and data_str != "[DONE]":
                                    try:
                                        chunk = json.loads(data_str)
                                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                                        if "content" in delta:
                                            full_content += delta["content"]
                                        if "usage" in chunk:
                                            usage = chunk["usage"]
                                    except (json.JSONDecodeError, IndexError, KeyError):
                                        pass
                # Save after stream completes
                db.add_message(conv_id, "assistant", full_content or "(empty response)")
                token_data = {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                    "ctx_size": conv.get("token_usage", {}).get("ctx_size") or config.get("ctx_size", 4096),
                }
                db.update_conversation(conv_id, last_instance_id=instance_id, token_usage=token_data)

            return StreamingResponse(_stream_and_save(), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        else:
            async with httpx.AsyncClient(timeout=300) as client:
                r = await client.post(f"http://127.0.0.1:{port}/v1/chat/completions", json=payload)
                data = r.json()
            # Save response
            assistant_msg = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            db.add_message(conv_id, "assistant", assistant_msg or "(empty response)")
            usage = data.get("usage", {})
            token_data = {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
                "ctx_size": config.get("ctx_size", 4096),
            }
            db.update_conversation(conv_id, last_instance_id=instance_id, token_usage=token_data)
            return JSONResponse(data, status_code=r.status_code)

    except httpx.ConnectError:
        raise HTTPException(503, f"Instance '{instance_id}' on port {port} is not reachable")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Chat error: {str(e)}")
