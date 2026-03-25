# Docker Image

What's inside the Docker image, how it's structured, and why.

## Base Image

```
nvidia/cuda:${CUDA_VERSION}-cudnn-devel-ubuntu24.04
```

The `devel` variant is used (not `runtime`) because some components need CUDA compilation headers:
- SageAttention compiles Triton kernels
- FlashAttention builds from source
- llama-server compiles with CUDA support

## Layer Order

The Dockerfile layers are ordered for optimal build cache efficiency. Layers that change less frequently are placed first, so that adding a custom node doesn't trigger a 60-minute llama-server recompilation.

```
Layer  1: Base CUDA image                     (changes: ~never)
Layer  2: System packages (apt-get)           (changes: ~never)
Layer  3: llama-server (conditional, ~60 min) (changes: ~never — pinned version)
Layer  4: Python venv                         (changes: ~never)
Layer  5: PyTorch                             (changes: ~never)
Layer  6: xformers                            (changes: ~never)
Layer  7: SageAttention (conditional)         (changes: ~never)
Layer  8: FlashAttention (conditional)        (changes: ~never)
Layer  9: FastAPI + backend dependencies      (changes: rarely)
Layer 10: ComfyUI core                        (changes: rarely)
Layer 11: COPY nodes.txt + install_nodes.sh   ← CACHE BREAK when nodes change
Layer 12: Custom nodes group 1                (rebuilt if nodes.txt changes)
Layer 13: Custom nodes group 2                (rebuilt if nodes.txt changes)
Layer 14: Custom nodes group 3                (rebuilt if nodes.txt changes)
Layer 15: Custom nodes group 4                (rebuilt if nodes.txt changes)
Layer 16: Cleanup
Layer 17: COPY bootstrap.py                   ← CACHE BREAK when bootstrap changes
Layer 18: COPY start.sh                       ← CACHE BREAK when start.sh changes
```

**Key insight:** llama-server is at layer 3 — right after system packages. It only depends on CUDA + cmake + git, nothing from Python or ComfyUI. Adding a custom node, a pip package, or updating PyTorch never triggers llama-server recompilation. Only changing the base CUDA image or system packages does (which ~never happens).

## What's Installed

### System Packages

| Package | Purpose |
|---------|---------|
| `python3.12`, `python3.12-venv`, `python3.12-dev` | Python runtime |
| `build-essential`, `cmake`, `ninja-build` | Compile C/C++ extensions (dlib, llama.cpp) |
| `gfortran`, `libopenblas-dev`, `liblapack-dev` | BLAS/LAPACK for dlib, scipy, numpy |
| `ffmpeg` | Video encode/decode (VideoHelperSuite) |
| `libgl1`, `libglib2.0-0`, `libsm6`, `libxext6`, `libxrender1` | OpenCV runtime dependencies |
| `git`, `wget`, `curl` | Download tools |

### Python Packages

| Package | Purpose |
|---------|---------|
| `torch`, `torchvision`, `torchaudio` | PyTorch (matched to CUDA via `PYTORCH_INDEX`) |
| `xformers` | Memory-efficient attention (all GPUs) |
| `triton`, `sageattention` | SageAttention v1/v2 (Ampere+ only, conditional) |
| `flash-attn` | FlashAttention v2/v3 (Ampere+ only, conditional, built from source) |
| `fastapi`, `uvicorn[standard]` | Web framework for Studio backend |
| `httpx` | Async HTTP client (for ComfyUI API calls) |
| `python-multipart` | File upload handling |
| `huggingface_hub` | HuggingFace model downloads |
| `aiofiles` | Async file operations |
| `requests` | HTTP client (for downloads) |
| `pyyaml` | YAML parsing (workflow manifests) |

### ComfyUI + Custom Nodes

ComfyUI is cloned from GitHub and installed with all its requirements. 38 custom nodes are installed from `docker/production/nodes.txt`, organized in categories:

| Category | Nodes | Purpose |
|----------|-------|---------|
| Fundamentals / QoL | 10 | Manager, essentials, seed control, utilities, login |
| Image Generation | 14 | ControlNet, IP-Adapter, face swap, upscale, GGUF, segmentation |
| Performance | 1 | WaveSpeed (FBCache + torch.compile) |
| Video Generation | 8 | VHS, AnimateDiff, WAN, Hunyuan, LTX, CogVideo, Mochi |
| CivitAI Integration | 3 | CivitAI model loader, browser, toolkit |

### llama-server (Optional)

When `ENABLE_LLM=true` (default), llama.cpp is compiled from source with CUDA support:

- **Source:** Cloned from `ggml-org/llama.cpp` at a pinned release tag (`LLAMA_CPP_VERSION`, default `b8505`)
- **CUDA architectures:** SM 75 through SM 100 (Turing to Blackwell)
- **Binary location:** `/opt/llama-server`
- **Build time:** ~10 minutes with local GPU, ~60 minutes on CI without GPU
- **Build flags:** Based on [llama.cpp official CUDA Dockerfile](https://github.com/ggml-org/llama.cpp/blob/master/.devops/cuda.Dockerfile), using `--allow-shlib-undefined` for CUDA stubs

## Build Cache

The CI uses **registry-based caching** instead of GitHub Actions cache:

```yaml
cache-from: type=registry,ref=ghcr.io/diego-devita/comfyui-studio:cache
cache-to: type=registry,ref=ghcr.io/diego-devita/comfyui-studio:cache,mode=max
```

This avoids the 10 GB limit of GHA cache, which was causing llama-server to be recompiled on every build (the layer is ~5-6 GB). With registry cache, there's no size limit.

## Image Tags

| Tag | Meaning |
|-----|---------|
| `:latest` | Always points to the most recent successful build from `main` |
| `:sha-<commit>` | Pinned to a specific commit (e.g., `:sha-4adfae8`) |
| `:cache` | Internal — stores build cache layers, not meant for running |

## Image Size

The compressed image is approximately **12 GB**. Decompressed on disk, it's approximately **25-30 GB**. This is managed separately by the container runtime — it does not count against the pod's container disk allocation.
