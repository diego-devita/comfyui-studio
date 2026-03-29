# Models API

Endpoints for managing the checkpoint, VAE, CLIP, and technical LoRA catalog. These models are defined in `catalogs/models.json`.

---

## GET /api/admin/models

List all models from the catalog with download/presence status and disk info.

**Auth:** Required

**Response:** `200 OK`

```json
{
  "version": 21,
  "date": "2026-03-23 15:00",
  "stats": {
    "queued_count": 0,
    "downloading_count": 1,
    "fetching_count": 0,
    "present_count": 12,
    "total_count": 85,
    "global_speed": 52428800,
    "models_bytes": 64424509440,
    "free_bytes": 42949672960
  },
  "categories": [
    {
      "id": "sdxl-checkpoints",
      "name": "SDXL Checkpoints",
      "models": [
        {
          "name": "Juggernaut XL v9 [SDXL FP16]",
          "file": "juggernautXL_v9.safetensors",
          "dest": "checkpoints",
          "size_gb": 6.5,
          "status": "present",
          "on_disk_bytes": 6979321856,
          "base_model": "SDXL 1.0",
          "tags": ["sdxl", "general"],
          "source": "civitai",
          "civitai_version_id": "123456"
        },
        {
          "name": "RealVisXL V5.0 [SDXL FP16]",
          "file": "realvisxl_v5.safetensors",
          "dest": "checkpoints",
          "size_gb": 6.5,
          "status": "not_downloaded"
        }
      ]
    }
  ]
}
```

| Field | Description |
|-------|-------------|
| `stats.global_speed` | Total download speed in bytes/sec across all active downloads |
| `stats.models_bytes` | Total disk usage of downloaded models |
| `stats.free_bytes` | Free space on the network volume |
| `models[].status` | `"present"`, `"not_downloaded"`, `"downloading"`, `"queued"`, `"error"` |
| `models[].on_disk_bytes` | Actual file size on disk (0 if not downloaded) |

```bash
curl https://your-pod.runpod.io/api/admin/models \
  -H "X-API-Key: your-api-key"
```

---

## POST /api/admin/models/download/{filename}

Queue a single model for download.

**Auth:** Required

**Path parameters:**

| Parameter | Description |
|-----------|-------------|
| `filename` | The model filename as defined in the catalog |

**Response:** `200 OK`

```json
{
  "status": "queued",
  "file": "juggernautXL_v9.safetensors"
}
```

If the model is already downloading or queued:

```json
{
  "status": "downloading",
  "file": "juggernautXL_v9.safetensors"
}
```

**Error response:** `404 Not Found`

```json
{
  "detail": "Model 'nonexistent.safetensors' not found in catalog"
}
```

```bash
curl -X POST https://your-pod.runpod.io/api/admin/models/download/juggernautXL_v9.safetensors \
  -H "X-API-Key: your-api-key"
```

---

## POST /api/admin/models/download-batch

Queue multiple models for download.

**Auth:** Required

**Request body:**

```json
{
  "filenames": [
    "juggernautXL_v9.safetensors",
    "realvisxl_v5.safetensors",
    "sdxl_vae.safetensors"
  ]
}
```

**Response:** `200 OK`

```json
{
  "queued": ["juggernautXL_v9.safetensors", "sdxl_vae.safetensors"],
  "skipped": ["realvisxl_v5.safetensors"]
}
```

Models are skipped if they are already downloading/queued or not found in the catalog.

```bash
curl -X POST https://your-pod.runpod.io/api/admin/models/download-batch \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"filenames": ["juggernautXL_v9.safetensors", "realvisxl_v5.safetensors"]}'
```

---

## GET /api/admin/models/status

Server-Sent Events (SSE) stream of download status for all models. Emits one event per second.

**Auth:** Required

**Response:** `200 OK` with `text/event-stream`

Each SSE event contains:

```
data: {"downloads": {"juggernautXL_v9.safetensors": {"status": "downloading", "bytes_downloaded": 1073741824, "bytes_total": 6979321856, "speed": 52428800, "percent": 15.4}}, "timestamp": 1711234567.89}
```

| Field | Description |
|-------|-------------|
| `downloads[file].status` | `"queued"`, `"downloading"`, `"done"`, `"error"` |
| `downloads[file].bytes_downloaded` | Bytes downloaded so far |
| `downloads[file].bytes_total` | Total file size in bytes |
| `downloads[file].speed` | Current download speed in bytes/sec |
| `downloads[file].percent` | Download progress percentage |
| `downloads[file].error` | Error message (if status is `"error"`) |

```bash
curl -N https://your-pod.runpod.io/api/admin/models/status \
  -H "X-API-Key: your-api-key"
```

---

## DELETE /api/admin/models/{filename}

Delete a model file from disk. The catalog entry remains; the model returns to `"not_downloaded"` status.

**Auth:** Required

**Path parameters:**

| Parameter | Description |
|-----------|-------------|
| `filename` | The model filename |

**Response:** `200 OK`

```json
{
  "status": "deleted",
  "file": "juggernautXL_v9.safetensors"
}
```

**Error response:** `404 Not Found`

```json
{
  "detail": "Model 'nonexistent.safetensors' not found in catalog"
}
```

```bash
curl -X DELETE https://your-pod.runpod.io/api/admin/models/juggernautXL_v9.safetensors \
  -H "X-API-Key: your-api-key"
```

---

## GET /api/admin/models/civitai-map

Return a compact double-indexed map of all CivitAI version and model IDs across both the models and loras catalogs. Used by the Chrome extension for fast model status lookups.

**Auth:** Required

**Response:** `200 OK`

```json
{
  "by_version": {
    "123456": {
      "file": "juggernautXL_v9.safetensors",
      "dest": "checkpoints",
      "name": "Juggernaut XL v9 [SDXL FP16]",
      "base_model": "SDXL 1.0",
      "status": "present",
      "civitai_model_id": 789,
      "catalog": "models"
    }
  },
  "by_model": {
    "789": [123456, 123457]
  }
}
```

| Field | Description |
|-------|-------------|
| `by_version` | Map keyed by `civitai_version_id` string |
| `by_model` | Map keyed by `civitai_model_id` string, values are arrays of version IDs |
| `status` | `"present"` (file on disk) or `"missing"` (catalog entry only) |
| `catalog` | `"models"` or `"loras"` -- which catalog the entry is in |

```bash
curl https://your-pod.runpod.io/api/admin/models/civitai-map \
  -H "X-API-Key: your-api-key"
```

---

## DELETE /api/admin/models/{filename}/catalog

Remove a model entry from the `models.json` catalog. The model file must not exist on disk.

**Auth:** Required

**Path parameters:**

| Parameter | Description |
|-----------|-------------|
| `filename` | The model filename |

**Response:** `200 OK`

```json
{
  "status": "removed",
  "file": "old_model.safetensors"
}
```

**Error:** `404 Not Found` if not in catalog. `409 Conflict` if the file exists on disk (delete the file first).

```bash
curl -X DELETE https://your-pod.runpod.io/api/admin/models/old_model.safetensors/catalog \
  -H "X-API-Key: your-api-key"
```

---

## POST /api/admin/models/import

Import models from a JSON file. New models are added to the catalog with an `"imported"` tag. Existing models (matched by filename) are skipped.

**Auth:** Required

**Request:** Multipart form upload with a `file` field containing a JSON file in the same format as `models.json`.

**Response:** `200 OK`

```json
{
  "added": ["newModel_v1.safetensors", "newModel_v2.safetensors"],
  "skipped": ["existingModel.safetensors"],
  "total_added": 2
}
```

**Error response:** `400 Bad Request`

```json
{
  "detail": "Invalid JSON: ..."
}
```

```bash
curl -X POST https://your-pod.runpod.io/api/admin/models/import \
  -H "X-API-Key: your-api-key" \
  -F "file=@my-models.json"
```

---

## POST /api/admin/models/fetch-metadata

Fetch metadata from CivitAI and HuggingFace for all models that have a `civitai_version_id` or `hf_repo` field. Runs in a background thread. Updates model names, tags, base model, trained words, and timestamps.

**Auth:** Required

**Request body:** None

**Response:** `200 OK`

```json
{
  "queued": 42,
  "files": ["model1.safetensors", "model2.safetensors", "..."]
}
```

```bash
curl -X POST https://your-pod.runpod.io/api/admin/models/fetch-metadata \
  -H "X-API-Key: your-api-key"
```

---

## GET /api/admin/models/metadata-status

Check progress of the metadata fetch operation.

**Auth:** Required

**Response:** `200 OK`

```json
{
  "model1.safetensors": {"status": "done"},
  "model2.safetensors": {"status": "fetching_metadata"},
  "model3.safetensors": {"status": "error", "error": "HTTP 404"},
  "model4.safetensors": {"status": "queued_metadata"}
}
```

| Status | Description |
|--------|-------------|
| `queued_metadata` | Waiting in the background queue |
| `fetching_metadata` | Currently fetching from CivitAI/HuggingFace |
| `done` | Metadata fetched successfully |
| `error` | Fetch failed (see `error` field) |

```bash
curl https://your-pod.runpod.io/api/admin/models/metadata-status \
  -H "X-API-Key: your-api-key"
```

---

## POST /api/admin/models/sync

Sync `models.json` from the local git repo clone (`.repo/`). Requires a prior `Check for Updates` to have fetched the latest code.

**Auth:** Required

**Request body:** None

**Response (updated):** `200 OK`

```json
{
  "status": "updated",
  "old_version": 20,
  "new_version": 21,
  "new_date": "2026-03-23 15:00"
}
```

**Response (already current):** `200 OK`

```json
{
  "status": "up_to_date",
  "version": 21
}
```

```bash
curl -X POST https://your-pod.runpod.io/api/admin/models/sync \
  -H "X-API-Key: your-api-key"
```

---

## GET /api/admin/activity-log

Get the metadata fetch activity log. Each entry records a metadata fetch attempt.

**Auth:** Required

**Response:** `200 OK`

```json
[
  {"time": "14:30:01", "message": "Queued 42 models for metadata fetch", "level": "info"},
  {"time": "14:30:02", "message": "Fetching metadata for model1.safetensors...", "level": "info"},
  {"time": "14:30:03", "message": "OK -- model1.safetensors: base_model=SDXL 1.0, +5 civitai_tags", "level": "ok"},
  {"time": "14:30:04", "message": "ERROR -- model2.safetensors: HTTP 404", "level": "error"}
]
```

```bash
curl https://your-pod.runpod.io/api/admin/activity-log \
  -H "X-API-Key: your-api-key"
```

---

## POST /api/admin/activity-log/clear

Clear the metadata fetch activity log.

**Auth:** Required

**Request body:** None

**Response:** `200 OK`

```json
{
  "status": "cleared"
}
```

```bash
curl -X POST https://your-pod.runpod.io/api/admin/activity-log/clear \
  -H "X-API-Key: your-api-key"
```
