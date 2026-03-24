# Environment Variables

All environment variables that configure ComfyUI Studio, organized by category.

## Authentication & API Tokens

These are the variables you set when creating your RunPod pod or Docker container.

| Variable | Default | Recommended | Description |
|----------|---------|-------------|-------------|
| `API_KEY` | `changeme` | **Change it** | The password for the web UI login and for programmatic access via the `X-API-Key` header. Anyone with this password has full access to your instance — model downloads, job execution, file management, settings. Choose a strong, unique password. |
| `CIVITAI_API_KEY` | _(empty)_ | **Yes** | Your CivitAI API token. Required to download models hosted on CivitAI and to fetch model metadata (descriptions, preview images, tags). Without this, CivitAI downloads fail silently. Get your token from [civitai.com/user/account](https://civitai.com/user/account) → API Keys. |
| `HF_TOKEN` | _(empty)_ | **Yes** | Your HuggingFace access token. Required to download gated models — Flux, WAN, HunyuanVideo, and many others require accepting a license on HuggingFace before downloading. Without this token, gated model downloads return 401 errors. Get your token from [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) → New token → Read access is sufficient. |

!!! note "Where tokens are used"
    These tokens are stored as environment variables on the pod. The backend injects them into download requests automatically — `HF_TOKEN` as a Bearer header for HuggingFace URLs, `CIVITAI_API_KEY` as a query parameter for CivitAI URLs. They are never sent to any other service.

## Configurable

These variables let you customize the behavior of the system. All have sensible defaults.

| Variable | Default | Description |
|----------|---------|-------------|
| `STUDIO_DIR` | `/workspace/studio` | Root directory for all Studio data on the persistent volume. All other paths derive from this. Change this only if you want Studio data in a different location. |
| `STUDIO_PORT` | `8000` | The port the Studio backend listens on. Change this if you have a port conflict or want to run multiple instances. |
| `COMFYUI_DIR` | `/workspace/ComfyUI` | Path to the ComfyUI installation. On first boot, ComfyUI is copied from the Docker image (`/comfyui`) to this location. Downloaded models go into `COMFYUI_DIR/models/`. |
| `COMFYUI_PORT` | `8188` | The port ComfyUI listens on. The Studio backend connects to ComfyUI on `localhost:COMFYUI_PORT`. |
| `COMFYUI_FLAGS` | `--highvram` | ComfyUI launch flags that control VRAM management. Choose based on your GPU's VRAM: |

### COMFYUI_FLAGS Options

| Flag | VRAM | Behavior |
|------|------|----------|
| `--highvram` | > 24 GB | Keeps models in VRAM. Fastest inference but uses the most memory. Default for datacenter GPUs (A100, H100, B200). |
| `--normalvram` | 12-24 GB | Balances between VRAM and system RAM. Good for RTX 4090, A5000, L4. |
| `--lowvram` | < 12 GB | Aggressively offloads to system RAM. Slower but works on 8 GB GPUs. |

| Variable | Default | Description |
|----------|---------|-------------|
| `COMFYUI_EXTRA_ARGS` | _(empty)_ | Additional ComfyUI command-line arguments appended after `COMFYUI_FLAGS`. For example, `--dont-upcast-attention` or `--force-fp16`. See [ComfyUI CLI arguments](https://github.com/comfyanonymous/ComfyUI/blob/master/comfy/cli_args.py) for all options. |
| `LLAMA_SERVER_PATH` | `/opt/llama-server` | Path to the llama.cpp server binary. If ENABLE_LLM was set to true during the Docker build, the binary is at `/opt/llama-server`. If you compiled it manually on the pod, point this to wherever you put the binary. |
| `LLAMA_SERVER_PORT` | `8080` | The port llama-server listens on when started from the LLM page. The Studio backend connects to it on `localhost:LLAMA_SERVER_PORT`. |
| `MAX_CONCURRENT_DOWNLOADS` | `3` | Maximum number of model downloads that run in parallel. Range: 1-10. Can also be changed at runtime from the Settings page without restarting. Higher values download faster but use more bandwidth and can cause timeouts on slow connections. |

## Read-only (Set by Infrastructure)

These are set by the Docker image or the RunPod platform. Do not change them manually.

| Variable | Default | Set by | Description |
|----------|---------|--------|-------------|
| `RUNTIME_VERSION` | `3` | Dockerfile | The Docker image version number. The application checks this against `min_runtime` in `version.json` to ensure compatibility. If your image is older than what the application requires, you'll see a "Runtime Incompatible" message and need to pull a newer image. This number is incremented when the Docker image includes breaking changes (new dependencies, new custom nodes, updated CUDA). |
| `REPO_URL` | `https://github.com/diego-devita/comfyui-studio.git` | Dockerfile | The Git repository URL used by the bootstrap script and update mechanism. The application clones this repo on first boot and fetches from it when checking for updates. |
| `RUNPOD_API_KEY` | _(auto)_ | RunPod | Automatically injected by RunPod into the container. Used by the telemetry system to query the RunPod API for network volume size (to calculate free disk space on the dashboard). |
| `RUNPOD_POD_ID` | _(auto)_ | RunPod | The pod identifier. Used in telemetry API calls. |
| `RUNPOD_DC_ID` | _(auto)_ | RunPod | The datacenter identifier. |
| `RUNPOD_VOLUME_ID` | _(auto)_ | RunPod | The network volume identifier. |

## Build Arguments (Docker Build Time)

These are set when building the Docker image, not at runtime. They control what's included in the image.

| Argument | Default | Description |
|----------|---------|-------------|
| `CUDA_VERSION` | `12.8.1` | NVIDIA CUDA base image version. Must match your target GPU architecture. See [GPU Compatibility](../docker/gpu-compatibility.md). |
| `PYTORCH_INDEX` | `cu128` | PyTorch wheel index tag. Must correspond to CUDA_VERSION: `cu128` for 12.8, `cu124` for 12.4, `cu121` for 12.1. |
| `PYTHON_VERSION` | `3.12` | Python interpreter version. 3.12 is recommended for ComfyUI. |
| `ENABLE_SAGE_ATTENTION` | `true` | Install SageAttention 2 + Triton for 2-3x faster attention. Requires Ampere (SM 80) or newer. Set to `false` for Turing/Volta GPUs. |
| `ENABLE_FLASH_ATTENTION` | `true` | Install FlashAttention for memory-efficient attention. Builds from source (20-30 min). Requires Ampere or newer. |
| `ENABLE_LLM` | `true` | Compile llama-server for local LLM inference. Compiles with CUDA for all GPU architectures (SM 75-100). Takes ~60 min on CI without GPU. Set to `false` to skip. |
| `LLAMA_CPP_VERSION` | `b8505` | The llama.cpp release tag to build. Pinned to a known-good version for reproducible builds. Set to `latest` for the newest code (may break). |

Use the [Build Configurator](../docker/configurator.md) (`docker/configure.sh`) to automatically determine the right values for your GPU.
