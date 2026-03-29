# CivitAI API

Endpoints for CivitAI integration: generation data proxy, catalog add, promote to style LoRA. All endpoints require authentication.

---

## GET /api/admin/civitai/image/{image_id}

Proxy CivitAI's image generation data endpoint. Fetches generation parameters and enriches resources with local catalog status.

**Auth:** Required

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `image_id` | integer | CivitAI image ID |

**Response:** `200 OK`

```json
{
  "raw": { "...tRPC response..." },
  "resources": [
    {
      "modelName": "Juggernaut XL",
      "versionId": 123456,
      "catalog_status": "present",
      "catalog_file": "juggernautXL_v9.safetensors"
    }
  ],
  "detected_deps": [
    {
      "name": "DetailTweaker",
      "weight": 0.8,
      "source": "prompt",
      "catalog_status": "not_found"
    }
  ],
  "clean_prompt": "prompt with LoRA tags removed",
  "meta": { "prompt": "...", "steps": 30 },
  "type": "image",
  "process": "txt2img",
  "techniques": [],
  "tools": [],
  "detected_type": "t2i"
}
```

See [Image Generation Data](../civitai/image-generation-data.md) for full response details.

---

## POST /api/admin/civitai/add/{version_id}

Fetch a CivitAI model version and add it to the `models.json` catalog without downloading the file.

**Auth:** Required

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `version_id` | integer | CivitAI model version ID |

**Response (added):** `200 OK`

```json
{
  "status": "added",
  "file": "model_v1.safetensors",
  "name": "Model Name v1 [SDXL FP16]",
  "category": "checkpoints",
  "dest": "checkpoints"
}
```

**Response (already exists):** `200 OK`

```json
{
  "status": "already_exists",
  "file": "model_v1.safetensors"
}
```

**Response (restricted):** `200 OK`

```json
{
  "status": "restricted",
  "reason": "This model is 'Generation' only — download not allowed by the creator"
}
```

---

## POST /api/admin/civitai/promote-to-lora/{version_id}

Move a LoRA entry from `models.json` to `loras.json`.

**Auth:** Required

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `version_id` | integer | CivitAI model version ID (must be a LoRA in models.json) |

**Response (promoted):** `200 OK`

```json
{
  "status": "promoted",
  "file": "style_lora.safetensors",
  "category": "sdxl_loras"
}
```

**Response (already in loras.json):** `200 OK`

```json
{
  "status": "already_exists"
}
```

**Error:** `404 Not Found` if not in models catalog. `400 Bad Request` if the entry is not a LoRA (`dest != "loras"`).
