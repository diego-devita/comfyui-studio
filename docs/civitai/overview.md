# CivitAI Integration Overview

The CivitAI integration spans multiple backend modules and provides several capabilities:

## Capabilities

1. **Catalog cross-reference** -- map CivitAI model/version IDs to local catalog entries, checking download status
2. **Add models from CivitAI** -- fetch a CivitAI model version's metadata and add it to the local catalog without downloading the file
3. **Promote LoRAs** -- move a LoRA entry from `models.json` to `loras.json` (promoting it to a style LoRA)
4. **Image generation data** -- proxy CivitAI's tRPC API to fetch generation parameters for any image, enriched with local catalog status
5. **Dependency detection** -- parse `<lora:Name:weight>` tags from prompts and embeddings from negative prompts, then resolve them via CivitAI hash lookup
6. **Workflow type detection** -- heuristically determine if an image was generated with t2i, i2i, i2v, or t2v
7. **Gallery downloads** -- download CivitAI images and videos for LoRA galleries

## Backend Modules

| Module | Responsibilities |
|--------|-----------------|
| `civitai_api.py` | Generation data proxy, catalog add, promote-to-lora, dependency resolution, workflow type detection |
| `loras_api.py` | LoRA lookup, gallery download/serve, CivitAI tag sync |
| `models_api.py` | CivitAI map endpoint, metadata fetch from CivitAI |
| `gallery_db.py` | SQLite index for downloaded gallery images |

## Authentication

CivitAI API calls use the `CIVITAI_API_KEY` environment variable. The key is sent as a Bearer token in the `Authorization` header. Without this key:

- Model version fetches may fail for restricted content
- Image generation data may be unavailable for some images
- Hash-based model resolution still works for public models

The key is configured either as an environment variable on the pod or edited at runtime from the Settings page.
