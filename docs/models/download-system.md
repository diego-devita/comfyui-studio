# Download System

ComfyUI Studio includes a thread-pool-based download manager implemented in `backend/download.py`. It handles downloading models from HuggingFace and CivitAI with concurrent execution, progress tracking, and automatic authentication.

## Architecture

```
User clicks "Download"
        │
        ▼
  _enqueue_download(model)
        │
        ▼
  _pending_queue  ←── ordered FIFO list
        │
        ▼
  _schedule_downloads()  ←── runs under _queue_lock
        │                     submits up to _max_concurrent threads
        ▼
  ThreadPoolExecutor (max_workers=10)
        │
        ▼
  _do_download(item)  ←── one thread per active download
        │
        ├── _get_download_url(model)  ← construct URL from catalog fields
        ├── _inject_auth(url)         ← add HF_TOKEN or CIVITAI_API_KEY
        ├── requests.get(stream=True) ← 8 MB chunks
        ├── write to {dest}/{file}.tmp
        └── rename to {dest}/{file}   ← atomic on success
```

## Concurrency Control

### Max Concurrent Downloads

The maximum number of simultaneous downloads defaults to **3** and is controlled by the `MAX_CONCURRENT_DOWNLOADS` environment variable:

```
MAX_CONCURRENT_DOWNLOADS=5
```

This value can also be changed at runtime from the Settings page without restarting the backend.

The `ThreadPoolExecutor` itself has 10 worker threads, but `_schedule_downloads()` enforces the concurrency limit by only submitting tasks when `_active_count < _max_concurrent`. When a download finishes (success or error), `_on_download_complete()` decrements the active count and tries to schedule the next pending download.

### Queue Behavior

Downloads that exceed the concurrent limit are held in `_pending_queue` (a Python list, FIFO order). They appear with status `"queued"` in the API response. As active downloads complete, queued items are promoted automatically.

All queue operations are protected by `_queue_lock` (a `threading.Lock`) to prevent race conditions between the API thread and download threads.

## Download State

### In-Memory State Dict

Download progress is tracked in `_download_state`, a module-level dict keyed by filename:

```python
_download_state = {
    "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors": {
        "status": "downloading",   # "queued" | "downloading" | "done" | "error"
        "bytes": 5_368_709_120,     # bytes written so far
        "total": 13_300_000_000,    # Content-Length from server (0 if unknown)
        "speed": 125_000_000.0,     # bytes/second (rolling estimate)
        "error": None,              # error message string, or None
        "_last_bytes": 5_100_000_000,  # internal: bytes at last speed sample
        "_last_time": 1711234567.89,   # internal: time of last speed sample
    }
}
```

Fields prefixed with `_` are internal and stripped by `_clean_state()` before being sent to the frontend.

### State Lifecycle

```
(not in dict)  ──→  "queued"  ──→  "downloading"  ──→  "done"
                                        │
                                        └──→  "error"
```

1. **Not in dict:** model has never been downloaded, or state was cleared after deletion
2. **Queued:** `_enqueue_download()` was called, waiting for a download slot
3. **Downloading:** thread is actively downloading, `bytes` and `speed` update in real time
4. **Done:** download completed successfully, file renamed from `.tmp` to final name
5. **Error:** download failed, `.tmp` file cleaned up, `error` field contains the reason

### State Persistence

Download state is **in-memory only**. If the backend restarts, all state is lost -- queued and in-progress downloads are forgotten. Partially downloaded `.tmp` files are left on disk but are not resumed. This is a known limitation; SQLite-backed state is planned for a future release.

## Download Flow (Detail)

### 1. Enqueue

When the user clicks download on a model card, the frontend calls:

```
POST /api/admin/models/download/{filename}
```

The endpoint:

1. Calls `_reload_models()` to get fresh catalog data
2. Finds the model entry by filename using `_find_model()`
3. Checks if the model is already downloading or queued -- if so, returns current status
4. Calls `_enqueue_download(model)` which sets state to `"queued"` and appends to `_pending_queue`
5. `_schedule_downloads()` immediately tries to start the download if a slot is available

### 2. URL Construction

`_get_download_url(model)` constructs the URL from catalog fields:

- If `civitai_version_id` is present: `https://civitai.com/api/download/models/{id}`
- If `hf_repo` and `hf_file` are present: `https://huggingface.co/{repo}/resolve/main/{file}`
- Otherwise: falls back to a legacy `url` field (not used in current catalogs)

### 3. Auth Injection

`_inject_auth(url)` adds authentication without modifying the catalog:

- **HuggingFace:** adds `Authorization: Bearer {HF_TOKEN}` header (if `HF_TOKEN` env var is set)
- **CivitAI:** appends `?token={CIVITAI_API_KEY}` query parameter (if `CIVITAI_API_KEY` env var is set)

Returns a tuple of `(modified_url, headers_dict)`.

### 4. Streaming Download

`_do_download(item)` runs in a thread pool thread:

1. Determines the destination directory: `ComfyUI/models/{dest}/` (or `STUDIO_DIR/llm/models/` for LLM models)
2. Creates the directory if it does not exist (`mkdir -p`)
3. Opens a streaming `requests.get` with 60-second timeout and redirect following
4. Reads `Content-Length` header to set `total` bytes
5. Writes data in **8 MB chunks** to a `.tmp` file
6. Updates `bytes` in `_download_state` after every chunk
7. Recalculates `speed` approximately every 1 second using a rolling window: `(current_bytes - last_sample_bytes) / elapsed_seconds`
8. On success: atomically renames `.tmp` to final filename, sets status to `"done"`
9. On error: deletes the `.tmp` file, sets status to `"error"` with the exception message

### 5. Events

The download system emits events through the EventBus:

| Event | When | Severity |
|-------|------|----------|
| `model.download.completed` | Download finished successfully | `success` |
| `model.download.failed` | Download failed with an error | `error` |

These events appear in the activity panel on all pages and are logged to `events.jsonl`.

## Batch Download

The batch download endpoint accepts multiple filenames at once:

```
POST /api/admin/models/download-batch
Content-Type: application/json

{
  "filenames": [
    "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
    "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
    "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
  ]
}
```

Response:

```json
{
  "queued": ["wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors", ...],
  "skipped": []
}
```

Models are skipped if they are not found in the catalog or are already downloading/queued. Each successfully queued model goes through the same `_enqueue_download()` path as individual downloads.

## Progress Monitoring

### SSE Endpoint

The Models page subscribes to a Server-Sent Events stream for real-time download progress:

```
GET /api/admin/models/status
```

This returns an infinite SSE stream that emits a JSON payload every second:

```json
{
  "downloads": {
    "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors": {
      "status": "downloading",
      "bytes": 5368709120,
      "total": 13300000000,
      "speed": 125000000.0,
      "error": null
    }
  },
  "timestamp": 1711234567.89
}
```

The frontend uses this to render progress bars, speed indicators, and status badges on model cards.

### Catalog List Response

The main `GET /api/admin/models` endpoint also includes download state merged into each model entry. The response stats object provides aggregate information:

| Stat | Description |
|------|-------------|
| `queued_count` | Number of models waiting to download |
| `downloading_count` | Number of active downloads |
| `global_speed` | Combined download speed across all active downloads (bytes/sec) |
| `present_count` | Number of models found on disk |
| `total_count` | Total models in catalog |
| `models_bytes` | Total disk space used by present models |
| `free_bytes` | Estimated free space on the volume |

## Model Deletion

When a model is deleted via `DELETE /api/admin/models/{filename}`:

1. The file is removed from disk (`ComfyUI/models/{dest}/{filename}`)
2. If the model has a download state of `"error"` or `"done"`, the state entry is cleared
3. Active downloads or queued downloads are **not** cancelled -- the state remains
4. A `model.deleted` event is emitted

The model remains in the catalog after deletion. It simply shows as `"missing"` status and can be re-downloaded.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_CONCURRENT_DOWNLOADS` | `3` | Maximum simultaneous downloads |
| `HF_TOKEN` | `""` | HuggingFace access token for gated models |
| `CIVITAI_API_KEY` | `""` | CivitAI API key for model downloads and metadata |
