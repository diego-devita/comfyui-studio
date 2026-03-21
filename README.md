# ComfyUI Studio

A complete platform for AI image and video generation built on ComfyUI. Runs as a Docker container on RunPod (or any NVIDIA GPU machine) with a dedicated web interface for managing models, workflows, custom nodes, and running generation jobs — without ever touching the ComfyUI graph editor.

The system is split into two independent layers:

1. **The Docker image** — ComfyUI + 28 custom nodes + performance optimizations, configured for a specific GPU
2. **The web application** — model catalog, workflow library, node manager, and workflow runner, all served on a separate port and updated independently from the image

Default build targets **NVIDIA B200** (192 GB VRAM). Supports any GPU from V100 to B200 via build arguments.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Quick Start](#quick-start)
- [Part 1: Docker Image](#part-1-docker-image)
  - [Build Arguments](#build-arguments)
  - [GPU Compatibility Table](#gpu-compatibility-table)
  - [Build Examples](#build-examples)
  - [Custom Nodes](#custom-nodes)
  - [Performance Optimizations](#performance-optimizations)
- [Part 2: Web Application](#part-2-web-application)
  - [Model Manager](#model-manager)
  - [Workflow Manager](#workflow-manager)
  - [Node Manager](#node-manager)
  - [Workflow Runner](#workflow-runner)
  - [Dynamic Catalogs](#dynamic-catalogs)
- [Environment Variables](#environment-variables)
- [Boot Sequence](#boot-sequence)
- [Project Structure](#project-structure)
- [CI/CD](#cicd)
- [Logs](#logs)

---

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│                     DOCKER IMAGE (build time)                │
│                                                              │
│   /comfyui        ComfyUI + 28 custom nodes (baked in)      │
│   /app            Web application (FastAPI + HTML/JS/CSS)    │
│   /start.sh       Boot script                                │
│                                                              │
│   NOT in image:   models, workflows, model catalog           │
├─────────────────────────────────────────────────────────────┤
│                   PERSISTENT VOLUME (runtime)                 │
│                                                              │
│   /workspace/ComfyUI/           ← copied from /comfyui       │
│   /workspace/ComfyUI/models/    ← downloaded via Model Mgr   │
│   /workspace/models.json        ← fetched from repo          │
│   /workspace/workflows/         ← fetched from repo          │
│   /workspace/www/               ← optional UI overrides      │
└─────────────────────────────────────────────────────────────┘
```

**Port 8188** — ComfyUI (direct access to the graph editor, for advanced use)

**Port 8000** — ComfyUI Studio web application:
- `/admin/models` — download, delete, and organize AI models
- `/admin/workflows` — browse workflows, check dependencies, sync updates
- `/admin/nodes` — view installed custom nodes, install new ones
- `/run/{id}` — run a workflow through a simple form (no graph editor needed)

On first boot, `start.sh` does three things:
1. Fetches the model catalog and workflow library from the configured repository
2. Copies the baked ComfyUI installation to the persistent volume
3. Starts ComfyUI (port 8188) and the web application (port 8000)

On subsequent boots, it reuses everything already on the volume. Custom nodes installed at runtime via ComfyUI-Manager persist across restarts.

---

## Quick Start

### Build (default: B200)

```bash
docker build -t comfyui-studio .
```

### Run

```bash
docker run -d --gpus all \
  -p 8188:8188 \
  -p 8000:8000 \
  -e API_KEY=your-secret-password \
  -e CIVITAI_API_KEY=your-civitai-token \
  -e HF_TOKEN=your-huggingface-token \
  comfyui-studio
```

### RunPod Template

Container image: `ghcr.io/diego-devita/comfyui-studio:latest`

Environment variables to set:

| Variable | Value |
|----------|-------|
| `API_KEY` | A strong password for the web application |
| `CIVITAI_API_KEY` | Your CivitAI API token |
| `HF_TOKEN` | Your HuggingFace access token |

Exposed ports: **8188** (ComfyUI), **8000** (Web App)

After the pod starts:
- `https://<PODID>-8000.proxy.runpod.net/admin/models` — start here to download models
- `https://<PODID>-8000.proxy.runpod.net/admin/workflows` — browse and run workflows
- `https://<PODID>-8188.proxy.runpod.net` — ComfyUI graph editor (advanced)

---

## Part 1: Docker Image

The Docker image contains everything needed to run ComfyUI: Python, PyTorch, CUDA libraries, ComfyUI itself, 28 custom nodes, and performance optimizations. It does **not** contain models or workflows — those are loaded dynamically at runtime.

### Build Arguments

All arguments have defaults optimized for B200. Override with `--build-arg` for other GPUs.

#### `CUDA_VERSION`

**Default: `12.8.1`**

The NVIDIA CUDA base image version. Must match your GPU architecture:

| GPU Generation | CUDA_VERSION |
|----------------|-------------|
| Blackwell (B200, B100) | `12.8.1` |
| Hopper (H100, H200) | `12.8.1` |
| Ampere (A100, A6000, A5000, A4000) | `12.4.1` |
| Ada Lovelace (RTX 40xx, L40, L40S, L4) | `12.4.1` |
| Ampere consumer (RTX 30xx) | `12.4.1` |
| Turing (RTX 20xx, T4) | `12.1.1` |
| Volta (V100) | `12.1.1` |

#### `PYTORCH_INDEX`

**Default: `cu128`**

PyTorch wheel index tag. Must correspond to `CUDA_VERSION`:

| CUDA_VERSION | PYTORCH_INDEX |
|-------------|---------------|
| `12.8.1` | `cu128` |
| `12.4.1` | `cu124` |
| `12.1.1` | `cu121` |

#### `PYTHON_VERSION`

**Default: `3.12`**

Python interpreter version. 3.12 is recommended for ComfyUI. Change only if a specific custom node requires a different version.

#### `ENABLE_SAGE_ATTENTION`

**Default: `true`**

Installs SageAttention 2 + Triton for 2-3x faster attention computation.

| GPU | What you get |
|-----|-------------|
| Hopper / Blackwell (H100, H200, B200) | SageAttention **v2** with FP8 kernels — maximum speedup |
| Ampere / Ada Lovelace (A100, RTX 30xx/40xx, L40, L4) | SageAttention **v1** — significant speedup |
| Turing / Volta (RTX 20xx, T4, V100) | **Not supported** — set to `false` |

#### `ENABLE_FLASH_ATTENTION`

**Default: `true`**

Installs FlashAttention for memory-efficient fused attention kernels. Builds from source, adding 20-30 minutes to the Docker build.

| GPU | What you get |
|-----|-------------|
| Hopper / Blackwell | FlashAttention **v3** |
| Ampere / Ada Lovelace | FlashAttention **v2** |
| Turing / Volta | **Not supported** — set to `false` |

**Note:** FlashAttention is disabled in CI builds (GitHub Actions has no GPU). It can be installed at runtime on the pod if needed.

### GPU Compatibility Table

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

### Build Examples

```bash
# B200 (default — no args needed)
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

### Custom Nodes

28 custom nodes are pre-installed in the Docker image, organized in four groups. The full list with descriptions is in [`nodes.txt`](nodes.txt).

**Fundamentals / QoL (9 nodes)** — ComfyUI-Manager, ComfyUI_essentials, rgthree-comfy, cg-use-everywhere, ComfyLiterals, ComfyUI-Custom-Scripts, ComfyUI-KJNodes, was-node-suite-comfyui, ComfyUI-Easy-Use.

**Image Generation (11 nodes)** — ComfyUI-Advanced-ControlNet, ComfyUI_IPAdapter_plus, ComfyUI_InstantID, ComfyUI-ReActor, ComfyUI_FaceAnalysis, ComfyUI-Impact-Pack, ComfyUI-Inspire-Pack, ComfyUI_UltimateSDUpscale, comfyui_controlnet_aux, ComfyUI-layerdiffuse, ComfyUI-BRIA_AI-RMBG.

**Video Generation (5 nodes)** — ComfyUI-VideoHelperSuite, ComfyUI-Frame-Interpolation, ComfyUI-AnimateDiff-Evolved, ComfyUI-WanVideoWrapper, ComfyUI-HunyuanVideoWrapper.

**CivitAI Integration (2 nodes)** — civitai_comfy_nodes (official), ComfyUI-EasyCivitai-XTNodes.

Additional nodes can be installed at runtime through the Node Manager (web UI) or ComfyUI-Manager. Runtime-installed nodes are saved to `/workspace/ComfyUI/custom_nodes/` and persist across pod restarts. To permanently add a node to the Docker image, add its URL to `nodes.txt` and rebuild.

### Performance Optimizations

The following optimizations are included in the image:

| Optimization | Installed | Benefit |
|-------------|-----------|---------|
| **xformers** | Always | Memory-efficient attention, works on all GPUs |
| **SageAttention** | Conditional | 2-3x faster attention (Ampere+) |
| **FlashAttention** | Conditional | Fused attention kernels (Ampere+) |
| **torch.compile** | Built into PyTorch | ~20-30% speedup on Ampere+, no install needed |

These work together automatically. ComfyUI and the custom nodes detect and use them when available.

---

## Part 2: Web Application

The web application runs on port 8000 and provides four pages accessible through a shared navigation bar. All pages are protected by HTTP Basic Auth (password = `API_KEY` environment variable).

### Model Manager

**URL:** `/admin/models`

Browse, download, and manage AI models across 10 categories: checkpoints, diffusion models, LoRA, VAE, text encoders, CLIP vision, ControlNet, IP-Adapter, upscalers, and embeddings.

Features:
- **Parallel downloads** — configurable concurrency (1-10, default 3)
- **Real-time progress** — per-download speed, global throughput, bytes transferred
- **Tag-based filtering** — filter by category, model tags (pony, sdxl, flux, wan, fp8, kijai...), and status (present/missing/queued/downloading)
- **Sorting** — by name, size, or status with ascending/descending toggle
- **Compact / extended view** — toggle between full cards and single-line rows
- **Resource links** — click through to the model page on CivitAI or HuggingFace
- **Disk usage** — shows total model storage and free space on the volume
- **Sync** — pull the latest model catalog from the repository without rebuilding the image

The model catalog ([`app/models.json`](app/models.json)) currently includes 84 models. See [Dynamic Catalogs](#dynamic-catalogs) for how it updates.

### Workflow Manager

**URL:** `/admin/workflows`

Browse the workflow library and verify that all dependencies (models and nodes) are satisfied before running.

Features:
- **Dependency checking** — for each workflow, shows which required models are present/missing and which required nodes are installed/missing
- **One-click install** — queue all missing models for download directly from the workflow card
- **Ready indicator** — green (all deps met), yellow (models missing), red (nodes missing)
- **Sync** — pull the latest workflows from the repository
- **Run** — opens the Workflow Runner for the selected workflow

Each workflow is defined by a YAML manifest that declares its inputs, outputs, required models, and required nodes. See [`workflows/`](workflows/) for examples.

### Node Manager

**URL:** `/admin/nodes`

View all custom nodes installed in ComfyUI, grouped by package.

Features:
- **Package list** — shows each custom node package with the nodes it provides
- **Search** — find a specific node across all packages
- **Install** — install a new custom node by providing a GitHub repository URL
- **Restart notice** — after installing a new node, ComfyUI must be restarted to load it

The node list is read from ComfyUI's `/object_info` API endpoint, so it always reflects what is actually loaded.

### Workflow Runner

**URL:** `/run/{workflow-id}`

Run a workflow through a simple form without touching the ComfyUI graph editor. This is the page you share with end users.

Features:
- **Dynamic form** — built automatically from the workflow manifest. Each input type renders as the appropriate control:
  - `image` — drag-and-drop file picker with preview
  - `text` — textarea (for prompts)
  - `float` — slider with numeric display
  - `int` — number input
  - `select` — dropdown menu
  - `seed` — number input with a "Random" button
- **Real-time progress** — shows current step, active node, and percentage
- **Result display** — video player (for video workflows) or image viewer, with download button
- **No ComfyUI knowledge required** — the user fills in a form and clicks "Generate"

### Dynamic Catalogs

Both the model catalog and the workflow library live in this Git repository as source of truth, but they are **not baked into the Docker image**. Instead:

1. On first boot, `start.sh` fetches the latest versions from the repository
2. They are stored on the persistent volume (`/workspace/models.json` and `/workspace/workflows/`)
3. They can be updated at any time through the "Sync" button in the web UI
4. Updating them does **not** require rebuilding or restarting the Docker image
5. Pushes that only change `workflows/**` or `app/models.json` do **not** trigger a Docker image rebuild in CI

Both catalogs carry a version number and date, displayed in the web UI.

| Catalog | Source in repo | Stored at runtime | Sync endpoint |
|---------|---------------|-------------------|---------------|
| Models | [`app/models.json`](app/models.json) | `/workspace/models.json` | `POST /api/admin/models/sync` |
| Workflows | [`workflows/`](workflows/) | `/workspace/workflows/` | `POST /api/admin/workflows/sync` |

The source URLs are configurable via environment variables (`MODELS_REPO`, `WORKFLOWS_REPO`) so you can point them at a fork or private repository.

---

## Environment Variables

Set these at runtime in the RunPod template or via `docker run -e`.

### Authentication

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `API_KEY` | **Yes** | `changeme` | Password for the web application (HTTP Basic Auth). Username can be anything. **Change this before exposing the pod.** |

### Model Download Tokens

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CIVITAI_API_KEY` | For CivitAI models | _(empty)_ | CivitAI API token. Get one at [civitai.com/user/account](https://civitai.com/user/account) under "API Keys". |
| `HF_TOKEN` | For gated HF models | _(empty)_ | HuggingFace access token. Get one at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens). |

**Never hardcode tokens in files or commit them to Git. Always use environment variables.**

### ComfyUI Runtime

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `COMFYUI_FLAGS` | No | `--highvram` | VRAM management. Use `--lowvram` for 8-12 GB, `--normalvram` for 16-24 GB, `--highvram` for 40 GB+. |
| `COMFYUI_EXTRA_ARGS` | No | _(empty)_ | Additional ComfyUI flags (e.g. `--force-fp16`). |

### Catalog Sources

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MODELS_REPO` | No | GitHub raw URL for `app/models.json` | URL to fetch the model catalog from. Change to point at a fork or private repo. |
| `WORKFLOWS_REPO` | No | GitHub raw URL for `workflows/` | URL to fetch workflows from. Change to point at a fork or private repo. |

### Download Settings

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MAX_CONCURRENT_DOWNLOADS` | No | `3` | Number of parallel model downloads (1-10). Also adjustable from the web UI at runtime. |

---

## Boot Sequence

When the container starts, `start.sh` runs these steps in order:

| Step | What happens | When |
|------|-------------|------|
| **0a** | Fetch `models.json` from `MODELS_REPO` to `/workspace/models.json` | First boot only |
| **0b** | Fetch workflows from `WORKFLOWS_REPO` to `/workspace/workflows/` | First boot only |
| **1** | Copy `/comfyui` to `/workspace/ComfyUI` | First boot only |
| **2** | Start ComfyUI on port 8188, wait for it to be ready (max 120s) | Every boot |
| **3** | Start the web application on port 8000 | Every boot |

On subsequent boots, steps 0a, 0b, and 1 are skipped because the files already exist on the persistent volume. To force a re-fetch of catalogs, delete `/workspace/models.json` or `/workspace/workflows/index.json` and restart, or use the Sync button in the web UI.

---

## Project Structure

```
comfyui-studio/
│
├── Dockerfile                 Docker image definition
├── start.sh                   Container boot script
├── install_nodes.sh           Helper: installs nodes from nodes.txt
├── nodes.txt                  List of custom nodes to bake into the image
├── README.md                  This file
│
├── app/                       Web application (baked into image)
│   ├── main.py                FastAPI backend (40+ endpoints)
│   ├── models.json            Model catalog (source of truth)
│   └── www/
│       ├── styles.css          Shared design system
│       ├── index.html          Model Manager page
│       ├── workflows.html      Workflow Manager page
│       ├── nodes.html          Node Manager page
│       └── runner.html         Workflow Runner page
│
├── workflows/                  Workflow library (source of truth, NOT in Docker image)
│   ├── index.json              Workflow index with versions
│   ├── wan22-i2v-fp8/          Example workflow
│   │   ├── manifest.yaml       Inputs, outputs, dependencies
│   │   └── workflow.json       ComfyUI API format workflow
│   ├── wan22-i2v-kijai/        Another workflow
│   │   ├── manifest.yaml
│   │   └── workflow.json
│   └── reference/              Reference workflows (not executed)
│
└── .github/
    └── workflows/
        └── build.yml           CI/CD — build and push to ghcr.io
```

---

## CI/CD

GitHub Actions builds and pushes the Docker image to `ghcr.io` on every push to `main`, **except** when only these files change:
- `workflows/**` (workflow library updates)
- `app/models.json` (model catalog updates)
- `*.md` (documentation)

This means you can update the model catalog or add new workflows without triggering a full image rebuild.

Build arguments can be overridden via GitHub Actions repository variables:

| Variable | Default |
|----------|---------|
| `CUDA_VERSION` | `12.8.1` |
| `PYTORCH_INDEX` | `cu128` |
| `PYTHON_VERSION` | `3.12` |
| `ENABLE_SAGE_ATTENTION` | `true` |
| `ENABLE_FLASH_ATTENTION` | `false` (disabled in CI — no GPU on runner) |

---

## Logs

Inside the running container:

| Service | Log file |
|---------|----------|
| ComfyUI | `/var/log/comfyui.log` |
| Web application | `/var/log/admin.log` |
