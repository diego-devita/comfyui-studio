# Catalog Integration

## CivitAI Map

The `GET /api/admin/models/civitai-map` endpoint builds a double-indexed map of all catalog entries that have CivitAI version IDs:

- **by_version** -- keyed by `civitai_version_id` string, returns file, dest, name, base_model, status, catalog name
- **by_model** -- keyed by `civitai_model_id` string, returns array of version IDs

This map is used by the Chrome extension to quickly check whether a CivitAI model version is already in the local catalog and whether it is downloaded.

Status values:

- `"present"` -- file exists on disk
- `"missing"` -- catalog entry exists but file is not downloaded

## Add from CivitAI

`POST /api/admin/civitai/add/{version_id}` fetches a model version from the CivitAI REST API and adds it to `models.json`:

1. Checks if the version ID is already in the catalog
2. Fetches `https://civitai.com/api/v1/model-versions/{version_id}`
3. Checks the `usageControl` field -- if the model is restricted (not downloadable), returns a `restricted` status
4. Builds a catalog entry using `_civitai_to_catalog_entry()`:
   - Maps CivitAI model type to catalog category and dest subfolder
   - Handles diffusion model base models (Flux, WAN, Hunyuan, CogVideo, LTX) routing to `diffusion_models/` instead of `checkpoints/`
   - Extracts filename, size, base_model, trigger words, SHA256 hash
   - Formats the display name as `"ModelName VersionName [BaseModel FP]"`
5. Adds the entry to the appropriate category in `models.json`
6. Bumps the catalog version and saves

### CivitAI Type Mapping

| CivitAI Type | Category | Dest Subfolder |
|-------------|----------|----------------|
| Checkpoint | checkpoints | checkpoints |
| LORA | loras | loras |
| VAE | vae | vae |
| TextualInversion | embeddings | embeddings |
| Controlnet | controlnet | controlnet |
| Upscaler | upscalers | upscale_models |

Checkpoints with base models matching Flux, WAN, Hunyuan Video, CogVideoX, or LTX Video are automatically routed to `diffusion_models` instead of `checkpoints`.

## Promote to Style LoRA

`POST /api/admin/civitai/promote-to-lora/{version_id}` moves a LoRA from `models.json` to `loras.json`:

1. Finds the entry in `models.json` by `civitai_version_id`
2. Verifies it has `dest: "loras"` (only LoRA entries can be promoted)
3. Determines the target category in `loras.json` by base model:
   - WAN base models -> `wan_loras`
   - Flux -> `flux_loras`
   - SDXL/Pony/Illustrious -> `sdxl_loras`
   - SD 1.5 -> `sd15_loras`
   - Other -> `other_loras`
4. Adds to `loras.json`, removes from `models.json`, saves both

## Remove from Catalog

`DELETE /api/admin/models/{filename}/catalog` removes a model entry from `models.json`:

- The file must **not** exist on disk (delete the file first if downloaded)
- Removes the entry from the catalog JSON
- Bumps version and saves
