# ComfyUI Studio -- Model Catalogs

This directory contains the model catalogs that drive the Model Manager, LoRA Manager, and LLM pages in the web UI. Each catalog is a JSON file with versioned metadata — the update mechanism uses these versions to sync catalogs between the repository and running pods.

---

## Files

| File | Description |
|------|-------------|
| `models.json` | AI models: checkpoints, diffusion models, LoRAs, VAE, text encoders, CLIP, ControlNet, IP-Adapter, upscalers, embeddings, detectors, segmentation, face swap, AnimateDiff motion modules |
| `loras.json` | Style LoRAs (separate catalog for user-curated LoRA collections) |
| `llm.json` | LLM GGUF models for the llama-server chat assistant |

---

## Model Catalog (`models.json`)

### Summary

**126 models** across **14 categories**, covering all features advertised by ComfyUI Studio.

Every model in this catalog has a verified download source (HuggingFace or CivitAI) and uses the standardized metadata format described below.

### Coverage by Feature

| Feature | Models | Categories | What's included |
|---------|--------|------------|-----------------|
| **WAN 2.1 / 2.2** | 29 | Diffusion, VAE, Text Enc, CLIP Vision, LoRAs | I2V + T2V (14B + 1.3B) in FP8, FP16, BF16, GGUF Q8; Kijai + LightX2V variants; 3 VAE formats; 4 text encoder formats; SVI Pro, Seko, LightX2V LoRAs |
| **Flux** | 15 | Checkpoints, Diffusion, VAE, Text Enc, CLIP Vision, LoRAs | dev + schnell (FP8 + FP16); Fill, Redux, Depth, Canny; VAE; CLIP-L + T5-XXL (FP8 + FP16); SigCLIP; Depth + Canny LoRAs |
| **HunyuanVideo** | 12 | Diffusion, VAE, Text Enc | T2V + I2V (FP8 + BF16); FramePack I2V; Custom 720p; GGUF Q4 + Q8; VAE (BF16 + FP32); LLaVA-LLaMA3 text encoder (FP8 + FP16) |
| **CogVideoX** | 7 | Diffusion, VAE | 1.0 + 1.5 I2V, 1.5 T2V (BF16); Fun Control (FP8); GGUF Q4; VAE |
| **AnimateDiff** | 16 | AnimateDiff | Motion modules v1.4-v3; Lightning 4/8-step; SDXL beta; v3 adapter; 6 camera LoRAs; SparseCtrl RGB + Scribble |
| **LTX Video** | 8 | Diffusion, Upscalers | v0.9.1, v0.9.5 (2B BF16); LTX-2 19B dev + distilled (FP8); LTX-2.3 22B dev + distilled (FP8); spatial + temporal upsamplers |
| **SDXL** | 9 | Diffusion, VAE, ControlNet, IP-Adapter | Base 1.0 + Turbo; VAE FP16; Union ControlNet ProMax + Depth/Canny/OpenPose; IP-Adapter (4 variants) + FaceID LoRA |
| **SD 1.5** | 11 | Checkpoints, VAE, Text Enc, ControlNet, IP-Adapter, Embeddings | Base checkpoint; VAE ft-mse; CLIP ViT-L/14; ControlNet Depth/Canny/OpenPose/Lineart/Tile; IP-Adapter (6 variants); EasyNegative + veryBadImageNegative |
| **Segmentation** | 4 | Segmentation | SAM 2.1 Hiera: Large, Base Plus, Small, Tiny (all FP16) |
| **Face Swap** | 1 | Face Swap | InsightFace inswapper_128 (ONNX) for ReActor |
| **Upscale** | 6 | Upscalers | 4x Remacri, 4x UltraSharp, RealESRGAN x4, RealESRGAN x4 Anime, LTX spatial + temporal |
| **Detection** | 1 | Detectors | Face YOLOv8m (Ultralytics) |
| | **126 total** | **14 categories** | |

### Categories

| Category | Count | Description |
|----------|-------|-------------|
| Checkpoints | 3 | Full model files (SD 1.5, Flux FP8 dev/schnell) |
| Diffusion Models | 41 | Diffusion UNets and transformers (Flux, WAN, HunyuanVideo, CogVideoX, LTX, SDXL) |
| LoRAs | 11 | Technical LoRAs (Flux ControlNet, WAN acceleration/quality, IP-Adapter FaceID) |
| VAE | 9 | Variational autoencoders (Flux, SD 1.5, SDXL, WAN, HunyuanVideo, CogVideoX) |
| Text Encoders | 10 | CLIP, T5-XXL, UMT5-XXL, LLaVA-LLaMA3 in multiple precisions |
| CLIP Vision | 3 | Visual encoders for WAN, Flux, IP-Adapter |
| ControlNet | 9 | SD 1.5 (Depth, Canny, OpenPose, Lineart, Tile) + SDXL (Union ProMax, Depth, Canny, OpenPose) |
| IP-Adapter | 10 | Image prompt adapters for SD 1.5 (6) and SDXL (4) |
| Upscalers | 6 | Super-resolution (4x) + LTX spatial/temporal upsamplers |
| Embeddings | 2 | Negative prompt embeddings for SD 1.5 |
| Detectors | 1 | Face detection (YOLOv8) for FaceDetailer |
| AnimateDiff | 16 | Motion modules v1.4-v3, Lightning, camera LoRAs, SparseCtrl, SDXL beta |
| Segmentation | 4 | SAM 2.1 segment-anything models |
| Face Swap | 1 | InsightFace model for ReActor face swap |

### Base Models

Models are tagged with a `base_model` field that indicates compatibility:

| base_model | Used by |
|------------|---------|
| `WAN` | WAN 2.1/2.2 diffusion, VAE, text encoders, CLIP Vision |
| `wan-i2v-14b` | WAN I2V LoRAs (used by the LoRA picker for compatibility filtering) |
| `FLUX.1` | Flux diffusion, checkpoints, VAE, text encoders, CLIP Vision, LoRAs |
| `HunyuanVideo` | HunyuanVideo diffusion, VAE, text encoders |
| `CogVideoX` | CogVideoX diffusion, VAE |
| `LTX-Video` | LTX Video diffusion models |
| `SDXL 1.0` | SDXL checkpoints, ControlNet, IP-Adapter |
| `SD 1.5` | SD 1.5 checkpoint, VAE, CLIP, ControlNet, IP-Adapter, embeddings, AnimateDiff |
| _(empty)_ | Models not tied to a specific base (upscalers, detectors, SAM2, face swap) |

### Model Entry Format

Each model entry in the catalog follows this structure:

```json
{
  "name": "WAN 2.2 I2V High Noise 14B [FP8]",
  "file": "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
  "dest": "diffusion_models",
  "source": "huggingface",
  "size_gb": 14.6,
  "base_model": "WAN",
  "tags": ["wan", "video", "i2v", "fp8"],
  "hf_repo": "owner/repo-name",
  "hf_file": "path/to/file.safetensors"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Display name shown in the UI, typically includes base model and precision in brackets |
| `file` | Yes | Exact filename as ComfyUI expects it on disk |
| `dest` | Yes | Subdirectory under `ComfyUI/models/` where the file is saved |
| `source` | Yes | Download source: `"huggingface"` or `"civitai"` |
| `size_gb` | Yes | Approximate file size in GB |
| `base_model` | Yes | Compatibility tag (see table above), empty string if not applicable |
| `tags` | Yes | Array of searchable tags |
| `hf_repo` | If HF | HuggingFace repository (e.g., `"Kijai/HunyuanVideo_comfy"`) |
| `hf_file` | If HF | File path within the HF repo |
| `civitai_version_id` | If CivitAI | CivitAI model version ID (used to build download URL) |

### Download URL Construction

The backend constructs download URLs automatically from the metadata — the `url` field is not needed:

- **HuggingFace**: `https://huggingface.co/{hf_repo}/resolve/main/{hf_file}`
- **CivitAI**: `https://civitai.com/api/download/models/{civitai_version_id}`

Authentication tokens (`HF_TOKEN`, `CIVITAI_API_KEY`) are injected automatically when present.

### Naming Conventions

Model display names follow this pattern:

```
{Model Name} [{Base/Architecture} {Precision}]
```

Examples:
- `WAN 2.2 I2V High Noise 14B [FP8]`
- `FLUX.1-dev [FLUX FP16]`
- `AnimateDiff Lightning 4-step [SD 1.5]`
- `SAM 2.1 Hiera Large [FP16]`
- `ControlNet Union SDXL ProMax [12 modes]`

### Versioning

The catalog has a top-level `version` (integer) and `date` that must match `version.json` → `components.models`:

```json
{
  "version": 23,
  "date": "2026-03-24 17:32",
  "categories": [...]
}
```

Bump both when adding, removing, or modifying models.
