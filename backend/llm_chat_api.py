"""ComfyUI Studio — LLM chat API (presets + conversations)."""

import json

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from config import DEV_MODE
from llm_server import (
    _get_running_instances, _get_instance_port, _is_running, _load_llm_config,
)
import llm_db as db

router = APIRouter()


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

    content = body.get("content", "").strip()
    if not content:
        raise HTTPException(400, "Missing 'content' field")

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

    # Save user message
    db.add_message(conv_id, "user", content)

    # Build messages array for llama-server
    llm_messages = []
    if conv.get("preset_id"):
        preset = db.get_preset(conv["preset_id"])
        if preset and preset.get("system_prompt"):
            llm_messages.append({"role": "system", "content": preset["system_prompt"]})

    for msg in conv["messages"]:
        if msg["role"] in ("user", "assistant"):
            llm_messages.append({"role": msg["role"], "content": msg["content"]})
    # Add the new user message (already saved but not in conv["messages"] snapshot)
    llm_messages.append({"role": "user", "content": content})

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
                            yield line + "\n"
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
