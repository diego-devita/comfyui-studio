# ComfyUI Studio

A complete platform for AI image and video generation built on ComfyUI. Runs as a Docker container on RunPod (or any NVIDIA GPU machine) with a dedicated web interface for managing models, workflows, custom nodes, and running generation jobs — without ever touching the ComfyUI graph editor.

The system is split into two independent layers:

1. **The Docker image** — ComfyUI + 28 custom nodes + performance optimizations, configured for a specific GPU. Rebuilt only when infrastructure changes.
2. **The web application** — homepage, model manager, workflow manager, node manager, and workflow runner. Updated live from the Git repository without rebuilding the image.

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
  - [Authentication](#authentication)
  - [Homepage](#homepage)
  - [Model Manager](#model-manager)
  - [Workflow Manager](#workflow-manager)
  - [Node Manager](#node-manager)
  - [Workflow Runner](#workflow-runner)
- [Live Updates](#live-updates)
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
│   /comfyui        ComfyUI + 28 custom nodes                 │
│   /app            Web app baseline (fallback)                │
│   /start.sh       Boot script                                │
│                                                              │
│   NOT in image:   models, workflows, catalogs, live app code │
├─────────────────────────────────────────────────────────────┤
│                   PERSISTENT VOLUME (runtime)                 │
│                                                              │
│   /workspace/app/               ← live app code (from repo)  │
│   /workspace/www/               ← live frontend (from repo)  │
│   /workspace/ComfyUI/           ← copied from /comfyui       │
│   /workspace/ComfyUI/models/    ← downloaded via Model Mgr   │
│   /workspace/models.json        ← fetched from repo          │
│   /workspace/workflows/         ← fetched from repo          │
│   /workspace/version.json       ← tracks component versions  │
└─────────────────────────────────────────────────────────────┘
```

**Port 8188** — ComfyUI (direct access to the graph editor, for advanced use)

**Port 8000** — ComfyUI Studio web application:
- `/home` — dashboard with system status and update controls
- `/admin/models` — download, delete, and organize AI models
- `/admin/workflows` — browse workflows, check dependencies, sync updates
- `/admin/nodes` — view installed custom nodes, install new ones
- `/run/{id}` — run a workflow through a simple form

On first boot, `start.sh`:
1. Copies the baked app baseline to `/workspace/app/` (one-time)
2. Fetches the latest model catalog, workflows, and version manifest from the Git repository
3. Copies ComfyUI to the persistent volume
4. Starts ComfyUI (port 8188) and the web application (port 8000)

On subsequent boots, it reuses everything already on the volume. Updates are pulled on-demand from the web UI — no rebuild needed.

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
  -e API_KEY=your-secret-key \
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

After the pod starts, open `https://<PODID>-8000.proxy.runpod.net` — you'll see the login page. Enter your API key to access the dashboard.

---

## Part 1: Docker Image

The Docker image contains everything needed to run ComfyUI: Python, PyTorch, CUDA libraries, ComfyUI itself, 28 custom nodes, and performance optimizations. It does **not** contain models, workflows, or the live application code — those are loaded dynamically at runtime from the Git repository.

The image is rebuilt only when infrastructure changes (Dockerfile, custom nodes, system libraries). All application logic and data updates happen live.

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

Python interpreter version. 3.12 is recommended for ComfyUI.

#### `ENABLE_SAGE_ATTENTION`

**Default: `true`**

Installs SageAttention 2 + Triton for 2-3x faster attention computation.

| GPU | What you get |
|-----|-------------|
| Hopper / Blackwell (H100, H200, B200) | SageAttention **v2** with FP8 kernels |
| Ampere / Ada Lovelace (A100, RTX 30xx/40xx, L40, L4) | SageAttention **v1** |
| Turing / Volta (RTX 20xx, T4, V100) | **Not supported** — set to `false` |

#### `ENABLE_FLASH_ATTENTION`

**Default: `true`**

Installs FlashAttention for memory-efficient fused attention kernels. Builds from source (20-30 min). Disabled in CI builds (no GPU on runner).

| GPU | What you get |
|-----|-------------|
| Hopper / Blackwell | FlashAttention **v3** |
| Ampere / Ada Lovelace | FlashAttention **v2** |
| Turing / Volta | **Not supported** — set to `false` |

### GPU Compatibility Table

| GPU | VRAM | Arch | CUDA_VERSION | PYTORCH_INDEX | SAGE_ATTN | FLASH_ATTN |
|-----|------|------|-------------|---------------|-----------|------------|
| B200 | 192 GB | SM 100 | `12.8.1` | `cu128` | v2 (fp8) | v3 |
| B100 | 80 GB | SM 100 | `12.8.1` | `cu128` | v2 (fp8) | v3 |
| H200 | 141 GB | SM 90 | `12.8.1` | `cu128` | v2 (fp8) | v3 |
| H100 | 80 GB | SM 90 | `12.8.1` | `cu128` | v2 (fp8) | v3 |
| A100 (80 GB) | 80 GB | SM 80 | `12.4.1` | `cu124` | v1 | v2 |
| A100 (40 GB) | 40 GB | SM 80 | `12.4.1` | `cu124` | v1 | v2 |
| A6000 | 48 GB | SM 86 | `12.4.1` | `cu124` | v1 | v2 |
| L40S | 48 GB | SM 89 | `12.4.1` | `cu124` | v1 | v2 |
| L40 | 48 GB | SM 89 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 4090 | 24 GB | SM 89 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 4080 | 16 GB | SM 89 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 3090 | 24 GB | SM 86 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 3080 | 10 GB | SM 86 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 3060 | 12 GB | SM 86 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 2080 Ti | 11 GB | SM 75 | `12.1.1` | `cu121` | no | no |
| T4 | 16 GB | SM 75 | `12.1.1` | `cu121` | no | no |
| V100 | 16-32 GB | SM 70 | `12.1.1` | `cu121` | no | no |

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

**Fundamentals / QoL (9)** — ComfyUI-Manager, ComfyUI_essentials, rgthree-comfy, cg-use-everywhere, ComfyLiterals, ComfyUI-Custom-Scripts, ComfyUI-KJNodes, was-node-suite-comfyui, ComfyUI-Easy-Use.

**Image Generation (11)** — ComfyUI-Advanced-ControlNet, ComfyUI_IPAdapter_plus, ComfyUI_InstantID, ComfyUI-ReActor, ComfyUI_FaceAnalysis, ComfyUI-Impact-Pack, ComfyUI-Inspire-Pack, ComfyUI_UltimateSDUpscale, comfyui_controlnet_aux, ComfyUI-layerdiffuse, ComfyUI-BRIA_AI-RMBG.

**Video Generation (5)** — ComfyUI-VideoHelperSuite, ComfyUI-Frame-Interpolation, ComfyUI-AnimateDiff-Evolved, ComfyUI-WanVideoWrapper, ComfyUI-HunyuanVideoWrapper.

**CivitAI Integration (2)** — civitai_comfy_nodes (official), ComfyUI-EasyCivitai-XTNodes.

Additional nodes can be installed at runtime through the Node Manager or ComfyUI-Manager. Runtime-installed nodes persist across pod restarts. To permanently add a node to the Docker image, add its URL to `nodes.txt` and rebuild.

### Performance Optimizations

| Optimization | Installed | Benefit |
|-------------|-----------|---------|
| **xformers** | Always | Memory-efficient attention, all GPUs |
| **SageAttention** | Conditional | 2-3x faster attention (Ampere+) |
| **FlashAttention** | Conditional | Fused attention kernels (Ampere+) |
| **torch.compile** | Built into PyTorch | ~20-30% speedup, no install needed |

---

## Part 2: Web Application

The web application runs on port 8000. All pages except the login page are protected by authentication.

### Authentication

ComfyUI Studio uses a **cookie-based authentication** system with a single API key:

1. Navigate to any page → redirected to `/login`
2. Enter your API key (the `API_KEY` environment variable)
3. A signed session cookie is set (valid for 7 days)
4. All subsequent requests are authenticated via the cookie

There is no username — just the API key. No browser popup, no Basic Auth.

**Programmatic access** (curl, scripts) is also supported via the `X-API-Key` header:

```bash
curl -H "X-API-Key: your-key" https://pod:8000/api/admin/models
```

**Logout:** Click the Logout link in the navigation bar, or POST to `/api/auth/logout`.

### Homepage

**URL:** `/home`

The landing page after login. Shows:

- **System status table** — version number and date of each component (backend, frontend, models catalog, workflows), with status indicators
- **Quick stats** — total models (how many present), total workflows (how many ready), total node packages
- **ComfyUI status** — whether ComfyUI is running on port 8188
- **Disk usage** — total model storage and free space
- **Check for Updates** button — fetches the latest `version.json` from the repository and updates any component that has a newer version

### Model Manager

**URL:** `/admin/models`

Browse, download, and manage AI models across 10 categories (84 models in the catalog).

Features:
- Parallel downloads (1-10 concurrent, default 3, adjustable from UI)
- Real-time progress with per-download speed
- Tag-based filtering (categories, model tags, status)
- Sorting by name, size, or status
- Compact / extended view toggle
- Resource links to CivitAI / HuggingFace source pages
- Disk usage display
- Sync button to pull latest catalog from repository

### Workflow Manager

**URL:** `/admin/workflows`

Browse the workflow library and verify dependencies before running.

Features:
- Dependency checking (required models present/missing, required nodes installed/missing)
- One-click install of missing models
- Ready/warning/error indicators per workflow
- Sync button to pull latest workflows from repository
- Direct link to run each workflow

Each workflow is defined by a YAML manifest (`manifest.yaml`) declaring inputs, outputs, required models, and required nodes, plus a `workflow.json` in ComfyUI API format.

### Node Manager

**URL:** `/admin/nodes`

View all custom nodes installed in ComfyUI, grouped by package.

Features:
- Package list with node counts
- Search across all nodes
- Install new custom nodes by GitHub URL
- Restart notification after installation

### Workflow Runner

**URL:** `/run/{workflow-id}`

Run a workflow through a simple form — this is the page you share with end users who don't need to know about ComfyUI.

Features:
- Dynamic form built from the workflow manifest (image upload, text prompts, sliders, dropdowns, seed control)
- Real-time progress (current step, active node, percentage)
- Result display (video player or image viewer) with download button

---

## Live Updates

The application code, model catalog, and workflow library all live in this Git repository as source of truth. They are **not baked into the Docker image**. Instead:

1. On first boot, `start.sh` copies the baked baseline to `/workspace/` and fetches the latest versions from the repository
2. Everything runs from `/workspace/` (persistent volume)
3. The **Check for Updates** button on the homepage compares local `version.json` with the repository and updates changed components
4. Pushing changes to the repository does **not** trigger a Docker image rebuild (CI ignores `app/**`, `workflows/**`, `version.json`, `*.md`)
5. The Docker image is rebuilt only when infrastructure changes: `Dockerfile`, `start.sh`, `install_nodes.sh`, `nodes.txt`

### What happens when each component is updated

| Component | Where it goes | Restart needed? | When visible? |
|-----------|--------------|-----------------|---------------|
| **Frontend** (HTML/CSS/JS) | `/workspace/www/` | No | Next page load |
| **Backend** (main.py) | `/workspace/app/main.py` | Yes (automatic) | After 2-3 second restart |
| **Models catalog** | `/workspace/models.json` | No | Next API call |
| **Workflows** | `/workspace/workflows/` | No | Next API call |

### version.json

A manifest in the repository root that tracks the version of each component:

```json
{
  "app_version": "3.0.0",
  "date": "2026-03-21",
  "components": {
    "backend": {"version": "3.0.0", "file": "app/main.py"},
    "frontend": {"version": "3.0.0", "dir": "app/www/"},
    "models": {"version": "1.0.0", "file": "app/models.json"},
    "workflows": {"version": "1.0.0", "dir": "workflows/"}
  }
}
```

When you click "Check for Updates," the system fetches this file from the repository and compares each component's version against the local copy. Only changed components are downloaded.

---

## Environment Variables

Set these at runtime in the RunPod template or via `docker run -e`.

### Authentication

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `API_KEY` | **Yes** | `changeme` | The single password for the web application. Used for both browser login and programmatic `X-API-Key` header. **Change this before exposing the pod.** |

### Model Download Tokens

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CIVITAI_API_KEY` | For CivitAI models | _(empty)_ | CivitAI API token. Get one at [civitai.com/user/account](https://civitai.com/user/account). |
| `HF_TOKEN` | For gated HF models | _(empty)_ | HuggingFace access token. Get one at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens). |

**Never hardcode tokens in files or commit them to Git.**

### ComfyUI Runtime

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `COMFYUI_FLAGS` | No | `--highvram` | VRAM management. `--lowvram` for 8-12 GB, `--normalvram` for 16-24 GB, `--highvram` for 40 GB+. |
| `COMFYUI_EXTRA_ARGS` | No | _(empty)_ | Additional ComfyUI flags (e.g. `--force-fp16`). |

### Repository Source

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `REPO_BASE` | No | `https://raw.githubusercontent.com/diego-devita/comfyui-studio/main` | Base URL for fetching app updates, model catalog, and workflows. Change to point at a fork or private repository. |

### Download Settings

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MAX_CONCURRENT_DOWNLOADS` | No | `3` | Parallel model downloads (1-10). Also adjustable from the web UI. |

---

## Boot Sequence

When the container starts, `start.sh` runs these steps:

| Step | What happens | When |
|------|-------------|------|
| **0a** | Copy `/app` baseline to `/workspace/app/` | First boot only |
| **0b** | Fetch `version.json` from repo | First boot only |
| **0c** | Fetch `models.json` from repo to `/workspace/models.json` | First boot only |
| **0d** | Fetch workflows from repo to `/workspace/workflows/` | First boot only |
| **1** | Copy `/comfyui` to `/workspace/ComfyUI` | First boot only |
| **2** | Start ComfyUI on port 8188, wait for ready (max 120s) | Every boot |
| **3** | Start web application on port 8000 from `/workspace/app/` | Every boot |

On subsequent boots, steps 0a-1 are skipped. To force a refresh, delete the relevant file/directory on the volume and restart, or use the Check for Updates button.

---

## Project Structure

```
comfyui-studio/
│
├── Dockerfile                 Docker image (infrastructure only)
├── start.sh                   Container boot script
├── install_nodes.sh           Custom node installer (build time)
├── nodes.txt                  Custom node list (build time)
├── version.json               Component version manifest
│
├── app/                       Web application (source of truth)
│   ├── main.py                FastAPI backend (50+ endpoints)
│   ├── models.json            Model catalog (84 models)
│   └── www/
│       ├── styles.css          Design system
│       ├── login.html          Login page (API key)
│       ├── home.html           Homepage / dashboard
│       ├── models.html         Model Manager
│       ├── workflows.html      Workflow Manager
│       ├── nodes.html          Node Manager
│       └── runner.html         Workflow Runner
│
├── workflows/                  Workflow library (source of truth)
│   ├── index.json              Index with versions
│   ├── wan22-i2v-fp8/
│   │   ├── manifest.yaml       Inputs, outputs, dependencies
│   │   └── workflow.json       ComfyUI API format
│   └── wan22-i2v-kijai/
│       ├── manifest.yaml
│       └── workflow.json
│
└── .github/
    └── workflows/
        └── build.yml           CI/CD — build to ghcr.io
```

---

## CI/CD

GitHub Actions builds and pushes the Docker image to `ghcr.io` on every push to `main`, **except** when only these paths change:

- `app/**` — application code (updated live)
- `workflows/**` — workflow library (updated live)
- `version.json` — version manifest (updated live)
- `*.md` — documentation

The Docker image is rebuilt only when these files change:
- `Dockerfile`, `start.sh`, `install_nodes.sh`, `nodes.txt` — infrastructure
- `.github/workflows/build.yml` — CI configuration

Build arguments can be overridden via GitHub Actions repository variables:

| Variable | CI Default |
|----------|-----------|
| `CUDA_VERSION` | `12.8.1` |
| `PYTORCH_INDEX` | `cu128` |
| `ENABLE_SAGE_ATTENTION` | `true` |
| `ENABLE_FLASH_ATTENTION` | `false` (no GPU on CI runner) |

---

## Logs

| Service | Log file |
|---------|----------|
| ComfyUI | `/var/log/comfyui.log` |
| Web application | `/var/log/admin.log` |
