# Deploy on RunPod

## One-Click Deploy

Use the public template:

[**Deploy on RunPod**](https://runpod.io/console/deploy?template=7ox0egslls)

This opens the RunPod GPU selection page with the ComfyUI Studio template pre-configured.

## GPU Selection

Any NVIDIA GPU works. Choose based on your use case:

| Use Case | Recommended | VRAM | Why |
|----------|-------------|------|-----|
| WAN 2.2 video (14B models) | A100 80GB, H100, B200 | 80+ GB | 14B models need ~28 GB VRAM at FP16, more with long videos |
| HunyuanVideo / CogVideoX | A100 40GB, L40S | 40+ GB | Large diffusion models |
| Flux image generation | RTX 4090, A6000, L40S | 24-48 GB | Flux dev FP16 needs ~24 GB |
| SDXL / SD 1.5 images | RTX 3090, A5000, L4 | 16-24 GB | Smaller models, fast generation |
| Budget / experimentation | RTX 3060, T4 | 12-16 GB | Works with FP8/GGUF quantized models |

## Environment Variables

Set these in the RunPod template before launching:

| Variable | Required | Value |
|----------|----------|-------|
| `API_KEY` | **Yes** | A strong password for the web UI. Default is `changeme` — **change it**. |
| `CIVITAI_API_KEY` | Recommended | Your CivitAI API token. Get it from [civitai.com/user/account](https://civitai.com/user/account) → API Keys. Without this, CivitAI model downloads and metadata fetch won't work. |
| `HF_TOKEN` | Recommended | Your HuggingFace access token. Get it from [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens). Without this, gated models (Flux, WAN, Hunyuan) can't be downloaded. |

## Disk Configuration

| Setting | Recommended | Why |
|---------|-------------|-----|
| Container Disk | 5 GB | The Docker image is managed separately — 5 GB is enough for logs and temp files |
| Network Volume | 50+ GB | AI models are large. A single WAN 2.2 FP16 model is ~26 GB. Start with 50-100 GB and expand as needed. |

## Ports

The template exposes:

| Port | Service | Access |
|------|---------|--------|
| 8000 | ComfyUI Studio | `https://<POD_ID>-8000.proxy.runpod.net` — password-protected web UI |
| 8188 | ComfyUI | `https://<POD_ID>-8188.proxy.runpod.net` — graph editor, no authentication |

!!! warning "ComfyUI has no authentication"
    Port 8188 (ComfyUI graph editor) has no password protection. Anyone who knows the URL can access it. Consider not exposing this port if you don't need the graph editor. Advanced users can access it via SSH tunnel instead.

## First Boot

The first boot takes 2-5 minutes:

1. Bootstrap clones the application from GitHub
2. ComfyUI is copied from the Docker image to the persistent volume
3. Both services start

Watch the boot progress in **RunPod → Pod → Logs**. Look for `=== Services started ===`.

## Accessing the Web UI

Open `https://<POD_ID>-8000.proxy.runpod.net` and enter your `API_KEY` at the login page.

## Subsequent Boots

After the first boot, subsequent restarts are faster (~30 seconds) because:

- Bootstrap is skipped (application already on the volume)
- ComfyUI copy is skipped (already on the volume)
- Only the two services need to start

## Updating the Application

Click **Check for Updates** on the Home page. The backend fetches the latest code from GitHub and updates changed components. If the backend code changed, it restarts automatically (~2 seconds).

No need to restart the pod or pull a new Docker image for application updates. Docker image rebuilds are only needed when the infrastructure changes (new custom nodes, new Python packages, CUDA version change).

## SSH Access

RunPod pods support SSH for advanced access:

```bash
ssh <POD_ID>@ssh.runpod.io -i ~/.ssh/id_ed25519
```

From inside the pod you can:

- View logs: `tail -f /var/log/comfyui.log` or `/var/log/admin.log`
- Access ComfyUI on localhost: `curl http://localhost:8188/system_stats`
- Browse files: `ls /workspace/studio/`
- Compile llama-server manually if not in the Docker image
