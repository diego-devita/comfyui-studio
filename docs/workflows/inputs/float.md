# Float Input Type

The `float` input type renders a horizontal range slider with a numeric value display. It is used for parameters that accept decimal values -- CFG scale, denoise strength, LoRA weights, upscale factors, and similar continuous values.

## YAML Example

From the `t2i-dynamic` manifest:

```yaml
inputs:
  - id: cfg
    name: "CFG Scale"
    type: float
    min: 1.0
    max: 30.0
    step: 0.5
    default: 7.0
    tooltip: "Prompt adherence. Lower for Pony/Illustrious (3-5), keep at 7-9 for SD 1.5."

  - id: hires_denoise
    name: "Hires Denoise"
    type: float
    min: 0.1
    max: 1.0
    step: 0.05
    default: 0.5
    tooltip: "How much to regenerate during hires. 0.3-0.4 = preserve composition. 0.5-0.6 = moderate rework."
```

From the `ipa-batch` manifest:

```yaml
  - id: ipa_weight
    name: "IP-Adapter Weight"
    type: float
    min: 0.0
    max: 2.0
    step: 0.05
    default: 0.8
    tooltip: "How strongly the reference image influences the output."
```

## Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | yes | -- | Unique identifier used as the parameter key in form submission and workflow injection. |
| `name` | string | yes | -- | Human-readable label displayed above the slider. |
| `type` | string | yes | -- | Must be `float` (or the alias `number`). |
| `min` | float | no | `0` | Minimum allowed value. Sets the left end of the slider track. |
| `max` | float | no | `10` | Maximum allowed value. Sets the right end of the slider track. |
| `step` | float | no | `0.1` | The granularity of the slider. This is the critical field that controls how precisely the user can adjust the value. Each click of the stepper or tap of an arrow key moves the value by this amount. |
| `default` | float | no | midpoint of min/max | Pre-selected value when the form loads. If not specified, defaults to the midpoint between `min` and `max`. |
| `required` | boolean | no | `false` | Whether the field must have a value before submission. Floats almost always have a default, so this is rarely needed. |
| `tooltip` | string | no | -- | Help text shown on hover over the `?` icon next to the label. |
| `node_id` | string | no | -- | (Static workflows only) The ComfyUI node ID where the value is injected. |
| `field` | string | no | -- | (Static workflows only) The input field name on the target node (e.g. `"Number"`, `"cfg"`, `"noise_seed"`). |

## The Step Field

The `step` field is the most important configuration choice for a `float` input. It determines:

1. **Slider granularity** -- how many discrete positions the slider has between min and max.
2. **Keyboard arrow increment** -- pressing left/right arrow keys moves the value by one step.
3. **Display precision** -- the displayed value shows the same number of decimal places as the step value.

### Common step values and their effects

| Step | Resulting values (example range) | Typical use |
|------|----------------------------------|-------------|
| `0.5` | 1.0, 1.5, 2.0, 2.5, ... 30.0 | CFG Scale. Coarse control is appropriate because the visual difference between e.g. 7.0 and 7.5 is noticeable but between 7.0 and 7.01 is not. |
| `0.1` | 1.0, 1.1, 1.2, ... 10.0 | Upscale factor, CFG on low-range workflows. Medium precision. |
| `0.05` | 0.0, 0.05, 0.10, 0.15, ... 1.0 | Denoise strength, LoRA strength, IP-Adapter weight. Fine control matters because small changes (e.g. 0.40 vs 0.45) produce visibly different results. |

Choosing the wrong step value leads to a poor user experience. A step of `0.01` on a CFG slider (range 1-30) creates 2900 positions -- the slider becomes nearly impossible to land on a specific value. A step of `0.5` on a denoise slider (range 0-1) gives only 3 positions (0.0, 0.5, 1.0) -- far too few for useful control.

## Frontend Behavior

When the runner page encounters a `type: float` input, the `buildRangeSlider()` function creates a composite element:

- A wrapper `<div>` with class `range-row` that uses flexbox to lay out the slider and its value display side by side.
- An `<input type="range">` element styled as a horizontal slider. The slider track is a thin line (4px tall) with the surface border color, and the thumb is a 16px circle in the accent color.
- A `<span>` with class `range-value` that displays the current numeric value to the right of the slider.

The slider element gets these attributes from the manifest:
- `min` from `input.min`
- `max` from `input.max`
- `step` from `input.step`
- `value` from `input.default`

The `data-input-id` attribute is set on the slider element (not the wrapper), so the form gathering logic can locate it directly.

As the user drags the slider, an `input` event listener updates the displayed value. The display precision matches the step value's decimal places -- if `step` is `0.05`, the display shows two decimal places (e.g. `0.75`); if `step` is `0.5`, it shows one decimal place (e.g. `7.5`).

When gathering parameters at submission, the frontend reads `parseFloat(el.value)` from the range input and sends the numeric value.

During re-run or JSON import, `prefillSimpleInput()` sets the slider's value and dispatches an `input` event to update the display span.

## Backend Behavior

### Static workflows

For static workflows, the float value is injected into the specified node:

```python
cfg = float(params.get("cfg", 1.5))
```

The backend casts the value with `float()` and writes it into the workflow JSON at the target node's input field.

### Dynamic workflows

Float values are passed as template variables and substituted into block templates:

```python
gen_vars = {
    "cfg": cfg,
    "seed": seed,
    "steps": steps,
    "sampler_name": sampler_name,
}
```

The `resolve_val()` function replaces `"{{cfg}}"` in the block JSON with the float value. Since JSON natively supports floating-point numbers, the final workflow JSON contains proper numeric values.

### Typical usage patterns

| Parameter | min | max | step | Typical default | Purpose |
|-----------|-----|-----|------|-----------------|---------|
| `cfg` | 1.0 | 30.0 | 0.5 | 4.0-7.0 | Prompt adherence strength |
| `cfg` (WAN) | 1.0 | 5.0-10.0 | 0.1-0.5 | 1.5-3.5 | CFG for video workflows (lower range) |
| `denoise` | 0.0 | 1.0 | 0.05 | 0.5-1.0 | Denoising strength |
| `hires_denoise` | 0.1 | 1.0 | 0.05 | 0.5 | Hires fix refinement strength |
| `facefix_denoise` | 0.1 | 1.0 | 0.05 | 0.4 | Face fix regeneration strength |
| `ipa_weight` | 0.0 | 2.0 | 0.05 | 0.8 | IP-Adapter reference influence |
| `ipa_start` | 0.0 | 1.0 | 0.05 | 0.0 | IP-Adapter start point in diffusion |
| `ipa_end` | 0.0 | 1.0 | 0.05 | 1.0 | IP-Adapter end point in diffusion |
| `faceid_weight` | 0.0 | 2.0 | 0.05 | 0.85 | FaceID identity strength |
| `faceid_lora_strength` | 0.0 | 2.0 | 0.05 | 0.6 | FaceID LoRA strength |
| `hires_scale` | 1.0 | 2.5 | 0.1 | 1.5 | Upscale multiplier |
| `upscale` | 1.0 | 2.5 | 0.5 | 1.5 | Video upscale factor |

## Notes

- The `float` type always renders as a range slider, never as a plain number input. This is a deliberate design choice: sliders provide immediate visual feedback about where the value sits within its range, which is important for parameters where the absolute number is less meaningful than its position (e.g. "how much denoise" is easier to understand as a slider position than as the number 0.45).
- The `step` field has no equivalent in the `int` type because integers always step by 1.
- If `step` is not specified, it defaults to `0.1`. Always specify `step` explicitly to ensure the correct granularity for your parameter.
- If `default` is not specified, the slider initializes to the midpoint of the `min`/`max` range, which may not be the intended starting value. Always specify `default`.
- The slider supports keyboard interaction: left/right arrow keys move by one step, Home/End jump to min/max.
