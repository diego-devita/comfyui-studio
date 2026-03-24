# Image Input Type

The `image` input type renders an upload dropzone with drag-and-drop support and a gallery picker for selecting from existing input assets. Images are uploaded to ComfyUI immediately when selected (not when the form is submitted), and the backend receives the filename string. This input type is used for reference images (IP-Adapter, FaceID), input images (Image-to-Video, Image-to-Image), and any other workflow that starts from a user-provided image.

## YAML Example

From the `wan22-i2v-fp8` manifest (static workflow):

```yaml
inputs:
  - id: input_image
    name: "Input Image"
    type: image
    node_id: "1"
    field: "image"
    required: true
    tooltip: "The first frame of your video. Use a clear, well-composed image."
```

From the `faceid-batch` manifest (dynamic workflow):

```yaml
  - id: image
    name: "Face Reference"
    type: image
    required: true
    tooltip: "A clear photo of the face you want to preserve."
```

From the `ipa-batch` manifest:

```yaml
  - id: image
    name: "Reference Image"
    type: image
    required: true
    tooltip: "The face or subject you want to inject into the generated image."
```

## Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | yes | -- | Unique identifier. Convention is `"image"` for the primary input or `"input_image"` for workflows that distinguish input from reference. |
| `name` | string | yes | -- | Human-readable label displayed above the dropzone. |
| `type` | string | yes | -- | Must be `image`. |
| `required` | boolean | no | `false` | Whether an image must be provided. Always `true` for workflows that depend on an input image (I2V, I2I, FaceID, IP-Adapter). |
| `tooltip` | string | no | -- | Help text explaining what kind of image works best. |
| `node_id` | string | no | -- | (Static workflows only) The ComfyUI `LoadImage` node ID where the filename is injected. |
| `field` | string | no | -- | (Static workflows only) The input field name on the `LoadImage` node (always `"image"`). |

## Frontend Behavior

When the runner page encounters a `type: image` input, the `buildDropzone()` function creates a composite upload zone:

### Dropzone structure

The dropzone contains:

1. **Instruction text**: "Drop image here or click to browse"
2. **Browse button**: styled button (pointer-events disabled -- clicking anywhere in the zone triggers the file picker)
3. **Hidden file input**: `<input type="file" accept="image/*">` with `data-input-id` set to the input's id
4. **"or" divider**: visual separator
5. **"Pick from existing inputs" button**: opens a gallery overlay of images already present in ComfyUI's input folder
6. **Preview image**: hidden by default, becomes visible when an image is selected
7. **Filename display**: hidden by default, shows the filename after selection

### Upload flow

When the user selects an image (via file picker, drag-and-drop, or gallery), the following happens:

1. **Immediate preview**: If the file is an image, a `FileReader` reads it as a data URL and displays it in the preview `<img>` element. The filename is shown below.

2. **Immediate upload**: The image is uploaded to ComfyUI right away via `POST /api/run/upload-image`. This is a proxied call to ComfyUI's native `/upload/image` endpoint. The dropzone shows "Uploading..." during the transfer.

3. **Upload confirmation**: On success, the filename returned by ComfyUI is stored in the `existingImages` map (keyed by input id). The file input reference is cleared. A toast notification confirms: "Image uploaded -- `filename.png`"

4. **Upload failure**: If the upload fails, the file is kept in the `inputFiles` map as a fallback for form-time upload. The filename shows "(upload failed)".

This immediate-upload design means the image is already in ComfyUI's input folder by the time the user clicks Generate. The form submission only needs to send the filename string, not the file bytes.

### Gallery picker

Clicking "Pick from existing inputs" opens an overlay that:

1. Fetches the input asset list via `GET /api/admin/assets/inputs`
2. Filters for image-type files
3. Displays them as a clickable thumbnail grid
4. Each thumbnail shows the image via `/api/comfyui/view?filename=...&type=input`
5. Clicking a thumbnail selects it: sets the preview, stores the filename in `existingImages`, and closes the overlay

This allows reusing images that were previously uploaded (from the current or past sessions) without re-uploading.

### Drag-and-drop

The dropzone supports drag-and-drop:
- `dragover` event adds a `dragover` CSS class for visual feedback
- `dragleave` removes it
- `drop` event processes the dropped file through the same `handleFile()` function as the file picker

### Supported formats

The file input's `accept` attribute is set to `image/*`, which allows JPEG, PNG, WebP, and other browser-recognized image formats. ComfyUI's upload endpoint handles the actual format validation.

## Backend Behavior

### Image parameter handling

The backend receives image references in two ways:

1. **Pre-uploaded (normal case)**: The `existingImages` map on the frontend stores the filename. It is sent as `_existing_input_image` (for the primary image input with id `"image"`) or `_existing_{id}` (for other image inputs). The backend reads this and uses the filename directly.

2. **Fallback upload**: If the immediate upload failed, the image file is included in the `FormData` submission. The backend uploads it to ComfyUI at form processing time.

### Static workflows

For static workflows, the uploaded filename is injected into the `LoadImage` node:

```python
for inp in manifest.get("inputs", []):
    if inp["type"] == "image":
        node_id = str(inp["node_id"])
        field = inp["field"]
        if node_id in workflow:
            workflow[node_id]["inputs"][field] = existing_img
```

### Dynamic workflows

For dynamic workflows, the uploaded filename is stored in `form_params["_uploaded_image"]` and passed as a template variable to block templates:

```python
uploaded_name = form_params.get("_uploaded_image", "input.png")
```

Block templates reference it as `"{{_uploaded_image}}"`:

```json
{
  "load_image": {
    "class_type": "LoadImage",
    "inputs": {
      "image": "{{_uploaded_image}}"
    }
  }
}
```

### File naming

When uploading, the backend generates a unique filename using `_make_input_filename()` to avoid collisions with existing files. The original extension is preserved.

## Notes

- Images are uploaded to ComfyUI's input folder (typically `/workspace/ComfyUI/input/`), not to the Studio assets folder. This is because ComfyUI's `LoadImage` node reads from its own input directory.
- The immediate upload on selection is a deliberate design choice. It avoids large file transfers at form submission time (which would add latency to the Generate click) and enables the gallery picker to reuse previously uploaded images.
- The `image` type only handles single-image inputs. There is no multi-image upload variant. Workflows that need multiple images (e.g. a reference image plus an input image) declare separate `image` inputs with different `id` values.
- When re-running a job (via the history page's re-run feature), the `prefillImage()` function checks if the previously used image still exists and shows it as a preview with "(existing)" label. The user can keep it or select a different image.
- The `image` type is used for both direct input images (which get encoded into latent space) and reference images (which get processed by IP-Adapter or FaceID). The workflow determines how the image is used; the input type just handles getting it into ComfyUI.
