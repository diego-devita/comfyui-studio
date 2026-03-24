# VAE Picker Input Type

The `vae_picker` input type renders an optional dropdown for overriding the checkpoint's built-in VAE. Most checkpoints include a baked-in VAE that handles encoding images to latent space and decoding latents back to images. However, some checkpoints have suboptimal built-in VAEs, and using a separate, higher-quality VAE file can improve color accuracy, reduce color shift, and produce sharper details.

## YAML Example

From the `t2i-dynamic` manifest:

```yaml
inputs:
  - id: vae_override
    name: "VAE Override"
    type: vae_picker
    required: false
    tooltip: "Override the checkpoint's built-in VAE. Most checkpoints have a good VAE baked in -- only override if you see color issues or know a specific VAE works better (e.g. ft-mse-840000 for SD 1.5)."
```

## Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | yes | -- | Unique identifier. Convention is `"vae_override"`. |
| `name` | string | yes | -- | Human-readable label displayed above the dropdown. |
| `type` | string | yes | -- | Must be `vae_picker`. |
| `required` | boolean | no | `false` | Whether a VAE must be selected. Always `false` -- this is an optional override. |
| `tooltip` | string | no | -- | Help text explaining when and why to override the VAE. |

## Frontend Behavior

When the runner page encounters a `type: vae_picker` input, the `buildVaePicker()` function creates a `<select>` element and asynchronously populates it:

### Loading sequence

1. **Initial state**: The dropdown has one pre-built option: `"Default (from checkpoint)"` with an empty value. This is the default selection.

2. **API call**: Fetches `GET /api/admin/models` to get the full model catalog.

3. **VAE collection**: Iterates through the categories, finds the `vae` category, and creates `<option>` elements for each VAE model with `status === "present"` (downloaded and on disk).

4. **Option rendering**: Each VAE option shows the model's `name` property and has its `value` set to the model's `file` property (the filename string).

### Default behavior

The first option -- `"Default (from checkpoint)"` with empty value -- means "use whatever VAE is baked into the checkpoint." This is pre-selected. The user only changes this if they have a specific reason to override.

### No checkpoint-changed interaction

Unlike `resolution_picker` and `lora_picker_dynamic`, the VAE picker does not respond to `checkpoint-changed` events. It shows all available VAE files regardless of which checkpoint is selected. This is because VAE compatibility is less strict than LoRA compatibility -- most VAE files work with any checkpoint of the same architecture family.

### Value gathering

The dropdown is a standard `<select>` with `data-input-id`. The form gathering logic reads `el.value`:
- Empty string `""` means "use default VAE"
- A filename string means "use this specific VAE file"

## Backend Behavior

### VAE override injection

The backend reads the `vae_override` parameter:

```python
vae_override = params.get("vae_override", "")
```

If the value is empty (no override), the checkpoint's built-in VAE is used. No additional nodes are created.

If a VAE filename is provided, the backend adds a `VAELoader` node to the setup block and redirects the VAE output:

```python
if vae_override:
    setup_tmpl["nodes"]["vae_override"] = {
        "inputs": {"vae_name": vae_override},
        "class_type": "VAELoader",
        "_meta": {"title": "VAE Override"}
    }
    setup_tmpl["exports"]["vae"] = {"node": "vae_override", "output": 0}
```

This works by:

1. **Adding a VAELoader node**: Creates a new node in the workflow that loads the specified VAE file.

2. **Overriding the VAE export**: Changes the setup block's `vae` export to point at the new `VAELoader` node instead of the `CheckpointLoaderSimple` node's VAE output (output index 2).

3. **Downstream effect**: All nodes that consume the VAE (VAEEncode, VAEDecode) now use the overridden VAE because they reference the setup block's `vae` export.

### Where VAE is used

In a typical workflow, the VAE is used in two places:

- **VAEEncode**: Converts the input image (for I2I/IP-Adapter workflows) from pixel space to latent space. The VAE's encoder must understand the image.
- **VAEDecode**: Converts the sampled latent back to pixel space. The VAE's decoder produces the final output image.

Using a mismatched VAE (e.g. an SD 1.5 VAE with an SDXL checkpoint) will produce corrupted output because the latent space dimensions and encoding differ between architectures.

### Common VAE files

| VAE file | Architecture | Use case |
|----------|-------------|----------|
| `vae-ft-mse-840000-ema-pruned.safetensors` | SD 1.5 | Improved color accuracy for SD 1.5 checkpoints. Reduces the "washed out" look some checkpoints have. |
| `sdxl_vae.safetensors` | SDXL | Standalone SDXL VAE. Useful if a checkpoint's baked-in VAE produces color shifts. |
| `ae.safetensors` | FLUX | FLUX autoencoder. Required for FLUX workflows. |

## Notes

- The VAE picker is entirely optional. Most users should leave it on "Default (from checkpoint)" unless they notice specific color issues. Modern checkpoints (especially Pony, Illustrious) almost always have excellent baked-in VAEs.
- The picker only shows VAE files that are downloaded and present on disk (status `"present"`). VAE files listed in the catalog but not downloaded do not appear.
- Unlike the checkpoint picker, the VAE picker has no impact on other form elements. Selecting a different VAE does not change resolution presets, LoRA grouping, or any other input.
- The VAE override only works in dynamic workflows where the backend can inject a `VAELoader` node. Static workflows have their VAE nodes pre-defined in the workflow JSON and cannot be overridden through this mechanism.
- The `vae_picker` type currently only appears in the `t2i-dynamic` workflow. Other dynamic workflows (I2I, FaceID, IP-Adapter) could add it by including a `vae_picker` input in their manifest and handling the `vae_override` parameter in their assembler function.
- If a user selects a VAE that is incompatible with their checkpoint (wrong architecture), ComfyUI will either error out or produce garbled output. The picker does not validate compatibility.
