# Download Pipeline

Gallery images are downloaded in bulk when a LoRA gallery is populated. The download pipeline handles media files, thumbnail generation, and metadata storage.

## Download Flow

When `POST /api/admin/loras/{model_id}/gallery` is called with download parameters:

1. The backend fetches image data from CivitAI (original images from the model version, community images from the image search API)
2. For each image, `_gallery_download_one()` is called:
   - Checks if the image already exists in the database (by `civitai_id` or `file_uuid`)
   - Downloads the media file from the CivitAI CDN
   - For video files, generates a thumbnail using `ffmpeg -ss 1 -frames:v 1`
   - Saves the full CivitAI metadata as a JSON file alongside the media
   - Inserts a record into `gallery_images` table
   - Links the image to the model version in `image_versions` table

## Deduplication

The pipeline uses two deduplication strategies:

1. **By civitai_id** -- `gallery_db.image_exists(civitai_id)` checks the primary key
2. **By file_uuid** -- `gallery_db.uuid_exists(file_uuid)` checks the CDN UUID. This catches cases where the same image appears with different CivitAI IDs in different API responses.

## Thumbnail Generation

For video files, thumbnails are generated using ffmpeg:

```
ffmpeg -ss 1 -i input.mp4 -frames:v 1 -q:v 5 output.thumb.jpg
```

This extracts a single frame at the 1-second mark. Image files do not get separate thumbnails -- the original serves as its own thumbnail.

## Metadata Storage

Each downloaded item gets a `.json` file containing the full CivitAI metadata:

- Image dimensions, type, creation date
- Post information (title, author)
- Generation data availability flags
- Reaction and engagement counts
- Tags (as CivitAI tag IDs)

## Corruption Recovery

The gallery database runs in WAL mode. If the database becomes corrupted (e.g., the pod was killed without a WAL checkpoint), `init_gallery_db()` detects the corruption, deletes the database files, and recreates them. The database is rebuildable because the files on disk are the source of truth.
