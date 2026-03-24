# Build Configurator

The interactive build configurator at `docker/configure.sh` walks you through every build decision and outputs a ready-to-run `docker build` command or a customized Dockerfile.

## Running the Configurator

```bash
bash docker/configure.sh
```

The script runs entirely in the terminal. No dependencies beyond bash. It reads `docker/nodes.txt` and `docker/Dockerfile` from the same directory.

## Walkthrough

The configurator has 5 steps:

### Step 1: GPU Selection

A numbered list of 33 GPUs, grouped by generation:

| Group | GPUs | Compute Capability |
|-------|------|--------------------|
| Blackwell / Hopper | B200, B100, H200, H100, H100 NVL | SM 100, SM 90 |
| Ampere (datacenter) | A100 (80/40 GB), A6000, A5000, A4000 | SM 80, SM 86 |
| Ada Lovelace (datacenter) | L40S, L40, L4 | SM 89 |
| Ada Lovelace (consumer) | RTX 4090, 4080 SUPER, 4080, 4070 Ti, 4070, 4060 Ti, 4060 | SM 89 |
| Ampere (consumer) | RTX 3090/3090 Ti, 3080 Ti, 3080, 3070 Ti, 3070, 3060 | SM 86 |
| Turing | RTX 2080 Ti, 2080 SUPER, 2080, 2070, T4 | SM 75 |
| Volta | V100 (32/16 GB) | SM 70 |

Each entry shows the GPU name, VRAM, and SM architecture. You type the number of your GPU.

### Step 2: Parameter Confirmation

Based on your GPU selection, the script auto-resolves all build parameters:

- **CUDA_VERSION** -- determined by GPU generation (12.8.1 / 12.4.1 / 12.1.1)
- **PYTORCH_INDEX** -- matched to CUDA version (cu128 / cu124 / cu121)
- **PYTHON_VERSION** -- always 3.12
- **ENABLE_SAGE_ATTENTION** -- true for Ampere+ (SM 80+), false otherwise
- **ENABLE_FLASH_ATTENTION** -- true for Ampere+ (SM 80+), false otherwise

The script displays the resolved values with explanations:

- For SageAttention, it shows the version that will be installed (v2 with FP8 kernels on Hopper/Blackwell, v1 on Ampere/Ada Lovelace)
- For FlashAttention, it notes the version (v3 on Hopper/Blackwell, v2 on Ampere/Ada Lovelace) and warns about the 20-30 minute build time

You can accept the defaults (`Y`) or override any value manually (`n`).

### Step 3: LLM Support

The script asks whether to include llama-server for local LLM inference. If you choose yes, two follow-up questions:

**Build environment:**

| Option | Description | Build Time |
|--------|-------------|------------|
| With target GPU | Compiler auto-detects the GPU and builds kernels for that single architecture only | ~10 min |
| Without GPU (CI) | Builds kernels for all supported architectures (SM 75 through SM 100) | ~60 min |

The distinction matters because CUDA compilation time scales with the number of target architectures. When a GPU is present during the build, CMake's native detection (`GGML_NATIVE=OFF` is still set, but the CUDA toolkit detects the device) can limit compilation. Without a GPU -- the typical case for CI runners like GitHub Actions -- the build must compile for every architecture listed in `CMAKE_CUDA_ARCHITECTURES`.

**llama.cpp version:**

| Option | Description |
|--------|-------------|
| `b8505` (default) | Pinned release, tested with this build. Reproducible. |
| `latest` | Clones HEAD of the llama.cpp repo. Gets newest features but may break. |
| Custom tag | Any valid git tag (e.g., `b8400`). |

If you decline LLM support, `ENABLE_LLM` is set to `false` and the entire llama.cpp compilation step is skipped.

### Step 4: Custom Node Categories

The script parses `docker/nodes.txt` and presents 6 toggleable categories:

| # | Category | Nodes | Description |
|---|----------|-------|-------------|
| 1 | Fundamentals / QoL | 10 | Manager, essentials, seed control, utilities |
| 2 | Image Generation | 14 | ControlNet, IP-Adapter, face swap, upscale, GGUF |
| 3 | Performance Optimization | 1 | WaveSpeed -- FBCache + torch.compile, 1.5-2x speedup |
| 4 | Segmentation | 2 | SAM2, Florence2 -- segment anything by text or click |
| 5 | Video Generation | 8 | VHS, AnimateDiff, WAN, Hunyuan, LTX, CogVideo, Mochi |
| 6 | CivitAI Integration | 3 | Load models by CivitAI ID, browse trends, apply recipes |

All categories are selected by default. Toggle individual categories by number, use `a` to select all, `n` to deselect all, or press Enter to confirm.

### Step 5: Output

The script offers two output formats:

**Docker build command** (when all node categories are selected):

```bash
docker build -f docker/Dockerfile -t comfyui-studio \
  --build-arg CUDA_VERSION=12.4.1 \
  --build-arg PYTORCH_INDEX=cu124 \
  .
```

Only non-default arguments are included. If your GPU matches the Dockerfile defaults (Blackwell/Hopper), the command is just `docker build -f docker/Dockerfile -t comfyui-studio .` with no extra args.

**Customized Dockerfile** (always used when node categories are deselected):

The script generates two files in the `docker/` directory:

- `Dockerfile.custom` -- Dockerfile with your build args baked into the ARG defaults
- `nodes.custom.txt` -- filtered `nodes.txt` with excluded categories removed

```bash
docker build -f docker/Dockerfile.custom -t comfyui-studio .
```

### Build Time Estimate

After output, the script shows an estimated build time breakdown:

```
Estimated build time:

  Base (ComfyUI + nodes + PyTorch):    ~15-25 min
  + FlashAttention (from source):      ~20-30 min
  + llama.cpp (all GPU architectures): ~60 min
  ──────────────────────────────────────
  Total estimate:                      ~85-115 min
```

The estimate adjusts based on your selections. Disabling FlashAttention and LLM support brings the build down to ~15-25 minutes.

## Examples

**Fastest possible build** (Turing GPU, no attention, no LLM):

The configurator would produce:

```bash
docker build -f docker/Dockerfile -t comfyui-studio \
  --build-arg CUDA_VERSION=12.1.1 \
  --build-arg PYTORCH_INDEX=cu121 \
  --build-arg ENABLE_SAGE_ATTENTION=false \
  --build-arg ENABLE_FLASH_ATTENTION=false \
  --build-arg ENABLE_LLM=false \
  .
```

Estimated time: ~15-25 minutes.

**Full build for A100** (all features, CI environment):

```bash
docker build -f docker/Dockerfile -t comfyui-studio \
  --build-arg CUDA_VERSION=12.4.1 \
  --build-arg PYTORCH_INDEX=cu124 \
  .
```

Estimated time: ~85-115 minutes (FlashAttention from source + llama.cpp for all architectures).

## How It Works

The script stores a GPU database as a bash array with pipe-delimited fields:

```
"name|vram|sm|cuda|pytorch|sage|flash"
```

When you select a GPU, the script extracts the fields and maps them to build arguments. Group boundaries are tracked with index arrays for display formatting.

The category parser reads `nodes.txt` line by line, detecting section markers (`# -- Section Name --`) and counting non-comment, non-empty lines within each section.

For the customized Dockerfile output, the script uses `sed` to replace `ARG` defaults in the Dockerfile and filters `nodes.txt` by skipping entire sections that were deselected.
