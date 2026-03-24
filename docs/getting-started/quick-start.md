# Quick Start

Deploy ComfyUI Studio on RunPod and open the web UI in under 5 minutes.

## Step 1: Deploy on RunPod

Click the deploy button or go to [RunPod Deploy](https://runpod.io/console/deploy?template=7ox0egslls).

Select a GPU. Any NVIDIA GPU from V100 to B200 works. Recommended:

| Use Case | Recommended GPU | VRAM |
|----------|----------------|------|
| Video generation (WAN 2.2, HunyuanVideo) | A100 80GB, H100, B200 | 80+ GB |
| Image generation (Flux, SDXL) | RTX 4090, A6000, L40S | 24-48 GB |
| Budget / experimentation | RTX 3090, A5000 | 24 GB |

## Step 2: Set Environment Variables

Before launching the pod, set these environment variables in the RunPod template:

| Variable | Required | Value |
|----------|----------|-------|
| `API_KEY` | **Yes** | Choose a strong password. This is your login to the web UI. |
| `CIVITAI_API_KEY` | Recommended | Your CivitAI API token. Without this, you cannot download models from CivitAI or fetch model metadata. Get it from [civitai.com/user/account](https://civitai.com/user/account) → API Keys. |
| `HF_TOKEN` | Recommended | Your HuggingFace access token. Without this, you cannot download gated models (Flux, WAN, Hunyuan, etc.). Get it from [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) → New token → Read access. |

!!! warning "API_KEY is required"
    The default API_KEY is `changeme`. You must set your own strong password. Anyone with this password has full access to your pod through the web UI.

## Step 3: Launch and Wait

Launch the pod. The first boot takes 2-5 minutes because:

1. The bootstrap script clones the application from GitHub
2. ComfyUI is copied from the Docker image to the persistent volume
3. Both services start (ComfyUI on 8188, Studio on 8000)

You can watch the boot progress in the RunPod container logs. Look for:

```
=== ComfyUI Studio — starting ===
[0/3] First boot — bootstrapping application...
[bootstrap] Cloning repo...
[bootstrap] Copied backend
[bootstrap] Copied frontend
[bootstrap] Bootstrap complete — app v12.3.0
[1/3] ComfyUI already present — skipping
[2/3] Starting ComfyUI on port 8188...
      ComfyUI ready after 10 seconds.
[3/3] Starting Studio backend on port 8000...
=== Services started ===
```

## Step 4: Open the Web UI

Once the services are running, open:

```
https://<POD_ID>-8000.proxy.runpod.net
```

Replace `<POD_ID>` with your pod's ID (shown in the RunPod dashboard).

You'll see a login page. Enter the `API_KEY` you set in step 2.

## Step 5: You're In

After login, you'll see the dashboard with:

- Component versions and update status
- GPU/CPU/RAM/disk telemetry
- Quick stats (models, workflows, nodes)

From here:

- Go to **Models** to download AI models
- Go to **Workflows** to see available generation pipelines
- Go to **Run** to execute a workflow

## Next Steps

- [Your First Generation](first-generation.md) — download a model and generate something
- [Environment Variables](environment-variables.md) — all configuration options
- [Architecture Overview](../architecture/overview.md) — understand how the system works
