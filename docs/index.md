# ComfyUI Studio

A web management platform for AI image and video generation built on [ComfyUI](https://github.com/comfyanonymous/ComfyUI). Runs as a Docker container on [RunPod](https://runpod.io) (or any NVIDIA GPU machine) with a dedicated interface for managing models, LoRAs, workflows, presets, custom nodes, an LLM assistant, and running generation jobs -- without touching the ComfyUI graph editor.

---

## What You Get

- **Model Manager** -- download, organize, and manage 126 AI models across 14 categories (checkpoints, diffusion models, LoRAs, VAE, text encoders, ControlNet, IP-Adapter, upscalers, and more)
- **Workflow Runner** -- execute 12 predefined workflows through simple forms instead of building node graphs, including inpainting
- **Presets** -- save and reuse workflow configurations, create presets from CivitAI images, run them from the web UI, Telegram, or API
- **Job Queue** -- real-time progress tracking with WebSocket, live preview frames, ETA estimation
- **Job History** -- browse past generations, retry failed jobs, export results
- **Asset Manager** -- browse input/output files, upload references, download results
- **CivitAI Integration** -- check model status, fetch generation data, detect dependencies, add models to catalog from CivitAI
- **Chrome Extension** -- RunPod pod management and CivitAI browser integration from the browser toolbar
- **Telegram Bot** -- run presets from Telegram by sending photos and answering questions
- **LLM Assistant** -- run large language models locally on the GPU for prompt generation and chat
- **Gallery System** -- download and browse CivitAI images for LoRA model galleries
- **Live Updates** -- application code updates from Git without rebuilding the Docker image
- **38 Custom Nodes** -- pre-installed for image generation, video generation, face swap, upscaling, segmentation

## Supported Features

| Category | What's Included |
|----------|----------------|
| **Video Generation** | WAN 2.1/2.2 (I2V, T2V, SVI Pro multi-scene), HunyuanVideo, CogVideoX, AnimateDiff, LTX Video |
| **Image Generation** | Flux, SDXL, SD 1.5 with ControlNet, IP-Adapter, FaceID, inpainting |
| **Processing** | Face swap (ReActor), upscaling (4x), segmentation (SAM2), frame interpolation (RIFE) |
| **LLM** | Local llama-server with Qwen, Llama models via GGUF |
| **Integrations** | CivitAI (model lookup, generation data, presets), Telegram bot, Chrome extension |

## Supported GPUs

Any NVIDIA GPU from V100 to B200. The Docker image is configurable via build arguments for CUDA version, attention optimizations (SageAttention, FlashAttention), and optional components (llama-server).

| Generation | GPUs | Attention |
|------------|------|-----------|
| Blackwell / Hopper | B200, B100, H200, H100 | SageAttention v2 (FP8), FlashAttention v3 |
| Ampere / Ada Lovelace | A100, A6000, L40S, RTX 4090/4080/4070/4060, RTX 3090/3080/3070/3060 | SageAttention v1, FlashAttention v2 |
| Turing | RTX 2080/2070, T4 | xformers only |
| Volta | V100 | xformers only |

## Quick Links

- [Quick Start](getting-started/quick-start.md) -- deploy on RunPod in 5 minutes
- [Architecture Overview](architecture/overview.md) -- how the system is built
- [Workflow Guide](workflows/overview.md) -- how workflows work
- [Presets Guide](presets/overview.md) -- save and reuse configurations
- [Chrome Extension](chrome-extension/overview.md) -- browser toolbar integration
- [Telegram Bot](telegram/overview.md) -- run presets from Telegram
- [API Reference](api/index.md) -- all REST endpoints
- [GitHub Repository](https://github.com/diego-devita/comfyui-studio)
