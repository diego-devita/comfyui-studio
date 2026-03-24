# Text Input Type

The `text` input type renders a multi-line text area for free-form text entry. It is the primary input type for prompts -- both positive (what to generate) and negative (what to avoid). Every workflow that accepts user-described content uses at least one `text` input.

## YAML Example

From the `t2i-dynamic` manifest:

```yaml
inputs:
  - id: positive_prompt
    name: "Positive Prompt"
    type: text
    required: true
    default: ""
    placeholder: "Describe what you want to generate..."
    tooltip: "Describes the image to generate. Quality tags first, then subject, then details. Include LoRA trigger words."

  - id: negative_prompt
    name: "Negative Prompt"
    type: text
    required: false
    default: "ugly, deformed, noisy, blurry, low quality, worst quality, bad anatomy, bad hands, missing fingers, extra fingers"
    tooltip: "What to avoid. This default covers common artifacts -- add specifics as needed."
```

## Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | yes | -- | Unique identifier for this input. Used as the parameter key when submitting the form and when injecting into workflow nodes. |
| `name` | string | yes | -- | Human-readable label displayed above the text area in the form. |
| `type` | string | yes | -- | Must be `text` (or the alias `string`). |
| `required` | boolean | no | `false` | If `true`, the form cannot be submitted with this field empty. Positive prompts are typically required; negative prompts are not. |
| `default` | string | no | `""` | Pre-filled value when the form loads. Negative prompts commonly ship with a default set of quality/artifact exclusions so users do not need to type them from scratch. |
| `placeholder` | string | no | `""` | Gray hint text displayed inside the empty text area. Disappears when the user starts typing. Used to suggest what kind of content to enter. |
| `tooltip` | string | no | -- | Help text shown on hover over the `?` icon next to the label. Explains the purpose, recommended usage, and tips for this field. |
| `node_id` | string | no | -- | (Static workflows only) The ComfyUI node ID where the value is injected. |
| `field` | string | no | -- | (Static workflows only) The input field name on the target node (e.g. `"text"`, `"positive_prompt"`, `"negative_prompt"`). |

## Frontend Behavior

When the runner page renders a `text` input, it creates an HTML `<textarea>` element with the following characteristics:

- The element uses the CSS class `form-input` for consistent styling (monospace font, dark background, accent-colored border on focus).
- The `rows` attribute is set to `3`, giving enough visible space for a short prompt. The text area is vertically resizable -- the user can drag the bottom edge to make it taller.
- The minimum height is 72px, and line-height is 1.5 for comfortable reading.
- If a `placeholder` is defined, it appears as gray hint text inside the empty textarea.
- If a `default` value is provided, the textarea is pre-populated with that text when the form first loads.
- The textarea carries a `data-input-id` attribute set to the input's `id`, which the form submission logic uses to gather values.

When gathering form parameters at submission time, the frontend reads the textarea's `.value` property and sends it as a string in the params JSON object, keyed by the input's `id`.

During re-run or JSON import, the `prefillSimpleInput()` function sets the textarea value directly from the saved parameters.

## Backend Behavior

### Static workflows

For static workflows (those with a `workflow.json` file), the text value is injected into a specific node's input field. The manifest entry must include `node_id` and `field`:

```yaml
- id: positive_prompt
  type: text
  node_id: "2"
  field: "text"
```

The backend locates node `"2"` in the workflow JSON and sets its `inputs.text` to the submitted string value. This typically targets `CLIPTextEncode` nodes.

### Dynamic workflows

For dynamic workflows (assembled from block templates), the text value is passed as a template variable. The block JSON files contain placeholders like `"{{positive_prompt}}"` which get replaced with the actual text during assembly:

```json
{
  "pos_prompt": {
    "class_type": "CLIPTextEncode",
    "inputs": {
      "text": "{{positive_prompt}}",
      "clip": ["clip_skip", 0]
    }
  }
}
```

The `resolve_val()` function in `workflows.py` scans all string values for `{{variable_name}}` patterns and replaces them with the corresponding parameter values.

### No transformation

The backend does not modify the text content in any way -- no trimming, no encoding, no sanitization. The raw string is passed directly to ComfyUI. This means prompt syntax features like `(emphasis:1.5)` or `BREAK` tokens work as expected because they are forwarded verbatim to the CLIP text encoder.

## Notes

- Positive prompts are almost always `required: true` because ComfyUI needs at least some text conditioning to generate meaningful output.
- Negative prompts are typically `required: false` with a sensible `default` value. This lets users generate without touching the negative prompt while still getting quality artifact prevention.
- The same `text` type is used in nested contexts -- for example, inside `scene_list` entries, each scene has a `text`-type prompt field defined in `per_scene`.
- Prompt order matters in diffusion models: words appearing earlier in the prompt tend to have slightly more influence. Quality tags (`masterpiece, best quality`) are conventionally placed first.
- There is no character limit enforced by the input type. However, CLIP text encoders have a token limit (typically 77 tokens for SD 1.5, 154 for SDXL with dual CLIP). Exceeding the token limit causes truncation at the model level, not at the input level.
