# Outputs

How workflows declare their outputs, how the backend captures them, and where the files end up.

## Output Declaration

The manifest declares what the workflow produces:

```yaml
outputs:
  - id: video
    name: "Output Video"
    type: video
    node_id: "94"
```

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `id` | **Yes** | string | Identifier for the output. |
| `name` | **Yes** | string | Display name shown in the UI. |
| `type` | **Yes** | string | `"video"` or `"image"`. |
| `node_id` | No | string | **Static workflows only.** The ComfyUI node ID that produces the final output. |

For dynamic workflows, `node_id` is not needed — the assembler determines the output node from the last block's exports.

## Output Types

### `video`

The workflow produces a video file (typically MP4 via `VHS_VideoCombine`). The queue page shows a video player for preview. The history page links to the video file.

### `image`

The workflow produces one or more images (via `SaveImage`). With `batch_size > 1`, multiple images are produced in one run. The queue shows the last preview frame. The history page shows thumbnails.

## Output Directory Patching

Before sending **any** workflow (static or dynamic) to ComfyUI, the backend automatically patches all output nodes to write into the job's output directory. This ensures every generated file is organized by job.

### Patching Rules

The backend scans every node in the assembled workflow and applies these rules:

| Node Type | Original Behavior | Patched Behavior |
|-----------|-------------------|------------------|
| `VHS_VideoCombine` with `save_output: true` | Saves video to ComfyUI output dir | Saves to `comfyui-studio/{jobid}/video/` |
| `VHS_VideoCombine` with `save_output: false` | Saves to temp (no persistent file) | Forced to `save_output: true`, saves to `comfyui-studio/{jobid}/intermediate/` |
| `SaveImage` | Saves to ComfyUI output dir with generic prefix | Saves to `comfyui-studio/{jobid}/image/` |
| `PreviewImage` | Saves to temp | Saves to `comfyui-studio/{jobid}/preview/` |

### Why This Matters

Without patching:
- Videos and images scatter across ComfyUI's default output directory
- Temp files are lost on restart
- There's no way to associate outputs with the job that created them

With patching:
- Every file lands in `STUDIO_DIR/assets/output/comfyui-studio/{jobid}/`
- Subfolders separate video, image, preview, and intermediate outputs
- The Assets page can browse outputs by job
- The History page links directly to the job's outputs
- Cleanup (delete job) removes the entire directory

### The `.incomplete` Marker

When a job starts executing, the backend creates a file called `.incomplete` inside the job's output directory:

```
assets/output/comfyui-studio/{jobid}/.incomplete
```

This file is removed when the job completes (success or failure). The Assets page checks for this marker and shows an `.incomplete` badge on directories where generation is still in progress.

## Output Directory Structure

After a video generation job completes:

```
assets/output/comfyui-studio/abc123def456/
├── video/
│   └── output_00001.mp4          # Final video
├── intermediate/
│   └── intermediate_00001.mp4    # Intermediate pass (if multi-pass)
├── preview/
│   └── preview_00001.png         # Preview frame
└── image/
    └── (empty for video workflows)
```

After an image generation job with batch_size=4:

```
assets/output/comfyui-studio/abc123def456/
├── image/
│   ├── output_00001.png
│   ├── output_00002.png
│   ├── output_00003.png
│   └── output_00004.png
└── preview/
    └── preview_00001.png
```

## Best Output Selection

When a job completes, the backend selects the "best" output for the job record:

1. Look for video files in the `video/` subdirectory (not `intermediate/`)
2. If no video, look for images in the `image/` subdirectory
3. The first found file becomes `job.output` (shown in history)
4. Multiple images are stored in `job.outputs` (array)

This selection is used by the History page to show a thumbnail/preview without scanning the filesystem.
