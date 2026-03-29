# Overview

## What is ComfyUI Studio?

ComfyUI Studio is a web application that sits on top of [ComfyUI](https://github.com/comfyanonymous/ComfyUI), the node-based AI image and video generation tool. It provides a management layer that lets you:

- **Download and manage AI models** from HuggingFace and CivitAI through a visual catalog of 126 models
- **Run generation workflows** through simple forms instead of building node graphs (12 workflows including inpainting)
- **Save and reuse presets** -- workflow configurations that can be run from the web UI, Telegram, or the API
- **CivitAI integration** -- check model status, fetch generation data, detect dependencies, create presets from CivitAI images
- **Chrome extension** -- manage RunPod pods and browse CivitAI with catalog cross-referencing from the browser toolbar
- **Telegram bot** -- run presets by sending photos from your phone
- **Track jobs** with real-time progress, live preview frames, and ETA
- **Browse results** with an asset manager for inputs and outputs
- **Gallery system** -- download and browse CivitAI images for LoRA model galleries
- **Chat with LLMs** running locally on the GPU

It is designed to run on cloud GPU machines (RunPod, or any NVIDIA GPU server) as a Docker container. The Docker image includes ComfyUI, 38 custom nodes, and all performance optimizations pre-configured. The web application itself updates live from the Git repository — you don't need to rebuild the Docker image when the application changes.

## What Problem Does It Solve?

ComfyUI is powerful but complex. Its graph-based interface requires you to understand nodes, connections, and ComfyUI-specific concepts to do anything. For many common tasks — generating an image from a text prompt, converting an image to video, applying a style LoRA — you just want to fill in a form and click "Generate".

ComfyUI Studio provides that form-based interface while keeping the full power of ComfyUI underneath. Advanced users can still access the ComfyUI graph editor directly (port 8188) for custom workflows.

## How It Works

The system has two processes running in the container:

1. **ComfyUI** (port 8188) — the generation engine. It loads models, runs workflows, and produces outputs. It has no authentication and is typically not exposed to the internet.

2. **ComfyUI Studio** (port 8000) — the web application. It provides a password-protected web UI, talks to ComfyUI on localhost, and manages everything else (model catalog, job queue, file management, LLM chat).

When you run a workflow through Studio:

1. You fill in the form (prompt, model, settings)
2. Studio builds the ComfyUI workflow JSON from your parameters
3. Studio sends the workflow to ComfyUI's API
4. Studio listens to ComfyUI's WebSocket for progress updates and preview frames
5. Studio saves the job record and outputs when complete

The user never needs to interact with ComfyUI directly unless they want to build custom node graphs.

## What's in the Docker Image

The Docker image is built once and contains everything that doesn't change between generations:

- **CUDA toolkit** matched to your GPU architecture
- **Python environment** with PyTorch, xformers, and optionally SageAttention + FlashAttention
- **ComfyUI** with 38 pre-installed custom nodes covering image generation, video generation, face swap, upscaling, segmentation, and more
- **llama-server** (optional) — a compiled llama.cpp binary for local LLM inference
- **Bootstrap script** — downloads the application code on first boot

What is NOT in the image:

- Application code (backend, frontend) — cloned from Git on first boot, updated live
- Model catalogs — synced from Git
- AI models — downloaded on-demand through the web UI
- Generated outputs — stored on the persistent volume
- Job history — stored on the persistent volume

## What's on the Persistent Volume

RunPod provides a persistent network volume at `/workspace` that survives pod restarts. ComfyUI Studio uses a subdirectory called `STUDIO_DIR` (default: `/workspace/studio`) for all its data:

| Directory | Purpose |
|-----------|---------|
| `.repo/` | Git clone of the repository — staging area for updates only, never served directly |
| `backend/` | Python backend code (working copy, served by uvicorn) |
| `frontend/` | HTML/CSS/JS frontend (working copy, served by the backend) |
| `catalogs/` | Model catalogs: `models.json`, `loras.json`, `llm.json` |
| `workflows/` | Workflow definitions (manifests, workflow JSONs, block templates) |
| `assets/input/` | Images uploaded as inputs for workflows |
| `assets/output/` | Generated outputs organized by job ID |
| `jobs/` | Job history records (migrating to SQLite) |
| `db/` | SQLite database |
| `llm/models/` | Downloaded LLM GGUF model files |
| `events.jsonl` | Activity log |

ComfyUI itself lives at `/workspace/ComfyUI` (copied from the Docker image on first boot). Downloaded AI models go into `/workspace/ComfyUI/models/` in the appropriate subdirectories.
