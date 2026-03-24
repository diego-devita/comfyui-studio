# Execution Flow

The complete sequence from clicking "Generate" to seeing the result.

## Step-by-Step

### 1. Form Submission

The user fills the form on the runner page and clicks **Generate** (or the multi-generate stepper sends N sequential requests).

The frontend sends:

```
POST /api/run/{workflow_id}/execute
Content-Type: multipart/form-data

Fields: all form values as key-value pairs
File: input image (if applicable)
```

### 2. Image Upload (if applicable)

If the workflow has an `image` type input and the user selected an image, it was already uploaded to ComfyUI when selected (not at form submission time):

```
POST /api/run/upload-image → ComfyUI POST /upload/image
```

The backend receives the filename from ComfyUI's response.

### 3. Build Workflow

The backend calls `_build_workflow()`:

**Static workflows:**
1. Load `workflow.json`
2. Scan all node inputs for `"{{variable}}"` patterns
3. Replace each with the corresponding form value, converting types (string→int, string→float, etc.)

**Dynamic workflows:**
1. Load manifest pipeline definition
2. For each block in order:
   - Load the block JSON from `blocks/`
   - Prefix all node IDs with `{block}_{instance}_`
   - Resolve imports (wire to previous block's exports)
   - Substitute `{{variables}}` with form values
3. Merge all nodes into one flat dict
4. Handle LoRA injection: if `lora_picker_dynamic` was used, insert a chain of `LoraLoader` nodes between the checkpoint and sampler
5. Handle resolution: extract `width` and `height` from `resolution_picker` and inject into `EmptyLatentImage`
6. Handle seed: resolve `-1` to a random integer

### 4. Patch Outputs

Before sending to ComfyUI, the backend patches ALL output nodes:

- `SaveImage` → prefix becomes `comfyui-studio/{jobid}/image`
- `VHS_VideoCombine` → prefix becomes `comfyui-studio/{jobid}/video`
- `PreviewImage` → prefix becomes `comfyui-studio/{jobid}/preview`
- Any `VHS_VideoCombine` with `save_output=false` → forced to `true`, prefix `intermediate`

### 5. Send to ComfyUI

```
POST http://localhost:8188/prompt
{
  "prompt": {assembled workflow dict},
  "client_id": "unique-client-id"
}
```

ComfyUI responds with a `prompt_id` that identifies this execution.

### 6. Save Job Record

The backend creates a job record:

```python
{
    "prompt_id": "abc123...",
    "workflow_id": "t2i-batch",
    "workflow_name": "Text to Image (Batch)",
    "status": "queued",
    "queued_at": "2026-03-24T15:30:00",
    "params": {form values},
    "seeds": {resolved seeds},
    "output_dir": "comfyui-studio/abc123...",
    "input_image": "uploaded_image.png",
    "output": null,
    "error": null
}
```

This is saved to the SQLite database. The in-memory progress tracker is also initialized.

### 7. Start WebSocket Listener

A background thread connects to ComfyUI's WebSocket:

```
ws://localhost:8188/ws?clientId={client_id}
```

This thread captures ALL messages from ComfyUI for this execution:

| Message Type | Action |
|-------------|--------|
| `execution_start` | Update status to "running", create `.incomplete` marker, record `started_at` |
| `execution_cached` | Track cached node IDs, adjust `effective_total` (exclude cached from progress) |
| `executing {node}` | Update progress: which node, nodes_done count. Exclude "instant" types (loaders, encoders) from progress percentage |
| `progress {value, max}` | Step-level progress within a node. Calculate ETA from rolling 10-step average. Calculate step rate (it/s) |
| `executed {node, output}` | Track node outputs (images, videos). Store in `node_outputs` for preview |
| Binary frame (JPEG/PNG) | Preview image. Detect by magic bytes: FF D8 = JPEG, 89 50 = PNG. Forward to connected WS clients |
| `execution_error` | Update status to "error", save error message with node title |

### 8. Progress Broadcast

The Studio WebSocket endpoint (`/api/run/ws`) runs a loop every 150ms that pushes the current progress state to ALL connected browser clients:

```json
{
  "status": "running",
  "node_title": "KSampler",
  "step": 15,
  "total_steps": 20,
  "nodes_done": 3,
  "total_nodes": 5,
  "effective_total": 4,
  "percent": 75,
  "eta_seconds": 12.5,
  "step_rate": 1.6,
  "node_outputs": {}
}
```

Binary preview frames are forwarded directly.

### 9. Completion

When ComfyUI finishes:

1. The WS listener receives the final `executed` message
2. Status updated to "completed"
3. `finished_at` timestamp recorded
4. `duration` calculated (finished - started)
5. Best output selected (video preferred over image)
6. `.incomplete` marker removed from output directory
7. Job record saved to database
8. Event emitted: `job.completed`

### 10. Result Display

The frontend on the Queue page sees the progress reach 100% and the status change to "completed". The History page shows the completed job with:

- Thumbnail/preview of the output
- Duration
- Parameters used
- Seeds (for reproducibility)
- Links to output files

## Progress Calculation

### Effective Total

Not all nodes contribute meaningfully to progress. The system distinguishes:

- **Processing nodes** (KSampler, VAEDecode, VHS_VideoCombine, etc.) — counted in progress
- **Instant nodes** (CheckpointLoaderSimple, CLIPTextEncode, EmptyLatentImage, etc.) — excluded

`effective_total = total_nodes - cached_nodes - instant_nodes`

This gives a more accurate percentage. Without this adjustment, a 10-node workflow where 5 nodes are instant loaders would show 50% complete before any actual processing starts.

### ETA Calculation

ETA is calculated from the step-level progress of the current sampling node:

1. Track the last 10 step timestamps
2. Calculate average time per step
3. Remaining steps = total_steps - current_step
4. ETA = remaining_steps × average_step_time

The step rate (iterations/second) is also calculated and displayed.

## Error Handling

If ComfyUI sends an `execution_error` message:

1. Status set to "error"
2. Error message extracted (includes the node title that failed)
3. `.incomplete` marker removed
4. Job record saved with error
5. Event emitted: `job.failed`

If the WebSocket connection drops unexpectedly:

1. The listener thread exits
2. If the job was "running", it stays as "running" in the database
3. On next backend startup, the startup task marks all "running"/"queued" jobs as "stalled"
