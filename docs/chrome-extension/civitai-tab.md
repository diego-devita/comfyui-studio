# CivitAI Tab

The CivitAI tab activates when you are browsing CivitAI. It detects the current page type and shows relevant information from your Studio catalog.

## Page Detection

When the popup opens, the extension checks the active browser tab's URL:

- **Model page** (`civitai.com/models/{id}`) -- shows model version status against your catalog
- **Image page** (`civitai.com/images/{id}`) -- fetches generation data and shows resource analysis
- **Other pages** -- shows a message that no CivitAI content was detected

## Model Version Status

When on a CivitAI model page, the extension calls `GET /api/admin/models/civitai-map` on your Studio backend. This returns a map of all CivitAI version IDs in your catalogs (both `models.json` and `loras.json`).

The tab then shows the status of each model version:

- **Present** (green) -- model is in your catalog and downloaded to disk
- **Missing** (yellow) -- model is in your catalog but not yet downloaded
- **Not Found** (grey) -- model is not in your catalog

## Image Generation Data

When on a CivitAI image page, the extension calls `GET /api/admin/civitai/image/{image_id}` on your Studio backend. This proxies the CivitAI tRPC `image.getGenerationData` endpoint and enriches the response with catalog cross-references.

The tab displays:

- **Detected workflow type** -- `t2i`, `i2i`, `i2v`, or `t2v` (heuristically determined)
- **Resources** -- models used in the generation, with catalog status for each
- **Detected dependencies** -- LoRAs parsed from `<lora:Name:weight>` tags in the prompt, embeddings from the negative prompt
- **Clean prompt** -- the positive prompt with LoRA tags stripped
- **Metadata** -- steps, CFG, sampler, and other generation parameters

## Create Preset

When viewing an image with generation data, a "Create Preset" button allows you to save the generation parameters as a Studio preset. The preset includes:

- The detected workflow type mapped to a Studio workflow ID
- All extracted parameters (prompt, negative prompt, steps, CFG, seed, etc.)
- A `source` field linking back to the CivitAI image

The preset is saved via `POST /api/admin/presets` on the Studio backend.
