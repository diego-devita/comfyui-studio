# Presets API

Endpoints for managing saved workflow presets. All endpoints require authentication.

---

## GET /api/admin/presets

List all saved presets.

**Auth:** Required

**Response:** `200 OK`

```json
[
  {
    "id": "ghibli-portrait",
    "name": "Ghibli Portrait",
    "description": "Studio Ghibli style portrait",
    "private": false,
    "workflow_id": "i2i-batch",
    "workflow_name": "Image to Image Batch",
    "source_type": "civitai",
    "civitai_image_id": 12345678,
    "civitai_url": "https://civitai.com/images/12345678",
    "detected_type": "i2i"
  }
]
```

Source fields (`source_type`, `civitai_image_id`, `civitai_url`, `detected_type`) are only present for presets created from CivitAI images.

---

## GET /api/admin/presets/{preset_id}

Get a single preset with full parameters.

**Auth:** Required

**Response:** `200 OK`

Returns the complete preset JSON including the `workflow.params` object.

**Error:** `404 Not Found` if preset does not exist.

---

## POST /api/admin/presets

Save a new preset.

**Auth:** Required

**Request body:**

```json
{
  "id": "my-preset",
  "name": "My Preset",
  "description": "A test preset",
  "private": false,
  "workflow": {
    "workflow_id": "t2i-batch",
    "workflow_name": "Text to Image Batch",
    "params": {
      "positive_prompt": "a beautiful landscape",
      "seed": -1
    }
  },
  "source": {
    "type": "civitai",
    "civitai_image_id": 12345678
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Alphanumeric with hyphens and underscores |
| `name` | string | No | Display name (defaults to id) |
| `description` | string | No | Description text |
| `private` | boolean | No | Default false |
| `workflow` | object | Yes | Workflow reference and params |
| `source` | object | No | Provenance info (CivitAI) |

**Response:** `200 OK`

```json
{
  "id": "my-preset",
  "message": "Preset saved"
}
```

---

## PUT /api/admin/presets/{preset_id}/rename

Update preset name, ID, description, or privacy.

**Auth:** Required

**Request body:**

```json
{
  "name": "New Name",
  "id": "new-id",
  "description": "Updated description",
  "private": true
}
```

All fields are optional. If `id` is provided and differs from the current ID, the preset file is renamed.

**Response:** `200 OK`

```json
{
  "id": "new-id",
  "name": "New Name"
}
```

**Error:** `409 Conflict` if the new ID already exists.

---

## DELETE /api/admin/presets/{preset_id}

Delete a preset.

**Auth:** Required

**Response:** `200 OK`

```json
{
  "ok": true
}
```

---

## POST /api/admin/presets/import

Import a preset from a JSON file upload.

**Auth:** Required

**Request:** Multipart form with a `file` field containing a JSON file.

**Response:** `200 OK`

```json
{
  "id": "imported-preset",
  "message": "Preset imported"
}
```

---

## GET /api/admin/presets/{preset_id}/placeholders

Extract placeholder questions from a preset's parameters.

**Auth:** Required

**Response:** `200 OK`

```json
[
  {
    "index": 0,
    "scene": 0,
    "question": "style",
    "options": ["anime", "realistic"],
    "raw": "[[style:anime|realistic]]",
    "field": "positive_prompt"
  }
]
```

Returns an empty array if no placeholders are found.

---

## POST /api/admin/presets/{preset_id}/run

Execute a preset. Applies placeholder answers, then delegates to the workflow runner.

**Auth:** Required

**Request:** Multipart form

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `input_image` | file | No | Input image for I2I/I2V workflows |
| `seed` | string | No | Seed value (default `"-1"` for random) |
| `answers` | string | No | JSON string of placeholder answers: `{"0": "anime"}` |
| `existing_image` | string | No | ComfyUI filename of already-uploaded image |

**Response:** `200 OK`

```json
{
  "prompt_id": "abc123-def456-...",
  "seeds": {"seed": 42}
}
```

---

## GET /api/admin/presets/{preset_id}/export

Download the preset as a JSON file.

**Auth:** Required

**Response:** `200 OK` with `Content-Disposition: attachment` header.
