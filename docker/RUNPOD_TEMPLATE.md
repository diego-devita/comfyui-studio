# ComfyUI Studio

Web management platform for ComfyUI -- manage models, LoRAs, workflows, presets,
and run generation jobs from a clean web UI without touching the graph editor.
The application updates itself live from the Git repository without rebuilding the image.

**Pre-installed:** 38 custom nodes, WAN 2.2 SVI Pro, HunyuanVideo, CogVideoX,
AnimateDiff, LTX Video, Flux, SDXL, ControlNet, IP-Adapter, FaceID, face swap,
upscaling, segmentation, LLM chat assistant (llama.cpp with CUDA).

**Key features:**
- Model & LoRA catalog with one-click download from CivitAI and HuggingFace
- Workflow runner with form UI, batch generation, scene chaining
- Preset system -- save and re-run workflows with one click
- Telegram bot integration -- run presets from your phone
- Real-time job queue with WebSocket progress, ETA, live preview
- Job history with retry, re-run, and output download
- Chrome extension for managing pods from your browser
- In-app updates -- backend, frontend, catalogs, and workflows update without image rebuild

## Setup

After launch, open `https://<POD_ID>-8000.proxy.runpod.net` and log in with your API key.
ComfyUI graph editor is also available at `https://<POD_ID>-8188.proxy.runpod.net`.

All settings (API keys, passwords) can be changed from the web UI after first login.
Changes are persisted on the network volume and survive pod restarts.

## Environment Variables

| Variable | Required | How to get it |
|----------|----------|---------------|
| `API_KEY` | **Yes** | Choose a strong password -- this is your login to the web UI |
| `CIVITAI_API_KEY` | Recommended | [civitai.com/user/account](https://civitai.com/user/account) → API Keys |
| `HF_TOKEN` | Recommended | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) → New token (Read) |

- Without `CIVITAI_API_KEY`: model downloads from CivitAI and metadata fetch won't work
- Without `HF_TOKEN`: gated models (Flux, WAN, Hunyuan, etc.) can't be downloaded from HuggingFace

## GPU Compatibility

This image supports any NVIDIA GPU from V100 to B200. Performance optimizations
(SageAttention, FlashAttention) activate automatically on compatible GPUs (Ampere+).

For GPUs with less VRAM, set `COMFYUI_FLAGS`:
- `--highvram` (default) -- >24 GB (datacenter GPUs)
- `--normalvram` -- 12-24 GB
- `--lowvram` -- <12 GB

## Disk Requirements

- **Container Disk:** 5 GB minimum
- **Network Volume:** 50+ GB recommended (models, outputs, workflows, and job history are stored here)

## Resources

- [GitHub Repository](https://github.com/diego-devita/comfyui-studio)
- [Documentation](https://diego-devita.github.io/comfyui-studio/)
- [Docker & Build Guide](https://github.com/diego-devita/comfyui-studio/blob/main/docker/README.md)
- [Backend API Reference](https://github.com/diego-devita/comfyui-studio/blob/main/backend/README.md)
