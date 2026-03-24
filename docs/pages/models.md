# Model Manager

The model catalog at `/admin/models`. Browse, download, and manage AI models (checkpoints, VAE, CLIP, ControlNet, IP-Adapter, upscalers, technical LoRAs) from the `catalogs/models.json` catalog.

## Layout

1. **Header** -- page title with "Import JSON..." and "Fetch Metadata..." action buttons
2. **Status bar** -- live counters for downloading, queued, present/total, disk usage, and parallel download selector
3. **Filter panel** -- category tags, base model tags, status filters, sort controls, view mode, text search
4. **Model cards** -- grouped by category, each card showing model details and actions

## Data Loading

On page load:

```
GET /api/admin/models
```

Returns the full model catalog with disk presence and download state merged in. Each model entry includes:

- `file`, `name`, `dest` (target subdirectory), `url` (download source)
- `size_gb`, `base_model`, `tags`
- `status` -- one of: `present`, `missing`, `queued`, `downloading`, `error`
- `progress` -- download percentage (when downloading)
- CivitAI metadata fields: `civitai_version_id`, `civitai_model_id`, `description`, `preview_url`, `civitai_tags`

The backend builds this by scanning the models catalog, checking each file's existence on disk, and merging active download states.

## Status Bar

A fixed bar below the header showing live aggregate stats:

| Counter | Meaning |
|---------|---------|
| N downloading | Models currently being downloaded |
| N queued | Models waiting in the download queue |
| N / M present | Models on disk out of total catalog |
| Disk | Volume usage (fetched from the status endpoint) |
| Parallel: [1-5] | Max concurrent downloads (select dropdown, saved immediately via `PUT /api/admin/settings`) |

## Filter Panel

### Category Filters

Tag buttons generated from the catalog's category names. Click to toggle; only models in active categories are shown. All categories are active by default.

### Base Model Filters

Tag buttons for base model identifiers (e.g., "wan-i2v-14b", "sdxl", "flux"). Extracted from all models in the catalog.

### Status Filters

Five toggle buttons: present, missing, queued, downloading, error. All active by default.

### Sort

Three sort buttons with ascending/descending toggle:

- **Name** (default, ascending) -- alphabetical
- **Size** -- by file size in GB
- **Status** -- by priority order: downloading first, then queued, error, missing, present

### View Mode

Two view modes:

- **Extended** (default) -- full card with name, file, size, tags, preview image, description, source link
- **Compact** -- condensed row with name, size, and status icon only

### Search

Text input that filters models by name, file, or tags. Searches across all categories.

## Model Cards

Each model is rendered as a card within its category section. In extended view, a card shows:

- **Status icon** -- checkmark (present), download arrow (missing), spinner (queued/downloading), warning (error)
- **Name** -- model display name
- **File** -- filename with destination path
- **Size** -- in GB or MB
- **Base model badge** -- if set
- **Tags** -- as small pills
- **Preview image** -- from CivitAI metadata (if fetched)
- **Description** -- from CivitAI metadata
- **Source link** -- link to CivitAI or HuggingFace page
- **Progress bar** -- visible during download, showing percentage

### Card Actions

- **Download button** -- starts download (calls `POST /api/admin/models/download/{filename}`)
- **Delete button** -- removes the file from disk with a confirm dialog (calls `DELETE /api/admin/models/{filename}`)

When downloading, the card shows a progress bar with percentage. The status badge changes to a spinning animation while queued.

## Polling

When any model is downloading or queued, the page polls `GET /api/admin/models` every 3 seconds to refresh download progress. Polling stops when no active downloads remain.

## Import JSON

The "Import JSON..." button opens a file picker for `.json` files. The imported JSON should be an array of model objects or a catalog-format object with categories. After validation, it calls:

```
POST /api/admin/models/import
```

This merges the imported models into the catalog, adding new entries and updating existing ones. A toast confirms the count of models added.

## Fetch Metadata

The "Fetch Metadata..." button triggers a batch metadata fetch from CivitAI for all models that have a `civitai_version_id` (extracted from CivitAI download URLs). The process:

1. Calls `POST /api/admin/models/fetch-metadata`
2. The backend spawns a background thread that sequentially fetches metadata for each model from the CivitAI API
3. For each model, it retrieves: clean display name, description, preview images, tags, base model info
4. Progress is shown via an activity log panel that streams status messages
5. On completion, the catalog file is updated and the page refreshes

The metadata fetcher cleans up model names by stripping CJK characters, emojis, and deduplicating words between the model name and version name.

## Related Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/admin/models` | GET | List all models with status |
| `/api/admin/models/download/{filename}` | POST | Start download |
| `/api/admin/models/{filename}` | DELETE | Delete from disk |
| `/api/admin/models/batch-download` | POST | Download multiple models |
| `/api/admin/models/import` | POST | Import models from JSON |
| `/api/admin/models/fetch-metadata` | POST | Fetch CivitAI metadata |
| `/api/admin/settings` | PUT | Update max concurrent downloads |
