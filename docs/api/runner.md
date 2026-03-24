# Runner API

Endpoints for executing workflows, uploading images, building workflows, and retrieving results. The runner handles both static workflows (pre-built JSON) and dynamic workflows (assembled from blocks at runtime).

---

## GET /api/run/{workflow_id}

Get the manifest for a workflow. Used to build the runner form with inputs, outputs, and metadata.

**Auth:** Required

**Path parameters:**

| Parameter | Description |
|-----------|-------------|
| `workflow_id` | The workflow ID |

**Response:** `200 OK`

Returns the full workflow manifest (parsed from `manifest.yaml`):

```json
{
  "id": "wan-i2v-14b",
  "name": "WAN 2.1 I2V 14B",
  "type": "static",
  "category": "video",
  "description": "Image-to-video with WAN 2.1 14B",
  "inputs": [
    {
      "id": "image",
      "type": "image",
      "label": "Input Image",
      "node_id": 1,
      "field": "image"
    },
    {
      "id": "prompt",
      "type": "text",
      "label": "Prompt",
      "node_id": 5,
      "field": "text",
      "default": ""
    },
    {
      "id": "steps",
      "type": "int",
      "label": "Steps",
      "node_id": 10,
      "field": "steps",
      "default": 30,
      "min": 1,
      "max": 100
    },
    {
      "id": "seed",
      "type": "seed",
      "label": "Seed",
      "node_id": 12,
      "field": "seed",
      "default": -1
    }
  ],
  "outputs": [
    {"type": "video", "format": "mp4"}
  ],
  "required_models": ["wan2.1_i2v_720p_14B_fp16.safetensors"],
  "required_nodes": ["ComfyUI-WanVideoWrapper"]
}
```

**Error response:** `404 Not Found`

```bash
curl https://your-pod.runpod.io/api/run/wan-i2v-14b \
  -H "X-API-Key: your-api-key"
```

---

## POST /api/run/upload-image

Upload an input image to ComfyUI's input directory. The image is proxied to ComfyUI's `/upload/image` endpoint. Returns the filename for use in subsequent execute calls.

**Auth:** Required

**Request:** Multipart form data with a `file` field.

**Response:** `200 OK`

```json
{
  "filename": "20260324_143052_a1b2c3_myimage.png"
}
```

The filename is made unique with a timestamp and random suffix to prevent collisions.

**Error response:** `500 Internal Server Error`

```json
{
  "detail": "Upload failed: ..."
}
```

```bash
curl -X POST https://your-pod.runpod.io/api/run/upload-image \
  -H "X-API-Key: your-api-key" \
  -F "file=@my-image.png"
```

---

## POST /api/run/{workflow_id}/build

Build a workflow with parameters applied and return the JSON without executing. Useful for previewing or exporting the workflow.

**Auth:** Required

**Path parameters:**

| Parameter | Description |
|-----------|-------------|
| `workflow_id` | The workflow ID |

**Query parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `format` | `api` | Output format: `api` (flat dict with node IDs, ready for ComfyUI `/prompt`) or `workflow` (ComfyUI UI format, converted using `/object_info` schemas) |

**Request:** Multipart form data.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `params` | string (JSON) | No | JSON string of workflow parameters (default: `"{}"`) |
| `input_image` | file | No | Input image file |

**Response (format=api):** `200 OK`

Returns ComfyUI API-format workflow JSON (flat dict with node IDs as string keys):

```json
{
  "1": {
    "class_type": "LoadImage",
    "inputs": {"image": "uploaded_image.png"}
  },
  "5": {
    "class_type": "CLIPTextEncode",
    "inputs": {"text": "a beautiful landscape"}
  }
}
```

**Response (format=workflow):** `200 OK`

Returns ComfyUI UI-format workflow JSON (with node positions, widget values, etc.).

```bash
# Build API format
curl -X POST "https://your-pod.runpod.io/api/run/wan-i2v-14b/build?format=api" \
  -H "X-API-Key: your-api-key" \
  -F 'params={"prompt": "a cat walking", "steps": 30, "seed": -1}'

# Build workflow format for ComfyUI UI import
curl -X POST "https://your-pod.runpod.io/api/run/wan-i2v-14b/build?format=workflow" \
  -H "X-API-Key: your-api-key" \
  -F 'params={"prompt": "a cat walking"}' \
  -F "input_image=@my-image.png"
```

---

## POST /api/run/{workflow_id}/execute

Execute a workflow. Builds the workflow with the provided parameters, sends it to ComfyUI, and starts a background WebSocket listener for progress tracking.

**Auth:** Required

**Path parameters:**

| Parameter | Description |
|-----------|-------------|
| `workflow_id` | The workflow ID |

**Request:** Multipart form data.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `params` | string (JSON) | No | JSON string of workflow parameters |
| `input_image` | file | No | Input image file |

The `params` JSON should contain key-value pairs matching the input IDs from the manifest. Special keys:

| Key | Description |
|-----|-------------|
| `_existing_input_image` | Use a previously uploaded image by filename (instead of uploading) |

Seed handling: if a seed input has value `-1`, a random seed is generated automatically.

**Response:** `200 OK`

```json
{
  "prompt_id": "abc12345-6789-0def-ghij-klmnopqrstuv",
  "client_id": "fedcba9876543210fedcba9876543210",
  "seeds": {
    "seed": 7293847561029384
  }
}
```

| Field | Description |
|-------|-------------|
| `prompt_id` | ComfyUI prompt ID, used to track progress and retrieve results |
| `client_id` | WebSocket client ID |
| `seeds` | Map of seed input IDs to their resolved values |

**Error responses:**

- `400 Bad Request` -- ComfyUI validation error (node errors included in detail)
- `404 Not Found` -- Workflow or manifest not found
- `500 Internal Server Error` -- ComfyUI unreachable or workflow assembly failed

```bash
# Execute with parameters
curl -X POST https://your-pod.runpod.io/api/run/wan-i2v-14b/execute \
  -H "X-API-Key: your-api-key" \
  -F 'params={"prompt": "a cat walking on the beach", "steps": 30, "seed": -1}' \
  -F "input_image=@my-image.png"

# Execute with a previously uploaded image
curl -X POST https://your-pod.runpod.io/api/run/wan-i2v-14b/execute \
  -H "X-API-Key: your-api-key" \
  -F 'params={"prompt": "a cat walking", "_existing_input_image": "20260324_143052_myimage.png"}'
```

---

## GET /api/run/status/{prompt_id}

Poll execution status for a job. While the WebSocket is the primary progress source, this endpoint provides a fallback.

**Auth:** Required

**Path parameters:**

| Parameter | Description |
|-----------|-------------|
| `prompt_id` | The prompt ID from the execute response |

**Response (running, from in-memory state):** `200 OK`

```json
{
  "status": "running",
  "node_title": "KSampler",
  "node_type": "KSampler",
  "step": 15,
  "total_steps": 30,
  "percent": 45,
  "nodes_done": 3,
  "total_nodes": 8,
  "effective_total": 6,
  "cached_count": 2,
  "eta_seconds": 25,
  "step_rate": 1.85,
  "node_outputs": {}
}
```

**Response (completed, from ComfyUI history):** `200 OK`

```json
{
  "status": "completed",
  "outputs": {
    "video": {
      "filename": "final_00001.mp4",
      "subfolder": "20260324_143052_a1b2c3/final",
      "type": "output"
    }
  }
}
```

**Response (pending):** `200 OK`

```json
{
  "status": "pending",
  "step": 0,
  "total_steps": 0
}
```

**Response (error):** `200 OK`

```json
{
  "status": "error",
  "error": "[error messages]"
}
```

```bash
curl https://your-pod.runpod.io/api/run/status/abc12345-6789-0def-ghij-klmnopqrstuv \
  -H "X-API-Key: your-api-key"
```

---

## GET /api/comfyui/view

Proxy to ComfyUI's `/view` endpoint for serving images and videos. Used to display input images and previews.

**Auth:** Required

**Query parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `filename` | (required) | The filename to retrieve |
| `type` | `input` | ComfyUI directory type: `"input"` or `"output"` |
| `subfolder` | `""` | Subfolder within the type directory |

**Response:** `200 OK` with the binary file content and appropriate `Content-Type` header.

**Error responses:**

- `404 Not Found` -- Image not found or ComfyUI unreachable

```bash
curl "https://your-pod.runpod.io/api/comfyui/view?filename=myimage.png&type=input" \
  -H "X-API-Key: your-api-key" \
  -o image.png
```

---

## GET /api/run/result/{prompt_id}

Get the result file (video or image) for a completed job. Returns the binary file content with appropriate content type.

**Auth:** Required

**Path parameters:**

| Parameter | Description |
|-----------|-------------|
| `prompt_id` | The prompt ID |

**Query parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `output_type` | `video` | Preferred output type (video preferred over images) |

**Response:** `200 OK`

Returns binary file content with:
- `Content-Type`: `video/mp4`, `video/webm`, `image/png`, `image/jpeg`, or `application/octet-stream`
- `Content-Disposition`: `inline; filename="<filename>"`

**Error responses:**

- `404 Not Found` -- Result not ready or no output found

```bash
curl "https://your-pod.runpod.io/api/run/result/abc12345-6789-0def-ghij-klmnopqrstuv" \
  -H "X-API-Key: your-api-key" \
  -o result.mp4
```
