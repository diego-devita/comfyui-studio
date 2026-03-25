# GPU Compatibility

ComfyUI Studio supports NVIDIA GPUs from Volta (2017) through Blackwell (2024). The Docker image build arguments must be set correctly for your target GPU to ensure CUDA compatibility, correct PyTorch wheels, and appropriate attention optimizations.

## Full Compatibility Table

### Blackwell (SM 100)

| GPU | VRAM | CUDA_VERSION | PYTORCH_INDEX | SageAttention | FlashAttention |
|-----|------|--------------|---------------|---------------|----------------|
| B200 | 192 GB | 12.8.1 | cu128 | v2 (FP8) | v3 |
| B100 | 80 GB | 12.8.1 | cu128 | v2 (FP8) | v3 |

### Hopper (SM 90)

| GPU | VRAM | CUDA_VERSION | PYTORCH_INDEX | SageAttention | FlashAttention |
|-----|------|--------------|---------------|---------------|----------------|
| H200 | 141 GB | 12.8.1 | cu128 | v2 (FP8) | v3 |
| H100 | 80 GB | 12.8.1 | cu128 | v2 (FP8) | v3 |
| H100 NVL | 94 GB | 12.8.1 | cu128 | v2 (FP8) | v3 |

### Ampere -- Datacenter (SM 80 / SM 86)

| GPU | VRAM | SM | CUDA_VERSION | PYTORCH_INDEX | SageAttention | FlashAttention |
|-----|------|----|--------------|---------------|---------------|----------------|
| A100 (80 GB) | 80 GB | 80 | 12.4.1 | cu124 | v1 | v2 |
| A100 (40 GB) | 40 GB | 80 | 12.4.1 | cu124 | v1 | v2 |
| A6000 | 48 GB | 86 | 12.4.1 | cu124 | v1 | v2 |
| A5000 | 24 GB | 86 | 12.4.1 | cu124 | v1 | v2 |
| A4000 | 16 GB | 86 | 12.4.1 | cu124 | v1 | v2 |

### Ada Lovelace -- Datacenter (SM 89)

| GPU | VRAM | CUDA_VERSION | PYTORCH_INDEX | SageAttention | FlashAttention |
|-----|------|--------------|---------------|---------------|----------------|
| L40S | 48 GB | 12.4.1 | cu124 | v1 | v2 |
| L40 | 48 GB | 12.4.1 | cu124 | v1 | v2 |
| L4 | 24 GB | 12.4.1 | cu124 | v1 | v2 |

### Ada Lovelace -- Consumer (SM 89)

| GPU | VRAM | CUDA_VERSION | PYTORCH_INDEX | SageAttention | FlashAttention |
|-----|------|--------------|---------------|---------------|----------------|
| RTX 4090 | 24 GB | 12.4.1 | cu124 | v1 | v2 |
| RTX 4080 SUPER | 16 GB | 12.4.1 | cu124 | v1 | v2 |
| RTX 4080 | 16 GB | 12.4.1 | cu124 | v1 | v2 |
| RTX 4070 Ti | 12 GB | 12.4.1 | cu124 | v1 | v2 |
| RTX 4070 | 12 GB | 12.4.1 | cu124 | v1 | v2 |
| RTX 4060 Ti | 16 GB | 12.4.1 | cu124 | v1 | v2 |
| RTX 4060 | 8 GB | 12.4.1 | cu124 | v1 | v2 |

### Ampere -- Consumer (SM 86)

| GPU | VRAM | CUDA_VERSION | PYTORCH_INDEX | SageAttention | FlashAttention |
|-----|------|--------------|---------------|---------------|----------------|
| RTX 3090 | 24 GB | 12.4.1 | cu124 | v1 | v2 |
| RTX 3090 Ti | 24 GB | 12.4.1 | cu124 | v1 | v2 |
| RTX 3080 Ti | 12 GB | 12.4.1 | cu124 | v1 | v2 |
| RTX 3080 | 10 GB | 12.4.1 | cu124 | v1 | v2 |
| RTX 3070 Ti | 8 GB | 12.4.1 | cu124 | v1 | v2 |
| RTX 3070 | 8 GB | 12.4.1 | cu124 | v1 | v2 |
| RTX 3060 | 12 GB | 12.4.1 | cu124 | v1 | v2 |

### Turing (SM 75)

| GPU | VRAM | CUDA_VERSION | PYTORCH_INDEX | SageAttention | FlashAttention |
|-----|------|--------------|---------------|---------------|----------------|
| RTX 2080 Ti | 11 GB | 12.1.1 | cu121 | -- | -- |
| RTX 2080 SUPER | 8 GB | 12.1.1 | cu121 | -- | -- |
| RTX 2080 | 8 GB | 12.1.1 | cu121 | -- | -- |
| RTX 2070 | 8 GB | 12.1.1 | cu121 | -- | -- |
| T4 | 16 GB | 12.1.1 | cu121 | -- | -- |

### Volta (SM 70)

| GPU | VRAM | CUDA_VERSION | PYTORCH_INDEX | SageAttention | FlashAttention |
|-----|------|--------------|---------------|---------------|----------------|
| V100 (32 GB) | 32 GB | 12.1.1 | cu121 | -- | -- |
| V100 (16 GB) | 16 GB | 12.1.1 | cu121 | -- | -- |

## Attention Optimization Summary

### SageAttention

SageAttention replaces the default attention computation with optimized CUDA kernels, providing 2-3x faster generation.

| Compute Capability | Version | Details |
|--------------------|---------|---------|
| SM 90+ (Hopper, Blackwell) | v2 | FP8 attention kernels -- highest performance, uses 8-bit floating point |
| SM 80-89 (Ampere, Ada Lovelace) | v1 | Optimized attention kernels -- significant speedup over default |
| SM 75 and below (Turing, Volta) | Not supported | Set `ENABLE_SAGE_ATTENTION=false` |

### FlashAttention

FlashAttention provides memory-efficient fused attention, reducing VRAM usage and enabling larger batch sizes or higher resolutions.

| Compute Capability | Version | Details |
|--------------------|---------|---------|
| SM 90+ (Hopper, Blackwell) | v3 | Latest version, optimized for Hopper architecture |
| SM 80-89 (Ampere, Ada Lovelace) | v2 | Memory-efficient fused kernels |
| SM 75 and below (Turing, Volta) | Not supported | Set `ENABLE_FLASH_ATTENTION=false` |

### Universal Optimizations

These work on all GPUs regardless of generation:

| Optimization | Minimum SM | Notes |
|-------------|-----------|-------|
| xformers | All listed GPUs | Always installed in the image. Memory-efficient attention and other optimized operations. |
| torch.compile | All listed GPUs | Built into PyTorch. Most effective on Ampere+ but works everywhere. |

## Build Argument Mapping

Three sets of build arguments cover all supported GPUs:

### Blackwell / Hopper

```bash
docker build -f docker/production/Dockerfile -t comfyui-studio .
```

All defaults. No `--build-arg` flags needed.

### Ampere / Ada Lovelace

```bash
docker build -f docker/production/Dockerfile -t comfyui-studio \
  --build-arg CUDA_VERSION=12.4.1 \
  --build-arg PYTORCH_INDEX=cu124 \
  .
```

### Turing / Volta

```bash
docker build -f docker/production/Dockerfile -t comfyui-studio \
  --build-arg CUDA_VERSION=12.1.1 \
  --build-arg PYTORCH_INDEX=cu121 \
  --build-arg ENABLE_SAGE_ATTENTION=false \
  --build-arg ENABLE_FLASH_ATTENTION=false \
  .
```

## VRAM Recommendations

While ComfyUI Studio runs on any GPU listed above, VRAM determines what you can generate:

| VRAM | Capabilities |
|------|-------------|
| 8 GB | SD 1.5 image generation, small LoRAs, limited SDXL |
| 12 GB | SDXL image generation, most LoRAs, basic video (short clips) |
| 16 GB | Comfortable SDXL, CogVideoX I2V, quantized Flux |
| 24 GB | Full Flux, WAN 2.1 video, multiple LoRAs, LTX Video |
| 40+ GB | HunyuanVideo, full-precision large models, long video generation |
| 80+ GB | Multiple models loaded simultaneously, large batch sizes |

!!! tip "Use the configurator"
    Rather than looking up your GPU in this table, run `bash docker/configure.sh`. It automatically selects the correct build arguments for your GPU and explains what each setting does.
