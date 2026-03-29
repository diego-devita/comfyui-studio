# Workflow Runner

The execution form at `/run/{workflow_id}`. Renders a dynamic form based on the workflow's manifest, executes jobs, and provides export options.

## Layout

1. **Back link** -- "Back to Workflows" navigation
2. **Workflow header** -- name, version badge, category badge, description
3. **Saved prompts** -- quick-load dropdown of previously saved prompt sets
4. **Form panel** -- input controls generated from the manifest
5. **Generate row** -- multi-generate stepper and Generate button
6. **Save Preset / Export dropdown** -- save as preset or export in three formats
7. **Progress panel** -- shown during execution
8. **Result panel** -- shown after completion

## Data Loading

```
GET /api/run/{workflow_id}
```

Returns the workflow manifest including:

- `id`, `name`, `description`, `category`, `version`, `type`
- `inputs` -- array of input definitions that drive form rendering
- `defaults` -- default values for inputs
- `base_model` -- determines which models appear in pickers

The form is built entirely from the `inputs` array in the manifest.

## Workflow Header

- **Title** -- workflow name in large display font
- **Version badge** -- e.g., "v9" in a bordered pill
- **Category badge** -- colored pill (T2I=yellow, I2V=blue, I2I=orange, IPA=purple)
- **Dynamic badge** -- if the workflow type is "dynamic", a yellow "DYNAMIC" pill appears
- **Description** -- full description text below the title

## Form Controls

Each input in the manifest's `inputs` array renders as a form group with a label, optional tooltip (hover `?` circle), and the appropriate control. Supported input types:

### text

A textarea for text input. Used for prompts and text parameters. Supports `placeholder` and `default` values. Resizable vertically.

### int

A number input with optional `min`, `max`, and `default`. Rendered as a text input with type="number".

### float

A range slider with a numeric value display. Configured with `min`, `max`, `step`, and `default`. The slider and the displayed value update together.

### boolean

A toggle switch (checkbox styled as a slider).

### select

A dropdown menu. Options defined as an array of `{label, value}` objects in the manifest. Rendered as a styled `<select>` element.

### seed

A number input with a "Random" button. Default of `-1` means random seed on each execution. The Random button generates a new random integer. When multi-generating, each execution gets a fresh random seed.

### image

A drag-and-drop zone for uploading an image. Features:

- **Drop zone** -- dashed border area that highlights on drag-over
- **File picker** -- hidden file input triggered by clicking the zone
- **Preview** -- uploaded image shown as a thumbnail within the zone
- **Filename** -- displayed below the preview
- **Pick from existing** -- button that opens a fullscreen overlay showing all images in the ComfyUI input directory as a grid. Clicking one selects it.

On file selection, the image is immediately uploaded via `POST /api/run/upload-image` and the returned ComfyUI filename is stored for the execute call.

### checkpoint_picker

A dropdown populated with checkpoint models present on disk. The backend filters the model catalog to show only downloaded checkpoints. Changing the checkpoint can affect which resolution presets are shown (via `base_model` mapping).

### resolution_picker

A dropdown of resolution presets that changes based on the selected checkpoint's base model. The manifest defines presets per base model family (e.g., SD 1.5 at 512px, SDXL at 1024px). Each option shows a label like "832x1216" and stores `{w, h}` values.

### lora_picker

A dropdown of compatible LoRAs with a strength slider. Filters LoRAs by the current base model.

### lora_picker_dynamic

A multi-LoRA picker. Users can add up to `max_loras` LoRA slots. Each slot has:

- A LoRA selector dropdown (filtered by base model compatibility)
- A strength slider
- A remove button

An "Add LoRA" button creates new slots (up to the maximum).

### scene_list

A dynamic list of scene cards for multi-scene workflows (like SVI Pro). Each scene card contains:

- A scene number header
- Per-scene inputs defined in the manifest's `per_scene` array (typically: prompt textarea, duration select, seed input)
- A remove button (except for the first scene)

An "Add Scene" button creates new scene cards. The first scene always exists and cannot be removed.

### vae_picker

A dropdown of VAE models present on disk.

## Generate Button and Stepper

### Multi-Generate Stepper

A `[- N +]` control next to the Generate button. Default value is 1. The minus button decreases (minimum 1), the plus button increases. When set to 1, the stepper appears dimmed.

### Generate Button

Clicking "Generate" with N > 1 sends N sequential execute calls. Each call:

1. Collects all form values
2. Generates a fresh random seed (if seed is -1)
3. Calls `POST /api/run/{workflow_id}/execute` with the form data
4. Waits briefly, then sends the next

During execution, the button is disabled and shows a spinner.

## Export Dropdown

A dropdown button with three options:

| Option | Format | Description |
|--------|--------|-------------|
| Job Params | JSON | Current form values as a JSON object |
| ComfyUI Workflow | JSON | The workflow converted to ComfyUI UI format (importable into the graph editor) |
| ComfyUI API | JSON | The workflow in API format with current params substituted (ready for `/prompt`) |

Export calls `POST /api/run/{workflow_id}/build?format=api|workflow` to get the processed workflow with current form values applied.

## Progress Panel

After clicking Generate, a progress panel appears below the form showing:

- **Step text** -- current node being processed
- **Progress bar** -- percentage complete
- **Percentage text** -- numeric percentage

The panel uses an indeterminate animation (sliding gradient) while waiting for the first progress update, then switches to a determinate bar as node execution progresses.

## Save Preset

The runner form includes a "Save Preset" option that saves the current form values as a [preset](../presets/overview.md). The saved preset captures the workflow ID and all parameter values. See [Creating Presets](../presets/creating.md).

## Prefill from Preset

When navigating to the runner from the Presets page, the preset's parameters are stored in `sessionStorage`. On page load, the runner checks for prefill data and populates the form fields automatically. This allows running a preset with the option to modify parameters before executing.

## Multi-Image Input

For workflows that support multiple image inputs (such as inpainting), the form renders multiple image upload zones. Each zone follows the same drag-and-drop pattern as the single image input, with its own preview and file picker. Inpainting workflows include a separate mask image input.

## Saved Prompts

The runner supports saving and loading prompt sets. Saved prompts store text field values (positive prompt, negative prompt) so they can be quickly recalled without creating a full preset.

## Result Panel

After job completion, the result panel shows:

- **Output media** -- the best output (video or image) displayed inline
- **Action buttons** -- "View in History" link, download link

## Related Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/run/{workflow_id}` | GET | Get workflow manifest for form rendering |
| `/api/run/{workflow_id}/execute` | POST | Execute workflow with parameters |
| `/api/run/{workflow_id}/build` | POST | Export workflow in API or UI format |
| `/api/run/upload-image` | POST | Upload input image to ComfyUI |
| `/api/run/ws` | WebSocket | Real-time progress during execution |
