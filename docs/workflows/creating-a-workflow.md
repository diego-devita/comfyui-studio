# Creating a Workflow

Step-by-step guide to adding a new workflow to ComfyUI Studio.

## Prerequisites

Before starting, you need:

- A working ComfyUI workflow (tested in the graph editor)
- The workflow exported in **API format** (for static) or broken into logical blocks (for dynamic)
- Knowledge of which models and nodes the workflow requires

## Choose: Static or Dynamic?

| If your workflow... | Use |
|---------------------|-----|
| Has a fixed graph structure (same nodes every time) | **Static** |
| Was exported from ComfyUI and you just want to parameterize it | **Static** |
| Has sections that repeat (N scenes, N batches) | **Dynamic** |
| Has conditional sections (enable/disable features) | **Dynamic** |
| Needs reusable blocks shared with other workflows | **Dynamic** |

## Creating a Static Workflow

### Step 1: Export from ComfyUI

1. Build and test your workflow in the ComfyUI graph editor
2. Enable Dev Mode: Settings → Dev Mode → Enable
3. Click **"Save (API Format)"** — saves as `workflow_api.json`
4. This is your `workflow.json`

### Step 2: Add Placeholders

Open the exported JSON and replace hardcoded values with `{{variable}}` placeholders:

Before:
```json
{"inputs": {"text": "a mountain lake", "seed": 12345, "steps": 20}}
```

After:
```json
{"inputs": {"text": "{{positive_prompt}}", "seed": "{{seed}}", "steps": "{{steps}}"}}
```

Every `{{name}}` must correspond to an input `id` in the manifest.

### Step 3: Create the Directory

```
workflows/my-workflow/
├── manifest.yaml
└── workflow.json
```

### Step 4: Write the Manifest

```yaml
id: my-workflow
category: t2i
name: "My Custom Workflow"
version: 1
date: "2026-03-25 10:00"
type: static
description: "Description of what this workflow does."
author: "Your Name"
workflow_file: workflow.json

inputs:
  - id: positive_prompt
    name: "Prompt"
    type: text
    required: true

  - id: seed
    name: "Seed"
    type: seed
    default: -1

  - id: steps
    name: "Steps"
    type: int
    min: 1
    max: 100
    default: 20

outputs:
  - id: image
    name: "Output Image"
    type: image
    node_id: "15"

required_models:
  - "v1-5-pruned-emaonly.safetensors"

required_nodes:
  - "KSampler"
  - "SaveImage"
```

### Step 5: Add to Index

Edit `workflows/index.json`:

```json
{
  "version": 33,
  "date": "2026-03-25 10:00",
  "workflows": [
    ...existing workflows...,
    {"id": "my-workflow", "version": 1, "date": "2026-03-25 10:00"}
  ]
}
```

### Step 6: Bump Versions

Update `version.json`:
- Bump `components.workflows.version` (integer)
- Update `components.workflows.date`
- Update top-level `date`

### Step 7: Test

1. Push to the repository
2. On the pod, click "Check for Updates"
3. Go to Workflows — your workflow should appear
4. Click Run, fill the form, generate

## Creating a Dynamic Workflow

### Step 1: Design the Blocks

Break your workflow into logical sections:

- **Setup block**: loads checkpoint, encodes prompts. Exports: model, clip, positive, negative, vae.
- **Generate block**: creates latent, samples, decodes. Imports: model, positive, negative, vae. Exports: image.
- **Optional blocks**: hires fix, face fix, style transfer — each with their own imports/exports.

### Step 2: Create Block JSONs

For each block, create a JSON file in `blocks/`:

```json
{
  "nodes": {
    "node_id": {
      "inputs": {"field": "{{variable}}", "connection": ["other_node", 0]},
      "class_type": "NodeClassName",
      "_meta": {"title": "Display Name"}
    }
  },
  "imports": ["model", "positive", "negative", "vae"],
  "exports": {
    "image": {"node": "vae_decode", "output": 0}
  },
  "variables": ["seed", "steps", "cfg"]
}
```

See [Block Format](block-format.md) for the complete reference.

### Step 3: Define the Pipeline

In the manifest:

```yaml
type: dynamic
blocks_dir: "blocks"
pipeline:
  - block: setup
    file: "setup.json"
  - block: generate
    file: "generate.json"
```

### Step 4: Write Inputs and Complete the Manifest

Same as static workflows — define all inputs, outputs, required_models, required_nodes.

### Step 5-7: Same as Static

Add to index, bump versions, test.

## Tips

### Converting CivitAI Workflows

Many workflows from CivitAI are in UI format (not API format). To convert:

1. Import the workflow into ComfyUI (drag and drop the JSON or image)
2. Fix any missing nodes (install from ComfyUI-Manager)
3. Fix model paths (CivitAI workflows often use Windows paths or nested directories)
4. Test the workflow runs successfully
5. Export in API format

### Model Path Convention

ComfyUI expects model filenames relative to the models subdirectory. For example:

- Checkpoint: `v1-5-pruned-emaonly.safetensors` (in `models/checkpoints/`)
- LoRA: `my_lora.safetensors` (in `models/loras/`)
- VAE: `vae-ft-mse-840000-ema-pruned.safetensors` (in `models/vae/`)

Some workflows from CivitAI use subdirectories: `WanVideo/2_2/model.safetensors`. Make sure your models are downloaded with the correct path structure, or adjust the workflow.

### Tooltip Writing

Good tooltips:
- Explain what the parameter **does** in practical terms
- Give **recommended values** for common scenarios
- Warn about **pitfalls** (wrong resolution = bad quality, too high CFG = artifacts)
- Reference the checkpoint type when relevant (SD 1.5 vs SDXL vs Pony)

Bad tooltips:
- Just repeating the field name ("The seed value")
- Technical jargon without explanation
- Too short to be useful
