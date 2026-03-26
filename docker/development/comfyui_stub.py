#!/usr/bin/env python3
"""ComfyUI Stub Server — fake responses for local development.

Responds to all ComfyUI API endpoints with plausible fake data so the
Studio backend can run without a real ComfyUI instance. No GPU, no models,
no actual inference — just enough to make the UI functional.

Generates real placeholder images (512x512 PNG) and stub MP4 videos so
the runner's output detection, history, and assets pages all work correctly.

Usage: python3 comfyui_stub.py --port 8188
"""

import argparse
import asyncio
import io
import json
import os
import random
import subprocess
import time
import uuid

from aiohttp import web
from PIL import Image, ImageDraw, ImageFont

# ── Configuration ─────────────────────────────────────────────

STUDIO_DIR = os.environ.get("STUDIO_DIR", "/workspace/studio")
OUTPUT_BASE = os.path.join(STUDIO_DIR, "assets", "output")

# ── Fake data ─────────────────────────────────────────────────

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
        "output_node": True,
    },
    "PreviewImage": {
        "input": {"required": {}},
        "output": [],
        "name": "PreviewImage",
        "display_name": "Preview Image",
        "category": "image",
        "python_module": "nodes",
        "output_node": True,
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
    "LoraLoader": {
        "input": {"required": {}},
        "output": ["MODEL", "CLIP"],
        "name": "LoraLoader",
        "display_name": "Load LoRA",
        "category": "loaders",
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
        "output_node": True,
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
    "Anything Everywhere": {
        "input": {"required": {}},
        "output": [],
        "name": "Anything Everywhere",
        "display_name": "Anything Everywhere",
        "category": "everywhere",
        "python_module": "custom_nodes.cg-use-everywhere",
    },
    "Anything Everywhere3": {
        "input": {"required": {}},
        "output": [],
        "name": "Anything Everywhere3",
        "display_name": "Anything Everywhere3",
        "category": "everywhere",
        "python_module": "custom_nodes.cg-use-everywhere",
    },
    "Prompts Everywhere": {
        "input": {"required": {}},
        "output": [],
        "name": "Prompts Everywhere",
        "display_name": "Prompts Everywhere",
        "category": "everywhere",
        "python_module": "custom_nodes.cg-use-everywhere",
    },
}

# Load external object_info dump if available (exported from production)
_object_info_path = os.path.join(os.path.dirname(__file__), "object_info.json")
if os.path.exists(_object_info_path):
    try:
        with open(_object_info_path) as f:
            FAKE_OBJECT_INFO = json.load(f)
        print(f"[stub] Loaded object_info from {_object_info_path} ({len(FAKE_OBJECT_INFO)} nodes)")
    except Exception as e:
        print(f"[stub] Warning: failed to load {_object_info_path}: {e}")

# Store for active prompts
active_prompts = {}


# ── Output generators ─────────────────────────────────────────

def _generate_placeholder_image(width=512, height=512, text="DEV MODE"):
    """Generate a placeholder PNG image with centered text."""
    img = Image.new("RGB", (width, height), color=(40, 40, 50))
    draw = ImageDraw.Draw(img)

    # Draw grid pattern
    for x in range(0, width, 64):
        draw.line([(x, 0), (x, height)], fill=(55, 55, 65), width=1)
    for y in range(0, height, 64):
        draw.line([(0, y), (width, y)], fill=(55, 55, 65), width=1)

    # Draw text — try large font, fall back to default
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (width - tw) // 2
    y = (height - th) // 2
    # Shadow
    draw.text((x + 2, y + 2), text, fill=(0, 0, 0), font=font)
    # Main text
    draw.text((x, y), text, fill=(180, 180, 255), font=font)

    # Timestamp
    ts = time.strftime("%H:%M:%S")
    try:
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    except Exception:
        font_sm = ImageFont.load_default()
    draw.text((10, height - 26), f"Stub output • {ts}", fill=(100, 100, 120), font=font_sm)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _generate_placeholder_video(output_path, width=512, height=512, duration=1, fps=8):
    """Generate a stub MP4 video using ffmpeg with lavfi color + text overlay."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=#28283A:size={width}x{height}:duration={duration}:rate={fps}",
        "-vf", "drawtext=text='DEV MODE':fontsize=36:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=10)
    except Exception:
        # Fallback: write a minimal file so something exists
        with open(output_path, "wb") as f:
            f.write(b"\x00" * 1024)


def _generate_preview_jpeg(width=256, height=256):
    """Generate a small JPEG for WS binary preview frames."""
    img = Image.new("RGB", (width, height), color=(40, 40, 50))
    draw = ImageDraw.Draw(img)
    draw.text((width // 4, height // 2 - 10), "PREVIEW", fill=(180, 180, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# ── Output file creation ──────────────────────────────────────

def _find_output_nodes(workflow):
    """Find output nodes and their output directories from the workflow."""
    outputs = []
    for nid, ndata in workflow.items():
        ct = ndata.get("class_type", "")
        inputs = ndata.get("inputs", {})
        prefix = inputs.get("filename_prefix", "")
        if ct == "SaveImage" and prefix:
            outputs.append({"node_id": nid, "type": "image", "prefix": prefix})
        elif ct == "PreviewImage" and prefix:
            outputs.append({"node_id": nid, "type": "preview", "prefix": prefix})
        elif ct == "VHS_VideoCombine" and prefix:
            outputs.append({"node_id": nid, "type": "video", "prefix": prefix})
    return outputs


def _create_output_files(workflow):
    """Create stub output files on disk matching what the runner expects.

    Returns a dict of {node_id: output_data} for the /history response.
    """
    output_nodes = _find_output_nodes(workflow)
    history_outputs = {}

    for out in output_nodes:
        prefix = out["prefix"]
        # prefix is like "20260326_120000_abc123/final" or "20260326_120000_abc123/preview"
        # ComfyUI writes to {output_directory}/{prefix}_00001.ext
        # The subfolder in history is the directory part of the prefix
        parts = prefix.rsplit("/", 1)
        if len(parts) == 2:
            subfolder = parts[0]
            base_name = parts[1]
        else:
            subfolder = ""
            base_name = parts[0]

        out_dir = os.path.join(OUTPUT_BASE, subfolder) if subfolder else OUTPUT_BASE
        os.makedirs(out_dir, exist_ok=True)

        if out["type"] == "video":
            filename = f"{base_name}_00001.mp4"
            filepath = os.path.join(out_dir, filename)
            _generate_placeholder_video(filepath)
            history_outputs[out["node_id"]] = {
                "gifs": [{"filename": filename, "subfolder": subfolder, "type": "output", "format": "video/h264-mp4"}]
            }
        elif out["type"] == "image":
            filename = f"{base_name}_00001_.png"
            filepath = os.path.join(out_dir, filename)
            with open(filepath, "wb") as f:
                f.write(_generate_placeholder_image())
            history_outputs[out["node_id"]] = {
                "images": [{"filename": filename, "subfolder": subfolder, "type": "output"}]
            }
        elif out["type"] == "preview":
            filename = f"{base_name}_00001_.png"
            filepath = os.path.join(out_dir, filename)
            with open(filepath, "wb") as f:
                f.write(_generate_placeholder_image(256, 256, "PREVIEW"))
            history_outputs[out["node_id"]] = {
                "images": [{"filename": filename, "subfolder": subfolder, "type": "output"}]
            }

    return history_outputs


# ── Handlers ──────────────────────────────────────────────────

async def system_stats(request):
    return web.json_response(FAKE_SYSTEM_STATS)


async def object_info(request):
    return web.json_response(FAKE_OBJECT_INFO)


async def prompt_handler(request):
    """Accept a workflow prompt and simulate queuing it."""
    data = await request.json()
    prompt_id = str(uuid.uuid4())
    client_id = data.get("client_id", "stub")
    workflow = data.get("prompt", {})

    active_prompts[prompt_id] = {
        "status": "queued",
        "client_id": client_id,
        "queued_at": time.time(),
        "workflow": workflow,
        "history_outputs": {},
    }

    # Simulate execution in background
    asyncio.create_task(_simulate_execution(prompt_id, client_id, workflow))

    return web.json_response({
        "prompt_id": prompt_id,
        "number": len(active_prompts),
        "node_errors": {},
    })


async def _simulate_execution(prompt_id, client_id, workflow):
    """Simulate a workflow execution with realistic progress messages.

    Sends the same WebSocket message sequence as real ComfyUI:
    execution_start → execution_cached → executing(node) → progress → executed → executing(None)
    """
    await asyncio.sleep(0.3)

    info = active_prompts.get(prompt_id)
    if not info:
        return

    # Create output files on disk
    history_outputs = _create_output_files(workflow)
    info["history_outputs"] = history_outputs
    info["status"] = "running"

    node_ids = list(workflow.keys())
    total_nodes = len(node_ids)

    # Track WS messages to send (the websocket_handler reads these)
    info["ws_queue"] = []

    # execution_start
    info["ws_queue"].append({
        "type": "execution_start",
        "data": {"prompt_id": prompt_id},
    })

    await asyncio.sleep(0.2)

    # Simulate each node executing
    for i, nid in enumerate(node_ids):
        ct = workflow[nid].get("class_type", "")

        # executing(node)
        info["ws_queue"].append({
            "type": "executing",
            "data": {"node": nid, "prompt_id": prompt_id},
        })

        # For sampler nodes, send progress steps
        if ct in ("KSampler", "KSamplerAdvanced"):
            total_steps = 20
            for step in range(1, total_steps + 1):
                info["ws_queue"].append({
                    "type": "progress",
                    "data": {"value": step, "max": total_steps, "prompt_id": prompt_id, "node": nid},
                })
                await asyncio.sleep(0.1)
        else:
            await asyncio.sleep(0.05)

        # If this node produced output, send executed message
        if nid in history_outputs:
            info["ws_queue"].append({
                "type": "executed",
                "data": {"node": nid, "output": history_outputs[nid], "prompt_id": prompt_id},
            })

    # executing(None) = completion signal
    info["ws_queue"].append({
        "type": "executing",
        "data": {"node": None, "prompt_id": prompt_id},
    })

    info["status"] = "completed"


async def upload_image(request):
    """Accept an image upload and save it to the ComfyUI input directory."""
    reader = await request.multipart()
    filename = None
    image_data = b""

    while True:
        field = await reader.next()
        if field is None:
            break
        if field.name == "image":
            filename = field.filename or f"stub_upload_{uuid.uuid4().hex[:8]}.png"
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                image_data += chunk

    if not filename:
        filename = f"stub_upload_{uuid.uuid4().hex[:8]}.png"

    # Save to ComfyUI input dir so LoadImage can find it
    input_dir = os.path.join(os.environ.get("COMFYUI_DIR", "/workspace/ComfyUI"), "input")
    os.makedirs(input_dir, exist_ok=True)
    with open(os.path.join(input_dir, filename), "wb") as f:
        if image_data:
            f.write(image_data)
        else:
            f.write(_generate_placeholder_image(512, 512, "UPLOADED"))

    return web.json_response({
        "name": filename,
        "subfolder": "",
        "type": "input",
    })


async def history(request):
    """Return history for a prompt_id with real output references."""
    prompt_id = request.match_info.get("prompt_id", "")
    info = active_prompts.get(prompt_id, {})

    if info.get("status") == "completed":
        outputs = info.get("history_outputs", {})
        return web.json_response({
            prompt_id: {
                "outputs": outputs,
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
    """Return a placeholder image for /view requests."""
    return web.Response(
        body=_generate_placeholder_image(512, 512, "VIEW"),
        content_type="image/png",
    )


async def websocket_handler(request):
    """WebSocket that sends progress messages matching real ComfyUI protocol."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    client_id = request.query.get("clientId", "stub")
    preview_jpeg = _generate_preview_jpeg()

    try:
        while True:
            for pid, info in list(active_prompts.items()):
                if info.get("client_id") != client_id:
                    continue

                ws_queue = info.get("ws_queue", [])
                while ws_queue:
                    msg = ws_queue.pop(0)

                    # Send text message
                    await ws.send_json(msg)

                    # Send binary preview frame after progress messages
                    if msg["type"] == "progress":
                        # ComfyUI sends a 4-byte header before the JPEG data
                        header = (1).to_bytes(4, byteorder="big")
                        await ws.send_bytes(header + preview_jpeg)

                    # If this is the completion signal, clean up after a delay
                    if msg["type"] == "executing" and msg["data"].get("node") is None:
                        # Keep in active_prompts briefly so /history can serve it
                        await asyncio.sleep(0.5)
                        break

            await asyncio.sleep(0.05)
    except Exception:
        pass

    return ws


# ── App ───────────────────────────────────────────────────────

def create_app():
    app = web.Application()
    app.router.add_get("/system_stats", system_stats)
    app.router.add_get("/object_info", object_info)
    app.router.add_post("/prompt", prompt_handler)
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
    print(f"[stub] Output base: {OUTPUT_BASE}")
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=args.port, print=None)
