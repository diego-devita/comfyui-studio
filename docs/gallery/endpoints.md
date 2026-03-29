# Gallery Endpoints

All gallery endpoints are in `loras_api.py` and prefixed with `/api/admin/loras/`.

## Media Serving

### GET /api/admin/loras/gallery/media/{item_id}

Serve a gallery media file (image or video) by its CivitAI ID. Looks up the file path in the database and returns the file with appropriate Content-Type.

### GET /api/admin/loras/gallery/thumb/{item_id}

Serve a thumbnail for a gallery item. For videos, returns the generated `.thumb.jpg`. For images, falls back to the media file itself.

### GET /api/admin/loras/images/{model_id}/previews/{filename}

Serve LoRA preview images from the `lookup/{model_id}/previews/` directory.

## Gallery Management

### POST /api/admin/loras/{model_id}/gallery

Start a gallery download for a model. Fetches original and community images from CivitAI and downloads them to the local gallery store.

### GET /api/admin/loras/{model_id}/gallery

List all gallery images for a model. Returns images from the database with metadata, sorted by creation date. Supports filtering by source (original/community) and starred status.

### DELETE /api/admin/loras/{model_id}/gallery

Delete all gallery images for a model. Removes database records and files from disk.

## Individual Image Actions

### GET /api/admin/loras/gallery/{item_id}/meta

Get the full metadata JSON for a gallery item.

### POST /api/admin/loras/gallery/{item_id}/star

Toggle the starred flag on a gallery image. Returns the new starred state.

### POST /api/admin/loras/gallery/to-input/{image_id}

Copy a gallery image to the ComfyUI input directory (`assets/input/`) so it can be used as an input image in workflows. Returns the ComfyUI filename.

### POST /api/admin/loras/gallery/download-single/{image_id}

Download a single CivitAI image by its ID and add it to the gallery store. Used when you want to add a specific image without downloading an entire gallery.

## CivitAI Tag Sync

### POST /api/admin/civitai/tags/sync

Sync CivitAI tag names for all tag IDs found in the gallery metadata. Calls the CivitAI tRPC batch API to resolve tag IDs to human-readable names.

### GET /api/admin/civitai/tags

List all cached CivitAI tags from the local database.
