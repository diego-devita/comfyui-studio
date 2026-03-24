# Boolean Input Type

The `boolean` input type renders a dropdown with two options: True and False. It is used for toggling optional workflow features on or off -- enabling a hires fix pass, activating face detection and inpainting, or any other binary choice that conditionally includes or excludes parts of the workflow.

## YAML Example

From the `t2i-dynamic` manifest:

```yaml
inputs:
  - id: hires_enabled
    name: "Hires Fix"
    type: boolean
    default: false
    tooltip: "Upscales the image and re-runs KSampler at higher resolution. Produces sharper, more detailed output."

  - id: facefix_enabled
    name: "Face Fix"
    type: boolean
    default: false
    tooltip: "Detects faces and re-generates them at higher detail. Fixes common face artifacts."
```

## Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | yes | -- | Unique identifier used as the parameter key. Conventionally ends with `_enabled` to make its purpose clear in code. |
| `name` | string | yes | -- | Human-readable label displayed above the dropdown. |
| `type` | string | yes | -- | Must be `boolean` (or the alias `bool`). |
| `default` | boolean | no | `false` | Whether the feature starts enabled or disabled. Almost always `false` -- optional features are off by default, and the user opts in. |
| `required` | boolean | no | `false` | Whether the field must have a value. Not meaningful for booleans since they always have a value (true or false). |
| `tooltip` | string | no | -- | Help text shown on hover over the `?` icon. Should explain what enabling this toggle actually does to the workflow. |

## Frontend Behavior

When the runner page encounters a `type: boolean` input, the `buildForm()` function transforms it into a select dropdown with two hardcoded options:

```javascript
case 'boolean':
case 'bool':
  group.appendChild(buildSelect(inputId, {
    ...input,
    options: [{ value: 'true', label: 'True' }, { value: 'false', label: 'False' }]
  }));
  break;
```

This means the boolean renders as a standard `<select>` element with exactly two options:

- **True** -- enables the feature
- **False** -- disables the feature (the default selection when `default: false`)

The element uses the same `form-input` CSS class and styling as all other select dropdowns. It has the custom dropdown arrow indicator and the same focus/hover behavior.

The selected value is sent as the string `"true"` or `"false"` in the form parameters (since HTML select values are always strings).

## Backend Behavior

### Value interpretation

The backend receives the boolean value as a string from the form submission. It reads it using `params.get()`:

```python
hires_enabled = params.get("hires_enabled", False)
facefix_enabled = params.get("facefix_enabled", False)
```

The string `"true"` is truthy in Python, and the string `"false"` is also truthy (any non-empty string is truthy). The backend handles this correctly through its parameter processing -- form data is JSON-parsed before reaching the assembler functions, so the values arrive as actual Python booleans.

### Conditional block inclusion

The primary purpose of boolean inputs is to conditionally include or exclude blocks in dynamic workflows. The `t2i-dynamic` manifest declares optional pipeline blocks with conditions:

```yaml
pipeline:
  - block: hires
    file: "hires.json"
    optional: true
    condition: "hires_enabled"
  - block: face_fix
    file: "face_fix.json"
    optional: true
    condition: "facefix_enabled"
```

In the backend assembler (`workflows.py`), the boolean value directly controls whether the block is instantiated:

```python
if hires_enabled:
    hires_tmpl = load_block("hires.json")
    # ... instantiate hires block, wire it into the pipeline
    current_image = hires_exports["image"]

if facefix_enabled:
    facefix_tmpl = load_block("face_fix.json")
    # ... instantiate face fix block
```

When the boolean is `false`, the corresponding block is simply skipped. The workflow is assembled without those nodes, saving VRAM and execution time. The pipeline's data flow adapts: if hires is disabled, the generate block's output connects directly to the output block; if hires is enabled, the hires block sits in between.

### Impact on workflow structure

This is fundamentally different from simply setting a parameter to zero. A disabled boolean block means:

- The ComfyUI nodes for that feature do not exist in the final workflow JSON.
- No VRAM is allocated for those nodes.
- No execution time is spent on those nodes.
- The progress tracker has fewer nodes to process (affecting the effective_total count).

Compared to having the block always present but with a neutral parameter (e.g. denoise=0), conditional exclusion is cleaner and avoids potential edge cases.

## Notes

- Boolean inputs are only meaningful in dynamic workflows where the backend assembles the workflow from block templates. Static workflows (with a fixed `workflow.json`) cannot conditionally include or exclude nodes -- all nodes are always present.
- The `default` should almost always be `false`. Optional features add processing time and VRAM usage, so they should be opt-in. A user who wants faster results gets them by default; a user who wants higher quality explicitly enables the extra passes.
- When a boolean controls related parameters (e.g. `hires_enabled` controls whether `hires_scale`, `hires_steps`, and `hires_denoise` are meaningful), those related parameters are always visible in the form regardless of the boolean's state. The frontend does not conditionally show/hide them. They simply have no effect when the boolean is false because the block that uses them is never instantiated.
- The rendering as a dropdown (rather than a toggle switch or checkbox) is a deliberate implementation choice in the current codebase. The `buildSelect()` function is reused with synthesized options.
