# LoRAs API

Endpoints for managing the style LoRA catalog. Style LoRAs are kept in a separate catalog (`catalogs/loras.json`) from the models catalog. Download and delete operations share the same endpoints as models (use the model filename with `/api/admin/models/download/{filename}` and `DELETE /api/admin/models/{filename}`).

---

## GET /api/admin/loras

List all style LoRAs from the catalog with download/presence status.

**Auth:** Required

**Response:** `200 OK`

```json
{
  "version": 2,
  "date": "2026-03-20 10:00",
  "stats": {
    "queued_count": 0,
    "downloading_count": 0,
    "present_count": 5,
    "total_count": 15,
    "global_speed": 0,
    "models_bytes": 2147483648,
    "free_bytes": 42949672960
  },
  "categories": [
    {
      "id": "wan-loras",
      "name": "WAN LoRAs",
      "models": [
        {
          "name": "Ghibli Style LoRA",
          "file": "ghibli_style_lora.safetensors",
          "dest": "loras",
          "size_gb": 0.4,
          "status": "present",
          "on_disk_bytes": 429496729,
          "base_model": "WAN 2.1",
          "pair_id": "ghibli",
          "pair_role": "both",
          "tags": ["style", "anime"]
        }
      ]
    }
  ]
}
```

The response format is identical to `GET /api/admin/models`. Each LoRA entry may include pairing fields:

| Field | Description |
|-------|-------------|
| `pair_id` | Identifier grouping related LoRAs (e.g., high/low noise variants) |
| `pair_role` | `"high"`, `"low"`, or `"both"` -- the noise level variant |
| `base_model` | The base model this LoRA is compatible with |

```bash
curl https://your-pod.runpod.io/api/admin/loras \
  -H "X-API-Key: your-api-key"
```

---

## GET /api/admin/loras/compatible/{base_model}

List LoRA pairs compatible with a given base model. Used by the LoRA picker in workflow runner forms. LoRAs are grouped by `pair_id`.

**Auth:** Required

**Path parameters:**

| Parameter | Description |
|-----------|-------------|
| `base_model` | The base model identifier (e.g., `"WAN 2.1"`, `"SDXL 1.0"`) |

**Response:** `200 OK`

```json
[
  {
    "pair_id": "ghibli",
    "name": "Ghibli Style",
    "high": "ghibli_style_high.safetensors",
    "low": "ghibli_style_low.safetensors",
    "both": null
  },
  {
    "pair_id": "anime",
    "name": "Anime Style",
    "high": null,
    "low": null,
    "both": "anime_style_lora.safetensors"
  }
]
```

| Field | Description |
|-------|-------------|
| `pair_id` | Unique pair identifier |
| `name` | Clean display name (suffixes like "High Noise" are stripped) |
| `high` | Filename of the high-noise variant, or `null` |
| `low` | Filename of the low-noise variant, or `null` |
| `both` | Filename of the combined variant, or `null` |

When `both` is set, the LoRA handles all noise levels. When `high` and `low` are set, the workflow should apply both with appropriate strength scheduling.

```bash
curl https://your-pod.runpod.io/api/admin/loras/compatible/WAN%202.1 \
  -H "X-API-Key: your-api-key"
```

---

## POST /api/admin/loras/gallery/download-single/{image_id}

Download a single CivitAI image by its ID and add it to the gallery store. Used to add specific images without downloading an entire gallery.

**Auth:** Required

**Path parameters:**

| Parameter | Description |
|-----------|-------------|
| `image_id` | CivitAI image ID |

**Response:** `200 OK`

```json
{
  "status": "downloaded",
  "civitai_id": "12345678"
}
```

```bash
curl -X POST https://your-pod.runpod.io/api/admin/loras/gallery/download-single/12345678 \
  -H "X-API-Key: your-api-key"
```

---

## POST /api/admin/loras/gallery/to-input/{image_id}

Copy a gallery image to the ComfyUI input directory so it can be used as an input image in workflows.

**Auth:** Required

**Path parameters:**

| Parameter | Description |
|-----------|-------------|
| `image_id` | CivitAI image ID (from the gallery database) |

**Response:** `200 OK`

```json
{
  "filename": "gallery_12345678.jpg"
}
```

The returned `filename` is the ComfyUI-relative path that can be used in workflow execute calls.

```bash
curl -X POST https://your-pod.runpod.io/api/admin/loras/gallery/to-input/12345678 \
  -H "X-API-Key: your-api-key"
```
