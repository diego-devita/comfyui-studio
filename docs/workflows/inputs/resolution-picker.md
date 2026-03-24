# Resolution Picker Input Type

The `resolution_picker` input type renders an adaptive preset dropdown that changes its available options based on the selected checkpoint's `base_model`. Different checkpoint architectures are trained at different native resolutions, and generating at the wrong resolution produces poor results (distorted anatomy, blurry output, artifacts). This picker ensures the user selects a resolution that matches their checkpoint.

## YAML Example

From the `t2i-dynamic` manifest:

```yaml
inputs:
  - id: resolution
    name: "Resolution"
    type: resolution_picker
    presets:
      sd15: [{label: "512x512", w: 512, h: 512}, {label: "512x768", w: 512, h: 768}, {label: "768x512", w: 768, h: 512}]
      sdxl: [{label: "1024x1024", w: 1024, h: 1024}, {label: "832x1216", w: 832, h: 1216}, {label: "1216x832", w: 1216, h: 832}]
      pony: [{label: "1024x1024", w: 1024, h: 1024}, {label: "832x1216", w: 832, h: 1216}, {label: "1216x832", w: 1216, h: 832}]
      flux: [{label: "1024x1024", w: 1024, h: 1024}, {label: "768x1344", w: 768, h: 1344}, {label: "1344x768", w: 1344, h: 768}]
    default: {w: 1024, h: 1024}
    tooltip: "Output size. Must match checkpoint training resolution."
```

From the `ipa-batch` manifest (includes illustrious presets):

```yaml
  - id: resolution
    name: "Resolution"
    type: resolution_picker
    presets:
      sd15: [{label: "512x512", w: 512, h: 512}, {label: "512x768", w: 512, h: 768}, {label: "768x512", w: 768, h: 512}]
      sdxl: [{label: "1024x1024", w: 1024, h: 1024}, {label: "832x1216", w: 832, h: 1216}, {label: "1216x832", w: 1216, h: 832}]
      pony: [{label: "1024x1024", w: 1024, h: 1024}, {label: "832x1216", w: 832, h: 1216}, {label: "1216x832", w: 1216, h: 832}]
      illustrious: [{label: "1024x1024", w: 1024, h: 1024}, {label: "832x1216", w: 832, h: 1216}, {label: "1216x832", w: 1216, h: 832}]
      flux: [{label: "1024x1024", w: 1024, h: 1024}, {label: "768x1344", w: 768, h: 1344}, {label: "1344x768", w: 1344, h: 768}]
    default: {w: 832, h: 1216}
    tooltip: "Output image size. Portrait (832x1216) works best for face-focused generation."
```

## Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | yes | -- | Unique identifier. Convention is `"resolution"`. |
| `name` | string | yes | -- | Human-readable label displayed above the picker. |
| `type` | string | yes | -- | Must be `resolution_picker`. |
| `presets` | object | yes | -- | A dictionary mapping preset group keys to arrays of resolution options. Each option has `label`, `w`, and `h`. See preset mapping below. |
| `default` | object | no | `{w: 1024, h: 1024}` | The default resolution as an object with `w` and `h` fields. Used as fallback when no preset group matches. |
| `tooltip` | string | no | -- | Help text explaining resolution matching and aspect ratios. |

### Preset object format

Each preset group maps to an array of resolution options:

```yaml
presets:
  sd15:
    - {label: "512x512", w: 512, h: 512}      # Square
    - {label: "512x768", w: 512, h: 768}      # Portrait
    - {label: "768x512", w: 768, h: 512}      # Landscape
```

| Field | Type | Description |
|-------|------|-------------|
| `label` | string | What the user sees in the dropdown. Usually `"WxH"` format. |
| `w` | integer | Width in pixels. |
| `h` | integer | Height in pixels. |

### Preset group mapping

The frontend maps the checkpoint's `base_model` string to a preset group key using substring matching:

| base_model contains | Preset key used | Typical resolutions |
|---------------------|-----------------|---------------------|
| `"sd 1.5"` or `"sd1"` | `sd15` | 512x512, 512x768, 768x512 |
| `"sdxl"` | `sdxl` | 1024x1024, 832x1216, 1216x832 |
| `"pony"` | `pony` | 1024x1024, 832x1216, 1216x832 |
| `"illustrious"` | `illustrious` (falls back to `sdxl` if not defined) | 1024x1024, 832x1216, 1216x832 |
| `"flux"` | `flux` | 1024x1024, 768x1344, 1344x768 |
| no match | `sdxl` (fallback) | 1024x1024, 832x1216, 1216x832 |

The matching is case-insensitive. The check order is: pony, illustrious, sdxl, sd 1.5/sd1, flux. If no group matches, `sdxl` is used as the default group.

## Frontend Behavior

When the runner page encounters a `type: resolution_picker` input, the `buildResolutionPicker()` function creates a composite element:

### Element structure

- A container `<div>` with `data-input-id` set to the input's id. Uses flexbox layout with an 8px gap.
- A **preset dropdown** (`<select>` with class `form-input`): Shows the resolution presets for the current base model, plus a "Custom..." option at the bottom.
- Two **number inputs** for width and height: Hidden by default. Only shown when "Custom..." is selected. Each has class `form-input`, width of 80px, and placeholder text ("W" or "H").

### Preset population

The `populatePresets(baseModel)` function:

1. Clears the dropdown
2. Determines the preset key from the base model string using the mapping above
3. Creates `<option>` elements for each resolution in the matching preset group
4. Each option has `value` set to `"WxH"` and `data-w`/`data-h` attributes with the numeric dimensions
5. Appends a "Custom..." option with value `"custom"`

### Checkpoint-changed interaction

The picker listens for the `checkpoint-changed` event (dispatched by `checkpoint_picker`):

```javascript
document.addEventListener('checkpoint-changed', function(e) {
    populatePresets(e.detail.baseModel);
});
```

When the user changes the checkpoint, the resolution dropdown is immediately repopulated with the appropriate presets. This prevents the user from accidentally generating at an incompatible resolution.

### Custom resolution mode

When the user selects "Custom...", the two number inputs become visible. The user can type any width and height. When they switch back to a preset, the inputs hide and their values are updated to match the selected preset's dimensions.

### Value gathering

The resolution picker does not use a standard `data-input-id` on a single element. Instead, the form gathering logic has a special case:

```javascript
if (el.dataset.inputId && el.querySelector && el.querySelector('input[placeholder="W"]')) {
    params['width'] = getResolutionValue(id).w;
    params['height'] = getResolutionValue(id).h;
}
```

The `getResolutionValue()` function reads the W and H inputs from the container and returns `{w, h}`. The form submission sends `width` and `height` as separate top-level parameters (not as a `resolution` object).

## Backend Behavior

### Parameter reception

The backend receives `width` and `height` as separate integer parameters:

```python
width = int(params.get("width", 1024))
height = int(params.get("height", 1024))
```

### Dynamic workflows

Width and height are passed as template variables to block templates:

```python
gen_vars = {
    "width": width,
    "height": height,
    "seed": seed,
    ...
}
```

They get substituted into `EmptyLatentImage` nodes:

```json
{
  "empty_latent": {
    "class_type": "EmptyLatentImage",
    "inputs": {
      "width": "{{width}}",
      "height": "{{height}}",
      "batch_size": 1
    }
  }
}
```

### Why resolution matters

Diffusion models are trained at specific resolutions. Generating at a different resolution causes:

- **SD 1.5 above 512px**: Duplicated subjects, distorted anatomy, poor quality
- **SDXL/Pony/Illustrious below 1024px**: Low detail, wasted model capacity
- **Any model at non-standard aspect ratio**: Composition issues, stretched features

The resolution picker's adaptive behavior prevents these issues by only showing resolutions appropriate for the selected checkpoint.

## Notes

- The resolution picker is tightly coupled to the `checkpoint_picker`. It requires a `checkpoint-changed` event to know which presets to show. If no checkpoint is selected, it defaults to SDXL presets.
- Pony and Illustrious use the same resolutions as SDXL (both are SDXL-based architectures). They have separate preset keys in case a workflow needs to define different resolutions for them, but in practice the values are identical.
- FLUX uses slightly different portrait/landscape ratios (768x1344 vs 832x1216). This reflects FLUX's different aspect ratio handling during training.
- The "Custom..." option is an escape hatch for advanced users who know exactly what resolution they need. It is not recommended for general use because most non-standard resolutions produce subpar results.
- The resolution picker does not appear in WAN video workflows because video resolution is typically determined by the input image dimensions and any upscale factor, not by a user-selected preset.
- The backend receives `width` and `height` as separate flat parameters, not as a nested `resolution` object. This is because ComfyUI nodes expect separate width and height values.
