# Storage Structure

All gallery files live under `STUDIO_DIR/assets/images/`:

```
assets/images/
├── gallery.db                      SQLite index
├── lookup/{model_id}/previews/     LoRA preview thumbnails (add-civitai flow)
├── models/{model_id}/              Original/card images (grouped by model)
│   ├── {civitai_id}.mp4            Media file
│   ├── {civitai_id}.thumb.jpg      ffmpeg thumbnail (video only)
│   └── {civitai_id}.json           Full CivitAI metadata
└── media/NNN/NNN/                  Community images (sharded)
    ├── {civitai_id}.mp4
    ├── {civitai_id}.thumb.jpg
    └── {civitai_id}.json
```

## Two Storage Areas

### Original Images (`models/{model_id}/`)

Images that belong to the model itself -- typically the model creator's showcase images. These are fetched from the CivitAI model version's `images` array and are grouped by `model_id` for easy browsing.

There are few originals per model (typically 5-20), so no sharding is needed.

### Community Images (`media/NNN/NNN/`)

Images created by CivitAI users using the model. These are fetched from the CivitAI image search API and can number in the thousands.

Community images are sharded by the first 6 characters of the CivitAI ID:

- `117242376` -> `media/117/242/117242376.jpeg`
- `745fa4bb-...` -> `media/745/fa4/745fa4bb.jpeg`

This keeps each directory under ~1000 files for filesystem performance.

## Database Schema

### gallery_images Table

The main table with one row per unique media file on disk:

| Column | Type | Description |
|--------|------|-------------|
| `civitai_id` | TEXT PK | CivitAI image ID (text to support UUIDs) |
| `file_uuid` | TEXT | CDN URL UUID for cross-endpoint dedup |
| `type` | TEXT | `"image"` or `"video"` |
| `ext` | TEXT | File extension (`.jpeg`, `.mp4`, etc.) |
| `file_path` | TEXT | Relative path from `assets/images/` |
| `thumb_path` | TEXT | Thumbnail path (video only) |
| `meta_path` | TEXT | Metadata JSON path |
| `model_id` | INTEGER | CivitAI model ID |
| `post_id` | INTEGER | CivitAI post ID |
| `post_title` | TEXT | Post title |
| `username` | TEXT | CivitAI username |
| `base_model` | TEXT | Base model string |
| `width`, `height` | INTEGER | Media dimensions |
| `duration` | REAL | Video duration in seconds |
| `audio` | INTEGER | 1 if video has audio |
| `file_size` | INTEGER | File size in bytes |
| `created_at` | TEXT | CivitAI creation timestamp |
| `downloaded_at` | TEXT | When we downloaded it |
| `reactions`, `comments`, `collected` | INTEGER | Stats snapshot at download time |
| `has_meta`, `has_gen_data` | INTEGER | Whether metadata/generation data exists |
| `source` | TEXT | `"original"` or `"community"` |
| `search_mode` | TEXT | How this image was found |
| `starred` | INTEGER | User star flag |
| `prompt` | TEXT | Extracted prompt for search |

### image_versions Table

Join table mapping images to model versions:

| Column | Type | Description |
|--------|------|-------------|
| `civitai_id` | TEXT | References `gallery_images` |
| `version_id` | INTEGER | CivitAI model version ID |

One image can appear in multiple model versions' galleries without duplicating files on disk.

### civitai_tags Table

Local cache of CivitAI's tag dictionary:

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | CivitAI tag ID |
| `name` | TEXT | Tag name |
| `type` | TEXT | Tag type (Moderation, UserGenerated, Label, Category) |
| `synced_at` | TEXT | When this tag was last synced |
