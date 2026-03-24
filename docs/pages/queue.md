# Job Queue

The real-time job monitor at `/admin/queue`. Shows active jobs (running and queued) with live progress updates via WebSocket.

## Layout

1. **Header** -- page title with LIVE indicator (green dot + "LIVE" text + progress bar)
2. **Telemetry gauges** -- GPU, VRAM, RAM, CPU, Disk (same as Home page, always visible)
3. **Current Job panel** -- detailed progress for the running job
4. **Job list** -- cards for all jobs in the queue

## Real-Time Updates

The Queue page is WebSocket-primary. It connects to:

```
ws://host/api/run/ws
```

The WebSocket carries two types of data:

- **Text frames** -- JSON progress state objects (pushed every 150ms when state changes) and EventBus event objects
- **Binary frames** -- JPEG or PNG preview images from ComfyUI's sampler output

The LIVE indicator in the header shows connection status: green dot when the WebSocket is connected. A progress bar beneath the indicator shows the polling cycle for the fallback mechanism.

### Fallback Polling

The job card list is also refreshed via polling as a fallback. The LIVE bar counts down and triggers a `GET /api/admin/queue` call to refresh the card list. WebSocket data is preferred for the progress panel.

## Current Job Panel

When a job is running, the progress panel shows:

### Progress Information

- **Current node** -- which ComfyUI node is being processed (e.g., "KSampler", "VAEDecode")
- **Progress bar** -- percentage complete based on effective node count
- **Percentage text** -- e.g., "67%"
- **Step detail** -- for sampler nodes: "Step 14/20"
- **ETA** -- estimated time remaining (rolling average of last 10 steps)
- **Step rate** -- iterations per second (e.g., "2.3 it/s")
- **Elapsed time** -- time since job started
- **Job ID** -- truncated prompt_id

The progress bar uses an indeterminate animation (sliding gradient) when the job is running but no step progress is available yet (e.g., during model loading).

### Preview Panel

An expandable section toggled by clicking "Preview":

- **Live sampler output** -- the latest preview image from ComfyUI, updated in real-time from binary WebSocket frames. The frontend detects JPEG (starts with `\xff\xd8`) or PNG (starts with `\x89PNG`) headers and renders them as blob URLs.
- **Node output strip** -- a horizontal scrollable strip of thumbnails showing outputs from completed nodes, with labels identifying which node produced each image.

### Progress Tracking Details

The backend's WS listener thread (`runner.py`) captures ComfyUI WebSocket messages and maintains a progress state per prompt_id:

- `execution_start` -- marks job as running, creates `.incomplete` marker in output directory
- `execution_cached` -- tracks cached nodes, subtracts them from the effective total for accurate percentages
- `executing {node}` -- increments node progress, excludes "instant" node types (routing nodes, primitives, math) that execute in microseconds
- `progress` -- step/total within a sampler node, used for ETA calculation
- `executed` -- captures node output references
- Binary frames -- JPEG/PNG preview images forwarded to all connected WebSocket clients

When the job is idle (no running job), the panel shows "No jobs running" text.

## Job Cards

Below the progress panel, a list of job cards for all queued and running jobs:

### Card Layout

Each card is a 3-column grid:

- **Thumbnail** -- output preview (if available), input image, or a placeholder icon
- **Info** -- workflow name, queued timestamp, prompt excerpt, prompt_id
- **Status badge** -- "running" (with pulse animation) or "queued"

Running jobs have a left accent border (yellow/green). Jobs are sorted: running first, then queued by time.

### Card Actions

Clicking a job card opens a detail overlay showing the full job record: all parameters, timestamps, seed, workflow ID, and output directory.

## Empty State

When no jobs are in the queue, the page shows "No jobs in queue" text.

## Related Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/admin/queue` | GET | List active jobs |
| `/api/run/ws` | WebSocket | Real-time progress + preview |
| `/api/admin/telemetry` | GET | Hardware telemetry for gauges |
