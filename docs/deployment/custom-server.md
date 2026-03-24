# Custom Server

Run ComfyUI Studio on your own machine with Docker.

## Prerequisites

- NVIDIA GPU with CUDA support
- Docker with NVIDIA Container Toolkit installed
- At least 20 GB disk space for the Docker image
- At least 50 GB additional space for AI models

## Quick Start

### Pull the Image

```bash
docker pull ghcr.io/diego-devita/comfyui-studio:latest
```

### Run

```bash
docker run -d --gpus all \
  -p 8000:8000 \
  -p 8188:8188 \
  -v /path/to/data:/workspace \
  -e API_KEY=your-strong-password \
  -e CIVITAI_API_KEY=your-civitai-token \
  -e HF_TOKEN=your-hf-token \
  --name comfyui-studio \
  ghcr.io/diego-devita/comfyui-studio:latest
```

Replace `/path/to/data` with a directory on your host where you want persistent data (models, outputs, configuration).

### Access

Open `http://localhost:8000` and log in with your `API_KEY`.

## Build Your Own Image

If the pre-built image doesn't match your GPU, use the build configurator:

```bash
git clone https://github.com/diego-devita/comfyui-studio.git
cd comfyui-studio
docker/configure.sh
```

The configurator asks about your GPU and outputs the right `docker build` command. See [Build Configurator](../docker/configurator.md) for details.

## Environment Variables

Same as RunPod deployment. See [Environment Variables](../getting-started/environment-variables.md) for the full reference.

Key differences from RunPod:

| Variable | RunPod | Custom Server |
|----------|--------|---------------|
| `STUDIO_DIR` | `/workspace/studio` (network volume) | Wherever your `-v` mount points |
| `COMFYUI_FLAGS` | `--highvram` (datacenter GPUs) | May need `--normalvram` or `--lowvram` for consumer GPUs |
| `RUNPOD_API_KEY` | Auto-injected | Not available (disk telemetry won't show total volume size) |

## Volume Mount

The `-v` mount maps a host directory to `/workspace` inside the container. Everything persists there:

```
/path/to/data/
├── studio/          ← STUDIO_DIR (app code, catalogs, jobs, config)
└── ComfyUI/         ← ComfyUI installation + downloaded models
```

!!! tip "Use a fast SSD"
    AI model loading speed depends on disk I/O. NVMe SSDs make a noticeable difference compared to spinning disks, especially for large models (10+ GB).

## Stopping and Restarting

```bash
# Stop
docker stop comfyui-studio

# Start again (data persists)
docker start comfyui-studio

# View logs
docker logs -f comfyui-studio

# Remove (data in volume persists)
docker rm comfyui-studio
```

## Updating

### Application Updates (No Rebuild)

Click **Check for Updates** in the web UI, same as RunPod.

### Docker Image Updates (Rebuild)

```bash
docker pull ghcr.io/diego-devita/comfyui-studio:latest
docker stop comfyui-studio
docker rm comfyui-studio
# Re-run with the same docker run command
```

Your data in the volume mount is preserved across image updates.

## Networking

By default, both services bind to `0.0.0.0`:

- Port 8000: Studio web UI (password-protected)
- Port 8188: ComfyUI graph editor (NO authentication)

For security, consider:

- Only exposing port 8000: `-p 8000:8000` (omit `-p 8188:8188`)
- Binding to localhost only: `-p 127.0.0.1:8000:8000`
- Putting a reverse proxy (Nginx, Caddy) in front with HTTPS
