# Jobs API

Endpoints for managing job queue and history. Jobs are stored in SQLite and enriched with real-time progress data from in-memory state.

---

## GET /api/admin/queue

List active (running/queued) jobs with real-time progress information.

**Auth:** Required

**Response:** `200 OK`

```json
[
  {
    "prompt_id": "abc12345-6789-0def-ghij-klmnopqrstuv",
    "workflow_id": "wan-i2v-14b",
    "workflow_name": "WAN 2.1 I2V 14B",
    "output_dir": "20260324_143052_a1b2c3",
    "status": "running",
    "queued_at": "2026-03-24T14:30:52",
    "started_at": "2026-03-24T14:30:53",
    "finished_at": null,
    "duration": null,
    "input_image": "20260324_143050_myimage.png",
    "params": {
      "prompt": "a cat walking on the beach",
      "steps": 30
    },
    "seeds": {"seed": 7293847561029384},
    "output": null,
    "error": null,
    "progress": {
      "status": "running",
      "node_title": "KSampler",
      "node_type": "KSampler",
      "step": 15,
      "total_steps": 30,
      "nodes_done": 3,
      "total_nodes": 8,
      "effective_total": 6,
      "cached_count": 2,
      "percent": 45,
      "eta_seconds": 25,
      "step_rate": 1.85,
      "node_outputs": {}
    }
  }
]
```

The `progress` field is enriched from in-memory execution state. If the job has no in-memory state (e.g., after a backend restart), the progress falls back to the stored job status.

| Progress field | Description |
|----------------|-------------|
| `node_title` | Human-readable title of the currently executing node |
| `node_type` | ComfyUI class type of the current node |
| `step` / `total_steps` | Step progress within the current node (e.g., sampler steps) |
| `nodes_done` / `effective_total` | Node-level progress (cached and instant nodes excluded from total) |
| `cached_count` | Number of cached nodes (skipped during execution) |
| `percent` | Overall percentage (0-99, jumps to 100 on completion) |
| `eta_seconds` | Estimated time remaining in seconds |
| `step_rate` | Steps per second (rolling average) |
| `node_outputs` | Map of node outputs produced so far |

```bash
curl https://your-pod.runpod.io/api/admin/queue \
  -H "X-API-Key: your-api-key"
```

---

## GET /api/admin/history

List completed, failed, and stalled job records, newest first.

**Auth:** Required

**Response:** `200 OK`

```json
[
  {
    "prompt_id": "abc12345-6789-0def-ghij-klmnopqrstuv",
    "workflow_id": "wan-i2v-14b",
    "workflow_name": "WAN 2.1 I2V 14B",
    "output_dir": "20260324_143052_a1b2c3",
    "status": "completed",
    "queued_at": "2026-03-24T14:30:52",
    "started_at": "2026-03-24T14:30:53",
    "finished_at": "2026-03-24T14:33:15",
    "duration": 142,
    "input_image": "20260324_143050_myimage.png",
    "params": {"prompt": "a cat walking", "steps": 30},
    "seeds": {"seed": 7293847561029384},
    "output": {
      "filename": "final_00001.mp4",
      "subfolder": "20260324_143052_a1b2c3/final",
      "type": "output"
    },
    "error": null
  },
  {
    "prompt_id": "def67890-...",
    "workflow_id": "wan-i2v-14b",
    "workflow_name": "WAN 2.1 I2V 14B",
    "output_dir": "20260324_140000_b2c3d4",
    "status": "error",
    "queued_at": "2026-03-24T14:00:00",
    "started_at": "2026-03-24T14:00:01",
    "finished_at": "2026-03-24T14:00:05",
    "duration": 4,
    "input_image": null,
    "params": {},
    "seeds": {},
    "output": null,
    "error": "[KSampler] out of memory"
  },
  {
    "prompt_id": "ghi01234-...",
    "status": "stalled",
    "error": null
  }
]
```

Job statuses:

| Status | Description |
|--------|-------------|
| `completed` | Job finished successfully |
| `error` | Job failed with an error |
| `stalled` | Job was running/queued when the backend restarted (marked on startup) |

```bash
curl https://your-pod.runpod.io/api/admin/history \
  -H "X-API-Key: your-api-key"
```

---

## POST /api/admin/history/delete

Delete job records and their output files from disk.

**Auth:** Required

**Request body:**

```json
{
  "prompt_ids": [
    "abc12345-6789-0def-ghij-klmnopqrstuv",
    "def67890-1234-5678-9abc-def012345678"
  ]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `prompt_ids` | string[] | Yes | List of prompt IDs to delete |

**Response:** `200 OK`

```json
{
  "deleted": [
    "abc12345-6789-0def-ghij-klmnopqrstuv",
    "def67890-1234-5678-9abc-def012345678"
  ]
}
```

For each deleted job, the output directory (`ASSETS_OUTPUT_DIR/{output_dir}`) is also removed. An event `job.deleted` is emitted for each deletion.

```bash
curl -X POST https://your-pod.runpod.io/api/admin/history/delete \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"prompt_ids": ["abc12345-6789-0def-ghij-klmnopqrstuv"]}'
```

---

## POST /api/admin/history/retry

Re-queue a failed or stalled job with the same parameters and resolved seeds. Creates a new job linked to the original via `retry_of`.

**Auth:** Required

**Request body:**

```json
{
  "prompt_id": "abc12345-6789-0def-ghij-klmnopqrstuv"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `prompt_id` | string | Yes | The prompt ID of the job to retry |

**Response:** `200 OK`

```json
{
  "prompt_id": "new12345-6789-0def-ghij-klmnopqrstuv",
  "retry_of": "abc12345-6789-0def-ghij-klmnopqrstuv"
}
```

The retry rebuilds the workflow from the original parameters with the same resolved seeds (no re-randomization). If the original job had an input image, it is reused. The new job record includes a `retry_of` field pointing to the original prompt ID.

**Error responses:**

- `400 Bad Request` -- Missing `prompt_id` or job has no `workflow_id`
- `404 Not Found` -- Original job not found
- `500 Internal Server Error` -- ComfyUI unreachable or workflow error

```bash
curl -X POST https://your-pod.runpod.io/api/admin/history/retry \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"prompt_id": "abc12345-6789-0def-ghij-klmnopqrstuv"}'
```

---

## GET /api/admin/history/{prompt_id}/package

Download a ZIP archive containing the job record, input image, and all output files.

**Auth:** Required

**Path parameters:**

| Parameter | Description |
|-----------|-------------|
| `prompt_id` | The prompt ID |

**Response:** `200 OK`

Returns a streamed ZIP file with:
- `Content-Type: application/zip`
- `Content-Disposition: attachment; filename="job_<name>.zip"`

ZIP structure:

```
job_<name>.zip
  job.json          # Full job record
  input/            # Input image (if any)
    myimage.png
  output/           # All output files
    final_00001.mp4
    preview_00001.png
```

**Error response:** `404 Not Found`

```json
{
  "detail": "Job not found"
}
```

```bash
curl "https://your-pod.runpod.io/api/admin/history/abc12345-6789-0def-ghij-klmnopqrstuv/package" \
  -H "X-API-Key: your-api-key" \
  -o job_package.zip
```
