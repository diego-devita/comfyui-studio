# Select Input Type

The `select` input type renders a dropdown menu with a fixed set of predefined options. Each option has a human-readable label (what the user sees) and a machine value (what gets sent to the backend). It is used for parameters with a discrete set of valid choices -- samplers, schedulers, durations, presets, and similar enumerations.

## YAML Example

Sampler selection from the `t2i-dynamic` manifest:

```yaml
inputs:
  - id: sampler_name
    name: "Sampler"
    type: select
    options:
      - {label: "Euler", value: "euler"}
      - {label: "Euler Ancestral", value: "euler_ancestral"}
      - {label: "DPM++ 2M", value: "dpmpp_2m"}
      - {label: "DPM++ SDE", value: "dpmpp_sde"}
      - {label: "DPM++ 2M SDE", value: "dpmpp_2m_sde"}
      - {label: "UniPC", value: "uni_pc"}
      - {label: "LMS", value: "lms"}
    default: "euler"
    tooltip: "Denoising algorithm. Euler is clean and fast. Euler Ancestral adds variety."
```

Duration selection from the `wan22-i2v-fp8` manifest (values are integers, not strings):

```yaml
  - id: duration
    name: "Duration"
    type: select
    node_id: "4"
    field: "value"
    options:
      - label: "5 seconds"
        value: 81
      - label: "10 seconds"
        value: 161
      - label: "15 seconds"
        value: 241
      - label: "20 seconds"
        value: 321
    default: 81
    tooltip: "Video length before frame interpolation."
```

Preset selection from the `faceid-batch` manifest:

```yaml
  - id: faceid_preset
    name: "FaceID Preset"
    type: select
    options:
      - {label: "FACEID PLUS V2 (recommended)", value: "FACEID PLUS V2"}
      - {label: "FACEID", value: "FACEID"}
      - {label: "FACEID PLUS - SD1.5 only", value: "FACEID PLUS - SD1.5 only"}
      - {label: "FACEID PORTRAIT (style transfer)", value: "FACEID PORTRAIT (style transfer)"}
      - {label: "FACEID PORTRAIT UNNORM - SDXL only (strong)", value: "FACEID PORTRAIT UNNORM - SDXL only (strong)"}
    default: "FACEID PLUS V2"
    tooltip: "Which FaceID model to use."
```

## Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | yes | -- | Unique identifier used as the parameter key in form submission and workflow injection. |
| `name` | string | yes | -- | Human-readable label displayed above the dropdown. |
| `type` | string | yes | -- | Must be `select` (or the aliases `dropdown`, `enum`). |
| `options` | list | yes | -- | Array of option objects. Each object has a `label` (displayed text) and a `value` (submitted value). See details below. |
| `default` | string or number | no | first option | The `value` of the option that should be pre-selected. Must match one of the option values exactly (using string comparison). |
| `required` | boolean | no | `false` | Whether a selection must be made. Since the first option is always selected by default, this is rarely needed. |
| `tooltip` | string | no | -- | Help text shown on hover over the `?` icon. |
| `node_id` | string | no | -- | (Static workflows only) The ComfyUI node ID where the value is injected. |
| `field` | string | no | -- | (Static workflows only) The input field name on the target node. |

### Option object format

Each item in the `options` array should be an object with:

| Field | Type | Description |
|-------|------|-------------|
| `label` | string | What the user sees in the dropdown menu. Can include descriptive text, compatibility notes, or recommendations. |
| `value` | string or number | What gets sent to the backend. This is the actual value used in the workflow -- it must match what ComfyUI expects. |

The `label` and `value` can differ significantly. For example, the duration options display "5 seconds" but submit `81` (the frame count at 16fps + 1). This separation lets the UI be human-friendly while the backend receives machine-ready values.

If an option is a plain string instead of an object, both `label` and `value` are set to that string.

## Frontend Behavior

When the runner page encounters a `type: select` input, the `buildSelect()` function creates an HTML `<select>` element:

- The element uses the CSS class `form-input` for consistent styling.
- The native browser dropdown arrow is hidden via `appearance: none`, replaced by a custom SVG chevron positioned on the right side of the element.
- Each option from the manifest is rendered as an `<option>` element, with `value` set to the option's value and `textContent` set to the option's label.
- The default option is pre-selected by matching `String(option.value) === String(input.default)`. Note the string comparison -- this means `default: 81` will match an option with `value: 81` even though one is in YAML and the other in the DOM (which stores everything as strings).
- Option styling: options have the surface background and text color to match the dark theme.

The `data-input-id` attribute is set on the select element for form gathering. At submission time, the frontend reads `el.value`, which returns the value of the currently selected option as a string.

## Backend Behavior

### Static workflows

For static workflows, the selected value is injected into the specified node's input field:

```yaml
node_id: "4"
field: "value"
```

The backend writes the value directly into `workflow["4"]["inputs"]["value"]`. For numeric values like frame counts, the form submission and JSON parsing handle the type conversion -- the value arrives as the appropriate type.

### Dynamic workflows

For dynamic workflows, the selected value is passed as a template variable:

```python
sampler_name = params.get("sampler_name", "euler")
scheduler = params.get("scheduler", "normal")
```

The value is substituted into block templates:

```json
{
  "sampler": {
    "class_type": "KSampler",
    "inputs": {
      "sampler_name": "{{sampler_name}}",
      "scheduler": "{{scheduler}}"
    }
  }
}
```

### Common select parameters

**Samplers** (denoising algorithms):
| Value | Description |
|-------|-------------|
| `euler` | Deterministic, clean, fast. Good default. |
| `euler_ancestral` | Adds randomness per step. Good for variety in batches. |
| `dpmpp_2m` | Fast convergence, deterministic. |
| `dpmpp_sde` | Middle ground between deterministic and stochastic. |
| `dpmpp_2m_sde` | SDE variant of DPM++ 2M. |
| `uni_pc` | Predictor-corrector. Good quality at low step counts. |
| `lms` | Linear multi-step. Older algorithm, still viable. |

**Schedulers** (noise schedules):
| Value | Description |
|-------|-------------|
| `normal` | Linear noise schedule. Standard default. |
| `karras` | Front-loads denoising. Sharper details. Popular choice. |
| `exponential` | Aggressive early, gentle late. |
| `sgm_uniform` | Uniform spacing. Used by some newer models. |
| `simple` | Simplified schedule. |

**Durations** (WAN video workflows):
| Label | Value (frames) | Calculation |
|-------|---------------|-------------|
| 5 seconds | 81 | 5 * 16 + 1 |
| 10 seconds | 161 | 10 * 16 + 1 |
| 15 seconds | 241 | 15 * 16 + 1 |
| 20 seconds | 321 | 20 * 16 + 1 |

The `+1` comes from WAN's frame encoding convention where the frame count includes the start frame.

## Notes

- The `select` type is used for both string values (sampler names, preset names) and numeric values (frame counts). The YAML value field determines the type; HTML always stores it as a string, but JSON parsing on the backend restores the original type.
- Labels can be much more descriptive than values. Use labels to communicate compatibility constraints (e.g. "LIGHT - SD1.5 only") or recommendations (e.g. "FACEID PLUS V2 (recommended)").
- The select type has no search or filtering capability. For large option sets, consider whether the user experience would be better served by a different approach.
- The `select` type also appears nested inside `scene_list` entries (as per-scene duration dropdowns) and is reused internally to render `boolean` inputs.
- Unlike `checkpoint_picker` or `vae_picker`, the `select` type has a static option list defined in the manifest. It does not query the backend for available choices. Use the picker types when options depend on what is installed on disk.
