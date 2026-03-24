# Assets API

Endpoints for managing input and output files. Input files are stored in ComfyUI's input directory. Output files are organized per job in `STUDIO_DIR/assets/output/`.

---

## POST /api/admin/assets/upload-inputs

Upload one or more images to ComfyUI's input directory. Files are proxied to ComfyUI's `/upload/image` endpoint with unique filenames.

**Auth:** Required

**Request:** Multipart form data with one or more `files` fields.

**Response:** `200 OK`

```json
{
  "uploaded": [
    "20260324_143052_a1b2c3_photo1.png",
    "20260324_143052_d4e5f6_photo2.jpg"
  ],
  "errors": []
}
```

If some uploads fail:

```json
{
  "uploaded": ["20260324_143052_a1b2c3_photo1.png"],
  "errors": ["photo2.jpg: Upload failed: connection timeout"]
}
```

An `assets.uploaded` event is emitted when files are uploaded successfully.

```bash
# Upload a single file
curl -X POST https://your-pod.runpod.io/api/admin/assets/upload-inputs \
  -H "X-API-Key: your-api-key" \
  -F "files=@photo1.png"

# Upload multiple files
curl -X POST https://your-pod.runpod.io/api/admin/assets/upload-inputs \
  -H "X-API-Key: your-api-key" \
  -F "files=@photo1.png" \
  -F "files=@photo2.jpg"
```

---

## GET /api/admin/assets/{asset_type}

List files in the input or output directory. For outputs, files are organized into studio job groups with thumbnails and media type classification.

**Auth:** Required

**Path parameters:**

| Parameter | Description |
|-----------|-------------|
| `asset_type` | `"inputs"` or `"outputs"` |

**Response (inputs):** `200 OK`

```json
{
  "files": [
    {
      "filename": "20260324_143052_a1b2c3_photo.png",
      "path": "20260324_143052_a1b2c3_photo.png",
      "subfolder": "",
      "size": 2097152,
      "modified": 1711290652.0,
      "type": "image"
    }
  ],
  "studio_jobs": [],
  "total_size": 2097152
}
```

**Response (outputs):** `200 OK`

```json
{
  "files": [],
  "studio_jobs": [
    {
      "folder": "20260324_143052_a1b2c3",
      "folder_path": "20260324_143052_a1b2c3",
      "total_size": 52428800,
      "modified": 1711290852.0,
      "incomplete": false,
      "type": "studio_job",
      "video_count": 1,
      "image_count": 0,
      "preview_count": 3,
      "intermediate_count": 1,
      "video": {
        "filename": "final_00001.mp4",
        "subfolder": "20260324_143052_a1b2c3/final"
      },
      "thumbnail": {
        "filename": "preview_00001.png",
        "subfolder": "20260324_143052_a1b2c3/preview"
      },
      "previews": [
        {"filename": "preview_00001.png", "subfolder": "20260324_143052_a1b2c3/preview"}
      ],
      "intermediates": [
        {"filename": "intermediate_00001.mp4", "subfolder": "20260324_143052_a1b2c3/intermediate"}
      ]
    },
    {
      "folder": "20260324_130000_b2c3d4",
      "folder_path": "20260324_130000_b2c3d4",
      "total_size": 10485760,
      "modified": 1711280400.0,
      "incomplete": false,
      "type": "studio_gallery",
      "video_count": 0,
      "image_count": 4,
      "preview_count": 0,
      "intermediate_count": 0,
      "images": [
        {"filename": "final_00001.png", "subfolder": "20260324_130000_b2c3d4/final"},
        {"filename": "final_00002.png", "subfolder": "20260324_130000_b2c3d4/final"}
      ],
      "thumbnail": {
        "filename": "final_00001.png",
        "subfolder": "20260324_130000_b2c3d4/final"
      }
    }
  ],
  "total_size": 62914560
}
```

| Field | Description |
|-------|-------------|
| `files` | Flat list of individual files (sorted by modification time, newest first) |
| `studio_jobs` | Output folders grouped as jobs (only for `outputs`) |
| `studio_jobs[].type` | `"studio_job"` (has video) or `"studio_gallery"` (images only) |
| `studio_jobs[].incomplete` | `true` if the `.incomplete` marker file exists (job still running) |
| `studio_jobs[].video` | Primary video file info (for `studio_job` type) |
| `studio_jobs[].images` | Image file list (for `studio_gallery` type) |
| `studio_jobs[].thumbnail` | Best thumbnail: preview > image > null |
| `total_size` | Total bytes of all files listed |

Supported file types: `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp` (images), `.mp4`, `.webm`, `.mov`, `.avi` (videos). Hidden files (starting with `.`) are excluded.

**Error response:** `400 Bad Request`

```json
{
  "detail": "Invalid asset type. Use 'inputs' or 'outputs'."
}
```

```bash
# List input files
curl https://your-pod.runpod.io/api/admin/assets/inputs \
  -H "X-API-Key: your-api-key"

# List output files
curl https://your-pod.runpod.io/api/admin/assets/outputs \
  -H "X-API-Key: your-api-key"
```

---

## GET /api/admin/outputs-zip

Download the entire output directory as a ZIP archive.

**Auth:** Required

**Response:** `200 OK`

Returns a streamed ZIP file with:
- `Content-Type: application/zip`
- `Content-Disposition: attachment; filename="outputs_20260324_143052.zip"`

The ZIP preserves the directory structure under `assets/output/`.

**Error response:** `404 Not Found`

```json
{
  "detail": "Output directory not found"
}
```

```bash
curl https://your-pod.runpod.io/api/admin/outputs-zip \
  -H "X-API-Key: your-api-key" \
  -o outputs.zip
```

---

## POST /api/admin/assets/delete

Delete one or more files or folders from the input or output directory.

**Auth:** Required

**Request body:**

```json
{
  "type": "outputs",
  "files": [
    "20260324_143052_a1b2c3",
    "20260324_130000_b2c3d4/final/image_00001.png"
  ]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | `"inputs"` or `"outputs"` |
| `files` | string[] | Yes | List of relative paths to delete |

Path validation:
- Paths containing `..` or starting with `/` are rejected
- Top-level directories can be deleted (e.g., a job folder)
- Nested directory deletion is not allowed (only files within subdirectories)

**Response:** `200 OK`

```json
{
  "deleted": ["20260324_143052_a1b2c3"],
  "errors": ["nonexistent_file.png: not found"]
}
```

An `assets.deleted` event is emitted when files are deleted.

```bash
# Delete a job output folder
curl -X POST https://your-pod.runpod.io/api/admin/assets/delete \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"type": "outputs", "files": ["20260324_143052_a1b2c3"]}'

# Delete specific input files
curl -X POST https://your-pod.runpod.io/api/admin/assets/delete \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"type": "inputs", "files": ["photo1.png", "photo2.jpg"]}'
```
