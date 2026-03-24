# Supported Models

Complete table of all 126 models in the catalog, organized by feature area. All models are from HuggingFace unless noted otherwise.

## WAN 2.1 / 2.2 (29 models)

WAN is Alibaba's open-source video generation architecture. The catalog includes both the original 2.1 release and the improved 2.2 release with dual-pass sampling.

### Diffusion Models (13)

| Model | File | Precision | Size | Notes |
|-------|------|-----------|------|-------|
| WAN 2.1 I2V 480p 14B | `wan2.1_i2v_480p_14B_fp16.safetensors` | FP16 | 28.6 GB | Original I2V model |
| WAN 2.1 T2V 14B | `wan2.1_t2v_14B_bf16.safetensors` | BF16 | 26.6 GB | Text-to-video |
| WAN 2.1 T2V 1.3B | `wan2.1_t2v_1.3B_bf16.safetensors` | BF16 | 2.6 GB | Small text-to-video |
| WAN 2.2 I2V High Noise 14B | `wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors` | FP8 | 13.3 GB | Comfy-Org repack |
| WAN 2.2 I2V Low Noise 14B | `wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors` | FP8 | 13.3 GB | Comfy-Org repack |
| WAN 2.2 I2V High Noise 14B | `wan2.2_i2v_high_noise_14B_fp16.safetensors` | FP16 | 28.6 GB | Comfy-Org repack |
| WAN 2.2 I2V Low Noise 14B | `wan2.2_i2v_low_noise_14B_fp16.safetensors` | FP16 | 28.6 GB | Comfy-Org repack |
| WAN 2.2 I2V High Noise 14B Kijai | `Wan2_2-I2V-A14B-HIGH_fp8_e4m3fn_scaled_KJ.safetensors` | FP8 | 15.0 GB | Kijai repack, dest: `diffusion_models/WanVideo/2_2` |
| WAN 2.2 I2V Low Noise 14B Kijai | `Wan2_2-I2V-A14B-LOW_fp8_e4m3fn_scaled_KJ.safetensors` | FP8 | 15.0 GB | Kijai repack, dest: `diffusion_models/WanVideo/2_2` |
| WAN 2.2 I2V High Noise LightX2V | `wan2.2_i2v_A14b_high_noise_lightx2v.safetensors` | FP16 | 28.6 GB | LightX2V official |
| WAN 2.2 I2V Low Noise LightX2V | `wan2.2_i2v_A14b_low_noise_lightx2v.safetensors` | FP16 | 28.6 GB | LightX2V official |
| WAN 2.2 I2V High Noise 14B | `wan2.2_i2v_high_noise_14B_Q8_0.gguf` | GGUF Q8 | 14.6 GB | Quantized |
| WAN 2.2 I2V Low Noise 14B | `wan2.2_i2v_low_noise_14B_Q8_0.gguf` | GGUF Q8 | 14.6 GB | Quantized |

### VAE (3)

| Model | File | Precision | Size |
|-------|------|-----------|------|
| WAN 2.1 VAE | `wan_2.1_vae.safetensors` | FP16 | 0.5 GB |
| WAN 2.1 VAE | `Wan2_1_VAE_fp32.safetensors` | FP32 | 0.5 GB |
| WAN 2.1 VAE | `Wan2_1_VAE_bf16.safetensors` | BF16 | 0.2 GB |

### Text Encoders (4)

| Model | File | Precision | Size |
|-------|------|-----------|------|
| UMT5-XXL | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | FP8 | 4.8 GB |
| UMT5-XXL | `wan21UMT5XxlFP32_fp32.safetensors` | FP32 | 11.0 GB |
| UMT5-XXL | `umt5-xxl-enc-bf16.safetensors` | BF16 | 11.4 GB |
| UMT5-XXL | `umt5_xxl_fp16.safetensors` | FP16 | 9.5 GB |

### CLIP Vision (1)

| Model | File | Size |
|-------|------|------|
| CLIP Vision H | `clip_vision_h.safetensors` | 1.7 GB |

### LoRAs (8)

| Model | File | Size | Pair |
|-------|------|------|------|
| LightX2V 4-step High | `wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors` | 1.1 GB | -- |
| LightX2V 4-step Low | `wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors` | 1.1 GB | -- |
| LightX2V CFG+Step Distill (Kijai) | `lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors` | 0.7 GB | -- |
| Seko-V1 High | `seko_v1_i2v_high_noise_model.safetensors` | 1.2 GB | -- |
| Seko-V1 Low | `seko_v1_i2v_low_noise_model.safetensors` | 1.2 GB | -- |
| LightX2V Unified | `Wan21_I2V_14B_lightx2v_cfg_step_distill_lora_rank64.safetensors` | 0.7 GB | lightx2v-unified (both) |
| SVI v2 PRO High | `SVI_v2_PRO_Wan2.2-I2V-A14B_HIGH_lora_rank_128_fp16.safetensors` | 2.3 GB | svi-v2-pro (high) |
| SVI v2 PRO Low | `SVI_v2_PRO_Wan2.2-I2V-A14B_LOW_lora_rank_128_fp16.safetensors` | 2.3 GB | svi-v2-pro (low) |

All WAN LoRAs have `base_model: "wan-i2v-14b"`. See [LoRA Pairing](lora-pairing.md) for details on dual-pass sampling.

---

## Flux (15 models)

Black Forest Labs' Flux architecture for high-quality image generation.

### Checkpoints (2)

| Model | File | Precision | Size |
|-------|------|-----------|------|
| FLUX.1-dev FP8 | `flux1-dev-fp8.safetensors` | FP8 | 11.6 GB |
| FLUX.1-schnell FP8 | `flux1-schnell-fp8.safetensors` | FP8 | 11.6 GB |

### Diffusion Models (6)

| Model | File | Precision | Size | Notes |
|-------|------|-----------|------|-------|
| FLUX.1-dev | `flux1-dev.safetensors` | FP16 | 23.8 GB | |
| FLUX.1-schnell | `flux1-schnell.safetensors` | FP16 | 23.8 GB | Fast generation |
| FLUX.1-Fill-dev | `flux1-fill-dev.safetensors` | FP16 | 23.8 GB | Inpainting |
| FLUX.1-Redux-dev | `flux1-redux-dev.safetensors` | FP16 | 0.2 GB | Style transfer |
| FLUX.1-Depth-dev | `flux1-depth-dev.safetensors` | FP16 | 23.8 GB | Depth ControlNet |
| FLUX.1-Canny-dev | `flux1-canny-dev.safetensors` | FP16 | 23.8 GB | Canny ControlNet |

### VAE (1)

| Model | File | Size |
|-------|------|------|
| FLUX.1 VAE | `ae.safetensors` | 0.3 GB |

### Text Encoders (3)

| Model | File | Precision | Size |
|-------|------|-----------|------|
| CLIP-L | `clip_l.safetensors` | -- | 0.2 GB |
| T5-XXL | `t5xxl_fp16.safetensors` | FP16 | 9.5 GB |
| T5-XXL | `t5xxl_fp8_e4m3fn.safetensors` | FP8 | 4.8 GB |

### CLIP Vision (1)

| Model | File | Size |
|-------|------|------|
| SigCLIP Vision 384 | `sigclip_vision_patch14_384.safetensors` | 0.9 GB |

### LoRAs (2)

| Model | File | Size |
|-------|------|------|
| FLUX.1-Depth-dev LoRA | `flux1-depth-dev-lora.safetensors` | 0.4 GB |
| FLUX.1-Canny-dev LoRA | `flux1-canny-dev-lora.safetensors` | 0.4 GB |

---

## HunyuanVideo (12 models)

Tencent's open-source video generation model. Supports both text-to-video and image-to-video.

### Diffusion Models (8)

| Model | File | Precision | Size | Notes |
|-------|------|-----------|------|-------|
| HunyuanVideo T2V 720p | `hunyuan_video_720_cfgdistill_fp8_e4m3fn.safetensors` | FP8 | 12.3 GB | |
| HunyuanVideo T2V 720p | `hunyuan_video_720_cfgdistill_bf16.safetensors` | BF16 | 23.9 GB | |
| HunyuanVideo I2V 720p | `hunyuan_video_I2V_720_fixed_fp8_e4m3fn.safetensors` | FP8 | 12.3 GB | |
| HunyuanVideo I2V 720p | `hunyuan_video_I2V_720_fixed_bf16.safetensors` | BF16 | 23.9 GB | |
| HunyuanVideo FramePack I2V | `FramePackI2V_HY_fp8_e4m3fn.safetensors` | FP8 | 15.2 GB | FramePack architecture |
| HunyuanVideo Custom 720p | `hunyuan_video_custom_720p_fp8_scaled.safetensors` | FP8 Scaled | 12.3 GB | |
| HunyuanVideo I2V | `hunyuan_video_I2V-Q4_K_S.gguf` | GGUF Q4 | 7.2 GB | Quantized |
| HunyuanVideo I2V | `hunyuan_video_I2V-Q8_0.gguf` | GGUF Q8 | 13.0 GB | Quantized |

### VAE (2)

| Model | File | Precision | Size |
|-------|------|-----------|------|
| HunyuanVideo VAE | `hunyuan_video_vae_bf16.safetensors` | BF16 | 0.5 GB |
| HunyuanVideo VAE | `hunyuan_video_vae_fp32.safetensors` | FP32 | 0.9 GB |

### Text Encoders (2)

| Model | File | Precision | Size |
|-------|------|-----------|------|
| LLaVA-LLaMA3 | `llava_llama3_fp8_scaled.safetensors` | FP8 | 8.5 GB |
| LLaVA-LLaMA3 | `llava_llama3_fp16.safetensors` | FP16 | 15.0 GB |

---

## CogVideoX (7 models)

Zhipu's open-source video generation model, available in 5B parameter variants.

### Diffusion Models (6)

| Model | File | Precision | Size | Notes |
|-------|------|-----------|------|-------|
| CogVideoX 1.0 5B I2V | `CogVideoX_1_0_5b_I2V_bf16.safetensors` | BF16 | 10.5 GB | |
| CogVideoX 1.5 5B I2V | `CogVideoX_1_5_5b_I2V_bf16.safetensors` | BF16 | 10.4 GB | |
| CogVideoX 1.5 5B T2V | `CogVideoX_1_5_5b_T2V_bf16.safetensors` | BF16 | 10.4 GB | Text-to-video |
| CogVideoX Fun 1.1 5B Control | `CogVideoX_Fun_1_1_5b_Control_fp8_e4m3fn.safetensors` | FP8 | 5.2 GB | ControlNet variant |
| CogVideoX 5B I2V | `CogVideoX_5b_I2V_GGUF_Q4_0.safetensors` | GGUF Q4 | 3.3 GB | Quantized |
| CogVideoX 1.5 5B I2V | `CogVideoX_5b_1_5_I2V_GGUF_Q4_0.safetensors` | GGUF Q4 | 4.1 GB | Quantized |

### VAE (1)

| Model | File | Precision | Size |
|-------|------|-----------|------|
| CogVideoX VAE | `cogvideox_vae_bf16.safetensors` | BF16 | 0.4 GB |

---

## AnimateDiff (16 models)

AnimateDiff motion modules and camera LoRAs for animating Stable Diffusion generations.

### Motion Modules (7)

| Model | File | Base | Size | Notes |
|-------|------|------|------|-------|
| AnimateDiff v3 | `v3_sd15_mm.ckpt` | SD 1.5 | 1.6 GB | Latest |
| AnimateDiff v2 | `mm_sd_v15_v2.ckpt` | SD 1.5 | 1.7 GB | |
| AnimateDiff v1.5 | `mm_sd_v15.ckpt` | SD 1.5 | 1.6 GB | |
| AnimateDiff v1.4 | `mm_sd_v14.ckpt` | SD 1.5 | 1.6 GB | |
| AnimateDiff Lightning 4-step | `animatediff_lightning_4step_comfyui.safetensors` | SD 1.5 | 0.9 GB | Fast |
| AnimateDiff Lightning 8-step | `animatediff_lightning_8step_comfyui.safetensors` | SD 1.5 | 0.9 GB | Fast |
| AnimateDiff SDXL v1.0 Beta | `mm_sdxl_v10_beta.ckpt` | SDXL 1.0 | 0.9 GB | SDXL support |

### Adapter (1)

| Model | File | Size |
|-------|------|------|
| AnimateDiff v3 Adapter | `v3_sd15_adapter.ckpt` | 0.1 GB |

### Camera LoRAs (6)

| Model | File | Size |
|-------|------|------|
| Camera ZoomIn | `v2_lora_ZoomIn.ckpt` | 0.1 GB |
| Camera ZoomOut | `v2_lora_ZoomOut.ckpt` | 0.1 GB |
| Camera PanLeft | `v2_lora_PanLeft.ckpt` | 0.1 GB |
| Camera PanRight | `v2_lora_PanRight.ckpt` | 0.1 GB |
| Camera TiltUp | `v2_lora_TiltUp.ckpt` | 0.1 GB |
| Camera TiltDown | `v2_lora_TiltDown.ckpt` | 0.1 GB |

### SparseCtrl (2)

| Model | File | Size |
|-------|------|------|
| SparseCtrl RGB | `v3_sd15_sparsectrl_rgb.ckpt` | 1.9 GB |
| SparseCtrl Scribble | `v3_sd15_sparsectrl_scribble.ckpt` | 1.9 GB |

---

## LTX Video (8 models)

Lightricks' video generation models, from the 2B v0.9 series through the 19B LTX-2 and 22B LTX-2.3.

### Diffusion Models (6)

| Model | File | Precision | Size | Notes |
|-------|------|-----------|------|-------|
| LTX-Video 2B v0.9.1 | `ltx-video-2b-v0.9.1.safetensors` | BF16 | 5.3 GB | |
| LTX-Video 2B v0.9.5 | `ltx-video-2b-v0.9.5.safetensors` | BF16 | 5.9 GB | T2V + I2V |
| LTX-2 19B Dev | `ltx-2-19b-dev-fp8.safetensors` | FP8 | 25.2 GB | |
| LTX-2 19B Distilled | `ltx-2-19b-distilled-fp8.safetensors` | FP8 | 25.2 GB | Step-distilled |
| LTX-2.3 22B Dev | `ltx-2.3-22b-dev-fp8.safetensors` | FP8 | 27.1 GB | |
| LTX-2.3 22B Distilled | `ltx-2.3-22b-distilled-fp8.safetensors` | FP8 | 27.5 GB | Step-distilled |

### Upsamplers (2)

| Model | File | Size | Notes |
|-------|------|------|-------|
| LTX-2.3 Spatial Upscaler 2x | `ltx-2.3-spatial-upscaler-x2-1.0.safetensors` | 0.9 GB | Resolution upscale |
| LTX-2.3 Temporal Upscaler 2x | `ltx-2.3-temporal-upscaler-x2-1.0.safetensors` | 0.2 GB | Frame rate upscale |

---

## SDXL (9 models)

Stability AI's SDXL 1.0 architecture for high-resolution image generation.

### Diffusion Models (2)

| Model | File | Precision | Size | Notes |
|-------|------|-----------|------|-------|
| SDXL Base 1.0 | `sd_xl_base_1.0.safetensors` | FP16 | 6.9 GB | |
| SDXL Turbo 1.0 | `sd_xl_turbo_1.0.safetensors` | FP16 | 6.9 GB | Fast (1-4 steps) |

### VAE (1)

| Model | File | Size |
|-------|------|------|
| SDXL VAE (FP16 Fix) | `sdxl_vae.safetensors` | 0.3 GB |

### ControlNet (4)

| Model | File | Size | Notes |
|-------|------|------|-------|
| ControlNet Union ProMax | `diffusion_pytorch_model_promax.safetensors` | 2.3 GB | 12 modes in one |
| ControlNet Depth Mid | `diffusers_xl_depth_mid.safetensors` | 0.5 GB | |
| ControlNet Canny Mid | `diffusers_xl_canny_mid.safetensors` | 0.5 GB | |
| ControlNet OpenPose | `diffusion_pytorch_model.safetensors` | 2.3 GB | |

### IP-Adapter (4)

| Model | File | Size | Notes |
|-------|------|------|-------|
| IP-Adapter Plus | `ip-adapter-plus_sdxl_vit-h.safetensors` | 0.8 GB | Style transfer |
| IP-Adapter Plus Face | `ip-adapter-plus-face_sdxl_vit-h.safetensors` | 0.8 GB | Face transfer |
| IP-Adapter FaceID Plus V2 | `ip-adapter-faceid-plusv2_sdxl.bin` | 0.8 GB | FaceID |
| IP-Adapter | `ip-adapter_sdxl_vit-h.safetensors` | 0.7 GB | Base IP-Adapter |

Note: The FaceID Plus V2 model also has a companion LoRA (`ip-adapter-faceid-plusv2_sdxl_lora.safetensors`, 0.3 GB) in the LoRAs category.

---

## SD 1.5 (11 models)

Stability AI's Stable Diffusion 1.5, the most widely used base model for image generation.

### Checkpoint (1)

| Model | File | Precision | Size |
|-------|------|-----------|------|
| Stable Diffusion v1.5 | `v1-5-pruned-emaonly.safetensors` | EMA FP16 | 4.0 GB |

### VAE (1)

| Model | File | Size |
|-------|------|------|
| VAE ft-mse-840000 | `vae-ft-mse-840000-ema-pruned.safetensors` | 0.3 GB |

### Text Encoder (1)

| Model | File | Size |
|-------|------|------|
| CLIP ViT-L/14 | `clip-vit-large-patch14.safetensors` | 0.6 GB |

### ControlNet (5)

| Model | File | Size |
|-------|------|------|
| ControlNet v1.1 Depth | `control_v11f1p_sd15_depth_fp16.safetensors` | 1.4 GB |
| ControlNet v1.1 Canny | `control_v11f1p_sd15_canny_fp16.safetensors` | 1.4 GB |
| ControlNet v1.1 OpenPose | `control_v11f1p_sd15_openpose_fp16.safetensors` | 1.4 GB |
| ControlNet v1.1 Lineart | `control_v11p_sd15_lineart.pth` | 1.4 GB |
| ControlNet v1.1 Tile | `control_v11f1e_sd15_tile.pth` | 1.4 GB |

### IP-Adapter (6)

| Model | File | Size | Notes |
|-------|------|------|-------|
| IP-Adapter Plus | `ip-adapter-plus_sd15.safetensors` | 0.1 GB | Style transfer |
| IP-Adapter Plus Face | `ip-adapter-plus-face_sd15.safetensors` | 0.1 GB | |
| IP-Adapter Full Face | `ip-adapter-full-face_sd15.safetensors` | < 0.1 GB | |
| IP-Adapter | `ip-adapter_sd15.safetensors` | < 0.1 GB | Base |
| IP-Adapter Light v1.1 | `ip-adapter_sd15_light_v11.bin` | < 0.1 GB | Lightweight |
| IP-Adapter ViT-G | `ip-adapter_sd15_vit-G.safetensors` | < 0.1 GB | |

### Embeddings (2) -- from CivitAI

| Model | File | Size |
|-------|------|------|
| EasyNegative | `easynegative.safetensors` | < 0.1 GB |
| veryBadImageNegative v1.3 | `verybadimagenegative_v1.3.pt` | < 0.1 GB |

These are the only two models in the entire catalog sourced from CivitAI rather than HuggingFace.

---

## Shared Components

### CLIP Vision (1)

Shared across SD 1.5 and SDXL IP-Adapter workflows:

| Model | File | Size |
|-------|------|------|
| CLIP Vision H ViT-H/14 | `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` | 2.4 GB |

---

## Segmentation (4 models)

SAM2.1 (Segment Anything Model 2.1) from Meta, in four sizes. All FP16. Used for masking and region selection.

| Model | File | Size |
|-------|------|------|
| SAM 2.1 Hiera Large | `sam2.1_hiera_large-fp16.safetensors` | 0.4 GB |
| SAM 2.1 Hiera Base Plus | `sam2.1_hiera_base_plus-fp16.safetensors` | 0.2 GB |
| SAM 2.1 Hiera Small | `sam2.1_hiera_small-fp16.safetensors` | 0.1 GB |
| SAM 2.1 Hiera Tiny | `sam2.1_hiera_tiny-fp16.safetensors` | 0.1 GB |

---

## Face Swap (1 model)

| Model | File | Size | Format |
|-------|------|------|--------|
| InsightFace inswapper_128 | `inswapper_128.onnx` | 0.5 GB | ONNX |

---

## Upscale (6 models)

Four architecture-agnostic upscalers (empty `base_model`) plus two LTX-specific upsamplers:

| Model | File | Size | Type |
|-------|------|------|------|
| 4x Foolhardy Remacri | `4x_foolhardy_Remacri.pth` | 0.1 GB | General |
| 4x UltraSharp | `4x-UltraSharp.pth` | 0.1 GB | Sharpening |
| RealESRGAN x4 | `RealESRGAN_x4plus.pth` | 0.1 GB | General |
| RealESRGAN x4 Anime | `RealESRGAN_x4plus_anime_6B.pth` | 0.1 GB | Anime |
| LTX-2.3 Spatial Upscaler 2x | `ltx-2.3-spatial-upscaler-x2-1.0.safetensors` | 0.9 GB | LTX spatial |
| LTX-2.3 Temporal Upscaler 2x | `ltx-2.3-temporal-upscaler-x2-1.0.safetensors` | 0.2 GB | LTX temporal |

---

## Detection (1 model)

| Model | File | Size |
|-------|------|------|
| Face YOLOv8m | `face_yolov8m.pt` | 0.1 GB |

Ultralytics YOLOv8 medium model, trained for face detection. Used by face-fix and FaceID workflows.

---

## Summary by Category

| Category | Count | Typical Size Range |
|----------|-------|--------------------|
| Diffusion Models | 41 | 0.2 -- 28.6 GB |
| AnimateDiff | 16 | 0.1 -- 1.9 GB |
| LoRAs | 11 | 0.3 -- 2.3 GB |
| IP-Adapter | 10 | < 0.1 -- 0.8 GB |
| Text Encoders | 10 | 0.2 -- 15.0 GB |
| VAE | 9 | 0.2 -- 0.9 GB |
| ControlNet | 9 | 0.5 -- 2.3 GB |
| Upscalers | 6 | 0.1 -- 0.9 GB |
| Segmentation | 4 | 0.1 -- 0.4 GB |
| Checkpoints | 3 | 4.0 -- 11.6 GB |
| CLIP Vision | 3 | 0.9 -- 2.4 GB |
| Embeddings | 2 | < 0.1 GB |
| Detectors | 1 | 0.1 GB |
| Face Swap | 1 | 0.5 GB |
| **Total** | **126** | |
