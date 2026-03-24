# Home

The dashboard at `/home`. Provides a system overview, component version management, update controls, resource counts, and hardware telemetry.

## Layout

The page has four sections from top to bottom:

1. **Header** -- application name, version tag, "Check for Updates" button with last-updated timestamp
2. **Stat cards** -- counts for Models, LoRAs, LLM Models, Workflows, and Nodes
3. **Telemetry accordion** -- GPU, VRAM, RAM, CPU, and Disk gauges (collapsed by default)
4. **Component table** -- version, date, status, and update toggle for each component

## Data Loading

On page load, the frontend calls:

```
GET /api/admin/system/status
```

This single endpoint returns everything the dashboard needs:

- `app_version`, `date` -- displayed in the header
- `components` -- object with runtime, backend, frontend, models, loras, llm_models, workflows (each with version, date, status)
- `models` -- total count and present count
- `comfyui` -- running status
- `nodes` -- total custom node packages (derived from ComfyUI `/object_info`)
- `disk` -- total, used, and free bytes (from RunPod volume API + `du`)

The backend scans the model catalog and checks which files exist on disk to determine the present count. ComfyUI status is checked via its `/system_stats` endpoint.

## Stat Cards

Five cards displayed in a horizontal flex row:

| Card | Value | Subtitle | Link |
|------|-------|----------|------|
| Models | Total in catalog | N present | /admin/models |
| LoRAs | Total in catalog | N loras | /admin/loras |
| LLM Models | Total in catalog | N llm models | /admin/llm |
| Workflows | Total registered | N ready | /admin/workflows |
| Nodes | Package count | custom node packages | /admin/nodes |

Each card links to its management page via an arrow link at the bottom.

## Component Table

A table with columns: Component, Version, Date, Status, Update.

| Component | Version format | Status text |
|-----------|---------------|-------------|
| Runtime | `#N` (integer) | Docker image vN |
| Backend | Semver string | Running |
| Frontend | Semver string | Loaded |
| Models Catalog | `#N` (integer) | N models |
| LoRAs Catalog | `#N` (integer) | N loras |
| LLM Models | `#N` (integer) | N llm models |
| Workflows | `#N` (integer) | N workflows |

Status is shown with a colored dot: green for running/loaded/ok, orange for unknown states, red for errors.

The **Update** column contains toggle switches. Each toggle controls whether that component is included in the next update. By default, LoRAs and LLM Models are unchecked (since those catalogs rarely change and users may have local edits). Runtime has no toggle since it cannot be updated via git.

The Models, LoRAs, and LLM Models rows also have an eye icon that opens a catalog overlay showing the raw JSON data.

## Check for Updates

The "Check for Updates" button in the header triggers the update mechanism:

1. Reads which component toggles are unchecked and sends them as `skip_components`
2. Calls `POST /api/admin/system/update` with `{skip_components: [...]}`
3. While waiting, the button shows a spinner and "Checking..." text

### Possible outcomes

- **Updates found**: An overlay shows which components were updated. If backend was updated, the page shows "Restarting..." and polls `/api/admin/system/status` every 2 seconds until the backend comes back, then reloads the page.
- **No updates**: An overlay shows "Everything is up to date" for 5 seconds.
- **Auto-retry polling**: After "no updates," the button enters a polling mode. It shows a progress bar that fills over 15 seconds, then retries. A badge shows the attempt counter (e.g., "Stop 3/20"). Click the button again to stop polling.
- **Blocked**: If the remote requires a newer runtime version, an error overlay explains the user must pull a new Docker image.
- **Error**: Network or server errors show in a red overlay for 5 seconds.

The progress bar inside the button uses a CSS animation that fills from left to right over 15 seconds with a pulsing opacity effect.

## Telemetry

Collapsed by default behind a "Telemetry" toggle bar. Clicking it opens a panel with five circular gauge cards:

| Gauge | Data source | Sub-label |
|-------|------------|-----------|
| GPU Load | `nvidia-smi` utilization.gpu | GPU name and temperature |
| VRAM | ComfyUI `/system_stats` (vram_total - vram_free) | Used / Total in GB |
| System RAM | cgroup memory (`/sys/fs/cgroup/memory.current`) | Used / Total in GB |
| CPU | `/proc/loadavg` normalized by core count | "load" |
| Disk | RunPod volume API + cached `du` | Used / Total in GB |

When the accordion is open, the page polls `GET /api/admin/telemetry` every 3 seconds. Polling stops when the accordion is closed.

Each gauge is an SVG ring that fills proportionally. Colors change based on utilization: normal below 65%, yellow (warn) at 65-85%, red (critical) above 85%. A brief yellow flash on the panel background serves as a heartbeat indicator when fresh data arrives.

## System Info

Below the component table, two lines of system information:

- **ComfyUI status**: green dot + "Running on port 8188" with an external link icon that opens ComfyUI in a new tab (URL rewritten for RunPod proxy), or red dot + "Not running"
- **Disk**: "Used / Total -- Free free" in human-readable sizes

## Related Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/admin/system/status` | GET | Full system status |
| `/api/admin/system/update` | POST | Trigger update |
| `/api/admin/telemetry` | GET | Hardware telemetry |
