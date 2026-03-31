## Chrome Web Store — Description

Browser companion for ComfyUI Studio — connects your RunPod GPU pods and CivitAI browsing to your Studio instance.

### RunPod Management
- View running pods with GPU, uptime, and cost tracking
- Launch new pods with GPU selection, region, volume, and template
- Stop, resume, and terminate pods
- Billing overview with credit balance, spend rate, and estimated time remaining
- Network volume storage costs
- Auto-retry resume/launch when GPU unavailable
- Webhook notifications for pod events (ready, launched, retry success)

### CivitAI Integration
- Browse any CivitAI model page and see which versions are in your catalog, downloaded, or missing
- Add models to your catalog with one click
- View image generation data: checkpoint, LoRAs, embeddings, and settings
- Detect hidden dependencies from prompt tags and negative embeddings, resolved via hash lookup
- Create presets directly from CivitAI images with full parameter mapping
- Auto-detect workflow type (t2i, i2v, t2v) and pre-select the right workflow

### Requires
- A running ComfyUI Studio instance (https://github.com/diego-devita/comfyui-studio)
- RunPod API key for pod management
- Studio URL and API key for CivitAI features

### Open Source
https://github.com/diego-devita/comfyui-studio
