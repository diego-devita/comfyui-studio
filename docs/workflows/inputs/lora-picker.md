# LoRA Picker Input Type

The `lora_picker` input type renders a paired LoRA selector designed for WAN SVI Pro dual-pass sampling workflows. Unlike `lora_picker_dynamic` (which manages individual LoRA files), this picker works with LoRA **pairs** -- each pair consists of a "high noise" variant and a "low noise" variant that are applied to different sampling passes. This exists because WAN SVI Pro uses two sampling stages (high noise removal first, then low noise refinement), and each stage benefits from a different LoRA weight.

## YAML Example

From the `wan22-svi-dynamic` manifest:

```yaml
inputs:
  - id: loras
    name: "LoRAs"
    type: lora_picker
    base_model: "wan-i2v-14b"
    max_loras: 3
    tooltip: "Select up to 3 LoRA pairs compatible with WAN I2V 14B. LoRAs come in high/low noise pairs -- both are applied automatically at different sampling stages."
```

## Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | yes | -- | Unique identifier. Convention is `"loras"`. |
| `name` | string | yes | -- | Human-readable label displayed above the picker. |
| `type` | string | yes | -- | Must be `lora_picker`. |
| `base_model` | string | yes | -- | The model family to filter compatible LoRAs. Passed to the backend API to fetch only LoRAs compatible with this model (e.g. `"wan-i2v-14b"`). |
| `max_loras` | integer | no | `3` | Maximum number of LoRA pair slots. Lower than `lora_picker_dynamic` because WAN workflows are more VRAM-constrained. |
| `tooltip` | string | no | -- | Help text explaining paired LoRA behavior. |

## Frontend Behavior

When the runner page encounters a `type: lora_picker` input, the `buildLoraPicker()` function creates a container and asynchronously populates it with compatible LoRA pairs.

### Loading sequence

1. **Initial state**: Shows "Loading compatible LoRAs..." text.

2. **API call**: Fetches `GET /api/admin/loras/compatible/{base_model}` (e.g. `/api/admin/loras/compatible/wan-i2v-14b`). This endpoint returns LoRAs grouped by `pair_id`, with each pair containing high, low, and/or both variants.

3. **Filtering**: The response is filtered to exclude system LoRAs that are always applied automatically:
   - `lightx2v-unified` (the LightX2V acceleration LoRA, always included in the workflow's setup block)
   - `svi-v2-pro` (the SVI Pro LoRA, always included)

   Only user-selectable style/motion LoRAs remain.

4. **Empty state**: If no compatible LoRA pairs are available, shows: "No style LoRAs available. Download them from the Models page."

### Slot structure

Each LoRA slot is a horizontal row containing:

1. **Pair dropdown** (`<select>` with class `lora-select`): Lists all available LoRA pairs by their `name` or `pair_id`. The first option is "-- None --" (empty value).

2. **Strength toggle button** (labeled "str"): Toggles visibility of the H/L strength controls. Hidden by default to keep the interface clean.

3. **Strength panel** (hidden by default): Contains two sub-rows:
   - **H (High)**: A range slider (0.0 to 3.0, step 0.1, default 1.0) controlling the strength of the high-noise LoRA variant.
   - **L (Low)**: A range slider (same range) controlling the strength of the low-noise LoRA variant.

   Each slider has a numeric display showing the current value.

4. **Remove button** (X): Removes this slot. All slots are removable.

### Adding slots

A "+ Stack another LoRA" button appears below the slot list. Clicking it adds a new empty slot. No slot is added by default on initial load -- the user must actively choose to add LoRA pairs.

### Value gathering

The `getLoraPickerValue()` function collects values from all slots:

```javascript
function getLoraPickerValue(inputId) {
    var result = [];
    container.querySelectorAll('.lora-slot').forEach(function(slot) {
        var sel = slot.querySelector('.lora-select');
        var strH = slot.querySelector('.lora-str-high');
        var strL = slot.querySelector('.lora-str-low');
        if (sel && sel.value) {
            result.push({
                pair_id: sel.value,
                strength_high: parseFloat(strH ? strH.value : 1),
                strength_low: parseFloat(strL ? strL.value : 1)
            });
        }
    });
    return result;
}
```

The result is an array of objects, each with:
- `pair_id`: the LoRA pair identifier string
- `strength_high`: strength for the high-noise pass (default 1.0)
- `strength_low`: strength for the low-noise pass (default 1.0)

### Re-run prefill

When re-running a job, the `prefillLoraPicker()` function stores the saved LoRA data in `container.dataset.prefillLoras`. After the API response loads the available pairs, the picker reads this data and:

1. Clears any default slots
2. Creates a slot for each saved LoRA pair
3. Selects the matching pair_id in each dropdown
4. Sets the H/L strength sliders to the saved values
5. Shows the strength panel if either value differs from the default (1.0)

## Backend Behavior

### Compatible LoRA API

The `GET /api/admin/loras/compatible/{base_model}` endpoint returns LoRAs from the catalog that match the specified base model. Each LoRA in the catalog has:

- `pair_id`: Groups related high/low variants together (e.g. `"wan-motion-style-01"`)
- `pair_role`: Either `"high"` (for high-noise pass), `"low"` (for low-noise pass), or `"both"` (works for either pass)
- `base_model`: Which model family the LoRA is compatible with

The endpoint groups LoRAs by `pair_id` and returns pairs where at least one variant exists on disk.

### LoRA pair resolution

The backend assembler receives the `loras` array and maps `pair_id` values to actual filenames:

```python
for lora_sel in user_loras:
    pid = lora_sel["pair_id"]
    str_h = lora_sel["strength_high"]
    str_l = lora_sel["strength_low"]
    pair = lora_file_map.get(pid, {})
    high_file = pair.get("high", pair.get("both", ""))
    low_file = pair.get("low", pair.get("both", ""))
```

For each pair:
- The `high` variant file is looked up. If not found, the `both` variant is used.
- The `low` variant file is looked up. If not found, the `both` variant (or the high variant) is used.

### Application to dual-pass sampling

The WAN SVI Pro workflow uses two sampling passes:

1. **High-noise pass**: Removes large-scale noise. Uses `sigmas_high` (first half of the sigma schedule). The high-noise LoRA variant is applied to the model used in this pass.

2. **Low-noise pass**: Refines details. Uses `sigmas_low` (second half of the sigma schedule). The low-noise LoRA variant is applied to the model used in this pass.

The backend applies LoRAs to the setup block's `Power Lora Loader (rgthree)` nodes:

```python
setup_tmpl["nodes"]["lora_high"]["inputs"][slot] = {
    "on": True,
    "lora": high_file,
    "strength": str_h
}
setup_tmpl["nodes"]["lora_low"]["inputs"][slot] = {
    "on": True,
    "lora": low_file or high_file,
    "strength": str_l
}
```

The `lora_high` node feeds into the high-noise model path, and `lora_low` feeds into the low-noise model path. This separation allows different LoRA weights per pass -- a common technique where the high-noise pass uses a stronger LoRA influence and the low-noise pass uses a more conservative one.

### Multiple pairs

Multiple LoRA pairs are applied in order. Each pair occupies a slot (`lora_1`, `lora_2`, etc.) in the Power Lora Loader. The loader applies all LoRAs simultaneously, not in a sequential chain like `lora_picker_dynamic`. After all slots are filled, template placeholder slots (`{{...}}`) are cleaned up.

## Notes

- The `lora_picker` type is specifically designed for WAN SVI Pro workflows. Do not use it for standard image generation workflows -- use `lora_picker_dynamic` instead.
- The `base_model` field in the manifest is required and determines which LoRAs the API returns. It is not derived from a checkpoint_picker selection (unlike `lora_picker_dynamic`).
- System LoRAs (LightX2V accelerator, SVI Pro base) are automatically excluded from the picker because they are always loaded by the workflow's setup block regardless of user selection.
- The strength range goes up to 3.0 (higher than `lora_picker_dynamic`'s 2.0) because WAN workflows sometimes use elevated LoRA strengths, especially for the accelerator LoRA.
- The "str" toggle keeps the interface minimal by default. Most users will leave strengths at 1.0. Advanced users can click "str" to fine-tune per-pass strengths.
- When no LoRA pairs are selected, the workflow still works -- it just uses the base model without additional style modifications. The system LoRAs (LightX2V, SVI Pro) are still applied.
