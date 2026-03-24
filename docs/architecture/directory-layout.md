# Directory Layout

Every file and directory in the system, where it lives, and what it does.

## Persistent Volume (`/workspace`)

This is the RunPod network volume. Everything here survives pod restarts.

### `/workspace/studio/` (STUDIO_DIR)

The root of all Studio data. Every path below is relative to this.

```
/workspace/studio/
├── .repo/                          Git clone — staging area for updates
│   ├── backend/                    Latest backend code from repo
│   ├── frontend/                   Latest frontend code from repo
│   ├── catalogs/                   Latest catalog files from repo
│   ├── workflows/                  Latest workflow files from repo
│   └── version.json                Latest version manifest from repo
│
├── backend/                        Working copy — served by uvicorn
│   ├── main.py                     Entry point, imports all modules
│   ├── config.py                   All paths, env vars, app instance
│   ├── auth.py                     Cookie auth, middleware, maintenance mode
│   ├── catalogs.py                 Catalog loading, file resolver, version helper
│   ├── db.py                       SQLite database layer
│   ├── download.py                 Download queue, HF/CivitAI auth injection
│   ├── events.py                   EventBus, WS pusher, startup tasks
│   ├── runner.py                   ComfyUI WS listener, progress tracking
│   ├── runner_api.py               Execute, upload, build, status endpoints
│   ├── jobs_api.py                 Queue, history, assets, nodes endpoints
│   ├── models_api.py               Model/LoRA download, delete, import, metadata
│   ├── llm_api.py                  LLM model catalog, server control, chat
│   ├── llm_server.py               llama-server process manager
│   ├── workflows_api.py            Workflow list, readiness check
│   ├── workflows.py                Workflow loading, dynamic assembly, conversion
│   ├── system_api.py               Status, update, telemetry, settings
│   └── pages.py                    HTML page serve routes
│
├── frontend/                       Working copy — served by backend
│   ├── css/
│   │   ├── styles.css              Design system (colors, layout, typography)
│   │   ├── components.css          Shared components (cards, tables, toggles)
│   │   └── icons.css               Font Awesome icons via CSS mask-image
│   ├── js/
│   │   └── shared.js               Shared utilities (apiFetch, showToast, etc.)
│   └── pages/
│       ├── home.html               Dashboard
│       ├── models.html             Model Manager
│       ├── loras.html              LoRA Manager
│       ├── llm.html                LLM Assistant
│       ├── workflows.html          Workflow Manager
│       ├── queue.html              Job Queue
│       ├── history.html            Job History
│       ├── assets.html             Asset Manager
│       ├── settings.html           Settings
│       ├── runner.html             Workflow Runner
│       └── login.html              Login page
│
├── catalogs/
│   ├── models.json                 AI model catalog (126 models)
│   ├── loras.json                  Style LoRA catalog (currently empty)
│   └── llm.json                    LLM GGUF model catalog (3 models)
│
├── workflows/
│   ├── index.json                  Workflow registry with versions
│   ├── wan22-i2v-lightx2v/         Static workflow (manifest + workflow.json)
│   ├── wan22-i2v-fp8/              Static workflow
│   ├── wan22-i2v-kijai/            Static workflow
│   ├── wan22-svi-dynamic/          Dynamic workflow (manifest + blocks/)
│   ├── t2i-dynamic/                Dynamic workflow
│   ├── t2i-batch/                  Dynamic workflow
│   ├── i2i-batch/                  Dynamic workflow
│   ├── ipa-batch/                  Dynamic workflow
│   └── faceid-batch/               Dynamic workflow
│
├── assets/
│   ├── input/                      Images uploaded as workflow inputs
│   └── output/                     Generated outputs, organized by job
│       └── comfyui-studio/
│           └── {job_id}/
│               ├── video/          Final video outputs
│               ├── image/          Final image outputs
│               ├── preview/        Preview images
│               ├── intermediate/   Intermediate outputs
│               └── .incomplete     Marker file during generation
│
├── db/
│   └── studio.db                   SQLite database (jobs, events, settings)
│
├── jobs/                           Legacy job records (JSON files, migrating to SQLite)
│
├── llm/
│   ├── models/                     Downloaded GGUF model files
│   └── config.json                 llama-server configuration
│
├── version.json                    Component version tracking (local copy)
├── events.jsonl                    Activity log (append-only, 5MB rotate)
└── .session_secret                 Random auth secret (generated on first boot)
```

### Key Distinction: `.repo/` vs Working Directories

| | `.repo/` | Working dirs |
|---|---------|--------------|
| **Purpose** | Git staging area | Running application |
| **Modified by** | `git fetch` + `git reset` | Update mechanism (copy from .repo/) |
| **Served by** | Nothing | uvicorn (backend), FastAPI (frontend) |
| **When modified** | During update check | After update copies |

The application **never** reads from `.repo/` during normal operation. It always uses the working copies. `.repo/` is only touched during bootstrap and updates.

### `/workspace/ComfyUI/`

The ComfyUI installation. Copied from `/comfyui` in the Docker image on first boot.

```
/workspace/ComfyUI/
├── main.py                         ComfyUI entry point
├── requirements.txt
├── models/                         Downloaded AI models
│   ├── checkpoints/                Full model files (SD 1.5, Flux FP8)
│   ├── diffusion_models/           Diffusion UNets (WAN, Hunyuan, CogVideo, LTX)
│   ├── loras/                      LoRA files
│   ├── vae/                        VAE files
│   ├── text_encoders/              CLIP, T5-XXL, UMT5-XXL, LLaVA-LLaMA3
│   ├── clip_vision/                CLIP Vision models
│   ├── controlnet/                 ControlNet models
│   ├── ipadapter/                  IP-Adapter models
│   ├── insightface/                Face swap models (inswapper_128)
│   ├── upscale_models/             4x upscalers
│   ├── embeddings/                 Negative prompt embeddings
│   ├── animatediff_models/         AnimateDiff motion modules
│   ├── sam2/                       SAM2 segmentation models
│   └── latent_upscale_models/      LTX upsamplers
├── custom_nodes/                   38 pre-installed custom nodes
│   ├── ComfyUI-Manager/
│   ├── ComfyUI-Login/
│   ├── ComfyUI_essentials/
│   ├── ... (36 more)
└── input/                          Symlinked to STUDIO_DIR/assets/input

```

## Docker Image

Files baked into the image (not on the persistent volume):

| Path | Purpose |
|------|---------|
| `/comfyui/` | ComfyUI + custom nodes (copied to volume on first boot) |
| `/app/bootstrap.py` | First-boot installer script |
| `/opt/llama-server` | llama.cpp binary (if `ENABLE_LLM=true`) |
| `/start.sh` | Container entrypoint script |
| `/opt/venv/` | Python virtual environment with all packages |

## Log Files

| Path | Content | Also on stdout? |
|------|---------|-----------------|
| `/var/log/comfyui.log` | ComfyUI stdout/stderr | Yes (via tee) |
| `/var/log/admin.log` | Studio backend stdout/stderr | Yes (via tee) |
