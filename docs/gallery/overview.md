# Gallery Overview

The gallery system manages images and videos downloaded from CivitAI for LoRA model galleries. It provides local storage, indexing, and serving of media files so the LoRA manager can display example images for each model.

## Design Principles

- **Two storage areas** -- original/card images belong to a specific model and are grouped by `model_id`. Community images are numerous and cross-version, so they are sharded for scale.
- **Co-located files** -- for each media item, the media file, thumbnail, and metadata JSON are stored in the same directory
- **SQLite index** -- a single `gallery.db` database indexes all files. The DB is rebuildable from files on disk.
- **Cross-endpoint dedup** -- the same CivitAI image can have different IDs in the REST vs tRPC API, but the CDN URL UUID is always unique. The `file_uuid` field prevents duplicates.
- **Thread safety** -- WAL mode + busy_timeout, each thread gets its own connection via `threading.local()`

## Components

| Component | Purpose |
|-----------|---------|
| `gallery_db.py` | SQLite database operations: CRUD, queries, tag caching |
| `loras_api.py` | REST endpoints for gallery download, serve, query, star, to-input |
| `assets/images/` | File storage root |
| `gallery.db` | SQLite database file |
