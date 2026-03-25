# Development Image

A lightweight Docker image for local development and testing. No GPU, no CUDA, no PyTorch, no ComfyUI — just Python, the backend dependencies, and a ComfyUI stub server.

## Why

The production image is 12 GB because of CUDA, PyTorch, and 38 custom nodes. For developing the Studio application (backend, frontend, workflows), you don't need any of that. The development image is ~200 MB and builds in 30 seconds.

## What's Included

| Component | Size | Purpose |
|-----------|------|---------|
| Python 3.12 (slim) | ~150 MB | Runtime |
| fastapi, uvicorn, httpx, requests, pyyaml, huggingface_hub, aiofiles, python-multipart | ~50 MB | Backend dependencies |
| aiohttp | ~5 MB | ComfyUI stub server |
| comfyui_stub.py | ~5 KB | Fake ComfyUI responses |

## What's NOT Included

- CUDA toolkit
- PyTorch, xformers, SageAttention, FlashAttention
- ComfyUI
- Custom nodes
- llama-server

## Build

From the repository root:

```bash
docker build -f docker/development/Dockerfile -t comfyui-studio-dev .
```

## Run

```bash
docker run -p 8000:8000 \
  -v $(pwd):/workspace/studio \
  -e API_KEY=test \
  comfyui-studio-dev
```

This mounts your entire repository as `/workspace/studio` inside the container. The backend runs from the mounted code with hot reload — every file change triggers an automatic restart (~1 second).

Open `http://localhost:8000` and log in with `test`.

## How It Works

The development entrypoint (`start.sh`) does three things:

1. **Creates directories** the backend expects (`assets/input`, `assets/output`, `db`, `jobs`, `llm/models`)
2. **Starts the ComfyUI stub** on port 8188 (background)
3. **Starts uvicorn** with `--reload` on port 8000

### Hot Reload

uvicorn watches two directories for changes:

- `backend/` — Python code changes trigger server restart
- `frontend/` — HTML/CSS/JS changes are served immediately (no restart needed, just refresh browser)

The reload happens in ~1 second. You edit a file in your IDE, save, refresh the browser, and see the change.

### ComfyUI Stub

The stub (`comfyui_stub.py`) is a minimal aiohttp server that responds to all 8 ComfyUI API endpoints the backend calls:

| Endpoint | Stub Response |
|----------|--------------|
| `GET /system_stats` | Fake GPU info (24 GB VRAM, "NVIDIA Stub GPU") |
| `GET /object_info` | Common node types (KSampler, SaveImage, LoadImage, etc.) |
| `POST /prompt` | Accepts workflow, returns prompt_id, simulates 3-second execution |
| `POST /upload/image` | Accepts upload, returns fake filename |
| `GET /history/{id}` | Returns fake output (stub_output.png) |
| `GET /queue` | Shows active/pending from simulated prompts |
| `GET /view` | Returns a 1x1 transparent PNG pixel |
| `WS /ws` | Sends fake progress updates (10 steps, 0.3s each) |

The stub simulates a ~3 second "generation" with progress updates. No real inference happens — it's just timers and fake data.

## What Works

- All pages render correctly
- Forms submit and validation works
- Job queue shows simulated progress
- Job history stores completed (fake) jobs
- Model catalog displays (no actual downloads)
- Settings page works
- Activity panel shows events
- WebSocket connection is live

## What Doesn't Work

- No actual image/video generation (stub returns a 1x1 pixel)
- Model downloads fail (no real HuggingFace/CivitAI connection from stub)
- LLM chat doesn't work (no llama-server)
- Preview frames are fake
- Object info has limited node types (add more to stub as needed)

## Adding Nodes to the Stub

If your workflow needs a specific node type that the stub doesn't report in `/object_info`, add it to `FAKE_OBJECT_INFO` in `comfyui_stub.py`:

```python
"MyCustomNode": {
    "input": {"required": {}},
    "output": ["IMAGE"],
    "name": "MyCustomNode",
    "display_name": "My Custom Node",
    "category": "custom",
    "python_module": "custom_nodes.MyNodePack",
},
```

## Environment Variables

The development image supports the same env vars as production, but most are irrelevant:

| Variable | Default | Relevant in dev? |
|----------|---------|-----------------|
| `API_KEY` | `changeme` | Yes — login password |
| `STUDIO_PORT` | `8000` | Yes — backend port |
| `COMFYUI_PORT` | `8188` | Yes — stub port |
| `STUDIO_DIR` | `/workspace/studio` | Yes — must match volume mount |
| Everything else | — | No — no GPU, no ComfyUI, no downloads |
