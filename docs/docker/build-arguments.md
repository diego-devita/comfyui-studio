# Build Arguments

The Dockerfile accepts 7 build arguments that control CUDA version, attention optimizations, and LLM support. All have sensible defaults targeting the latest GPU generation (Blackwell/Hopper).

## Reference

### CUDA_VERSION

NVIDIA CUDA base image version. Determines the CUDA toolkit used for compilation and runtime.

| Value | Target GPUs | Base Image |
|-------|-------------|------------|
| `12.8.1` (default) | Blackwell (B200, B100), Hopper (H200, H100) | `nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04` |
| `12.4.1` | Ampere (A100, A6000, RTX 30xx), Ada Lovelace (L40S, RTX 40xx) | `nvidia/cuda:12.4.1-cudnn-devel-ubuntu24.04` |
| `12.1.1` | Turing (RTX 20xx, T4), Volta (V100) | `nvidia/cuda:12.1.1-cudnn-devel-ubuntu24.04` |

Must be paired with the matching `PYTORCH_INDEX`.

---

### PYTORCH_INDEX

PyTorch wheel index tag. Selects the correct pre-built PyTorch wheels for your CUDA version.

| Value | CUDA Version | PyTorch Install URL |
|-------|-------------|---------------------|
| `cu128` (default) | 12.8.1 | `https://download.pytorch.org/whl/cu128` |
| `cu124` | 12.4.1 | `https://download.pytorch.org/whl/cu124` |
| `cu121` | 12.1.1 | `https://download.pytorch.org/whl/cu121` |

This must always match `CUDA_VERSION`. Mismatched pairs will produce a broken image (PyTorch compiled for one CUDA version running on another).

---

### PYTHON_VERSION

Python interpreter version installed in the image.

| Value | Notes |
|-------|-------|
| `3.12` (default) | Recommended for ComfyUI as of 2026. Used in the venv at `/opt/venv`. |

Change only if a specific custom node requires a different Python version. The Dockerfile installs `python${PYTHON_VERSION}`, `python${PYTHON_VERSION}-venv`, and `python${PYTHON_VERSION}-dev` from the Ubuntu package repositories.

---

### ENABLE_SAGE_ATTENTION

Install SageAttention and Triton for optimized attention computation.

| Value | Behavior |
|-------|----------|
| `true` (default) | Installs `triton` and `sageattention` via pip |
| `false` | Skips installation entirely |

**GPU requirements:**

| GPU Generation | Compute Capability | SageAttention Version |
|---------------|--------------------|-----------------------|
| Hopper, Blackwell | SM 90+ | v2 with FP8 kernels -- fastest, uses 8-bit floating point for attention |
| Ampere, Ada Lovelace | SM 80-89 | v1 -- optimized CUDA kernels, 2-3x faster than default attention |
| Turing, Volta | SM 70-75 | Not supported -- set to `false` |

SageAttention provides 2-3x faster attention computation during image and video generation. It installs from pre-built wheels, so there is minimal impact on build time.

!!! warning "Set to `false` for SM 75 and below"
    On Turing (RTX 20xx, T4) and Volta (V100) GPUs, SageAttention will fail at runtime. Always set `ENABLE_SAGE_ATTENTION=false` for these GPUs.

---

### ENABLE_FLASH_ATTENTION

Install FlashAttention for memory-efficient fused attention kernels.

| Value | Behavior |
|-------|----------|
| `true` (default) | Installs `flash-attn` from source via pip (`--no-build-isolation`) |
| `false` | Skips installation entirely |

**GPU requirements:**

| GPU Generation | Compute Capability | FlashAttention Version |
|---------------|--------------------|-----------------------|
| Hopper, Blackwell | SM 90+ | v3 -- newest, optimized for Hopper architecture |
| Ampere, Ada Lovelace | SM 80-89 | v2 -- memory-efficient fused kernels |
| Turing, Volta | SM 70-75 | Not supported -- set to `false` |

FlashAttention lets you run larger batch sizes or higher resolutions without running out of VRAM by reducing the memory footprint of attention computation.

!!! warning "Builds from source -- 20-30 minutes"
    Unlike SageAttention, FlashAttention builds from source during `pip install`. This adds 20-30 minutes to the Docker build. The CI/CD pipeline defaults to `false` for this reason.

!!! warning "Set to `false` for SM 75 and below"
    On Turing (RTX 20xx, T4) and Volta (V100) GPUs, FlashAttention is not supported. Always set `ENABLE_FLASH_ATTENTION=false` for these GPUs.

---

### ENABLE_LLM

Compile llama.cpp server for local LLM inference on the pod GPU.

| Value | Behavior |
|-------|----------|
| `true` (default) | Clones llama.cpp, compiles `llama-server` with CUDA, installs binary to `/opt/llama-server` |
| `false` | Skips the entire llama.cpp clone and compilation step |

The binary supports GPU-accelerated inference with GGUF models (Qwen, Llama, Mistral, etc.) and is managed through the ComfyUI Studio LLM page.

!!! info "Build time impact"
    llama-server compilation takes ~10 minutes when a GPU is present during the build (single architecture) or ~60 minutes on CI runners without a GPU (compiles for all architectures SM 75 through SM 100). Set to `false` to save this time if you do not need LLM support.

See [llama-server](llama-server.md) for details on the compilation process.

---

### LLAMA_CPP_VERSION

The llama.cpp git tag to clone and build. Only relevant when `ENABLE_LLM=true`.

| Value | Behavior |
|-------|----------|
| `b8505` (default) | Pinned release, tested and known to build correctly. Pinned on 2026-03-24. |
| `latest` | Clones HEAD of the llama.cpp repository (`--depth 1`, no tag) |
| Any tag (e.g., `b8400`) | Clones that specific release tag |

!!! tip "Pin for reproducibility"
    The default pinned version ensures reproducible builds. Using `latest` gets the newest features and fixes but risks build failures from upstream breaking changes. If a `latest` build fails, switch back to the pinned version or specify a known-good tag.

## Build Examples

### Default (Blackwell/Hopper, all features)

```bash
docker build -f docker/Dockerfile -t comfyui-studio .
```

Uses all defaults: CUDA 12.8.1, cu128, SageAttention v2, FlashAttention v3, llama-server b8505.

### Ampere / Ada Lovelace (A100, RTX 30xx/40xx, L40S)

```bash
docker build -f docker/Dockerfile -t comfyui-studio \
  --build-arg CUDA_VERSION=12.4.1 \
  --build-arg PYTORCH_INDEX=cu124 \
  .
```

SageAttention v1 and FlashAttention v2 are installed (both default to `true`).

### Turing / Volta (RTX 20xx, T4, V100)

```bash
docker build -f docker/Dockerfile -t comfyui-studio \
  --build-arg CUDA_VERSION=12.1.1 \
  --build-arg PYTORCH_INDEX=cu121 \
  --build-arg ENABLE_SAGE_ATTENTION=false \
  --build-arg ENABLE_FLASH_ATTENTION=false \
  .
```

No attention optimizations. xformers and torch.compile still work on these GPUs.

### Fast CI build (no FlashAttention, no LLM)

```bash
docker build -f docker/Dockerfile -t comfyui-studio \
  --build-arg ENABLE_FLASH_ATTENTION=false \
  --build-arg ENABLE_LLM=false \
  .
```

Skips both source compilations. Build time drops from ~85-115 minutes to ~15-25 minutes.

### Custom llama.cpp version

```bash
docker build -f docker/Dockerfile -t comfyui-studio \
  --build-arg LLAMA_CPP_VERSION=b8400 \
  .
```

### Latest llama.cpp (bleeding edge)

```bash
docker build -f docker/Dockerfile -t comfyui-studio \
  --build-arg LLAMA_CPP_VERSION=latest \
  .
```

## Argument Pairing Quick Reference

| GPU Family | CUDA_VERSION | PYTORCH_INDEX | SAGE_ATTENTION | FLASH_ATTENTION |
|-----------|--------------|---------------|----------------|-----------------|
| Blackwell / Hopper | `12.8.1` | `cu128` | `true` (v2 FP8) | `true` (v3) |
| Ampere / Ada Lovelace | `12.4.1` | `cu124` | `true` (v1) | `true` (v2) |
| Turing / Volta | `12.1.1` | `cu121` | `false` | `false` |

See [GPU Compatibility](gpu-compatibility.md) for the full per-GPU breakdown.
