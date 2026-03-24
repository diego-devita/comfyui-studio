# ComfyUI Studio

A web-based management platform for AI image and video generation built on ComfyUI. Runs as a Docker container on RunPod (or any NVIDIA GPU machine) with a dedicated interface for managing models, LoRAs, workflows, custom nodes, an LLM assistant, and running generation jobs -- without touching the ComfyUI graph editor. The Docker image provides ComfyUI + 37 custom nodes + performance optimizations. The web application updates live from the Git repository without rebuilding.

Default build targets **NVIDIA B200** (192 GB VRAM). Supports any GPU from V100 to B200 via build arguments.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                  DOCKER IMAGE (build time)                       │
│                                                                  │
│  /comfyui           ComfyUI + 37 custom nodes (baked in)        │
│  /app/bootstrap.py  First-boot installer                        │
│  /opt/llama-server  llama.cpp server (CUDA, SM 75-100) [optional]│
│  /start.sh          Boot script                                 │
│                                                                  │
│  NOT in image: models, workflows, live app code, user data       │
├──────────────────────────────────────────────────────────────────┤
│              PERSISTENT VOLUME (runtime)                         │
│                                                                  │
│  /workspace/studio/                  ← STUDIO_DIR               │
│    .repo/                            ← git clone (staging only)   │
│    backend/                          ← live Python backend       │
│    frontend/                         ← live frontend (HTML/CSS/JS)│
│    catalogs/                         ← models, loras, llm-models │
│    workflows/                        ← workflow library           │
│    assets/input/ + assets/output/    ← ComfyUI I/O               │
│    jobs/                             ← job history records        │
│    llm/                              ← LLM models + config        │
│    db/                               ← database files             │
│    version.json                      ← component version tracking │
│  /workspace/ComfyUI/                 ← copied from /comfyui       │
│  /workspace/ComfyUI/models/          ← downloaded via Model Mgr   │
└──────────────────────────────────────────────────────────────────┘

Bootstrap flow (first boot only):
  1. bootstrap.py clones repo to STUDIO_DIR/.repo/
  2. Checks RUNTIME_VERSION >= min_runtime (blocks if incompatible)
  3. Copies backend/, frontend/, catalogs/, workflows/ to STUDIO_DIR working dirs
  4. start.sh copies /comfyui → /workspace/ComfyUI
  5. Starts ComfyUI (port 8188) + Studio backend (port 8000)
  All output visible in RunPod container logs (stdout via tee)
```

---

## Quick Start

### Build

The easiest way is to use the interactive configurator, which auto-detects the right settings for your GPU:

```bash
docker/configure.sh
```

Or build directly (default: B200, all features):

```bash
docker build -f docker/Dockerfile -t comfyui-studio .
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

| Variable | Value |
|----------|-------|
| `API_KEY` | A strong password for the web application |
| `CIVITAI_API_KEY` | Your CivitAI API token |
| `HF_TOKEN` | Your HuggingFace access token |
| `RUNPOD_API_KEY` | Your RunPod API key (for disk telemetry) |

Exposed ports: **8188** (ComfyUI), **8000** (Web App)

After the pod starts, open `https://<PODID>-8000.proxy.runpod.net` and enter your API key to access the dashboard.

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
| `/admin/settings` | Settings | Download concurrency, environment variables |
| `/run/{id}` | Workflow Runner | Execute workflows through a simple form |
| `/login` | Login | API key authentication |

**Port 8188** -- ComfyUI graph editor (direct access for advanced use).

---

## Live Updates

Application code, catalogs, and workflows live in this Git repository as source of truth. They are **not baked into the Docker image**.

1. On **first boot**, `bootstrap.py` downloads the latest versions from the repository into `STUDIO_DIR`
2. If the Docker image's `RUNTIME_VERSION` is below `min_runtime` in version.json, bootstrap **blocks** and serves an error page
3. During updates, the backend enters **maintenance mode** (returns 503 to all requests with an auto-reloading page)
4. The **Check for Updates** button compares local `version.json` with the repository and updates changed components
5. Pushing to the repository does **not** trigger a Docker rebuild (CI ignores `backend/`, `frontend/`, `catalogs/`, `workflows/`, `version.json`, `*.md`)

| Component | Where it goes | Restart? | When visible? |
|-----------|--------------|----------|---------------|
| **Frontend** (HTML/CSS/JS) | `STUDIO_DIR/frontend/` | No | Next page load |
| **Backend** (16 Python modules) | `STUDIO_DIR/backend/` | Yes (auto) | After ~2s restart |
| **Model catalog** | `STUDIO_DIR/catalogs/models.json` | No | Next API call |
| **LoRA catalog** | `STUDIO_DIR/catalogs/loras.json` | No | Next API call |
| **LLM catalog** | `STUDIO_DIR/catalogs/llm-models.json` | No | Next API call |
| **Workflows** | `STUDIO_DIR/workflows/` | No | Next API call |

---

## Environment Variables

### Authentication & API Tokens

| Variable | Default | Recommended | Description |
|----------|---------|-------------|-------------|
| `API_KEY` | `changeme` | **Change it** | Password for web login and `X-API-Key` header |
| `CIVITAI_API_KEY` | _(empty)_ | **Yes** | CivitAI API token — needed to download models and fetch metadata |
| `HF_TOKEN` | _(empty)_ | **Yes** | HuggingFace token — needed for gated models (Flux, WAN, etc.) |
| `RUNPOD_API_KEY` | _(empty)_ | **Yes** | RunPod API key — enables disk/volume telemetry on the dashboard |

### Configurable

| Variable | Default | Description |
|----------|---------|-------------|
| `STUDIO_DIR` | `/workspace/studio` | Root directory for all Studio data on the persistent volume |
| `COMFYUI_DIR` | `/workspace/ComfyUI` | ComfyUI installation path |
| `COMFYUI_FLAGS` | `--highvram` | VRAM mode: `--highvram` (>24 GB), `--normalvram` (12-24 GB), `--lowvram` (<12 GB) |
| `COMFYUI_EXTRA_ARGS` | _(empty)_ | Additional ComfyUI launch flags |
| `COMFYUI_PORT` | `8188` | ComfyUI port |
| `LLAMA_SERVER_PATH` | `/opt/llama-server` | Path to llama.cpp binary |
| `LLAMA_SERVER_PORT` | `8080` | llama-server port |
| `MAX_CONCURRENT_DOWNLOADS` | `3` | Parallel model downloads (1-10, also adjustable from UI) |

### Read-only (set by infrastructure, do not change)

| Variable | Default | Set by | Description |
|----------|---------|--------|-------------|
| `RUNTIME_VERSION` | `3` | Dockerfile | Docker image version — must match `version.json` → `components.runtime.version` |
| `REPO_URL` | `https://github.com/diego-devita/comfyui-studio.git` | Dockerfile | Git repo for updates |
| `RUNPOD_POD_ID` | _(auto)_ | RunPod | Pod identifier — used for telemetry |
| `RUNPOD_DC_ID` | _(auto)_ | RunPod | Datacenter ID |
| `RUNPOD_VOLUME_ID` | _(auto)_ | RunPod | Network volume ID |

---

## Build Arguments

All arguments have defaults optimized for B200. Override with `--build-arg` for other GPUs. See [`docker/README.md`](docker/README.md) for full details.

| Argument | Default | Description |
|----------|---------|-------------|
| `CUDA_VERSION` | `12.8.1` | NVIDIA CUDA base image version |
| `PYTORCH_INDEX` | `cu128` | PyTorch wheel index tag |
| `PYTHON_VERSION` | `3.12` | Python interpreter version |
| `ENABLE_SAGE_ATTENTION` | `true` | SageAttention 2 + Triton (Ampere+) |
| `ENABLE_FLASH_ATTENTION` | `true` | FlashAttention (Ampere+, builds from source) |
| `ENABLE_LLM` | `true` | llama.cpp server for local LLM inference |
| `LLAMA_CPP_VERSION` | `b8505` | llama.cpp release tag (or `latest` for HEAD) |

### GPU Compatibility Table

| GPU | VRAM | CUDA_VERSION | PYTORCH_INDEX | SageAttn | FlashAttn |
|-----|------|-------------|---------------|----------|-----------|
| B200 / B100 | 80-192 GB | `12.8.1` | `cu128` | v2 (fp8) | v3 |
| H200 / H100 | 80-141 GB | `12.8.1` | `cu128` | v2 (fp8) | v3 |
| A100 / A6000 / A5000 / A4000 | 16-80 GB | `12.4.1` | `cu124` | v1 | v2 |
| L40S / L40 / L4 | 24-48 GB | `12.4.1` | `cu124` | v1 | v2 |
| RTX 4090 / 4080 / 4070 / 4060 | 8-24 GB | `12.4.1` | `cu124` | v1 | v2 |
| RTX 3090 / 3080 / 3070 / 3060 | 8-24 GB | `12.4.1` | `cu124` | v1 | v2 |
| RTX 2080 Ti / 2080 / 2070 / T4 | 8-16 GB | `12.1.1` | `cu121` | no | no |
| V100 | 16-32 GB | `12.1.1` | `cu121` | no | no |

### Build Examples

```bash
# B200 (default)
docker build -f docker/Dockerfile -t comfyui-studio .

# A100 / RTX 4090 / RTX 3090
docker build -f docker/Dockerfile -t comfyui-studio \
  --build-arg CUDA_VERSION=12.4.1 \
  --build-arg PYTORCH_INDEX=cu124 .

# T4 / V100 (no attention optimizations, no LLM)
docker build -f docker/Dockerfile -t comfyui-studio \
  --build-arg CUDA_VERSION=12.1.1 \
  --build-arg PYTORCH_INDEX=cu121 \
  --build-arg ENABLE_SAGE_ATTENTION=false \
  --build-arg ENABLE_FLASH_ATTENTION=false \
  --build-arg ENABLE_LLM=false .

# Fast CI build (skip slow compilations)
docker build -f docker/Dockerfile -t comfyui-studio \
  --build-arg ENABLE_FLASH_ATTENTION=false \
  --build-arg ENABLE_LLM=false .
```

> **Tip:** Use `docker/configure.sh` instead of memorizing build args — it picks the right values for your GPU and explains each option.

---

## Project Structure

```
comfyui-studio/
├── backend/                  Python backend (16 modules, ~5900 lines)
│   ├── main.py               Entry point — imports and wires everything
│   ├── config.py             App instance, env vars, all paths
│   ├── auth.py               Cookie auth, middleware, login/logout
│   ├── events.py             EventBus, WebSocket pusher, startup tasks
│   ├── pages.py              HTML page serve routes
│   ├── catalogs.py           Catalog loaders, static file helper, version helper
│   ├── download.py           Download pool, state tracking, auth injection
│   ├── models_api.py         Model + LoRA endpoints
│   ├── llm_api.py            LLM model + chat endpoints
│   ├── llm_server.py         llama-server process manager
│   ├── workflows_api.py      Workflow list, readiness, sync
│   ├── workflows.py          Workflow loading, dynamic assembly, conversion
│   ├── runner.py             Execution tracking, WS listener, job persistence
│   ├── runner_api.py         Runner API: upload, execute, status, result
│   ├── system_api.py         System status, update, telemetry, settings
│   └── jobs_api.py           Queue, history, assets, nodes, output downloads
│
├── frontend/
│   ├── css/                  styles.css, components.css, icons.css
│   ├── js/                   shared.js
│   └── pages/                12 HTML pages (home, models, loras, runner, etc.)
│
├── catalogs/                 Model catalogs (source of truth)
│   ├── models.json           AI model catalog
│   ├── loras.json            LoRA catalog
│   └── llm-models.json       LLM model catalog
│
├── workflows/                Workflow library (source of truth)
│   ├── index.json            Index with versions
│   └── <workflow-id>/        Per-workflow dirs with manifest.yaml + workflow.json
│
├── docker/                   Docker infrastructure
│   ├── Dockerfile            Image definition (CUDA, PyTorch, nodes, llama-server)
│   ├── configure.sh          Interactive build configurator
│   ├── start.sh              Container boot script
│   ├── bootstrap.py          First-boot installer (clones repo, copies to working dirs)
│   ├── nodes.txt             Custom node list
│   └── install_nodes.sh      Node installer (build time)
│
├── version.json              Component version manifest
└── .github/workflows/
    └── build.yml             CI/CD — build and push to ghcr.io
```

For detailed documentation, see:
- **[`backend/README.md`](backend/README.md)** -- Backend architecture, module reference, API endpoints, dependency graph
- **[`docker/README.md`](docker/README.md)** -- Docker build, bootstrap flow, runtime versioning, custom nodes, CI/CD

---

## Logs

| Service | Log file |
|---------|----------|
| ComfyUI | `/var/log/comfyui.log` |
| Studio backend | `/var/log/admin.log` |

---

## Development

This project was developed from start to finish with the assistance of [Claude Code](https://claude.com/claude-code) by Anthropic, using the Claude Opus 4.6 model.
