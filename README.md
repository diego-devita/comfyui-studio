# ComfyUI Studio

Docker template for running ComfyUI on RunPod with 26 pre-installed custom nodes, a web-based model manager, and hardware-specific optimizations. Designed for image and video generation (Stable Diffusion, SDXL, Pony, Illustrious, Flux, WAN 2.1/2.2, HunyuanVideo, AnimateDiff).

Default configuration targets **NVIDIA B200** but can be built for any GPU from V100 to B200 via build arguments.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Docker Image                          │
│                                                          │
│  /comfyui          ComfyUI + 26 custom nodes (baked)     │
│  /app              Model Manager (FastAPI + web UI)      │
│  /start.sh         Boot script                           │
│                                                          │
├──────────────────────────────────────────────────────────┤
│                  RunPod Network Volume                    │
│                                                          │
│  /workspace/ComfyUI    ← copied from /comfyui on 1st boot│
│  /workspace/ComfyUI/models/   ← downloaded via manager   │
│  /workspace/models.json       ← optional catalog override│
│  /workspace/www/              ← optional UI override     │
└──────────────────────────────────────────────────────────┘
```

- **Port 8188** — ComfyUI (direct access, full UI)
- **Port 8000** — Model Manager (download/delete models, auth required)

On first boot, `start.sh` copies the baked ComfyUI installation to the persistent volume. On subsequent boots it reuses what's already there, so custom nodes installed at runtime via ComfyUI-Manager survive pod restarts.

Models are **not** included in the image (they're too large). Use the Model Manager on port 8000 to download them after the pod starts.

---

## Quick Start

### Default build (B200)

```bash
docker build -t comfyui-studio .
```

### Run

```bash
docker run -d --gpus all \
  -p 8188:8188 \
  -p 8000:8000 \
  -e API_KEY=your-secret-key \
  -e CIVITAI_API_KEY=your-civitai-token \
  -e HF_TOKEN=your-huggingface-token \
  comfyui-studio
```

### RunPod Template

Set these in the template environment variables:

| Variable | Value |
|----------|-------|
| `API_KEY` | A strong password for the Model Manager |
| `CIVITAI_API_KEY` | Your CivitAI API token |
| `HF_TOKEN` | Your HuggingFace access token |

Then access:
- `https://<PODID>-8188.proxy.runpod.net` — ComfyUI
- `https://<PODID>-8000.proxy.runpod.net/admin/models` — Model Manager

---

## Build Arguments

All build arguments have defaults optimized for B200. Override them with `--build-arg` for other GPUs.

### `CUDA_VERSION`

**Default: `12.8.1`**

The NVIDIA CUDA base image version. Must match the GPU architecture:

| GPU generation | CUDA_VERSION |
|----------------|-------------|
| Blackwell (B200, B100) | `12.8.1` |
| Hopper (H100, H200) | `12.8.1` |
| Ampere (A100, A6000, A5000, A4000) | `12.4.1` |
| Ada Lovelace (RTX 40xx, L40, L40S, L4) | `12.4.1` |
| Ampere consumer (RTX 30xx) | `12.4.1` |
| Turing (RTX 20xx, T4) | `12.1.1` |
| Volta (V100) | `12.1.1` |

### `PYTORCH_INDEX`

**Default: `cu128`**

The PyTorch wheel index tag. Must correspond to `CUDA_VERSION`:

| CUDA_VERSION | PYTORCH_INDEX |
|-------------|---------------|
| `12.8.1` | `cu128` |
| `12.4.1` | `cu124` |
| `12.1.1` | `cu121` |

### `PYTHON_VERSION`

**Default: `3.12`**

Python interpreter version. 3.12 is the recommended version for ComfyUI. Change only if a specific custom node requires something different.

### `ENABLE_SAGE_ATTENTION`

**Default: `true`**

Installs SageAttention 2 + Triton, providing 2-3x faster attention computation.

- **Hopper / Blackwell** (H100, H200, B200): SageAttention **v2** with FP8 kernels — maximum performance
- **Ampere / Ada Lovelace** (A100, RTX 30xx, RTX 40xx, L40, L4): SageAttention **v1** — significant speedup
- **Turing / Volta** (RTX 20xx, T4, V100): **not supported** — set to `false`

### `ENABLE_FLASH_ATTENTION`

**Default: `true`**

Installs FlashAttention, memory-efficient fused attention kernels. Builds from source, which adds 20-30 minutes to the Docker build.

- **Hopper / Blackwell**: FlashAttention **v3**
- **Ampere / Ada Lovelace**: FlashAttention **v2**
- **Turing / Volta**: **not supported** — set to `false`

---

## GPU Compatibility Table

Use this table to pick the right build arguments for your GPU.

| GPU | VRAM | Arch | CUDA_VERSION | PYTORCH_INDEX | SAGE_ATTN | FLASH_ATTN |
|-----|------|------|-------------|---------------|-----------|------------|
| B200 | 192 GB | SM 100 | `12.8.1` | `cu128` | v2 (fp8) | v3 |
| B100 | 80 GB | SM 100 | `12.8.1` | `cu128` | v2 (fp8) | v3 |
| H200 | 141 GB | SM 90 | `12.8.1` | `cu128` | v2 (fp8) | v3 |
| H100 | 80 GB | SM 90 | `12.8.1` | `cu128` | v2 (fp8) | v3 |
| H100 NVL | 94 GB | SM 90 | `12.8.1` | `cu128` | v2 (fp8) | v3 |
| A100 (80 GB) | 80 GB | SM 80 | `12.4.1` | `cu124` | v1 | v2 |
| A100 (40 GB) | 40 GB | SM 80 | `12.4.1` | `cu124` | v1 | v2 |
| A6000 | 48 GB | SM 86 | `12.4.1` | `cu124` | v1 | v2 |
| A5000 | 24 GB | SM 86 | `12.4.1` | `cu124` | v1 | v2 |
| A4000 | 16 GB | SM 86 | `12.4.1` | `cu124` | v1 | v2 |
| L40S | 48 GB | SM 89 | `12.4.1` | `cu124` | v1 | v2 |
| L40 | 48 GB | SM 89 | `12.4.1` | `cu124` | v1 | v2 |
| L4 | 24 GB | SM 89 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 4090 | 24 GB | SM 89 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 4080 SUPER | 16 GB | SM 89 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 4080 | 16 GB | SM 89 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 4070 Ti | 12 GB | SM 89 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 4060 Ti | 16 GB | SM 89 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 4060 | 8 GB | SM 89 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 3090 / Ti | 24 GB | SM 86 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 3080 Ti | 12 GB | SM 86 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 3080 | 10 GB | SM 86 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 3070 / Ti | 8 GB | SM 86 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 3060 | 12 GB | SM 86 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 2080 Ti | 11 GB | SM 75 | `12.1.1` | `cu121` | no | no |
| RTX 2080 SUPER | 8 GB | SM 75 | `12.1.1` | `cu121` | no | no |
| RTX 2070 | 8 GB | SM 75 | `12.1.1` | `cu121` | no | no |
| T4 | 16 GB | SM 75 | `12.1.1` | `cu121` | no | no |
| V100 (32 GB) | 32 GB | SM 70 | `12.1.1` | `cu121` | no | no |
| V100 (16 GB) | 16 GB | SM 70 | `12.1.1` | `cu121` | no | no |

**Additional optimizations always installed:**
- **xformers** — memory-efficient attention, works on all GPUs listed above
- **torch.compile** — no install needed (built into PyTorch), works on all GPUs, most effective on Ampere+

### Build examples

```bash
# B200 (default — just build with no args)
docker build -t comfyui-studio .

# A100 / RTX 4090 / RTX 3090
docker build -t comfyui-studio \
  --build-arg CUDA_VERSION=12.4.1 \
  --build-arg PYTORCH_INDEX=cu124 .

# T4 / V100 (no attention optimizations)
docker build -t comfyui-studio \
  --build-arg CUDA_VERSION=12.1.1 \
  --build-arg PYTORCH_INDEX=cu121 \
  --build-arg ENABLE_SAGE_ATTENTION=false \
  --build-arg ENABLE_FLASH_ATTENTION=false .
```

---

## Environment Variables

Set these at runtime (in the RunPod template or `docker run -e`).

### Authentication

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `API_KEY` | **Yes** | `changeme` | Password for the Model Manager (HTTP Basic Auth). Username can be anything. **Change this before exposing the pod.** |

### Model Download Tokens

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CIVITAI_API_KEY` | For CivitAI models | _(empty)_ | Your CivitAI API token. Required to download models from CivitAI. Get one at [civitai.com/user/account](https://civitai.com/user/account) under "API Keys". |
| `HF_TOKEN` | For gated HF models | _(empty)_ | Your HuggingFace access token. Required for gated models (Flux, some SDXL variants). Get one at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens). |

**Important:** never hardcode tokens in files or commit them to git. Always use environment variables.

### ComfyUI Runtime

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `COMFYUI_FLAGS` | No | `--highvram` | VRAM management flag passed to ComfyUI. Use `--lowvram` for GPUs with 8-12 GB, `--normalvram` for 16-24 GB, `--highvram` for 40 GB+. |
| `COMFYUI_EXTRA_ARGS` | No | _(empty)_ | Additional flags passed to ComfyUI (e.g. `--force-fp16`). |

---

## Custom Nodes

28 custom nodes are pre-installed in the Docker image, organized in four groups. The full list with descriptions is in [`nodes.txt`](nodes.txt).

### Fundamentals / QoL (9 nodes)

ComfyUI-Manager, ComfyUI_essentials, rgthree-comfy, cg-use-everywhere, ComfyLiterals, ComfyUI-Custom-Scripts, ComfyUI-KJNodes, was-node-suite-comfyui, ComfyUI-Easy-Use.

### Image Generation (11 nodes)

ComfyUI-Advanced-ControlNet, ComfyUI_IPAdapter_plus, ComfyUI_InstantID, ComfyUI-ReActor, ComfyUI_FaceAnalysis, ComfyUI-Impact-Pack, ComfyUI-Inspire-Pack, ComfyUI_UltimateSDUpscale, comfyui_controlnet_aux, ComfyUI-layerdiffuse, ComfyUI-BRIA_AI-RMBG.

### Video Generation (5 nodes)

ComfyUI-VideoHelperSuite, ComfyUI-Frame-Interpolation, ComfyUI-AnimateDiff-Evolved, ComfyUI-WanVideoWrapper, ComfyUI-HunyuanVideoWrapper.

### CivitAI Integration (2 nodes)

civitai_comfy_nodes (official), ComfyUI-EasyCivitai-XTNodes.

### Installing additional nodes

You can install more nodes at runtime through **ComfyUI-Manager** (in the ComfyUI interface). Nodes installed at runtime are saved to `/workspace/ComfyUI/custom_nodes/` and persist across pod restarts.

To permanently add a node to the Docker image, add its repo URL to `nodes.txt` and rebuild.

---

## Model Catalog

The model catalog is defined in [`app/models.json`](app/models.json). It contains 71 models across 10 categories (checkpoints, diffusion models, LoRA, VAE, text encoders, CLIP vision, ControlNet, IP-Adapter, upscalers, embeddings).

Models are **not baked into the image**. Use the Model Manager at `https://<PODID>-8000.proxy.runpod.net/admin/models` to download them after the pod starts.

The Model Manager supports:
- Downloading individual models or entire categories at once
- Real-time download progress
- Deleting models to free up space
- CivitAI and HuggingFace authentication (via environment variables)

### Overriding the catalog

To customize the model list without rebuilding the image, place a modified `models.json` at `/workspace/models.json`. The Model Manager checks this path first and falls back to the baked-in version.

---

## Project Structure

```
comfyui-studio/
├── Dockerfile              Build args, GPU table, optimizations, custom nodes
├── start.sh                Boot: copy to volume → ComfyUI → Model Manager
├── nodes.txt               Custom node list (read by Dockerfile at build time)
├── app/
│   ├── main.py             FastAPI backend (download queue, SSE, auth)
│   ├── models.json         Model catalog (10 categories, 71 models)
│   └── www/
│       └── index.html      Model Manager web UI
├── .github/
│   └── workflows/
│       └── build.yml       CI/CD — build and push to ghcr.io
└── README.md
```

---

## CI/CD

The GitHub Actions workflow builds and pushes the Docker image to `ghcr.io` on every push to `main`. Build arguments can be overridden via GitHub Actions repository variables:

| Variable | Default |
|----------|---------|
| `CUDA_VERSION` | `12.8.1` |
| `PYTORCH_INDEX` | `cu128` |
| `PYTHON_VERSION` | `3.12` |
| `ENABLE_SAGE_ATTENTION` | `true` |
| `ENABLE_FLASH_ATTENTION` | `true` |

---

## Logs

Inside the running container:

| Log | Path |
|-----|------|
| ComfyUI | `/var/log/comfyui.log` |
| Model Manager | `/var/log/admin.log` |
