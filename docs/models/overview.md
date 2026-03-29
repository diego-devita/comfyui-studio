# Model Management Overview

ComfyUI Studio manages AI models through three separate JSON catalogs stored in `STUDIO_DIR/catalogs/`. Each catalog tracks which models are available, where to download them from, and how they relate to each other. The backend enriches this catalog data at runtime with download state and disk presence information.

## Three Catalogs

### models.json -- AI Models

The primary catalog. Contains **126 models** across **14 categories** covering everything needed for image and video generation: checkpoints, diffusion models, LoRAs, VAE, text encoders, CLIP vision, ControlNet, IP-Adapter, upscalers, embeddings, detectors, AnimateDiff, segmentation, and face swap.

All 126 models come from HuggingFace except 2 embeddings (EasyNegative and veryBadImageNegative) which come from CivitAI.

**File:** `STUDIO_DIR/catalogs/models.json`

### loras.json -- Style LoRAs

A separate catalog for user-curated style LoRAs (artistic, NSFW, or otherwise subjective). Kept separate from the main models catalog by design -- the main catalog is maintained upstream and updated automatically, while `loras.json` is a personal collection that stays local.

Currently empty (no categories). Users populate it by importing JSON or adding entries manually through the metadata fetch system.

**File:** `STUDIO_DIR/catalogs/loras.json`

### llm.json -- LLM Models

Catalog for large language model GGUF files used by the built-in llama-server. Contains **3 models**: Qwen 2.5 7B Instruct (Q4_K_M), Qwen 2.5 14B Instruct (Q4_K_M), and Llama 3.1 8B Instruct (Q4_K_M). All sourced from HuggingFace (bartowski GGUF quantizations).

LLM models have additional fields not present in the other catalogs: `quant` (quantization format like `Q4_K_M`) and `context_default` (default context window size).

**File:** `STUDIO_DIR/catalogs/llm.json`

## Backend Loading

All three catalogs are loaded by `backend/catalogs.py` at import time into module-level variables:

| Variable | Source file | Contents |
|----------|-------------|----------|
| `_models_data` | `models.json` | 126 AI models in 14 categories |
| `_loras_data` | `loras.json` | Style LoRAs (currently empty) |
| `_llm_models_data` | `llm.json` | 3 LLM GGUF models |

### Key Functions

**`_reload_models()`** -- Reloads all three catalogs from disk. Called before every API response to ensure fresh data. This means changes saved to the JSON files (e.g., by the metadata fetch system or import feature) are immediately visible on the next request.

**`_all_categories()`** -- Returns a merged list of categories from both `_models_data` and `_loras_data`. Used for cross-catalog searches, such as finding a model by filename regardless of which catalog it belongs to, or filtering compatible LoRAs across both catalogs.

**`_find_model(filename)`** -- Searches both models and loras catalogs by filename. Returns the model entry dict or `None`.

**`_find_llm_model(filename)`** -- Searches the LLM catalog by filename.

**`_build_catalog_response(catalog_data, base_dir, download_state)`** -- Shared builder that enriches raw catalog data for API responses. It takes any of the three catalogs and produces a response with:

- All original model fields (name, file, dest, source, etc.)
- `status` -- one of `"present"`, `"downloading"`, `"queued"`, `"error"`, `"missing"`
- `progress` -- download progress percentage (0-100, or `null` if total unknown)
- `on_disk_bytes` -- actual file size on disk
- `expected_bytes` -- expected file size (from Content-Length during download, or computed from `size_gb`)
- `speed` -- current download speed in bytes/second
- `error` -- error message string if download failed
- `url` -- constructed download URL (never stored in catalog, always built at runtime)

### Disk Scanning Optimization

`_build_catalog_response()` pre-scans all destination directories once using `os.scandir()` and builds a cache keyed by `"dest/filename"`. This avoids an expensive `stat()` call per model -- important when the catalog has 126+ entries and the models directory contains large files.

For flat directories (like LLM models that have no `dest` subdirectory), the base directory itself is scanned.

## How the Three Catalogs Interact

The models and loras catalogs share the same format and the same backend infrastructure. They use the same download system, the same disk path base (`ComfyUI/models/`), and the same response builder. The only difference is which JSON file they come from and which API endpoint serves them.

The LLM catalog is similar in format but uses a different base directory (`STUDIO_DIR/llm/models/`) and is served by `llm_api.py` instead of `models_api.py`.

```
models.json ──┐
              ├──→ _all_categories() ──→ cross-catalog searches
loras.json ──┘                          compatibility filtering
                                        _find_model() lookups

llm.json ─────→ (standalone)  ──→ LLM server management
```

## CivitAI Integration

Models can be added to the catalog directly from CivitAI:

- **Add from CivitAI** (`POST /api/admin/civitai/add/{version_id}`) -- fetches a model version's metadata and adds it to `models.json` without downloading the file
- **CivitAI Map** (`GET /api/admin/models/civitai-map`) -- returns a double-indexed map of all catalog entries with CivitAI version IDs, used by the Chrome extension
- **Remove from Catalog** (`DELETE /api/admin/models/{filename}/catalog`) -- removes a catalog entry for a model that is not downloaded

See [CivitAI Catalog Integration](../civitai/catalog-integration.md) for details.

## API Endpoints

| Endpoint | Catalog | Module |
|----------|---------|--------|
| `GET /api/admin/models` | models.json | models_api.py |
| `GET /api/admin/models/civitai-map` | models + loras | models_api.py |
| `DELETE /api/admin/models/{filename}/catalog` | models.json | models_api.py |
| `GET /api/admin/loras` | loras.json | models_api.py |
| `GET /api/admin/loras/compatible/{base_model}` | models + loras merged | models_api.py |
| `GET /api/admin/llm/models` | llm.json | llm_api.py |

Each list endpoint returns stats alongside the categories: present count, total count, active downloads, global download speed, and disk usage. The frontend uses these stats for status badges and progress indicators in the page header.

## Where Models Live on Disk

Models from the models and loras catalogs are downloaded to `ComfyUI/models/` under the subdirectory specified by each model's `dest` field:

```
/workspace/ComfyUI/models/
├── checkpoints/           ← dest: "checkpoints"
├── diffusion_models/      ← dest: "diffusion_models"
├── loras/                 ← dest: "loras"
├── vae/                   ← dest: "vae"
├── text_encoders/         ← dest: "text_encoders"
├── clip_vision/           ← dest: "clip_vision"
├── controlnet/            ← dest: "controlnet"
├── ipadapter/             ← dest: "ipadapter"
├── upscale_models/        ← dest: "upscalers"
├── embeddings/            ← dest: "embeddings"
├── animatediff_models/    ← dest: "animatediff"
├── sam2/                  ← dest: "segmentation"
└── insightface/           ← dest: "faceswap"
```

LLM models are downloaded to a completely separate location:

```
/workspace/studio/llm/models/    ← flat directory, no subdirectories
```

## Catalog Versioning

Each catalog has its own `version` and `date` fields at the top level. These must stay in sync with the corresponding component entry in `version.json`:

| Catalog file | version.json component |
|-------------|----------------------|
| `models.json` version/date | `components.models` version/date |
| `loras.json` version/date | `components.loras` version/date |
| `llm.json` version/date | `components.llm_models` version/date |

When the update mechanism runs, it compares these versions to determine if a catalog needs updating. See [Catalog Format](catalog-format.md) for the full JSON structure.
