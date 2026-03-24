# Catalog Format

All three catalogs (`models.json`, `loras.json`, `llm.json`) share the same JSON structure. This page documents every field and the rules for constructing valid catalog entries.

## Top-Level Structure

```json
{
  "version": 24,
  "date": "2026-03-24 21:30",
  "categories": [
    {
      "id": "checkpoints",
      "name": "Checkpoints",
      "models": [...]
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `version` | integer | Sequential version number, incremented on every change |
| `date` | string | Last modification timestamp, format `YYYY-MM-DD HH:MM` (Italian timezone, Europe/Rome) |
| `categories` | array | List of category objects |

## Category Object

```json
{
  "id": "diffusion_models",
  "name": "Diffusion Models",
  "models": [...]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Machine-readable identifier. Must match one of the valid category IDs listed below |
| `name` | string | Human-readable display name |
| `models` | array | List of model entry objects |

### Valid Category IDs

The `id` field must be one of these exact strings. The UI and backend logic rely on these identifiers:

| Category ID | Display Name | Typical Contents |
|-------------|-------------|-----------------|
| `checkpoints` | Checkpoints | Full model files (SD 1.5, Flux FP8 merged) |
| `diffusion_models` | Diffusion Models | Diffusion UNets (WAN, Flux, Hunyuan, CogVideoX, LTX) |
| `loras` | LoRAs | LoRA adapter files (technical LoRAs in models.json) |
| `vae` | VAE | Variational autoencoder files |
| `text_encoders` | Text Encoders | CLIP, T5-XXL, UMT5-XXL, LLaVA-LLaMA3 |
| `clip_vision` | CLIP Vision | Vision encoder models for IP-Adapter and I2V |
| `controlnet` | ControlNet | ControlNet condition models |
| `ipadapter` | IP-Adapter | IP-Adapter models for image prompting |
| `upscalers` | Upscalers | Super-resolution models (4x, spatial, temporal) |
| `embeddings` | Embeddings | Textual inversion embeddings |
| `detectors` | Detectors | Face/object detection models |
| `animatediff` | AnimateDiff | Motion modules, camera LoRAs, SparseCtrl |
| `segmentation` | Segmentation | SAM2 segmentation models |
| `faceswap` | Face Swap | InsightFace inswapper models |

## Model Entry -- Standard Fields

A model entry in `models.json` or `loras.json`:

```json
{
  "name": "WAN 2.2 I2V High Noise 14B [FP8]",
  "file": "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
  "dest": "diffusion_models",
  "source": "huggingface",
  "size_gb": 13.3,
  "base_model": "WAN",
  "tags": ["wan", "video", "i2v", "fp8"],
  "hf_repo": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged",
  "hf_file": "split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"
}
```

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Display name. Convention: `"{Model Name} [{Base Precision}]"`, e.g., `"WAN 2.2 I2V High Noise 14B [FP8]"` or `"FLUX.1-dev FP8 [FLUX]"` |
| `file` | string | Exact filename on disk. This is the primary key -- used for download tracking, disk scanning, and all lookups |
| `dest` | string | Subdirectory under `ComfyUI/models/` where the file is stored. E.g., `"diffusion_models"`, `"loras"`, `"vae"`. Some models use nested paths like `"diffusion_models/WanVideo/2_2"` |
| `source` | string | Download provider: `"huggingface"` or `"civitai"` |
| `size_gb` | number | Approximate file size in gigabytes. Used for expected download size calculation and disk space estimates |

### Source-Specific Fields

**For HuggingFace models** (`source: "huggingface"`):

| Field | Type | Description |
|-------|------|-------------|
| `hf_repo` | string | Repository path, e.g., `"Comfy-Org/Wan_2.2_ComfyUI_Repackaged"` |
| `hf_file` | string | File path within the repo, e.g., `"split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"`. May include subdirectories |

**For CivitAI models** (`source: "civitai"`):

| Field | Type | Description |
|-------|------|-------------|
| `civitai_version_id` | integer | Model version ID on CivitAI. Used to construct the download URL |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `base_model` | string | Compatibility tag for filtering. See [Base Models](base-models.md) for valid values |
| `tags` | array of strings | Searchable tags for filtering: `["wan", "video", "i2v", "fp8"]` |
| `pair_id` | string | Groups LoRAs into high/low noise pairs. See [LoRA Pairing](lora-pairing.md) |
| `pair_role` | string | Role within a pair: `"high"`, `"low"`, or `"both"` |

### Metadata Fields (populated by Fetch Metadata)

These fields are populated automatically when the user clicks "Fetch Metadata" on the Models page. They come from the CivitAI and HuggingFace APIs:

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `civitai_model_id` | integer | CivitAI | Parent model ID |
| `civitai_file_id` | integer | CivitAI | Specific file ID |
| `civitai_base_model` | string | CivitAI | Base model tag from CivitAI (e.g., `"Wan 2"`) |
| `civitai_version` | string | CivitAI | Version name string |
| `civitai_type` | string | CivitAI | Model type (e.g., `"Checkpoint"`, `"LORA"`) |
| `civitai_fp` | string | CivitAI | Floating point precision (e.g., `"fp16"`, `"fp8"`) |
| `civitai_tags` | array | CivitAI | Tags from CivitAI |
| `trainedWords` | array | CivitAI | Trigger words for the model |
| `lastModified` | string | CivitAI/HF | Last modification timestamp from the source |
| `name_locked` | boolean | Manual | If `true`, Fetch Metadata will not overwrite the `name` field |

## Model Entry -- LLM Fields

LLM model entries in `llm.json` have the same base fields plus additional LLM-specific ones:

```json
{
  "name": "Qwen 2.5 7B Instruct (Q4_K_M)",
  "file": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
  "dest": "",
  "source": "huggingface",
  "size_gb": 4.7,
  "hf_repo": "bartowski/Qwen2.5-7B-Instruct-GGUF",
  "hf_file": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
  "tags": ["chat", "instruct", "7b", "multilingual"],
  "context_default": 8192,
  "quant": "Q4_K_M"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `quant` | string | GGUF quantization format: `"Q4_K_M"`, `"Q8_0"`, etc. |
| `context_default` | integer | Default context window size in tokens |
| `dest` | string | Always `""` (empty) for LLM models -- they use a flat directory (`STUDIO_DIR/llm/models/`) |

## URL Construction

Download URLs are **never stored** in the catalog. They are constructed at runtime by `download.py`'s `_get_download_url()` function:

**HuggingFace:**
```
https://huggingface.co/{hf_repo}/resolve/main/{hf_file}
```

Example: `hf_repo: "Comfy-Org/Wan_2.2_ComfyUI_Repackaged"` and `hf_file: "split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"` produces:
```
https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors
```

**CivitAI:**
```
https://civitai.com/api/download/models/{civitai_version_id}
```

Example: `civitai_version_id: 94057` produces:
```
https://civitai.com/api/download/models/94057
```

### Authentication Injection

Auth tokens are injected at download time by `_inject_auth()`, never stored in the catalog:

- **HuggingFace:** If `HF_TOKEN` environment variable is set, it is sent as a `Bearer` token in the `Authorization` header
- **CivitAI:** If `CIVITAI_API_KEY` environment variable is set, it is appended as a `?token=` query parameter

## Name Convention

Display names follow the pattern: `"{Model Name} [{Base Precision}]"`

The bracket suffix communicates the model family and precision at a glance:

| Example | Base | Precision |
|---------|------|-----------|
| `WAN 2.2 I2V High Noise 14B [FP8]` | (implied WAN) | FP8 |
| `FLUX.1-dev FP8 [FLUX]` | FLUX | (implied FP8) |
| `HunyuanVideo T2V 720p [BF16]` | (implied HunyuanVideo) | BF16 |
| `SAM 2.1 Hiera Large [FP16]` | (standalone) | FP16 |
| `4x Foolhardy Remacri` | (no bracket) | N/A |

The Fetch Metadata system auto-generates names from CivitAI data using the `_clean_civitai_name()` function, which strips CJK characters, emojis, deduplicates version numbers, and appends the `[Base Precision]` suffix. Set `name_locked: true` on an entry to prevent auto-rename.

## Complete Example

A minimal valid model entry:

```json
{
  "name": "My Custom Model [SD 1.5 FP16]",
  "file": "my_custom_model_fp16.safetensors",
  "dest": "checkpoints",
  "source": "huggingface",
  "size_gb": 2.0,
  "hf_repo": "username/my-model",
  "hf_file": "my_custom_model_fp16.safetensors",
  "base_model": "SD 1.5",
  "tags": ["sd15", "custom"]
}
```

A CivitAI model entry:

```json
{
  "name": "EasyNegative [SD 1.5 FP16]",
  "file": "easynegative.safetensors",
  "dest": "embeddings",
  "source": "civitai",
  "size_gb": 0.0,
  "civitai_version_id": 9208,
  "base_model": "SD 1.5",
  "tags": ["sd15", "negative"]
}
```
