# ComfyUI Studio

A web-based management platform for AI image and video generation built on ComfyUI. Runs as a Docker container on RunPod (or any NVIDIA GPU machine) with a dedicated interface for managing models, LoRAs, workflows, presets, and running generation jobs -- without touching the ComfyUI graph editor.

The Docker image provides ComfyUI + 38 custom nodes + performance optimizations (SageAttention, FlashAttention, xformers, WaveSpeed). The web application updates itself live from the Git repository without rebuilding the image.

Default build targets **NVIDIA B200** (192 GB VRAM). Supports any GPU from V100 to B200 via build arguments.

https://diego-devita.github.io/comfyui-studio/

---

## Deploy on RunPod

1. Go to [RunPod Console](https://runpod.io/console/deploy?template=rik3ydjtjv) and deploy the **ComfyUI Studio** template
2. Select a GPU -- any NVIDIA GPU from V100 to B200 works
3. Attach a **Network Volume** (50+ GB recommended) for persistent storage
4. Set your environment variables and launch

Once running, open `https://<POD_ID>-8000.proxy.runpod.net` and log in with your API key.
ComfyUI graph editor is also available at `https://<POD_ID>-8188.proxy.runpod.net`.

### Environment Variables

| Variable | Required | How to get it |
|----------|----------|---------------|
| `API_KEY` | **Yes** | Choose a strong password -- this is your login to the web UI |
| `CIVITAI_API_KEY` | Recommended | [civitai.com/user/account](https://civitai.com/user/account) → API Keys |
| `HF_TOKEN` | Recommended | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) → New token (Read) |

- Without `CIVITAI_API_KEY`: model downloads from CivitAI and metadata fetch won't work
- Without `HF_TOKEN`: gated models (Flux, WAN, Hunyuan, etc.) can't be downloaded from HuggingFace
- All three can be changed later from the Settings page -- changes persist on the network volume across restarts

### Disk Requirements

- **Container Disk:** 5 GB minimum
- **Network Volume:** 50+ GB recommended (models, outputs, workflows, and job history are stored here)

---

## Features

### Pre-installed

- **38 custom nodes** covering image generation, video generation, ControlNet, IP-Adapter, FaceID, face swap, upscaling, segmentation, CivitAI integration, and performance optimizations
- **Performance:** xformers, SageAttention, FlashAttention, torch.compile, WaveSpeed (FBCache)
- **LLM assistant:** llama.cpp server with CUDA for local inference (Qwen, Llama, etc.)

### Web Application

- **Model Manager** -- catalog of 126 models with one-click download from CivitAI and HuggingFace, disk scan, metadata fetch
- **LoRA Manager** -- style LoRA catalog with base model compatibility matching and pair grouping
- **Workflow Runner** -- 11 workflows with form UI, batch generation, scene chaining, conditional inputs
- **Preset System** -- save workflow parameters as reusable templates, run with one click
- **Telegram Bot** -- run presets from your phone, configurable from the Settings page
- **Job Queue** -- real-time progress via WebSocket with ETA, step rate, and live preview
- **Job History** -- completed/failed jobs with retry, re-run, output download
- **Asset Manager** -- browse input/output files with upload, delete, download
- **LLM Chat** -- download GGUF models, start/stop server, chat interface
- **Node Manager** -- view and install custom node packages at runtime
- **Chrome Extension** -- manage RunPod pods, storage, and launch GPUs from your browser
- **Live Updates** -- backend, frontend, catalogs, and workflows update from Git without image rebuild

---

## Pages

**Port 8000** -- ComfyUI Studio web application:

| URL | Page | Description |
|-----|------|-------------|
| `/home` | Homepage | Dashboard with component versions, telemetry gauges, update controls |
| `/admin/models` | Model Manager | Download, delete, organize AI models across categories |
| `/admin/loras` | LoRA Manager | LoRA catalog with base model compatibility and pair grouping |
| `/admin/workflows` | Workflow Manager | Browse workflows, check dependencies, sync updates |
| `/admin/nodes` | Node Manager | View and install custom node packages |
| `/admin/queue` | Job Queue | Active/queued jobs with real-time progress |
| `/admin/history` | Job History | Past jobs with retry, delete, and package download |
| `/admin/assets` | Asset Manager | Browse input/output files, upload, delete, download |
| `/admin/llm` | LLM Assistant | Download LLM models, start/stop llama-server, chat |
| `/admin/presets` | Presets | Save, manage, and run workflow presets |
| `/admin/settings` | Settings | API keys, Telegram bot, download concurrency, restart |
| `/run/{id}` | Workflow Runner | Execute workflows through a form UI |
| `/login` | Login | API key authentication |

**Port 8188** -- ComfyUI graph editor (direct access for advanced use).

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                    DOCKER IMAGE (build time)                          │
│                                                                      │
│  /comfyui           ComfyUI + 38 custom nodes (baked in)             │
│  /app/bootstrap.py  First-boot installer                             │
│  /opt/llama-server  llama.cpp server (CUDA, SM 75-100)               │
│  /start.sh          Boot script                                      │
│                                                                      │
│  NOT in image: models, workflows, live app code, user data           │
├──────────────────────────────────────────────────────────────────────┤
│                PERSISTENT VOLUME (runtime)                            │
│                                                                      │
│  /workspace/studio/                    ← STUDIO_DIR                  │
│    .repo/                              ← git clone (staging only)    │
│    backend/                            ← live Python backend         │
│    frontend/                           ← live frontend (HTML/CSS/JS) │
│    catalogs/                           ← models, loras, llm-models   │
│    workflows/                          ← workflow library            │
│    presets/                            ← saved presets               │
│    assets/input/ + assets/output/      ← ComfyUI I/O                │
│    jobs/                               ← job history records         │
│    llm/                                ← LLM models + config         │
│    db/                                 ← SQLite database             │
│    version.json                        ← component version tracking  │
│  /workspace/ComfyUI/                   ← copied from /comfyui       │
│  /workspace/ComfyUI/models/            ← downloaded via Model Mgr   │
└──────────────────────────────────────────────────────────────────────┘

Bootstrap flow (first boot only):
  1. bootstrap.py clones repo to STUDIO_DIR/.repo/
  2. Checks RUNTIME_VERSION >= min_runtime (blocks if incompatible)
  3. Copies backend/, frontend/, catalogs/, workflows/ to working dirs
  4. start.sh copies /comfyui → /workspace/ComfyUI
  5. Starts ComfyUI (port 8188) + Studio backend (port 8000)
  All output visible in RunPod container logs (stdout via tee)
```

---

## Live Updates

Application code, catalogs, and workflows live in this Git repository as source of truth. They are **not baked into the Docker image**.

1. On **first boot**, `bootstrap.py` downloads the latest from the repository
2. If the image's `RUNTIME_VERSION` is below `min_runtime`, bootstrap **blocks** with an error
3. The **Check for Updates** button on the homepage compares local vs remote versions
4. During updates the backend enters **maintenance mode** (503 with auto-reloading page)
5. Pushing to the repo does **not** trigger a Docker rebuild (CI ignores app code paths)

| Component | Restart needed? | When visible? |
|-----------|----------------|---------------|
| Frontend (HTML/CSS/JS) | No | Next page load |
| Backend (21 Python modules) | Yes (auto) | After ~2s restart |
| Model/LoRA/LLM catalogs | No | Next API call |
| Workflows | No | Next API call |

---

## Quick Start

### Build

The easiest way is the interactive configurator:

```bash
docker/configure.sh
```

Or build directly (default: B200, all features):

```bash
docker build -f docker/production/Dockerfile -t comfyui-studio .
```

### Run locally

```bash
docker run -d --gpus all \
  -p 8188:8188 \
  -p 8000:8000 \
  -e API_KEY=your-secret-key \
  -e CIVITAI_API_KEY=your-civitai-token \
  -e HF_TOKEN=your-huggingface-token \
  comfyui-studio
```

### Development

Lightweight image (~200 MB) without GPU, with ComfyUI stub and hot reload:

```bash
docker build -f docker/development/Dockerfile -t comfyui-studio-dev .
docker run -p 8000:8000 -v $(pwd):/workspace/studio -e API_KEY=test comfyui-studio-dev
```

### RunPod Template

Container image: `ghcr.io/diego-devita/comfyui-studio:latest`

| Variable | Value |
|----------|-------|
| `API_KEY` | A strong password for the web application |
| `CIVITAI_API_KEY` | Your CivitAI API token |
| `HF_TOKEN` | Your HuggingFace access token |

Exposed ports: **8188** (ComfyUI), **8000** (Studio)

---

## Environment Variables

### Authentication & API Tokens

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | `changeme` | Password for web login and `X-API-Key` header |
| `CIVITAI_API_KEY` | _(empty)_ | CivitAI API token for model downloads and metadata |
| `HF_TOKEN` | _(empty)_ | HuggingFace token for gated models (Flux, WAN, Hunyuan) |

### Configurable

| Variable | Default | Description |
|----------|---------|-------------|
| `COMFYUI_FLAGS` | `--highvram` | VRAM mode: `--highvram` (>24 GB), `--normalvram` (12-24 GB), `--lowvram` (<12 GB) |
| `COMFYUI_EXTRA_ARGS` | _(empty)_ | Additional ComfyUI launch flags |
| `STUDIO_DIR` | `/workspace/studio` | Root directory for all Studio data |
| `COMFYUI_DIR` | `/workspace/ComfyUI` | ComfyUI installation path |
| `MAX_CONCURRENT_DOWNLOADS` | `3` | Parallel model downloads (1-10, also adjustable from UI) |

### Read-only (set by infrastructure)

| Variable | Default | Set by |
|----------|---------|--------|
| `RUNTIME_VERSION` | `3` | Dockerfile |
| `REPO_URL` | `https://github.com/diego-devita/comfyui-studio.git` | Dockerfile |
| `REPO_BRANCH` | `main` | Dockerfile |
| `RUNPOD_*` | _(auto)_ | RunPod |

---

## Build Arguments

All arguments have defaults optimized for B200. See [`docker/README.md`](docker/README.md) for full details.

| Argument | Default | Description |
|----------|---------|-------------|
| `CUDA_VERSION` | `12.8.1` | NVIDIA CUDA base image version |
| `PYTORCH_INDEX` | `cu128` | PyTorch wheel index tag |
| `PYTHON_VERSION` | `3.12` | Python interpreter version |
| `ENABLE_SAGE_ATTENTION` | `true` | SageAttention 2 + Triton (Ampere+) |
| `ENABLE_FLASH_ATTENTION` | `true` | FlashAttention (Ampere+, builds from source) |
| `ENABLE_LLM` | `true` | llama.cpp server for local LLM inference |
| `LLAMA_CPP_VERSION` | `b8505` | llama.cpp release tag |

### GPU Compatibility

| GPU | VRAM | CUDA | SageAttn | FlashAttn |
|-----|------|------|----------|-----------|
| B200 / B100 | 80-192 GB | `12.8.1` | v2 (fp8) | v3 |
| H200 / H100 | 80-141 GB | `12.8.1` | v2 (fp8) | v3 |
| A100 / A6000 / A5000 / A4000 | 16-80 GB | `12.4.1` | v1 | v2 |
| L40S / L40 / L4 | 24-48 GB | `12.4.1` | v1 | v2 |
| RTX 4090 / 4080 / 4070 / 4060 | 8-24 GB | `12.4.1` | v1 | v2 |
| RTX 3090 / 3080 / 3070 / 3060 | 8-24 GB | `12.4.1` | v1 | v2 |
| RTX 2080 Ti / 2080 / 2070 / T4 | 8-16 GB | `12.1.1` | no | no |
| V100 | 16-32 GB | `12.1.1` | no | no |

---

## Project Structure

```
comfyui-studio/
├── backend/                  Python backend (21 modules, ~9000 lines)
│   ├── main.py               Entry point
│   ├── config.py             App instance, env vars, paths
│   ├── auth.py               Cookie auth, middleware, login/logout
│   ├── events.py             EventBus, WebSocket pusher, startup tasks
│   ├── db.py                 SQLite database, settings persistence
│   ├── pages.py              HTML page serve routes
│   ├── catalogs.py           Catalog loaders, version helper
│   ├── download.py           Download pool, state tracking, auth injection
│   ├── models_api.py         Model endpoints
│   ├── loras_api.py          LoRA endpoints, compatibility matching
│   ├── llm_api.py            LLM model + chat endpoints
│   ├── llm_server.py         llama-server process manager
│   ├── workflows_api.py      Workflow list, readiness, sync
│   ├── workflows.py          Workflow loading, dynamic pipeline assembler
│   ├── runner.py             Job execution, WS listener, progress tracking
│   ├── runner_api.py         Runner API: upload, execute, status, result
│   ├── presets_api.py        Preset CRUD and execution
│   ├── system_api.py         System status, update, telemetry, settings
│   ├── jobs_api.py           Queue, history, assets, output downloads
│   ├── gallery_db.py         Gallery database
│   └── telegram_bot.py       Telegram bot integration
│
├── frontend/
│   ├── css/                  styles.css, components.css, icons.css
│   ├── js/                   shared.js
│   └── pages/                13 HTML pages
│
├── catalogs/                 Model catalogs (source of truth)
│   ├── models.json           126 AI models (checkpoints, VAE, CLIP, LoRAs)
│   ├── loras.json            Style LoRA catalog
│   └── llm.json              3 LLM GGUF models
│
├── workflows/                11 workflows (source of truth)
│   ├── index.json            Index with versions
│   └── <workflow-id>/        manifest.yaml + workflow.json + blocks/
│
├── chrome-extension/         Browser extension for RunPod management
│
├── docker/
│   ├── production/           Production image (CUDA, PyTorch, ComfyUI, 38 nodes)
│   ├── development/          Development image (lightweight, stub ComfyUI)
│   ├── configure.sh          Interactive build configurator
│   └── README.md
│
├── version.json              Component version manifest
└── .github/workflows/
    └── build.yml             CI/CD — build and push to ghcr.io
```

For detailed documentation:
- **[`docker/README.md`](docker/README.md)** -- Docker build, bootstrap, runtime versioning, custom nodes, CI/CD
- **[`backend/README.md`](backend/README.md)** -- Backend architecture, module reference, API endpoints

---

## Logs

| Service | Log file |
|---------|----------|
| ComfyUI | `/var/log/comfyui.log` |
| Studio backend | `/var/log/admin.log` |

Both are also streamed to stdout (visible in RunPod container logs).

---

## Development

This project was developed from start to finish with the assistance of [Claude Code](https://claude.com/claude-code) by Anthropic, using the Claude Opus 4.6 model.
