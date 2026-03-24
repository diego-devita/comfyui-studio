# Checkpoint Picker Input Type

The `checkpoint_picker` input type renders a dynamic dropdown populated with checkpoint models that are actually present on disk. Unlike the `select` type (which has a static option list defined in the manifest), this picker queries the backend at page load to discover which checkpoints are downloaded and available. Selecting a checkpoint triggers a `checkpoint-changed` event that updates dependent inputs like `resolution_picker` and `lora_picker_dynamic`.

## YAML Example

From the `t2i-dynamic` manifest:

```yaml
inputs:
  - id: checkpoint
    name: "Checkpoint"
    type: checkpoint_picker
    required: true
    tooltip: "The base model that defines the visual style. This is the advanced T2I workflow with optional hires fix and face detailer."
```

From the `ipa-batch` manifest:

```yaml
  - id: checkpoint
    name: "Checkpoint"
    type: checkpoint_picker
    required: true
    tooltip: "The base model that defines the visual style. Must be SD 1.5 or SDXL-based -- FLUX is not supported by IP-Adapter."
```

## Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | yes | -- | Unique identifier. Convention is `"checkpoint"`. |
| `name` | string | yes | -- | Human-readable label displayed above the dropdown. |
| `type` | string | yes | -- | Must be `checkpoint_picker`. |
| `required` | boolean | no | `false` | Whether a checkpoint must be selected before submission. Almost always `true` for workflows that use a checkpoint. |
| `tooltip` | string | no | -- | Help text explaining what the checkpoint does and any compatibility constraints. |

## Frontend Behavior

When the runner page encounters a `type: checkpoint_picker` input, the `buildCheckpointPicker()` function creates a `<select>` element and asynchronously populates it:

### Loading sequence

1. **Initial state**: The dropdown shows a single disabled option: "Loading checkpoints..."

2. **API call**: The frontend fetches `GET /api/admin/models`, which returns the full model catalog organized by categories.

3. **Filtering**: Only models from the `checkpoints` category are included. The code iterates over `data.categories`, finds the category with `id === "checkpoints"`, and creates `<option>` elements for each model.

4. **Option rendering**: Each option shows:
   - The model's `name` property (human-readable name from the catalog)
   - The `civitai_base_model` in square brackets if available (e.g. `[Pony]`, `[SDXL 1.0]`, `[SD 1.5]`)
   - "(not downloaded)" suffix with `disabled` attribute if the model's `status` is not `"present"`

5. **Placeholder**: A `"-- Select Checkpoint --"` option with empty value is added at the top.

### Option data

Each `<option>` element carries:
- `value`: the model's `file` property (the filename string, e.g. `"cyberrealisticPony_v83.safetensors"`)
- `data-base-model`: the `civitai_base_model` or `base_model` property (e.g. `"Pony"`, `"SDXL 1.0"`, `"SD 1.5"`)

### Checkpoint-changed event

When the user selects a checkpoint, the `change` event listener:

1. Reads the `data-base-model` attribute from the selected option
2. Stores it in the `_selectedCheckpointBase` variable
3. Dispatches a `CustomEvent` named `checkpoint-changed` with `detail.baseModel` set to the base model string

This event is consumed by:
- **`resolution_picker`**: Repopulates its presets based on the base model (see resolution_picker.md)
- **`lora_picker_dynamic`**: Regroups and re-sorts LoRA options to show compatible ones first (see lora-picker-dynamic.md)

### Selected value

The selected value is the checkpoint's filename string (e.g. `"cyberrealisticPony_v83.safetensors"`). This is what gets sent to the backend as the `checkpoint` parameter.

## Backend Behavior

### How the catalog is queried

The `GET /api/admin/models` endpoint (in `models_api.py`) returns the full model catalog built by `catalogs.py`. The catalog includes:

- Models from `catalogs/models.json` (the curated catalog)
- Disk scan results: each model's `status` is set to `"present"` if the file exists in the expected directory, or `"missing"` otherwise
- Download state: models currently being downloaded show `"downloading"` status

Only models with `dest: "checkpoints"` appear in the `checkpoints` category. This includes standard Stable Diffusion checkpoints (SD 1.5, SDXL, Pony, Illustrious, Flux).

### How the selected checkpoint is used

In dynamic workflows, the checkpoint filename is passed as a template variable:

```python
checkpoint = params.get("checkpoint", "")
```

It gets substituted into the setup block's `CheckpointLoaderSimple` node:

```json
{
  "checkpoint": {
    "class_type": "CheckpointLoaderSimple",
    "inputs": {
      "ckpt_name": "{{checkpoint}}"
    }
  }
}
```

The `CheckpointLoaderSimple` node in ComfyUI loads the checkpoint file and outputs three things: the model, the CLIP text encoder, and the VAE. These outputs are then wired to downstream nodes (text encoding, sampling, decoding).

### What base_model means

The `base_model` (or `civitai_base_model`) property indicates which architecture family the checkpoint belongs to. Common values:

| base_model | Architecture | Native resolution | Notes |
|------------|-------------|-------------------|-------|
| `SD 1.5` | Stable Diffusion 1.5 | 512x512 | Oldest, smallest, fastest |
| `SDXL 1.0` | Stable Diffusion XL | 1024x1024 | Larger, higher quality |
| `Pony` | SDXL-based (Pony Diffusion) | 1024x1024 | SDXL architecture with anime/art training |
| `Illustrious` | SDXL-based (Illustrious) | 1024x1024 | SDXL architecture with illustration training |
| `Flux.1 D` / `Flux.1 S` | FLUX | 1024x1024 | Latest architecture, different internals |

This value is critical because it determines:
- Which resolution presets are valid (generating at the wrong resolution produces poor results)
- Which LoRAs are compatible (LoRAs trained for SD 1.5 do not work with SDXL, and vice versa)

## Notes

- Only downloaded checkpoints appear as selectable options. Models in the catalog that have not been downloaded are shown but disabled with the "(not downloaded)" label. The user must go to the Models page to download them first.
- The `checkpoint_picker` has no `default` field. The user must always make an explicit selection. This is intentional -- the checkpoint choice is the most impactful parameter in any image generation workflow, and defaulting to a specific one would bias the output.
- The `checkpoint-changed` event propagation is the mechanism that ties the checkpoint selection to resolution and LoRA pickers. Without selecting a checkpoint, the resolution picker shows generic presets and the LoRA picker shows all LoRAs without base-model grouping priority.
- The selected value is a plain filename string. It does not include any path prefix -- ComfyUI resolves it from its configured checkpoints directory.
- The `checkpoint_picker` type does not appear in WAN video workflows because those use fixed model files (GGUF quantized WAN models) that are loaded by different node types (`UnetLoaderGGUF`, `WanVideoModelLoader`). The picker is specific to standard diffusion checkpoints loaded by `CheckpointLoaderSimple`.
