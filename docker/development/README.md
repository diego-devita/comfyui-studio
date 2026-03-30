# ComfyUI Studio -- Development Image

Lightweight Docker image (~200MB) for local development. No GPU, no CUDA, no PyTorch, no ComfyUI. Just Python, backend dependencies, and a stub server that fakes all ComfyUI API responses.

## Purpose

- Live code editing with hot reload (uvicorn `--reload`)
- Test backend/frontend changes without a GPU pod
- Inspect the SQLite database via sqlite-web
- Full backend functionality with stubbed external services

## How It Works

### ComfyUI Stub Server

A minimal Python server on port 8188 that responds to all ComfyUI API endpoints (`/system_stats`, `/prompt`, `/object_info`, `/ws`, etc.) with fake data. The backend thinks it's talking to a real ComfyUI instance.

### DEV_MODE=true

When `DEV_MODE=true`, the backend stubs out operations that require real infrastructure:

- **Downloads**: creates empty files after a configurable delay (no actual network transfer)
- **GPU stats**: returns fake VRAM/utilization numbers
- **LLM server**: simulated start/stop/status

### Host Mounts and Persistent Data

The host repository is mounted directly into the container -- backend, frontend, and workflows are live-editable. No bootstrap step, no `.repo/` staging area.

Persistent data (catalogs, database, assets, LLM models) lives in a volume at `DATA_DIR` (`STUDIO_DIR/data`), which should be mounted from `~/.studio-dev` on the host. This data survives container rebuilds.

On first boot, `start.sh`:

1. Creates DATA_DIR subdirectories: `catalogs`, `database`, `assets/{input,output}`, `llm/{models,logs}`, `presets`
2. Creates a fake ComfyUI directory tree (so model download paths resolve)
3. Seeds catalog files (`models.json`, `loras.json`, `llm.json`) from the image into DATA_DIR (only if they don't already exist)
4. Symlinks DATA_DIR subdirectories into STUDIO_DIR so the backend finds everything at expected paths

## Build & Run

```bash
# Build the image (from repo root)
docker build -f docker/development/Dockerfile -t comfyui-studio-dev .

# Run the container
docker run -d --name studio-dev \
  -p 8000:8000 -p 8188:8188 -p 8002:8002 \
  -v $(pwd)/backend:/workspace/studio/backend \
  -v $(pwd)/frontend:/workspace/studio/frontend \
  -v $(pwd)/workflows:/workspace/studio/workflows \
  -v $(pwd)/version.json:/workspace/studio/version.json \
  -v ~/.studio-dev:/workspace/studio/data \
  -e API_KEY=test \
  comfyui-studio-dev
```

Or use the shortcut script (from repo root):

```bash
./docker/dev.sh build   # rebuild image
./docker/dev.sh         # start (or restart)
./docker/dev.sh logs    # tail logs
./docker/dev.sh bash    # shell inside container
./docker/dev.sh reset   # wipe all data and restart fresh
```

## Directory Structure

```
/workspace/studio/           <- STUDIO_DIR
|-- backend/                 <- mounted from host (live)
|-- frontend/                <- mounted from host (live)
|-- workflows/               <- mounted from host (live)
|-- version.json             <- mounted from host (live)
|-- catalogs -> data/catalogs   <- symlink to persistent
|-- database -> data/database   <- symlink to persistent
|-- assets -> data/assets       <- symlink to persistent
|-- llm -> data/llm             <- symlink to persistent
|-- presets -> data/presets      <- symlink to persistent
`-- data/                    <- persistent volume (~/.studio-dev)
    |-- catalogs/            <- seeded from image on first boot
    |-- database/            <- studio.db created by backend
    |-- assets/input/
    |-- assets/output/
    |-- llm/models/
    |-- llm/logs/
    |-- presets/
    `-- comfyui/             <- fake ComfyUI tree (symlinked to /workspace/ComfyUI)
```

## Differences from Production

| Aspect | Production | Development |
|--------|-----------|-------------|
| Bootstrap | `bootstrap.py` clones repo, copies to working dirs | Repo mounted directly, no bootstrap |
| ComfyUI | Real ComfyUI with GPU | Stub server (fake responses) |
| DEV_MODE | `false` | `true` (stubs downloads, GPU stats, LLM) |
| Code reload | Manual restart or in-app update | Automatic hot reload on file changes |
| Database browser | None | sqlite-web on port 8002 |
| GPU | Required | Not required |
| Image size | ~25GB | ~200MB |

## Ports

| Port | Service |
|------|---------|
| 8000 | Studio backend (hot reload) |
| 8188 | ComfyUI stub server |
| 8002 | sqlite-web database browser |

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `API_KEY` | `changeme` | Auth API key |
| `DEV_MODE` | `true` | Enable development stubs |
| `DEV_DOWNLOAD_DELAY` | `5` | Seconds to simulate download time |
| `STUDIO_PORT` | `8000` | Studio backend port |
| `COMFYUI_PORT` | `8188` | ComfyUI stub port |
| `SQLITE_WEB_PORT` | `8002` | sqlite-web port |
