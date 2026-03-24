# ComfyUI Studio -- Docker & Deployment

This directory contains all Docker infrastructure: the Dockerfile, boot script, bootstrap installer, and custom node configuration.

---

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage image definition: CUDA base, Python, PyTorch, ComfyUI, 35 custom nodes, performance optimizations, FastAPI backend dependencies |
| `start.sh` | Container entry point. Runs bootstrap on first boot, copies ComfyUI to volume, starts ComfyUI + Studio backend |
| `bootstrap.py` | First-boot installer. Downloads the application from GitHub, checks runtime compatibility |
| `nodes.txt` | Custom node list with repo URLs, organized by category (35 nodes in 7 groups) |
| `install_nodes.sh` | Build-time helper. Reads `nodes.txt` between section markers, clones repos, installs requirements |

---

## Bootstrap Flow

On first boot (when `STUDIO_DIR/backend/main.py` does not exist), `start.sh` invokes `bootstrap.py`. This is the only time the application is downloaded from scratch. Subsequent updates are handled by the in-app update mechanism.

### Step by step

1. **Fetch `version.json`** from the GitHub repository (`REPO_BASE`).

2. **Check runtime compatibility**: compare `version.json.min_runtime` against `RUNTIME_VERSION` env var.
   - If `min_runtime > RUNTIME_VERSION`: write an error HTML page to `STUDIO_DIR/www/pages/error.html`, exit with code 2. `start.sh` serves this page on port 8000 so the user sees a clear "Runtime Incompatible" message.
   - If compatible: proceed.

3. **Download backend**: use GitHub Contents API to recursively list and download all files from `backend/` in the repo to `STUDIO_DIR/backend/`.

4. **Download frontend**: recursively download `frontend/` to `STUDIO_DIR/www/`.

5. **Download catalogs**: download `catalogs/models.json`, `catalogs/loras.json`, `catalogs/llm-models.json` to `STUDIO_DIR/catalogs/`.

6. **Download workflows**: fetch `workflows/index.json`, then for each workflow:
   - Download `manifest.yaml`
   - If dynamic workflow (`type: dynamic`): download block files from `blocks/` directory
   - If static workflow: download `workflow.json`

7. **Save `version.json`** to `STUDIO_DIR/version.json`.

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `STUDIO_DIR` | `/workspace/studio` | Where to install the application |
| `REPO_BASE` | `https://raw.githubusercontent.com/diego-devita/comfyui-studio/main` | Source repository |
| `RUNTIME_VERSION` | `0` | Docker image runtime version (set at build time) |

### Error handling

- If `version.json` cannot be fetched, bootstrap exits with code 1 (network error).
- If runtime is incompatible, bootstrap exits with code 2 and `start.sh` serves the error page.
- Individual file download failures are logged but do not abort the process.

---

## Runtime Versioning

The runtime version system prevents the live-updated application from running on an incompatible Docker image.

### How it works

1. The **Docker image** has a `RUNTIME_VERSION` environment variable set at build time (e.g., `ENV RUNTIME_VERSION=1`).

2. The **repository's `version.json`** has a `min_runtime` field (e.g., `"min_runtime": 1`).

3. On bootstrap, if `min_runtime > RUNTIME_VERSION`, the application **refuses to install** and shows an error page directing the user to pull the latest Docker image.

4. On update (via the in-app update button), if the remote `min_runtime > RUNTIME_VERSION`, the update returns `blocked: true` with a message. The frontend shows this to the user.

### When to bump `min_runtime`

Bump `min_runtime` in `version.json` when the application requires something that only exists in a new Docker image:
- A new Python dependency was added to the Dockerfile
- A new custom node was added to `nodes.txt`
- The base CUDA or PyTorch version changed
- A new system package is required

### When to bump `RUNTIME_VERSION`

Add or increment `ENV RUNTIME_VERSION=N` in the Dockerfile whenever you make infrastructure changes that the application might depend on.

---

## start.sh Boot Sequence

```
STEP 0: Bootstrap (first boot only)
  ├── Check if STUDIO_DIR/backend/main.py exists
  ├── If not: run bootstrap.py
  │   ├── Downloads app from GitHub
  │   └── Checks runtime compatibility
  └── If bootstrap fails: serve error page on port 8000, exit

STEP 1: Copy ComfyUI (first boot only)
  ├── Check if /workspace/ComfyUI exists
  └── If not: cp -r /comfyui /workspace/ComfyUI

STEP 2: Start ComfyUI
  ├── cd /workspace/ComfyUI
  ├── python main.py --listen 0.0.0.0 --port 8188 ...
  │   --input-directory STUDIO_DIR/assets/input
  │   --output-directory STUDIO_DIR/assets/output
  │   $COMFYUI_FLAGS (default: --highvram)
  │   $COMFYUI_EXTRA_ARGS
  ├── Create STUDIO_DIR/assets/input and STUDIO_DIR/assets/output
  └── Wait for ComfyUI ready (poll /system_stats every 2s, max 120s)

STEP 3: Start Studio backend
  ├── cd STUDIO_DIR/backend
  └── uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1

Container stays alive by waiting on the ComfyUI process.
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
   ENV RUNTIME_VERSION=2
   ```

3. Bump `min_runtime` in `version.json` to match:
   ```json
   "min_runtime": 2
   ```

4. Commit and push. This will trigger a CI build since the Dockerfile changed.

5. Existing pods will see "Runtime Incompatible" on their next update check, telling them to pull the new image.

---

## How to Add a Custom Node

Custom nodes are installed at Docker build time from `nodes.txt`.

1. Add the node's GitHub URL to the appropriate section in `nodes.txt`:
   ```
   # Description of the node
   https://github.com/author/ComfyUI-NodeName.git
   ```

   If the node has a non-standard requirements file or needs a post-install command:
   ```
   https://github.com/author/ComfyUI-NodeName.git requirements-special.txt python install.py
   ```

2. Commit and push. The Dockerfile change will trigger a CI build.

3. The node will be available in `/comfyui/custom_nodes/` in the image, and copied to `/workspace/ComfyUI/custom_nodes/` on first boot.

### Format of nodes.txt

```
# Lines starting with # are comments
# Section markers: # ── Section Name ──
# Format: repo_url [requirements_file] [post_install_command]

https://github.com/author/NodeName.git
https://github.com/author/NodeName.git requirements.txt
https://github.com/author/NodeName.git requirements.txt python install.py
```

The `install_nodes.sh` script reads between section markers, so nodes are installed in groups (each group is a separate Docker layer for better caching).

### Runtime node installation

Users can also install nodes at runtime through the Node Manager page (`/admin/nodes`) or ComfyUI-Manager. Runtime-installed nodes persist on the network volume across pod restarts but are not in the Docker image.

---

## Build Arguments

All arguments have defaults optimized for NVIDIA B200.

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

```bash
# B200 (default -- no args needed)
docker build -f docker/Dockerfile -t comfyui-studio .

# A100 / RTX 4090 / RTX 3090
docker build -f docker/Dockerfile -t comfyui-studio \
  --build-arg CUDA_VERSION=12.4.1 \
  --build-arg PYTORCH_INDEX=cu124 .

# T4 / V100 (no attention optimizations)
docker build -f docker/Dockerfile -t comfyui-studio \
  --build-arg CUDA_VERSION=12.1.1 \
  --build-arg PYTORCH_INDEX=cu121 \
  --build-arg ENABLE_SAGE_ATTENTION=false \
  --build-arg ENABLE_FLASH_ATTENTION=false .
```

---

## Custom Nodes

35 custom nodes are pre-installed in the Docker image, organized in 7 groups. The full list with descriptions is in [`nodes.txt`](nodes.txt).

**Fundamentals / QoL (9)** -- ComfyUI-Manager, ComfyUI_essentials, rgthree-comfy, cg-use-everywhere, ComfyLiterals, ComfyUI-Custom-Scripts, ComfyUI-KJNodes, was-node-suite-comfyui, ComfyUI-Easy-Use.

**Image Generation (11)** -- ComfyUI-Advanced-ControlNet, ComfyUI_IPAdapter_plus, ComfyUI_InstantID, ComfyUI-ReActor, ComfyUI_FaceAnalysis, ComfyUI-Impact-Pack, ComfyUI-Impact-Subpack, ComfyUI-Inspire-Pack, ComfyUI_UltimateSDUpscale, comfyui_controlnet_aux, ComfyUI-layerdiffuse, ComfyUI-BRIA_AI-RMBG, ComfyUI-GGUF, ComfyUI-mxToolkit.

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

---

## CI/CD

**File:** `.github/workflows/build.yml`

GitHub Actions builds and pushes the Docker image to `ghcr.io` on every push to `main`, **except** when only these paths change:

- `workflows/**` -- workflow library (updated live)
- `app/**` -- legacy path (kept in ignore list)
- `version.json` -- version manifest (updated live)
- `*.md` -- documentation

The Docker image is rebuilt when these files change:
- `docker/Dockerfile`, `docker/start.sh`, `docker/bootstrap.py`, `docker/install_nodes.sh`, `docker/nodes.txt`
- `.github/workflows/build.yml`

### Build configuration via GitHub Actions variables

| Variable | CI Default |
|----------|-----------|
| `CUDA_VERSION` | `12.8.1` |
| `PYTORCH_INDEX` | `cu128` |
| `PYTHON_VERSION` | `3.12` |
| `ENABLE_SAGE_ATTENTION` | `true` |
| `ENABLE_FLASH_ATTENTION` | `false` (no GPU on CI runner) |

Note: `ENABLE_FLASH_ATTENTION` defaults to `false` in CI because FlashAttention requires a GPU to compile. When building locally with a GPU, use `--build-arg ENABLE_FLASH_ATTENTION=true`.

### Image tags

- `latest` -- always points to the most recent build from `main`
- `sha-<commit>` -- pinned to a specific commit

---

## Logs

| Service | Log file | Description |
|---------|----------|-------------|
| ComfyUI | `/var/log/comfyui.log` | ComfyUI stdout/stderr |
| Studio backend | `/var/log/admin.log` | uvicorn/FastAPI stdout/stderr |

View logs on a running pod:
```bash
tail -f /var/log/comfyui.log
tail -f /var/log/admin.log
```
