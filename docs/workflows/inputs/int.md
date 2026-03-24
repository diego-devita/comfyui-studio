# Int Input Type

The `int` input type renders a number field with stepper buttons (browser-native up/down arrows) for entering whole numbers. It is used for parameters that must be integers -- denoising steps, batch sizes, CLIP skip levels, and similar discrete values.

## YAML Example

From the `t2i-dynamic` manifest:

```yaml
inputs:
  - id: steps
    name: "Steps"
    type: int
    min: 1
    max: 100
    default: 25
    tooltip: "Denoising steps. 20-30 is recommended for this workflow since it can include hires and face fix passes."

  - id: batch_count
    name: "Batch Count"
    type: int
    min: 1
    max: 10
    default: 1
    tooltip: "Number of images to generate sequentially."
```

From the `faceid-batch` manifest (negative range):

```yaml
  - id: clip_skip
    name: "CLIP Skip"
    type: int
    min: -12
    max: -1
    default: -2
    tooltip: "How many CLIP layers to skip from the end. -1 = use all layers. -2 = skip last layer (recommended for most models)."
```

## Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | yes | -- | Unique identifier used as the parameter key in form submission and workflow injection. |
| `name` | string | yes | -- | Human-readable label displayed above the number field. |
| `type` | string | yes | -- | Must be `int` (or the alias `integer`). |
| `min` | integer | no | -- | Minimum allowed value. The browser enforces this constraint natively on the `<input type="number">` element. |
| `max` | integer | no | -- | Maximum allowed value. The browser enforces this constraint natively. |
| `default` | integer | no | -- | Pre-filled value when the form loads. If not specified, the field starts empty. |
| `required` | boolean | no | `false` | Whether the field must have a value before submission. |
| `tooltip` | string | no | -- | Help text shown on hover over the `?` icon next to the label. |
| `node_id` | string | no | -- | (Static workflows only) The ComfyUI node ID where the value is injected. |
| `field` | string | no | -- | (Static workflows only) The input field name on the target node. |

## Frontend Behavior

When the runner page encounters a `type: int` input, the `buildNumberInput()` function creates an HTML `<input type="number">` element:

- The element uses the CSS class `form-input` for consistent styling.
- The `min`, `max`, and `step` attributes are set from the manifest fields when present.
- There is no `step` field for `int` inputs -- integers always step by 1. The browser's native stepper arrows increment or decrement by 1.
- The `default` value pre-fills the field on load.
- The element carries `data-input-id` for form gathering.

The stepper buttons (up/down arrows) are native browser controls that appear on the right side of the number field. Clicking them or pressing the up/down arrow keys increments or decrements by 1. The `min` and `max` constraints prevent the value from going out of range via the stepper, though users can still type an out-of-range value manually.

When gathering parameters at submission, the frontend reads the `.value` property and converts it with `Number()`. If the field is empty, `null` is sent instead.

## Backend Behavior

### Static workflows

For static workflows, the integer value is injected into the specified node's input field using `node_id` and `field`. The backend converts the received value with `int()`:

```python
steps = int(params.get("steps", 25))
```

### Dynamic workflows

For dynamic workflows, integer values are passed as template variables. The block templates contain `{{variable}}` placeholders that get replaced during assembly:

```json
{
  "sampler": {
    "class_type": "KSampler",
    "inputs": {
      "steps": "{{steps}}",
      "cfg": "{{cfg}}",
      "seed": "{{seed}}"
    }
  }
}
```

The backend explicitly casts the parameter to `int()` before substitution, ensuring the JSON output contains a numeric value rather than a string.

### Typical usage patterns

| Parameter | min | max | Typical default | Purpose |
|-----------|-----|-----|-----------------|---------|
| `steps` | 1 | 100 | 19-25 | Denoising iterations. More steps = more refined but slower. |
| `batch_size` | 1 | 100 | 1 | Images per KSampler pass (parallel, shared VRAM). |
| `batch_count` | 1 | 10-50 | 1 | Sequential generation passes (each with a new seed). |
| `clip_skip` | -12 | -1 | -2 | CLIP layers to skip. Negative values count from the end. |
| `hires_steps` | 1 | 50 | 15 | Steps for the hires fix refinement pass. |
| `facefix_steps` | 1 | 50 | 20 | Steps for the face inpainting pass. |

## Notes

- The `int` type differs from `float` in two ways: it renders as a plain number input (not a range slider), and integers always step by 1 -- there is no `step` field.
- Negative values are supported. The `clip_skip` parameter uses the range -12 to -1, where -1 means "use all CLIP layers" and more negative values skip more layers from the end.
- The `int` type should not be confused with the `seed` type. Although seeds are also integers, the `seed` type has special behavior (random resolution, dedicated UI with a Random button). Use `int` only for parameters that always take explicit numeric values.
- When `batch_count` is used in a dynamic workflow with `repeat_variable`, the backend instantiates the associated block template once per count value, each with an incremented seed. This is different from `batch_size`, which is a single value passed to the KSampler to produce multiple images in one pass.
