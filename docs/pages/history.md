# Job History

Past job records at `/admin/history`. Browse completed, failed, and stalled jobs with live auto-refresh, batch selection, retry, and export.

## Layout

1. **Header** -- page title with LIVE indicator
2. **Selection toolbar** -- select-all checkbox, selected count, "Delete selected" button
3. **Job list** -- cards for all past jobs, newest first

## Data Loading

```
GET /api/admin/history
```

Returns an array of job records sorted newest first. Each record includes:

- `prompt_id` -- unique job identifier
- `workflow_id`, `workflow_name` -- which workflow was run
- `status` -- `completed`, `error`, or `stalled`
- `queued_at`, `started_at`, `finished_at` -- timestamps
- `duration` -- elapsed seconds
- `params` -- the form parameters submitted (prompt, model, seed, etc.)
- `input_image` -- filename if an image was uploaded
- `output` -- best output file reference (for thumbnail)
- `outputs` -- array of all output file references
- `output_dir` -- subdirectory under `comfyui-studio/` in the output folder

## Live Auto-Refresh

The page uses the LIVE indicator system with a countdown bar. The page polls the history endpoint on each cycle. To avoid jarring full-page redraws:

1. The frontend tracks the list of `prompt_id` values from the last render
2. On each poll, it compares the new ID list with the previous one
3. If the lists match (same IDs in same order), no DOM update occurs
4. If they differ, the list is rebuilt

This means new jobs appearing or status changes trigger a smooth update, while idle polling causes zero visual disruption.

Events from the WebSocket (like `job.completed`) also trigger a refresh, so completed jobs appear in history almost instantly.

## Job Cards

Each card is a 4-column grid: checkbox, thumbnail, info, status.

### Checkbox

Completed, failed, and stalled jobs show a checkbox for batch selection. Running and queued jobs (which should not normally appear in history) show a placeholder.

### Thumbnail

- If the job produced image output, the first output image is shown as a 60x60 thumbnail. A count badge (e.g., "4") appears if multiple images were generated.
- If the job was image-to-video with an input image, that image is shown.
- Otherwise, a play icon placeholder is shown.

### Info Section

- **Workflow name** -- the display name of the workflow
- **Timestamps** -- "Q" (queued) and "S" (started) times, plus duration if available
- **Prompt ID** -- first 12 characters, shown in a muted bisque color
- **Prompt excerpt** -- first 80 characters of the positive prompt (or the first scene prompt for dynamic workflows)

### Status Badge

Colored pill badge:

- **completed** -- green
- **error** -- red
- **stalled** -- yellow

Failed and stalled jobs also show a **Retry** button that re-queues the job with the same parameters.

## Detail Overlay

Clicking a job card (not the checkbox) opens a full-screen overlay with complete job details:

### Fields Shown

- Job ID (with copy button)
- Workflow ID and name
- Output directory path
- Status
- Queued, Started, Finished timestamps
- Duration

### Parameters

All workflow parameters displayed in a table. Special handling for:

- **Prompts** -- shown with preserved whitespace and a copy button
- **Input image** -- filename with a hover preview (small popup image) and click to view fullscreen
- **Scenes** (for dynamic workflows) -- each scene's prompt, duration, and seed in a sub-table
- **Arrays and objects** -- rendered as formatted JSON

### Output

A "View in Assets" link opens the Assets page filtered to the job's output directory.

## Batch Operations

### Select All

The "Select all" checkbox in the toolbar toggles all visible job checkboxes. The selected count updates in real-time.

### Multi-Select

- **Click checkbox** -- toggles individual selection
- **Ctrl/Cmd+Click card** -- toggles selection without opening detail
- **Shift+Click** -- range-selects all cards between the last clicked and current

### Delete Selected

The "Delete selected" button (visible only when jobs are selected) triggers a confirm dialog:

> "Delete N job(s) and their output files? This cannot be undone."

On confirm, calls:

```
POST /api/admin/history/delete
{prompt_ids: ["id1", "id2", ...]}
```

This deletes both the job records and their output files from disk. The list refreshes after deletion.

## Retry

The Retry button on failed/stalled jobs calls the execute endpoint with the original workflow ID and parameters, creating a new job. After retry, the user is typically redirected or the queue page shows the new job.

## Related Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/admin/history` | GET | List past jobs |
| `/api/admin/history/delete` | POST | Batch delete jobs |
| `/api/admin/history/{prompt_id}` | GET | Single job detail |
| `/api/run/{workflow_id}/execute` | POST | Re-execute (retry) |
