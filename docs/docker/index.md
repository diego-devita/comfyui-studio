# Docker & Build

The ComfyUI Studio Docker image packages ComfyUI, 38 custom nodes, Python with PyTorch/CUDA, optional attention optimizations, and an optional llama-server binary into a single image ready for GPU cloud providers like RunPod.

The image is configurable via build arguments to target any NVIDIA GPU from Volta (V100) through Blackwell (B200).

## Pages

| Page | Description |
|------|-------------|
| [Build Configurator](configurator.md) | Interactive shell script that walks you through GPU selection, LLM support, and node categories, then outputs a ready-to-run `docker build` command or a customized Dockerfile. |
| [Build Arguments](build-arguments.md) | Reference for all 7 `--build-arg` parameters: CUDA version, PyTorch index, Python version, SageAttention, FlashAttention, LLM support, and llama.cpp version. Includes build examples. |
| [Custom Nodes](custom-nodes.md) | The 38 custom nodes bundled in the image, organized into 6 categories. How `nodes.txt` and `install_nodes.sh` work, how to add or remove nodes, and runtime installation via the UI. |
| [llama-server](llama-server.md) | How the llama.cpp server binary is compiled with CUDA inside the Docker image. Build flags, CUDA architecture targets, the `--allow-shlib-undefined` linker workaround, and version pinning. |
| [GPU Compatibility](gpu-compatibility.md) | Full compatibility table for 33 GPUs across 7 generations. Lists VRAM, compute capability, recommended CUDA version, PyTorch index, and supported SageAttention/FlashAttention versions. |
| [CI/CD](ci-cd.md) | GitHub Actions workflow that builds and pushes the image to GHCR. Trigger rules, registry caching strategy, image tagging, and configurable build variables. |

## Quick Reference

**Default build** (Blackwell/Hopper, all features):

```bash
docker build -f docker/Dockerfile -t comfyui-studio .
```

**Guided build** (interactive configurator):

```bash
bash docker/configure.sh
```

**Image registry:**

```
ghcr.io/diego-devita/comfyui-studio:latest
ghcr.io/diego-devita/comfyui-studio:sha-<commit>
```

## Key Files

| File | Purpose |
|------|---------|
| `docker/Dockerfile` | Multi-stage build, all build args, layer caching strategy |
| `docker/configure.sh` | Interactive build configurator script |
| `docker/nodes.txt` | Custom node list with section markers |
| `docker/install_nodes.sh` | Node installer (reads `nodes.txt` between section markers) |
| `docker/start.sh` | Container entrypoint (bootstrap + process supervision) |
| `docker/bootstrap.py` | First-boot setup (clone repo, copy to working dirs) |
| `.github/workflows/build.yml` | CI/CD workflow for automated builds |
