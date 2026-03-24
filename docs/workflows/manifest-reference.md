# Manifest Reference

Complete field reference for `manifest.yaml`, the file that defines every workflow.

## Full Example

```yaml
id: t2i-batch
category: t2i
name: "Text to Image (Batch)"
version: 3
date: "2026-03-23 01:05"
type: dynamic
description: "Simple text-to-image with checkpoint, CLIP skip, LoRA stack, and native batch support."
author: ""

blocks_dir: "blocks"

pipeline:
  - block: setup
    file: "setup.json"
  - block: generate
    file: "generate.json"

inputs:
  - id: checkpoint
    name: "Checkpoint"
    type: checkpoint_picker
    required: true
    tooltip: "The base model that defines the visual style."

  - id: positive_prompt
    name: "Positive Prompt"
    type: text
    required: true
    placeholder: "masterpiece, best quality, ..."

  - id: seed
    name: "Seed"
    type: seed
    default: -1

outputs:
  - id: image
    name: "Output Images"
    type: image

required_models: []

required_nodes:
  - "CheckpointLoaderSimple"
  - "KSampler"
```

## Top-Level Fields

| Field | Required | Type | Default | Description |
|-------|----------|------|---------|-------------|
| `id` | **Yes** | string | — | Unique workflow identifier. Must match the directory name. Used in URLs (`/run/{id}`) and API calls. Use lowercase with hyphens: `wan22-i2v-fp8`, `t2i-batch`. |
| `name` | **Yes** | string | — | Human-readable display name. Shown on workflow cards and the runner page. Examples: "WAN 2.2 Image to Video (FP8 Fast)", "Text to Image (Batch)". |
| `version` | **Yes** | integer | — | Sequential version number. Bump this every time the workflow changes. Must match the corresponding entry in `workflows/index.json`. |
| `date` | **Yes** | string | — | Last modified date in Italian timezone. Format: `"YYYY-MM-DD HH:MM"`. Example: `"2026-03-23 01:05"`. |
| `type` | No | string | `"static"` | Workflow type: `"static"` or `"dynamic"`. Determines whether the backend looks for `workflow.json` or `blocks/`. |
| `category` | No | string | — | Category badge shown on UI cards. Current values: `"t2i"` (yellow), `"i2v"` (blue), `"i2i"` (orange), `"ipa"` (purple). |
| `description` | No | string | `""` | Description shown in the workflow list and at the top of the runner page. Should explain what the workflow does and its key characteristics in 1-2 sentences. |
| `author` | No | string | `""` | Creator attribution. Currently unused in the UI but stored for metadata. |
| `base_model` | No | string | — | Used by `lora_picker` type inputs to filter compatible LoRAs. Example: `"wan-i2v-14b"`. Only needed for workflows that use the paired LoRA picker. |
| `workflow_file` | No | string | `"workflow.json"` | **Static only.** The filename of the ComfyUI API-format JSON. Must be in the workflow directory. |
| `blocks_dir` | No | string | `"blocks"` | **Dynamic only.** Subdirectory containing block template JSON files. |
| `pipeline` | No | list | — | **Dynamic only.** Ordered list of block stages. See [Dynamic Workflows](dynamic-workflows.md). |
| `inputs` | **Yes** | list | — | Form fields shown to the user. See [Input Types](inputs/index.md). |
| `outputs` | **Yes** | list | — | What the workflow produces. See [Outputs](outputs.md). |
| `required_models` | No | list | `[]` | List of model filenames required to run. Used for readiness check on the workflow list page. |
| `required_nodes` | No | list | `[]` | List of ComfyUI node `class_type` names required. Checked against ComfyUI's `/object_info`. |

## Pipeline Field (Dynamic Only)

The pipeline defines how blocks are assembled. It's a list of stages executed in order:

```yaml
pipeline:
  - block: setup
    file: "setup.json"
  - block: scene_first
    file: "scene_first.json"
    repeat: 1
  - block: scene_extend
    file: "scene_extend.json"
    repeat_variable: "extra_scenes"
  - block: output
    file: "output.json"
```

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `block` | **Yes** | string | Block name. Used for connection mapping between blocks. |
| `file` | **Yes** | string | JSON filename in `blocks_dir`. |
| `repeat` | No | integer | Fixed number of times to instantiate this block. Default: 1 (if neither repeat nor repeat_variable is set). |
| `repeat_variable` | No | string | Name of a variable from the inputs. The block is instantiated N times where N is the runtime value of this variable. Example: `"extra_scenes"` = number of scenes minus 1. |

## Outputs Field

```yaml
outputs:
  - id: video
    name: "Output Video"
    type: video
    node_id: "94"
```

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `id` | **Yes** | string | Output identifier. |
| `name` | **Yes** | string | Display name. |
| `type` | **Yes** | string | `"video"` or `"image"`. Determines how the output is handled (video combine vs save image). |
| `node_id` | No | string | **Static only.** The ComfyUI node ID that produces the final output. For dynamic workflows, the assembler determines this from the last block's exports. |

## Required Models

```yaml
required_models:
  - "ip-adapter-faceid-plusv2_sdxl.bin"
  - "ip-adapter-faceid-plusv2_sdxl_lora.safetensors"
```

Each entry is an exact filename that must exist in the appropriate ComfyUI models subdirectory. The workflow list page checks these and shows:

- **Green badge** — all required models found on disk
- **Red badge** — at least one model missing

Note: this only checks hardcoded requirements. Models selected dynamically by the user (via `checkpoint_picker`, `lora_picker_dynamic`) are not listed here — it's the user's responsibility to have them downloaded.

## Required Nodes

```yaml
required_nodes:
  - "CheckpointLoaderSimple"
  - "KSampler"
  - "IPAdapterFaceID"
```

Each entry is a ComfyUI node `class_type` name. The backend checks these against ComfyUI's `/object_info` endpoint. If a required node is not installed, the workflow shows as not ready.
