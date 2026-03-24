# Base Models

The `base_model` field on each catalog entry is a compatibility tag that links models to the architecture they belong to. It controls two runtime behaviors: the resolution picker shows appropriate resolutions for the selected checkpoint, and the LoRA picker filters to only compatible LoRAs.

## Valid Values

| Value | Used For | Architecture |
|-------|----------|-------------|
| `"WAN"` | WAN 2.1/2.2 diffusion models, VAE, text encoders, CLIP Vision | Alibaba WAN video generation |
| `"wan-i2v-14b"` | WAN I2V LoRAs specifically | Used by lora_picker for pair filtering (subset of WAN) |
| `"FLUX.1"` | All Flux models -- dev, schnell, Fill, Redux, Depth, Canny, VAE, CLIP, T5, SigCLIP, LoRAs | Black Forest Labs Flux image generation |
| `"HunyuanVideo"` | HunyuanVideo T2V, I2V, FramePack, Custom, GGUF, VAE, text encoders | Tencent HunyuanVideo |
| `"CogVideoX"` | CogVideoX 1.0, 1.5, Fun Control, GGUF, VAE | Zhipu CogVideoX video generation |
| `"LTX-Video"` | LTX-Video 2B, LTX-2, LTX-2.3, spatial/temporal upsamplers | Lightricks LTX video generation |
| `"SDXL 1.0"` | SDXL Base, Turbo, VAE, ControlNet (Union, Depth, Canny, OpenPose), IP-Adapter, FaceID LoRA, CLIP Vision | Stability AI SDXL |
| `"SD 1.5"` | SD 1.5 checkpoint, VAE, CLIP, ControlNet, IP-Adapter, embeddings, AnimateDiff | Stability AI Stable Diffusion 1.5 |
| `""` (empty) | Standalone models: upscalers, detectors, SAM2 segmentation, face swap | No architecture dependency |

## Exact Values Matter

The `base_model` field is matched as an **exact string** in the backend. Common mistakes:

| Wrong | Correct | Why |
|-------|---------|-----|
| `"flux"` | `"FLUX.1"` | Case-sensitive, must include the `.1` |
| `"FLUX"` | `"FLUX.1"` | Missing the `.1` suffix |
| `"Wan"` | `"WAN"` | Must be all-uppercase |
| `"wan"` | `"WAN"` | Must be all-uppercase |
| `"-"` | `""` | Use empty string, not a dash |
| `"sdxl"` | `"SDXL 1.0"` | Must include the ` 1.0` suffix |
| `"SD1.5"` | `"SD 1.5"` | Must include the space |
| `"sd 1.5"` | `"SD 1.5"` | Must be uppercase `SD` |
| `"HunyuanVideo "` | `"HunyuanVideo"` | No trailing space |
| `"wan-i2v"` | `"wan-i2v-14b"` | Must include the `-14b` suffix |

## WAN vs wan-i2v-14b

WAN has two base_model values because of the LoRA pairing system:

- **`"WAN"`** is used for all WAN diffusion models, VAE, text encoders, and CLIP Vision. These are the core components that any WAN workflow needs.

- **`"wan-i2v-14b"`** is used exclusively for WAN I2V LoRAs -- the acceleration LoRAs (LightX2V, Seko, SVI Pro) that pair with the 14B I2V diffusion models. This narrower tag ensures the LoRA picker only shows these LoRAs when an I2V 14B workflow is selected, not for T2V or 1.3B workflows where they would not be compatible.

When a workflow's `lora_picker` input specifies `base_model: "wan-i2v-14b"`, the API call `GET /api/admin/loras/compatible/wan-i2v-14b` returns only the LoRAs tagged with this specific value. See [LoRA Pairing](lora-pairing.md) for how these are grouped.

## How base_model is Used

### Resolution Picker

The `resolution_picker` input type in workflow manifests reads the `base_model` from the currently selected checkpoint to determine which resolution options to display.

Different architectures support different resolutions. For example:

- WAN video models typically work at 480p or 720p
- Flux image models work at various aspect ratios up to 1024px
- SDXL models work at 1024x1024 base with various aspect ratios
- SD 1.5 models work at 512x512 base

The resolution list is filtered by base_model so users only see valid options for their selected model.

### LoRA Picker

The `lora_picker` input type uses `base_model` to filter compatible LoRAs:

1. The manifest declares which `base_model` the LoRA picker should filter by
2. The frontend calls `GET /api/admin/loras/compatible/{base_model}`
3. The backend searches both `models.json` and `loras.json` for entries matching that `base_model` that also have `pair_id` set
4. Results are grouped by `pair_id` and returned as selectable pairs

### Download Page Filtering

The Models and LoRAs pages use tags for visual filtering (search bar, category filters), but `base_model` is what determines actual runtime compatibility. A model tagged `["wan", "video"]` might appear in a WAN search, but only `base_model: "WAN"` matters for workflow compatibility checks.

## Models with Empty base_model

Models that work independently of any specific architecture have an empty `base_model`:

| Category | Examples | Why empty |
|----------|----------|-----------|
| Upscalers | Remacri, UltraSharp, RealESRGAN | Architecture-agnostic super-resolution |
| Detectors | face_yolov8m | YOLO detection, not tied to diffusion |
| Segmentation | SAM2.1 Large/Base+/Small/Tiny | Segment Anything, independent model |
| Face Swap | inswapper_128 | InsightFace, not diffusion-based |

Two exceptions in the upscalers category:

- `LTX-2.3 Spatial Upscaler 2x` has `base_model: "LTX-Video"` because it is specifically designed for LTX video upscaling
- `LTX-2.3 Temporal Upscaler 2x` has `base_model: "LTX-Video"` for the same reason

## base_model in the Metadata System

When Fetch Metadata runs, CivitAI returns its own `baseModel` field (e.g., `"Wan 2"`, `"SDXL 1.0"`). This is stored as `civitai_base_model` on the entry. If the entry has no `base_model` set, the CivitAI value is copied over. Otherwise, the existing `base_model` is preserved -- because CivitAI's naming does not always match the exact values required by the Studio backend.
