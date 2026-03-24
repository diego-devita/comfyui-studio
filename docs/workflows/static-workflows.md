# Static Workflows

A static workflow uses a single `workflow.json` file — a ComfyUI API-format graph with parameter placeholders.

## File Structure

```
workflows/wan22-i2v-fp8/
├── manifest.yaml       # Metadata, inputs, outputs
└── workflow.json       # ComfyUI API format with {{placeholders}}
```

## Workflow JSON Format

The workflow JSON **must** be in ComfyUI **API format**, not the UI/graph format. The difference:

| | API Format (required) | UI Format (wrong) |
|---|----------------------|-------------------|
| Structure | Flat dict: `{"1": {...}, "2": {...}}` | Nested: `{"nodes": [...], "links": [...]}` |
| Node IDs | String keys: `"1"`, `"2"`, `"94"` | Integer IDs in objects |
| Connections | `["node_id", output_index]` | Link arrays with IDs |
| Export from ComfyUI | "Save (API Format)" or developer tools | Default save |

### How to get API format

1. Build your workflow in the ComfyUI graph editor
2. Enable Dev Mode (Settings → Dev Mode → Enable)
3. Click "Save (API Format)" — this saves as `workflow_api.json`
4. Rename to `workflow.json` and place in the workflow directory

### Example: simplified structure

```json
{
  "1": {
    "inputs": {
      "ckpt_name": "v1-5-pruned-emaonly.safetensors"
    },
    "class_type": "CheckpointLoaderSimple",
    "_meta": {"title": "Load Checkpoint"}
  },
  "2": {
    "inputs": {
      "text": "a mountain lake at sunset",
      "clip": ["1", 1]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {"title": "Positive Prompt"}
  },
  "3": {
    "inputs": {
      "seed": 12345,
      "steps": 20,
      "cfg": 7.0,
      "sampler_name": "euler",
      "scheduler": "normal",
      "denoise": 1.0,
      "model": ["1", 0],
      "positive": ["2", 0],
      "negative": ["4", 0],
      "latent_image": ["5", 0]
    },
    "class_type": "KSampler",
    "_meta": {"title": "Sampler"}
  }
}
```

Node connections use the format `["node_id", output_index]`:
- `["1", 0]` = node "1", first output (model)
- `["1", 1]` = node "1", second output (clip)
- `["1", 2]` = node "1", third output (vae)

## Parameter Substitution

To make a static workflow configurable, replace hardcoded values with `{{variable}}` placeholders:

```json
{
  "1": {
    "inputs": {
      "ckpt_name": "{{checkpoint}}"
    },
    "class_type": "CheckpointLoaderSimple"
  },
  "2": {
    "inputs": {
      "text": "{{positive_prompt}}",
      "clip": ["1", 1]
    },
    "class_type": "CLIPTextEncode"
  },
  "3": {
    "inputs": {
      "seed": "{{seed}}",
      "steps": "{{steps}}",
      "cfg": "{{cfg}}",
      "sampler_name": "{{sampler_name}}",
      "scheduler": "{{scheduler}}",
      "denoise": "{{denoise}}",
      "model": ["1", 0],
      "positive": ["2", 0],
      "negative": ["4", 0],
      "latent_image": ["5", 0]
    },
    "class_type": "KSampler"
  }
}
```

Each `{{variable}}` corresponds to an input `id` in the manifest. The backend scans all node inputs, finds `{{...}}` patterns, and replaces them with the user's form values.

### Type conversion

- `"{{seed}}"` (string placeholder) → `42` (integer) — the backend converts based on the input type
- `"{{cfg}}"` (string placeholder) → `7.0` (float)
- `"{{positive_prompt}}"` → `"a mountain lake at sunset"` (string stays string)

### What you can't do with placeholders

- You cannot use placeholders for node connections (`["1", 0]`) — the graph structure is fixed
- You cannot conditionally include/exclude nodes — the graph is always the same
- You cannot repeat sections — the number of nodes is fixed

For these capabilities, use [Dynamic Workflows](dynamic-workflows.md).

## Output Node Patching

Before sending the workflow to ComfyUI, the backend patches ALL output nodes to redirect files into the job's output directory. This happens automatically — you don't need to configure it in the workflow JSON.

The patching rules:

| Node Type | Condition | Output Path |
|-----------|-----------|-------------|
| `VHS_VideoCombine` | `save_output=true` | `comfyui-studio/{jobid}/video` |
| `VHS_VideoCombine` | `save_output=false` | Forced to `true`, `comfyui-studio/{jobid}/intermediate` |
| `SaveImage` | — | `comfyui-studio/{jobid}/image` |
| `PreviewImage` | — | `comfyui-studio/{jobid}/preview` |

This ensures **all output files land in the job folder**, never in ComfyUI's temp directory.

## Current Static Workflows

| ID | Name | Models Used |
|----|------|-------------|
| `wan22-i2v-fp8` | WAN 2.2 I2V (FP8 Fast) | WAN 2.2 FP8 high/low, UMT5-XXL FP8, WAN VAE, LightX2V LoRAs, RIFE |
| `wan22-i2v-kijai` | WAN 2.2 I2V (Kijai) | WAN 2.2 Kijai FP8 high/low, UMT5-XXL BF16, WAN VAE BF16, LightX2V distill |
| `wan22-i2v-lightx2v` | WAN 2.2 I2V (LightX2V) | WAN 2.2 LightX2V FP16 high/low, UMT5-XXL FP32, WAN VAE FP32, Remacri, RIFE |

All three are WAN 2.2 Image-to-Video workflows using different model formats and node implementations. They share the same input types (image, prompt, duration, CFG, seed) but use different ComfyUI nodes internally.
