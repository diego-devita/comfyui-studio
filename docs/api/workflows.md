# Workflows API

Endpoints for listing, inspecting, and managing workflows. Each workflow lives in `workflows/<id>/` with a `manifest.yaml` and optional `workflow.json`.

---

## GET /api/admin/workflows

List all workflows with readiness status. Each workflow is checked against installed models and custom nodes.

**Auth:** Required

**Response:** `200 OK`

```json
{
  "version": 32,
  "date": "2026-03-24 09:00",
  "workflows": [
    {
      "id": "wan-i2v-14b",
      "name": "WAN 2.1 I2V 14B",
      "category": "video",
      "type": "static",
      "version": 5,
      "date": "2026-03-22 14:00",
      "description": "Image-to-video generation with WAN 2.1 14B model",
      "author": "diego",
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
          "field": "text"
        },
        {
          "id": "seed",
          "type": "seed",
          "label": "Seed",
          "node_id": 10,
          "field": "seed",
          "default": -1
        }
      ],
      "outputs": [
        {"type": "video", "format": "mp4"}
      ],
      "required_models": [
        "wan2.1_i2v_720p_14B_fp16.safetensors",
        "umt5-xxl-enc-bf16.safetensors"
      ],
      "required_nodes": [
        "ComfyUI-WanVideoWrapper"
      ],
      "models_status": {
        "total": 2,
        "present": 2,
        "missing": []
      },
      "nodes_status": {
        "total": 1,
        "installed": 1,
        "missing": []
      },
      "ready": true
    },
    {
      "id": "t2i-dynamic",
      "name": "Text-to-Image Dynamic",
      "category": "image",
      "type": "dynamic",
      "version": 3,
      "date": "2026-03-20 11:00",
      "description": "Dynamic text-to-image with flexible model and LoRA selection",
      "author": "diego",
      "inputs": [],
      "outputs": [{"type": "image"}],
      "required_models": [],
      "required_nodes": [],
      "models_status": {"total": 0, "present": 0, "missing": []},
      "nodes_status": {"total": 0, "installed": 0, "missing": []},
      "ready": true
    }
  ]
}
```

| Field | Description |
|-------|-------------|
| `type` | `"static"` (uses `workflow.json`) or `"dynamic"` (assembled from blocks at runtime) |
| `ready` | `true` if all required models are downloaded and all required nodes are installed |
| `models_status.missing` | List of model filenames that need to be downloaded |
| `nodes_status.missing` | List of custom node package names that need to be installed |

```bash
curl https://your-pod.runpod.io/api/admin/workflows \
  -H "X-API-Key: your-api-key"
```

---

## GET /api/admin/workflows/{workflow_id}

Get detailed information about a single workflow, including its full manifest and readiness status.

**Auth:** Required

**Path parameters:**

| Parameter | Description |
|-----------|-------------|
| `workflow_id` | The workflow ID (directory name) |

**Response:** `200 OK`

Returns the full manifest with additional `models_status`, `nodes_status`, and `ready` fields (same format as items in the list response).

**Error response:** `404 Not Found`

```json
{
  "detail": "Workflow 'nonexistent' not found"
}
```

```bash
curl https://your-pod.runpod.io/api/admin/workflows/wan-i2v-14b \
  -H "X-API-Key: your-api-key"
```

---

## POST /api/admin/workflows/{workflow_id}/install-models

Download all missing required models for a workflow.

**Auth:** Required

**Path parameters:**

| Parameter | Description |
|-----------|-------------|
| `workflow_id` | The workflow ID |

**Response:** `200 OK`

```json
{
  "queued": ["wan2.1_i2v_720p_14B_fp16.safetensors"],
  "skipped": ["unknown_model.safetensors"],
  "message": "1 models queued for download"
}
```

| Field | Description |
|-------|-------------|
| `queued` | Models that were found in the catalog and queued for download |
| `skipped` | Models not found in any catalog |

```bash
curl -X POST https://your-pod.runpod.io/api/admin/workflows/wan-i2v-14b/install-models \
  -H "X-API-Key: your-api-key"
```

---

## POST /api/admin/workflows/sync

Sync workflows from the local git repo clone (`.repo/`). Compares versions and copies updated workflows. Requires a prior `Check for Updates`.

**Auth:** Required

**Request body:** None

**Response:** `200 OK`

```json
{
  "updated": ["wan-i2v-14b", "t2i-dynamic"],
  "checked": 12
}
```

```bash
curl -X POST https://your-pod.runpod.io/api/admin/workflows/sync \
  -H "X-API-Key: your-api-key"
```
