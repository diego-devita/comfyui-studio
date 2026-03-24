# LoRA Picker Dynamic Input Type

The `lora_picker_dynamic` input type renders a multi-slot LoRA stack for image generation workflows. It lets the user add multiple LoRA files, each with an individual strength slider, stacked in a specific order. All LoRA files present on disk are shown (grouped by base model), and the user decides which to apply. The backend builds a chain of `LoraLoader` nodes that feed sequentially into the sampler.

## YAML Example

From the `t2i-dynamic` manifest:

```yaml
inputs:
  - id: loras
    name: "LoRAs"
    type: lora_picker_dynamic
    max_loras: 5
    tooltip: "Optional style/concept LoRAs. Stack up to 5 with individual strength control. Include trigger words in your prompt."
```

From the `i2i-batch` manifest:

```yaml
  - id: loras
    name: "LoRAs"
    type: lora_picker_dynamic
    max_loras: 5
    tooltip: "Optional LoRAs to steer the style or concept. At low denoise LoRAs have subtle effect. At higher denoise LoRAs have more room."
```

## Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | yes | -- | Unique identifier. Convention is `"loras"`. |
| `name` | string | yes | -- | Human-readable label displayed above the picker. |
| `type` | string | yes | -- | Must be `lora_picker_dynamic`. |
| `max_loras` | integer | no | `5` | Maximum number of LoRA slots the user can add. The "+ Add LoRA" button is hidden once this limit is reached. The default of 5 is chosen because more than 5 LoRAs rarely improves results and significantly increases VRAM usage. |
| `tooltip` | string | no | -- | Help text explaining LoRA usage, strength tuning, and trigger words. |

## Frontend Behavior

When the runner page encounters a `type: lora_picker_dynamic` input, the `buildLoraDynamicPicker()` function creates a container and asynchronously populates it.

### Loading sequence

1. **Initial state**: Shows "Loading LoRAs..." text.

2. **API call**: Fetches `GET /api/admin/models` to get the full model catalog.

3. **LoRA collection**: Iterates through the categories, finds the `loras` category, and collects all models with `status === "present"` (downloaded and on disk). Groups them by `civitai_base_model` or `base_model`.

4. **Sorting**: Groups are sorted so that LoRAs matching the currently selected checkpoint's base model appear first. The `baseMatches()` function compares the checkpoint's base model with each group's base model label. Matching groups are prioritized in the sort order.

### Slot structure

Each LoRA slot is a horizontal row containing:

1. **LoRA dropdown** (`<select>` with class `lora-dyn-select`): Shows all available LoRAs organized in `<optgroup>` elements by base model. The first option is "-- None --" (empty value). Groups matching the selected checkpoint are marked with "(selected)" in their optgroup label.

2. **Strength label**: Small "str:" text.

3. **Strength slider** (`<input type="range">` with class `lora-dyn-strength`): Range 0.0 to 2.0, step 0.05, default 1.0. Controls how strongly this LoRA influences the output.

4. **Strength value display**: Shows the current slider value with two decimal places (e.g. "1.00", "0.75").

5. **Remove button** (X): Removes this slot from the stack.

6. **Compatibility warning**: A hidden `<div>` that appears when the selected LoRA's base model does not match the selected checkpoint's base model. Shows: "This LoRA may not be compatible with the selected checkpoint."

### Adding slots

An "+ Add LoRA" button appears below the slot list. Clicking it adds a new empty slot. The button uses the `scene-add-btn` CSS class for consistent styling.

The first slot is added automatically when the picker loads. All slots are removable (including the first).

### Checkpoint-changed interaction

The picker listens for the `checkpoint-changed` event:

```javascript
document.addEventListener('checkpoint-changed', function(e) {
    currentBase = e.detail.baseModel || '';
    rebuildPicker();
});
```

When the checkpoint changes, the entire picker rebuilds: groups are re-sorted (matching base model first), optgroup labels are updated, and compatibility warnings are re-evaluated. Existing selections are reset -- this is by design, since changing the checkpoint means previously selected LoRAs may no longer be compatible.

### Value gathering

The `getLoraDynamicValue()` function collects values from all slots:

```javascript
function getLoraDynamicValue(inputId) {
    var result = [];
    container.querySelectorAll('.lora-dyn-slot').forEach(function(slot) {
        var sel = slot.querySelector('.lora-dyn-select');
        var str = slot.querySelector('.lora-dyn-strength');
        if (sel && sel.value) {
            result.push({file: sel.value, strength: parseFloat(str ? str.value : 1)});
        }
    });
    return result;
}
```

The result is an array of objects, each with:
- `file`: the LoRA filename string
- `strength`: the strength value as a float

Slots with no selection (empty value) are skipped. The array preserves the order of the slots in the UI -- this order matters for the backend.

## Backend Behavior

### LoRA chain assembly

The backend receives the `loras` parameter as a JSON array of `{file, strength}` objects. It builds a chain of `LoraLoader` nodes:

```python
raw_loras = params.get("loras", [])
if raw_loras:
    prev_model = ["checkpoint", 0]    # MODEL output of checkpoint loader
    prev_clip = ["checkpoint", 1]     # CLIP output of checkpoint loader
    lora_nodes = {}

    for i, lora in enumerate(raw_loras):
        lora_file = lora.get("file", "")
        strength = float(lora.get("strength", 1.0))
        if not lora_file:
            continue
        lora_id = f"lora_{i}"
        lora_nodes[lora_id] = {
            "inputs": {
                "lora_name": lora_file,
                "strength_model": strength,
                "strength_clip": strength,
                "model": prev_model,
                "clip": prev_clip,
            },
            "class_type": "LoraLoader",
            "_meta": {"title": f"LoRA: {lora_file[:30]}"}
        }
        prev_model = [lora_id, 0]
        prev_clip = [lora_id, 1]
```

The chain works like this:

```
CheckpointLoader → LoRA_0 → LoRA_1 → LoRA_2 → ... → KSampler
    (model,clip)   (model,clip)   (model,clip)         (model)
```

Each `LoraLoader` node takes the previous node's model and clip outputs as inputs, applies the LoRA modification, and passes the modified model and clip to the next node. The final LoRA's outputs connect to the text encoding (clip) and sampling (model) nodes.

### Order matters

The order of LoRAs in the chain affects the output. Stacking LoRA A then LoRA B gives different results than B then A. This is because each LoRA modifies the model weights, and the second LoRA operates on already-modified weights. The backend preserves the exact order from the frontend array.

### Strength semantics

The `strength` value controls how much the LoRA modifies the base model:

- `0.0`: LoRA has no effect (equivalent to not using it)
- `0.5`: Half-strength application
- `1.0`: Full-strength application (the LoRA's intended effect)
- `1.5-2.0`: Over-strength application (amplified effect, may cause artifacts)

Both `strength_model` and `strength_clip` are set to the same value. Some advanced users may want separate control, but the current UI uses a single slider for simplicity.

### No filtering by compatibility

Unlike `lora_picker` (which filters by `base_model`), the dynamic picker shows ALL LoRAs on disk. The user decides whether a LoRA is compatible. The compatibility warning is informational only -- it does not prevent selection. This design choice exists because:

1. Some LoRAs work across architectures (rare but possible)
2. Users may want to experiment with cross-architecture LoRAs
3. Strict filtering could hide LoRAs the user wants to try

## Notes

- The `max_loras` limit of 5 is a practical guideline, not a technical limitation. More LoRAs means more VRAM usage and longer load times. Each LoRA typically adds 50-200MB of model modifications to keep in memory.
- The `lora_picker_dynamic` type is used in image generation workflows (T2I, I2I, FaceID, IP-Adapter). For WAN video workflows, the `lora_picker` type (with paired LoRAs) is used instead.
- If no LoRAs are selected (all slots empty or no slots added), the backend simply skips the LoRA injection step. The checkpoint's model connects directly to the sampler.
- The `strength_model` and `strength_clip` values are always equal in the current implementation. A future enhancement could add separate model/clip strength sliders.
- When re-running a job, LoRA selections cannot be perfectly restored because the picker rebuilds from current disk state. LoRAs that were used in the original job but have since been deleted will not appear.
