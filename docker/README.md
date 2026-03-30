# ComfyUI Studio -- Docker & Deployment

ComfyUI Studio ships two Docker images:

- **Production** -- Full GPU image with CUDA, PyTorch, ComfyUI, custom nodes, and llama-server. Built for RunPod GPU pods. See below.
- **Development** -- Lightweight ~200MB image for local development. No GPU required. See [`development/README.md`](development/README.md) for full details.

---

## Production Image

### Files

| File | Purpose |
|------|---------|
| `production/Dockerfile` | Image definition: CUDA base, Python, PyTorch, ComfyUI, custom nodes, performance optimizations, llama-server, FastAPI dependencies |
| `production/start.sh` | Container entry point. Runs bootstrap on first boot, copies ComfyUI to volume, starts ComfyUI + Studio backend |
| `production/bootstrap.py` | First-boot installer. Clones the repo, checks runtime compatibility, copies components to working directories |
| `production/nodes.txt` | Custom node list with repo URLs, organized by category |
| `production/install_nodes.sh` | Build-time helper. Reads `nodes.txt` between section markers, clones repos, installs requirements |
| `configure.sh` | Interactive build configurator -- guides you through GPU selection, optimizations, and outputs the right `docker build` command |
| `RUNPOD_TEMPLATE.md` | RunPod template description -- copy-paste for the RunPod dashboard template field |
| `dev.sh` | Development container manager -- start/stop/logs/bash/build/reset shortcuts |
| `prod.sh` | Production container manager -- start/stop/logs/bash/pull/build shortcuts for local GPU testing |

### Container Manager Scripts

Both scripts run from the repository root.

**`dev.sh`** — manage the development container:

| Command | What it does |
|---------|-------------|
| `./docker/dev.sh` | Start (or restart) the dev container |
| `./docker/dev.sh stop` | Stop and remove |
| `./docker/dev.sh logs` | Tail logs |
| `./docker/dev.sh bash` | Open a shell inside |
| `./docker/dev.sh build` | Rebuild the image |
| `./docker/dev.sh reset` | Wipe all data and restart fresh |

**`prod.sh`** — manage a local production container (requires GPU):

| Command | What it does |
|---------|-------------|
| `./docker/prod.sh` | Start with defaults |
| `./docker/prod.sh stop` | Stop and remove |
| `./docker/prod.sh logs` | Tail logs |
| `./docker/prod.sh bash` | Open a shell inside |
| `./docker/prod.sh pull` | Pull latest image from registry |
| `./docker/prod.sh build` | Build locally (interactive or default) |

`prod.sh` accepts env var overrides: `API_KEY=secret VOLUME=/data/studio ./docker/prod.sh`

---

### Quick Start: Build Configurator

The easiest way to build the Docker image is to use the interactive configurator:

```bash
cd comfyui-studio
docker/configure.sh
```

The configurator walks you through:

1. **GPU selection** -- pick your GPU from a list, the script auto-resolves CUDA version, PyTorch index, and attention optimizations
2. **Parameter confirmation** -- review and optionally override the auto-detected settings
3. **LLM support** -- include llama-server for local LLM inference (Qwen, Llama, etc.)
4. **Build environment** -- if LLM is enabled, whether you're building with or without a GPU (affects compilation time and strategy)
5. **Custom node categories** -- toggle which node groups to include
6. **Output** -- copy-paste `docker build` command, or generate a customized Dockerfile

At the end you get the exact command to run, with build time estimates.

#### Why the build environment matters

If you enable LLM support (llama-server), the script asks where you're building the image:

- **With the target GPU**: the compiler auto-detects the architecture and builds optimized kernels for that specific GPU only (~10 min)
- **Without a GPU** (GitHub Actions, CI runners): the compiler builds kernels for ALL supported architectures (Turing through Blackwell) -- produces a universal binary but takes ~60 min

---

## Bootstrap Flow

On first boot (when `STUDIO_DIR/backend/main.py` does not exist), `start.sh` invokes `bootstrap.py`. This is the only time the application is installed from scratch. Subsequent updates are handled by the in-app update mechanism.

### Key principle: `.repo/` is ONLY a staging area

The `.repo/` directory is a shallow git clone used exclusively for fetching updates. The running application NEVER serves files from `.repo/`. All components are copied to working directories.

### Step by step

1. **Git clone** the repository to `STUDIO_DIR/.repo/` (shallow, depth 1). If `.repo/` already exists (e.g., from a previous pod with the same network volume), does `git fetch + reset --hard` instead.

2. **Check runtime compatibility**: compare `version.json.min_runtime` against `RUNTIME_VERSION` env var.
   - If `min_runtime > RUNTIME_VERSION`: exit with code 2. `start.sh` exits the container.
   - If compatible: proceed.

3. **Copy ALL components** from `.repo/` to working directories:
   - `backend/` -> `STUDIO_DIR/backend/` (always overwritten)
   - `frontend/` -> `STUDIO_DIR/frontend/` (always overwritten)
   - `catalogs/*.json` -> `STUDIO_DIR/catalogs/` (only if file doesn't exist -- preserves user edits)
   - `workflows/` -> `STUDIO_DIR/workflows/` (only if dir doesn't exist or is empty)
   - `version.json` -> `STUDIO_DIR/version.json` (always overwritten)

4. **Create runtime directories**: `assets/input`, `assets/output`, `assets/images/{lookup,media,models}`, `database`, `llm/models`, `llm/logs`, `presets`.

All steps are logged with `[bootstrap]` prefix to stdout (visible in RunPod container logs).

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `STUDIO_DIR` | `/workspace/studio` | Where to install the application |
| `REPO_URL` | `https://github.com/diego-devita/comfyui-studio.git` | Git repository URL |
| `REPO_BRANCH` | `main` | Git branch to track (`main` for production, `dev` for testing) |
| `RUNTIME_VERSION` | `0` (image sets `4`) | Docker image runtime version (set at build time) |

### Error handling

- If git clone fails, bootstrap exits with code 1 (network error).
- If runtime is incompatible, bootstrap exits with code 2.

---

## start.sh Boot Sequence

```
STEP 0: Bootstrap (first boot only)
  |-- Check if STUDIO_DIR/backend/main.py exists
  |-- If not: run bootstrap.py
  |   |-- Clones repo to .repo/
  |   |-- Checks runtime compatibility
  |   `-- Copies all components to working dirs
  `-- If bootstrap fails: exit

STEP 1: Copy ComfyUI (first boot only)
  |-- Check if /workspace/ComfyUI exists
  `-- If not: cp -r /comfyui /workspace/ComfyUI

STEP 2: Start ComfyUI
  |-- Create STUDIO_DIR/assets/input and STUDIO_DIR/assets/output
  |-- cd /workspace/ComfyUI
  |-- python main.py --listen 0.0.0.0 --port 8188 ...
  |   --input-directory STUDIO_DIR/assets/input
  |   --output-directory STUDIO_DIR/assets/output
  |   $COMFYUI_FLAGS (default: --highvram)
  |   $COMFYUI_EXTRA_ARGS
  |   Output: stdout + /var/log/comfyui.log (via tee)
  `-- Wait for ComfyUI ready (poll /system_stats every 2s, max 120s)

STEP 3: Start Studio backend
  |-- cd STUDIO_DIR/backend
  `-- uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
      Output: stdout + /var/log/admin.log (via tee)

Container stays alive by waiting on all background processes.
All service output visible in RunPod container logs.
```

---

## Runtime Versioning

The runtime version system prevents the live-updated application from running on an incompatible Docker image.

### Where the version lives

The Docker image version is tracked in **two places that must stay in sync**:

| Location | What | Example |
|----------|------|---------|
| `docker/production/Dockerfile` -> `ENV RUNTIME_VERSION=N` | Baked into the image at build time. The running container reads this. | `ENV RUNTIME_VERSION=4` |
| `version.json` -> `components.runtime.version` | In the Git repo. The update mechanism reads this to compare. | `"version": 4` |

The Docker image is also tagged by CI with `:latest` and `:sha-<commit>`, but these are not used by the application -- only `RUNTIME_VERSION` matters for compatibility checks.

### How it works

1. The **Docker image** has `ENV RUNTIME_VERSION=4` set at build time.

2. The **repository's `version.json`** has a `min_runtime` field (e.g., `"min_runtime": 0`).

3. On bootstrap, if `min_runtime > RUNTIME_VERSION`, the application **refuses to install**.

4. On update (via the in-app update button), if the remote `min_runtime > RUNTIME_VERSION`, the update returns `blocked: true` with a message telling the user to pull a newer Docker image.

### When to bump `min_runtime`

Bump `min_runtime` in `version.json` when the application requires something that only exists in a new Docker image:
- A new Python dependency was added to the Dockerfile
- A new custom node was added to `nodes.txt`
- The base CUDA or PyTorch version changed
- A new system package is required

### When to bump `RUNTIME_VERSION`

Increment `ENV RUNTIME_VERSION=N` in the Dockerfile **and** `components.runtime.version` in `version.json` whenever you make infrastructure changes that the application might depend on. Both must match.

---

## Build Arguments

All arguments have defaults optimized for NVIDIA B200. Use `docker/configure.sh` to auto-detect the right values for your GPU.

### `CUDA_VERSION` (default: `12.8.1`)

NVIDIA CUDA base image version. Must match GPU architecture:

| GPU Generation | CUDA_VERSION |
|----------------|-------------|
| Blackwell (B200, B100) | `12.8.1` |
| Hopper (H100, H200) | `12.8.1` |
| Ampere (A100, A6000, A5000, A4000) | `12.4.1` |
| Ada Lovelace (RTX 40xx, L40, L40S, L4) | `12.4.1` |
| Ampere consumer (RTX 30xx) | `12.4.1` |
| Turing (RTX 20xx, T4) | `12.1.1` |
| Volta (V100) | `12.1.1` |

### `PYTORCH_INDEX` (default: `cu128`)

PyTorch wheel index tag. Must correspond to `CUDA_VERSION`:

| CUDA_VERSION | PYTORCH_INDEX |
|-------------|---------------|
| `12.8.1` | `cu128` |
| `12.4.1` | `cu124` |
| `12.1.1` | `cu121` |

### `PYTHON_VERSION` (default: `3.12`)

Python interpreter version. 3.12 is recommended for ComfyUI.

### `ENABLE_SAGE_ATTENTION` (default: `true`)

Installs SageAttention 2 + Triton for 2-3x faster attention computation.

| GPU | Result |
|-----|--------|
| Hopper / Blackwell (H100, H200, B200) | SageAttention **v2** with FP8 kernels |
| Ampere / Ada Lovelace (A100, RTX 30xx/40xx, L40, L4) | SageAttention **v1** |
| Turing / Volta (RTX 20xx, T4, V100) | **Not supported** -- set to `false` |

### `ENABLE_FLASH_ATTENTION` (default: `true`)

Installs FlashAttention for memory-efficient fused attention kernels. Builds from source (20-30 min).

| GPU | Result |
|-----|--------|
| Hopper / Blackwell | FlashAttention **v3** |
| Ampere / Ada Lovelace | FlashAttention **v2** |
| Turing / Volta | **Not supported** -- set to `false` |

### `ENABLE_LLM` (default: `true`)

Compiles llama.cpp server with CUDA support for local LLM inference (chat, prompt generation). The binary is installed to `/opt/llama-server`.

When building **without a GPU** (CI runners, GitHub Actions), the build compiles CUDA kernels for all supported architectures (SM 75 through SM 100). This produces a universal binary but takes ~60 minutes. When building **with the target GPU**, the compiler auto-detects the architecture and builds only for that GPU (~10 min).

Set to `false` to skip the compilation entirely and save build time. llama-server can always be compiled manually on the pod later.

### `LLAMA_CPP_VERSION` (default: `b8505`)

The llama.cpp release tag to build. Pinned to a known-good release for reproducible builds.

The default `b8505` was the latest stable release on 2026-03-24 when llama-server support was added to this project. Pinning ensures that every build produces the same binary regardless of when it runs.

| Value | Behavior |
|-------|----------|
| `b8505` (default) | Builds a specific, tested release. Reproducible. |
| `latest` | Clones the newest HEAD. Gets latest features/fixes but may break if llama.cpp introduces incompatible changes. |
| Any tag (e.g., `b8400`) | Builds that specific release. |

To update to a newer version, check [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases) and pass the tag:
```bash
docker build -f docker/production/Dockerfile -t comfyui-studio \
  --build-arg LLAMA_CPP_VERSION=b8600 .
```

---

## GPU Compatibility Table

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
| RTX 4070 | 12 GB | SM 89 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 4060 Ti | 16 GB | SM 89 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 4060 | 8 GB | SM 89 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 3090 / Ti | 24 GB | SM 86 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 3080 Ti | 12 GB | SM 86 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 3080 | 10 GB | SM 86 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 3070 Ti | 8 GB | SM 86 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 3070 | 8 GB | SM 86 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 3060 | 12 GB | SM 86 | `12.4.1` | `cu124` | v1 | v2 |
| RTX 2080 Ti | 11 GB | SM 75 | `12.1.1` | `cu121` | no | no |
| RTX 2080 SUPER | 8 GB | SM 75 | `12.1.1` | `cu121` | no | no |
| RTX 2080 | 8 GB | SM 75 | `12.1.1` | `cu121` | no | no |
| RTX 2070 | 8 GB | SM 75 | `12.1.1` | `cu121` | no | no |
| T4 | 16 GB | SM 75 | `12.1.1` | `cu121` | no | no |
| V100 (32 GB) | 32 GB | SM 70 | `12.1.1` | `cu121` | no | no |
| V100 (16 GB) | 16 GB | SM 70 | `12.1.1` | `cu121` | no | no |

---

## Build Examples

The quickest way is to use `docker/configure.sh`. But if you prefer manual commands:

```bash
# B200 (default -- no args needed)
docker build -f docker/production/Dockerfile -t comfyui-studio .

# A100 / RTX 4090 / RTX 3090
docker build -f docker/production/Dockerfile -t comfyui-studio \
  --build-arg CUDA_VERSION=12.4.1 \
  --build-arg PYTORCH_INDEX=cu124 .

# T4 / V100 (no attention optimizations, no LLM)
docker build -f docker/production/Dockerfile -t comfyui-studio \
  --build-arg CUDA_VERSION=12.1.1 \
  --build-arg PYTORCH_INDEX=cu121 \
  --build-arg ENABLE_SAGE_ATTENTION=false \
  --build-arg ENABLE_FLASH_ATTENTION=false \
  --build-arg ENABLE_LLM=false .

# Fast build for CI (skip LLM and FlashAttention)
docker build -f docker/production/Dockerfile -t comfyui-studio \
  --build-arg ENABLE_FLASH_ATTENTION=false \
  --build-arg ENABLE_LLM=false .
```

---

## Custom Nodes

Custom nodes are pre-installed in the Docker image, organized in 6 categories. The full list with descriptions is in [`production/nodes.txt`](production/nodes.txt).

**Fundamentals / QoL (9)** -- ComfyUI-Manager, ComfyUI_essentials, rgthree-comfy, cg-use-everywhere, ComfyLiterals, ComfyUI-Custom-Scripts, ComfyUI-KJNodes, was-node-suite-comfyui, ComfyUI-Easy-Use.

**Image Generation (14)** -- ComfyUI-Advanced-ControlNet, ComfyUI_IPAdapter_plus, ComfyUI_InstantID, ComfyUI-ReActor, ComfyUI_FaceAnalysis, ComfyUI-Impact-Pack, ComfyUI-Impact-Subpack, ComfyUI-Inspire-Pack, ComfyUI_UltimateSDUpscale, comfyui_controlnet_aux, ComfyUI-layerdiffuse, ComfyUI-BRIA_AI-RMBG, ComfyUI-GGUF, ComfyUI-mxToolkit.

**Performance Optimization (1)** -- Comfy-WaveSpeed (FBCache + torch.compile, 1.5-2x speedup).

**Segmentation (2)** -- ComfyUI-segment-anything-2, ComfyUI_Florence2SAM2.

**Video Generation (8)** -- ComfyUI-VideoHelperSuite, ComfyUI-Frame-Interpolation, ComfyUI-AnimateDiff-Evolved, ComfyUI-WanVideoWrapper, ComfyUI-HunyuanVideoWrapper, ComfyUI-LTXVideo, ComfyUI-CogVideoXWrapper, ComfyUI-MochiWrapper.

**CivitAI Integration (3)** -- civitai_comfy_nodes, ComfyUI-EasyCivitai-XTNodes, ComfyUI-Civitai-Toolkit.

### Performance Optimizations

| Optimization | Installed | Benefit |
|-------------|-----------|---------|
| **xformers** | Always | Memory-efficient attention, all GPUs |
| **SageAttention** | Conditional | 2-3x faster attention (Ampere+) |
| **FlashAttention** | Conditional | Fused attention kernels (Ampere+) |
| **torch.compile** | Built into PyTorch | ~20-30% speedup, no install needed |
| **WaveSpeed** | Always (custom node) | FBCache + compile, 1.5-2x speedup with LoRA |

### Runtime node installation

Users can also install nodes at runtime through the Node Manager page (`/admin/nodes`) or ComfyUI-Manager. Runtime-installed nodes persist on the network volume across pod restarts but are not in the Docker image.

---

## LLM Support (llama-server)

The Docker image can optionally include llama-server, a compiled binary from the llama.cpp project that provides GPU-accelerated LLM inference.

- **Binary location**: `/opt/llama-server`
- **Shared libraries**: `/opt/llama-lib/`
- **Library path**: `LD_LIBRARY_PATH=/opt/llama-lib` (set in image)
- **Models directory**: `STUDIO_DIR/llm/models/` (on the persistent volume)
- **Logs directory**: `STUDIO_DIR/llm/logs/`
- **Multi-model support**: multiple instances can run on different ports
- **Compiled with CUDA** for architectures SM 75 through SM 100 (Turing to Blackwell)

### Build time impact

| Build environment | Time |
|-------------------|------|
| With target GPU (local build) | ~10 min (native arch only) |
| Without GPU (CI / GitHub Actions) | ~60 min (all architectures) |
| Disabled (`ENABLE_LLM=false`) | 0 min |

### Runtime on the pod

Once built into the image, llama-server is managed by the Studio backend. The LLM page (`/admin/llm`) provides:
- Model catalog with download from HuggingFace
- Start/stop server with selected model
- Server status indicator

If llama-server is not in the image, it can be compiled manually on the pod (which has the GPU for fast native compilation).

---

## CI/CD

**File:** `.github/workflows/build.yml`

GitHub Actions builds and pushes the Docker image to `ghcr.io` on every push to `main` that changes files under `docker/production/**`. Can also be triggered manually via `workflow_dispatch`.

The Docker image is **not** rebuilt when these paths change (they are updated live via the in-app update mechanism):
- `workflows/**`, `backend/**`, `frontend/**`, `catalogs/**`, `version.json`, `*.md`

### Build configuration via GitHub Actions variables

| Variable | CI Default |
|----------|-----------|
| `CUDA_VERSION` | `12.8.1` |
| `PYTORCH_INDEX` | `cu128` |
| `PYTHON_VERSION` | `3.12` |
| `ENABLE_SAGE_ATTENTION` | `true` |
| `ENABLE_FLASH_ATTENTION` | `false` (no GPU on CI runner) |
| `ENABLE_LLM` | `true` |
| `LLAMA_CPP_VERSION` | `b8505` |

Note: `ENABLE_FLASH_ATTENTION` defaults to `false` in CI because FlashAttention requires a GPU to compile. `ENABLE_LLM` is `true` by default -- the build compiles for all GPU architectures on CI (~60 min).

### Image tags

- `latest` -- always points to the most recent build from `main`
- `sha-<commit>` -- pinned to a specific commit

---

## Development Image

Lightweight (~200MB) image for local development without a GPU. Includes a ComfyUI stub server, hot reload, and sqlite-web for database inspection.

See [`development/README.md`](development/README.md) for full documentation.

Quick start:

```bash
# Build
docker build -f docker/development/Dockerfile -t comfyui-studio-dev .

# Run
docker run -d --name studio-dev \
  -p 8000:8000 -p 8188:8188 -p 8002:8002 \
  -v $(pwd)/backend:/workspace/studio/backend \
  -v $(pwd)/frontend:/workspace/studio/frontend \
  -v $(pwd)/workflows:/workspace/studio/workflows \
  -v $(pwd)/version.json:/workspace/studio/version.json \
  -v ~/.studio-dev:/workspace/studio/data \
  -e API_KEY=test \
  comfyui-studio-dev
```

---

## How to Add a Python Dependency

Adding a pip package requires a Docker image rebuild.

1. Add the package to the `pip install` command in the Dockerfile (the FastAPI dependencies section near the end):
   ```dockerfile
   RUN pip install \
       fastapi \
       "uvicorn[standard]" \
       httpx \
       python-multipart \
       ... \
       your-new-package
   ```

2. Bump `RUNTIME_VERSION` in the Dockerfile:
   ```dockerfile
   ENV RUNTIME_VERSION=5
   ```

3. Bump `min_runtime` in `version.json` to match:
   ```json
   "min_runtime": 5
   ```

4. Commit and push. This will trigger a CI build since the Dockerfile changed.

5. Existing pods will see "Runtime Incompatible" on their next update check, telling them to pull the new image.

---

## How to Add a Custom Node

Custom nodes are installed at Docker build time from `production/nodes.txt`.

1. Add the node's GitHub URL to the appropriate section in `production/nodes.txt`:
   ```
   # Description of the node
   https://github.com/author/ComfyUI-NodeName.git
   ```

   If the node has a non-standard requirements file or needs a post-install command:
   ```
   https://github.com/author/ComfyUI-NodeName.git requirements-special.txt python install.py
   ```

2. Commit and push. The change under `docker/production/` will trigger a CI build.

3. The node will be available in `/comfyui/custom_nodes/` in the image, and copied to `/workspace/ComfyUI/custom_nodes/` on first boot.

### Format of nodes.txt

```
# Lines starting with # are comments
# Section markers: # -- Section Name --
# Format: repo_url [requirements_file] [post_install_command]

https://github.com/author/NodeName.git
https://github.com/author/NodeName.git requirements.txt
https://github.com/author/NodeName.git requirements.txt python install.py
```

The `install_nodes.sh` script reads between section markers, so nodes are installed in groups (each group is a separate Docker layer for better caching).

---

## Logs

All service output is visible in RunPod container logs (stdout via `tee`) and also saved to files:

| Service | Log file | Description |
|---------|----------|-------------|
| ComfyUI | `/var/log/comfyui.log` | ComfyUI stdout/stderr |
| Studio backend | `/var/log/admin.log` | uvicorn/FastAPI stdout/stderr |

View logs on a running pod:
```bash
tail -f /var/log/comfyui.log
tail -f /var/log/admin.log
```
