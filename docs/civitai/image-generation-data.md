# Image Generation Data

The `GET /api/admin/civitai/image/{image_id}` endpoint proxies CivitAI's tRPC `image.getGenerationData` API and enriches the response with local catalog cross-references.

## How It Works

1. Calls `https://civitai.com/api/trpc/image.getGenerationData` with the image ID
2. Parses the tRPC envelope (`result.data.json`)
3. Extracts: resources, meta, type, process, techniques, tools
4. Builds a CivitAI map from the local catalogs
5. Cross-references all resources against the local catalog
6. Detects the workflow type heuristically
7. Parses hidden dependencies from prompt text
8. Resolves detected dependencies via CivitAI hash lookup

## Response Structure

```json
{
  "raw": { "...tRPC envelope..." },
  "resources": [
    {
      "modelName": "Juggernaut XL",
      "versionId": 123456,
      "catalog_status": "present",
      "catalog_file": "juggernautXL_v9.safetensors",
      "catalog_dest": "checkpoints",
      "catalog_name": "Juggernaut XL v9 [SDXL FP16]"
    }
  ],
  "detected_deps": [
    {
      "name": "DetailTweaker",
      "weight": 0.8,
      "source": "prompt",
      "hash": "ABC123...",
      "civitai_model_id": 789,
      "civitai_version_id": 456,
      "civitai_file": "detailtweaker.safetensors",
      "catalog_status": "not_found"
    }
  ],
  "clean_prompt": "a portrait of a woman, detailed, soft lighting",
  "meta": { "prompt": "...", "negativePrompt": "...", "steps": 30 },
  "type": "image",
  "process": "txt2img",
  "techniques": [{"name": "txt2img"}],
  "tools": [],
  "detected_type": "t2i"
}
```

## Resource Catalog Status

Each resource in the response is enriched with a `catalog_status` field:

| Status | Meaning |
|--------|---------|
| `present` | Model is in the catalog and file exists on disk |
| `missing` | Model is in the catalog but not downloaded |
| `not_found` | Model is not in either catalog (models.json or loras.json) |
