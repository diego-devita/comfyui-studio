# System Overview

ComfyUI Studio runs as a Docker container with two services on a machine with an NVIDIA GPU. Everything is split between the **Docker image** (immutable, built once) and the **persistent volume** (data that survives restarts).

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                    DOCKER IMAGE (build time)                      │
│                                                                   │
│  /comfyui             ComfyUI + 38 custom nodes (baked in)       │
│  /app/bootstrap.py    First-boot installer                        │
│  /opt/llama-server    llama.cpp server (CUDA) [optional]          │
│  /start.sh            Boot script                                 │
│                                                                   │
│  NOT in image: models, workflows, app code, user data             │
├──────────────────────────────────────────────────────────────────┤
│                PERSISTENT VOLUME (runtime)                         │
│                                                                   │
│  /workspace/studio/                    ← STUDIO_DIR               │
│    .repo/                              ← git clone (staging only) │
│    backend/                            ← live Python backend      │
│    frontend/                           ← live frontend            │
│    catalogs/                           ← models, loras, llm       │
│    workflows/                          ← workflow library          │
│    assets/input/ + assets/output/      ← ComfyUI I/O              │
│    jobs/                               ← job history               │
│    db/                                 ← SQLite database           │
│    llm/                                ← LLM models + config       │
│    version.json                        ← version tracking          │
│                                                                   │
│  /workspace/ComfyUI/                   ← copied from /comfyui     │
│  /workspace/ComfyUI/models/            ← downloaded AI models      │
└──────────────────────────────────────────────────────────────────┘
```

## Two Services

The container runs two independent processes:

### ComfyUI (port 8188)

The generation engine. It loads AI models into GPU memory, processes workflow graphs, and produces images and videos. It exposes a REST API and a WebSocket endpoint for real-time progress.

ComfyUI has **no authentication**. It is bound to `0.0.0.0` so the Studio backend can reach it on localhost, but it should not be exposed to the internet directly. In the RunPod template, only port 8000 (Studio) is exposed.

### ComfyUI Studio (port 8000)

The web application. A Python FastAPI backend with an HTML/JS frontend. It provides:

- **Authentication** -- cookie-based session auth with HMAC signing
- **Model management** -- catalog, download queue, disk status
- **Workflow runner** -- form-based execution with parameter mapping
- **Presets** -- saved workflow configurations, runnable from web UI, Telegram, or API
- **CivitAI integration** -- model lookup, generation data proxy, dependency detection
- **Job tracking** -- queue, history, retry, export
- **Real-time updates** -- WebSocket for progress, preview frames, events
- **LLM chat** -- llama-server process management and chat API
- **Telegram bot** -- daemon thread for running presets from Telegram
- **Gallery system** -- CivitAI image storage with SQLite index

The backend is a single uvicorn process with one worker. It communicates with ComfyUI on `localhost:8188` for all generation tasks.

## Key Architectural Principle: .repo/ is Staging Only

The `.repo/` directory inside STUDIO_DIR is a shallow Git clone of the repository. It exists **only** as a staging area for fetching updates. The running application **never** serves files from `.repo/`.

All components are copied from `.repo/` to working directories:

| Source | Destination | When copied |
|--------|-------------|-------------|
| `.repo/backend/` | `STUDIO_DIR/backend/` | First boot + updates |
| `.repo/frontend/` | `STUDIO_DIR/frontend/` | First boot + updates |
| `.repo/catalogs/` | `STUDIO_DIR/catalogs/` | First boot (preserves existing) + updates |
| `.repo/workflows/` | `STUDIO_DIR/workflows/` | First boot (preserves existing) + updates |
| `.repo/version.json` | `STUDIO_DIR/version.json` | First boot + updates |

This separation means:

- Git operations (fetch, reset) never affect the running application
- The application can be updated atomically (copy, then restart)
- If an update fails, the previous working copy is still intact
- Catalogs and workflows can be edited on the pod without affecting the Git clone

## Communication Flow

```
User Browser
    │
    ├── HTTPS ──→ RunPod Proxy ──→ Studio Backend (port 8000)
    │                                    │
    │                                    ├── HTTP ──→ ComfyUI API (localhost:8188)
    │                                    ├── WS ───→ ComfyUI WebSocket (localhost:8188)
    │                                    └── HTTP ──→ llama-server (localhost:8080)
    │
    └── (not exposed by default)
         ComfyUI Web UI (port 8188)
```

The RunPod proxy handles HTTPS termination. Inside the container, all communication is plain HTTP on localhost.

## Technology Stack

| Component | Technology |
|-----------|------------|
| Backend | Python 3.12, FastAPI, uvicorn (22 modules, ~9800 lines) |
| Frontend | Vanilla HTML, CSS, JavaScript -- no framework (13 pages) |
| Database | SQLite (WAL mode) |
| Generation | ComfyUI (PyTorch, CUDA) |
| LLM | llama.cpp (CUDA) |
| Container | Docker, NVIDIA CUDA base image |
| CI/CD | GitHub Actions, ghcr.io |
| Deployment | RunPod (or any NVIDIA GPU machine) |
