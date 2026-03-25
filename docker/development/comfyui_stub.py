#!/usr/bin/env python3
"""ComfyUI Stub Server — fake responses for local development.

Responds to all ComfyUI API endpoints with plausible fake data so the
Studio backend can run without a real ComfyUI instance. No GPU, no models,
no actual inference — just enough to make the UI functional.

Usage: python3 comfyui_stub.py --port 8188
"""

import argparse
import asyncio
import json
import os
import random
import time
import uuid

from aiohttp import web

# ── Fake data ────────────────────────────────────────────────

FAKE_SYSTEM_STATS = {
    "system": {
        "os": "posix",
        "python_version": "3.12.0",
        "embedded_python": False,
    },
    "devices": [
        {
            "name": "cuda:0 NVIDIA Stub GPU (Development)",
            "type": "cuda",
            "index": 0,
            "vram_total": 24 * 1024 * 1024 * 1024,  # 24 GB
            "vram_free": 20 * 1024 * 1024 * 1024,   # 20 GB free
            "torch_vram_total": 24 * 1024 * 1024 * 1024,
            "torch_vram_free": 20 * 1024 * 1024 * 1024,
        }
    ],
}

# Minimal object_info with common node types the backend checks for
FAKE_OBJECT_INFO = {
    "CheckpointLoaderSimple": {
        "input": {"required": {"ckpt_name": [["model.safetensors"], {}]}},
        "output": ["MODEL", "CLIP", "VAE"],
        "output_name": ["MODEL", "CLIP", "VAE"],
        "name": "CheckpointLoaderSimple",
        "display_name": "Load Checkpoint",
        "category": "loaders",
        "python_module": "nodes",
    },
    "KSampler": {
        "input": {"required": {}},
        "output": ["LATENT"],
        "output_name": ["LATENT"],
        "name": "KSampler",
        "display_name": "KSampler",
        "category": "sampling",
        "python_module": "nodes",
    },
    "CLIPTextEncode": {
        "input": {"required": {}},
        "output": ["CONDITIONING"],
        "name": "CLIPTextEncode",
        "display_name": "CLIP Text Encode",
        "category": "conditioning",
        "python_module": "nodes",
    },
    "VAEDecode": {
        "input": {"required": {}},
        "output": ["IMAGE"],
        "name": "VAEDecode",
        "display_name": "VAE Decode",
        "category": "latent",
        "python_module": "nodes",
    },
    "SaveImage": {
        "input": {"required": {}},
        "output": [],
        "name": "SaveImage",
        "display_name": "Save Image",
        "category": "image",
        "python_module": "nodes",
    },
    "EmptyLatentImage": {
        "input": {"required": {}},
        "output": ["LATENT"],
        "name": "EmptyLatentImage",
        "display_name": "Empty Latent Image",
        "category": "latent",
        "python_module": "nodes",
    },
    "CLIPSetLastLayer": {
        "input": {"required": {}},
        "output": ["CLIP"],
        "name": "CLIPSetLastLayer",
        "display_name": "CLIP Set Last Layer",
        "category": "conditioning",
        "python_module": "nodes",
    },
    "LoraLoaderModelOnly": {
        "input": {"required": {}},
        "output": ["MODEL"],
        "name": "LoraLoaderModelOnly",
        "display_name": "Load LoRA (Model Only)",
        "category": "loaders",
        "python_module": "nodes",
    },
    "LoadImage": {
        "input": {"required": {}},
        "output": ["IMAGE", "MASK"],
        "name": "LoadImage",
        "display_name": "Load Image",
        "category": "image",
        "python_module": "nodes",
    },
    "VHS_VideoCombine": {
        "input": {"required": {}},
        "output": ["VHS_FILENAMES"],
        "name": "VHS_VideoCombine",
        "display_name": "Video Combine",
        "category": "Video Helper Suite",
        "python_module": "custom_nodes.ComfyUI-VideoHelperSuite",
    },
    "KSamplerAdvanced": {
        "input": {"required": {}},
        "output": ["LATENT"],
        "name": "KSamplerAdvanced",
        "display_name": "KSampler (Advanced)",
        "category": "sampling",
        "python_module": "nodes",
    },
    "WanImageToVideo": {
        "input": {"required": {}},
        "output": ["CONDITIONING"],
        "name": "WanImageToVideo",
        "display_name": "WAN Image to Video",
        "category": "conditioning/wan",
        "python_module": "custom_nodes.ComfyUI-WanVideoWrapper",
    },
    "RIFE VFI": {
        "input": {"required": {}},
        "output": ["IMAGE"],
        "name": "RIFE VFI",
        "display_name": "RIFE VFI",
        "category": "Video Helper Suite",
        "python_module": "custom_nodes.ComfyUI-Frame-Interpolation",
    },
    "IPAdapterFaceID": {
        "input": {"required": {}},
        "output": ["MODEL"],
        "name": "IPAdapterFaceID",
        "display_name": "IP-Adapter FaceID",
        "category": "ipadapter",
        "python_module": "custom_nodes.ComfyUI_IPAdapter_plus",
    },
}

# Store for active prompts
active_prompts = {}


# ── Handlers ─────────────────────────────────────────────────

async def system_stats(request):
    return web.json_response(FAKE_SYSTEM_STATS)


async def object_info(request):
    return web.json_response(FAKE_OBJECT_INFO)


async def prompt(request):
    """Accept a workflow prompt and simulate queuing it."""
    data = await request.json()
    prompt_id = str(uuid.uuid4())
    client_id = data.get("client_id", "stub")

    active_prompts[prompt_id] = {
        "status": "queued",
        "client_id": client_id,
        "queued_at": time.time(),
    }

    # Simulate execution in background
    asyncio.create_task(_simulate_execution(prompt_id, client_id))

    return web.json_response({
        "prompt_id": prompt_id,
        "number": len(active_prompts),
        "node_errors": {},
    })


async def _simulate_execution(prompt_id, client_id):
    """Simulate a workflow execution with fake progress."""
    await asyncio.sleep(0.5)
    active_prompts[prompt_id]["status"] = "running"

    # Simulate 10 steps
    for step in range(10):
        await asyncio.sleep(0.3)
        active_prompts[prompt_id]["step"] = step + 1

    # Mark as complete
    active_prompts[prompt_id]["status"] = "completed"
    active_prompts[prompt_id]["outputs"] = {
        "images": [{"filename": "stub_output.png", "subfolder": "", "type": "output"}]
    }


async def upload_image(request):
    """Accept an image upload and return a fake filename."""
    reader = await request.multipart()
    field = await reader.next()
    if field:
        # Read and discard the data
        while True:
            chunk = await field.read_chunk()
            if not chunk:
                break

    filename = f"stub_upload_{uuid.uuid4().hex[:8]}.png"
    return web.json_response({
        "name": filename,
        "subfolder": "",
        "type": "input",
    })


async def history(request):
    """Return fake history for a prompt_id."""
    prompt_id = request.match_info.get("prompt_id", "")
    info = active_prompts.get(prompt_id, {})

    if info.get("status") == "completed":
        return web.json_response({
            prompt_id: {
                "outputs": {
                    "9": {"images": [{"filename": "stub_output.png", "subfolder": "", "type": "output"}]}
                },
                "status": {"completed": True, "messages": []},
            }
        })

    return web.json_response({})


async def queue(request):
    """Return fake queue status."""
    running = [pid for pid, p in active_prompts.items() if p.get("status") == "running"]
    pending = [pid for pid, p in active_prompts.items() if p.get("status") == "queued"]
    return web.json_response({
        "queue_running": [[0, pid, {}, {}] for pid in running],
        "queue_pending": [[0, pid, {}, {}] for pid in pending],
    })


async def view(request):
    """Return a fake 1x1 PNG pixel for image view requests."""
    # Minimal valid PNG: 1x1 transparent pixel
    png_data = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
        b'\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
        b'\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01'
        b'\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    return web.Response(body=png_data, content_type="image/png")


async def websocket_handler(request):
    """Fake WebSocket that sends progress updates for active prompts."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    client_id = request.query.get("clientId", "stub")

    try:
        while True:
            # Check for active prompts and send progress
            for pid, info in list(active_prompts.items()):
                if info.get("client_id") != client_id:
                    continue

                status = info.get("status")
                if status == "running":
                    step = info.get("step", 0)
                    await ws.send_json({
                        "type": "progress",
                        "data": {"value": step, "max": 10, "prompt_id": pid},
                    })
                elif status == "completed":
                    await ws.send_json({
                        "type": "executed",
                        "data": {
                            "node": "9",
                            "output": {"images": [{"filename": "stub_output.png"}]},
                            "prompt_id": pid,
                        },
                    })
                    await ws.send_json({
                        "type": "executing",
                        "data": {"node": None, "prompt_id": pid},
                    })
                    # Clean up
                    del active_prompts[pid]
                    break

            await asyncio.sleep(0.15)
    except Exception:
        pass

    return ws


# ── App ──────────────────────────────────────────────────────

def create_app():
    app = web.Application()
    app.router.add_get("/system_stats", system_stats)
    app.router.add_get("/object_info", object_info)
    app.router.add_post("/prompt", prompt)
    app.router.add_post("/upload/image", upload_image)
    app.router.add_get("/history/{prompt_id}", history)
    app.router.add_get("/history", lambda r: web.json_response({}))
    app.router.add_get("/queue", queue)
    app.router.add_get("/view", view)
    app.router.add_get("/ws", websocket_handler)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ComfyUI Stub Server")
    parser.add_argument("--port", type=int, default=8188)
    args = parser.parse_args()

    print(f"[stub] ComfyUI stub server starting on port {args.port}")
    print(f"[stub] Endpoints: /system_stats, /object_info, /prompt, /upload/image, /history, /queue, /view, /ws")
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=args.port, print=None)
