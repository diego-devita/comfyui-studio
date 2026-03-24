# WebSocket API

Real-time progress updates, preview frames, and event notifications are delivered via a single WebSocket endpoint.

---

## WS /api/run/ws

WebSocket endpoint for real-time job progress, preview images, and event notifications. Used by the Queue page for live progress and the Activity Panel on all pages for live events.

### Authentication

The WebSocket verifies the session cookie before accepting the connection. The `SameSite=Strict` cookie attribute prevents Cross-Site WebSocket Hijacking at the browser level.

If authentication fails, the connection is closed immediately with code `4001` and reason `"Not authenticated"`.

### Connection

```javascript
const ws = new WebSocket("wss://your-pod.runpod.io/api/run/ws");

ws.onopen = () => console.log("Connected");
ws.onclose = () => {
  // Auto-reconnect after 2 seconds
  setTimeout(() => connect(), 2000);
};
```

The server pushes data to all connected clients. There is no request/response pattern -- the client only receives messages.

### Message Types

The WebSocket sends three types of messages:

#### 1. Progress State (Text)

JSON object with execution progress for an active job. Sent every 150ms when the state changes.

```json
{
  "prompt_id": "abc12345-6789-0def-ghij-klmnopqrstuv",
  "status": "running",
  "workflow_name": "WAN 2.1 I2V 14B",
  "workflow_id": "wan-i2v-14b",
  "node_id": "10",
  "node_title": "KSampler",
  "node_type": "KSampler",
  "step": 15,
  "total_steps": 30,
  "nodes_done": 3,
  "total_nodes": 8,
  "effective_total": 6,
  "cached_count": 2,
  "percent": 45,
  "eta_seconds": 25,
  "step_rate": 1.85,
  "preview_seq": 3,
  "node_outputs": {
    "5": {
      "node_title": "VHS_VideoCombine",
      "node_type": "VHS_VideoCombine",
      "items": [
        {
          "filename": "intermediate_00001.mp4",
          "subfolder": "20260324_143052_a1b2c3/intermediate",
          "type": "output",
          "media": "video"
        }
      ]
    }
  }
}
```

| Field | Description |
|-------|-------------|
| `prompt_id` | ComfyUI prompt ID identifying the job |
| `status` | `"queued"` or `"running"` |
| `workflow_name` / `workflow_id` | The workflow being executed |
| `node_id` / `node_title` / `node_type` | Currently executing node |
| `step` / `total_steps` | Step progress within the current node |
| `nodes_done` / `effective_total` | Node-level progress |
| `cached_count` | Nodes that were cached (excluded from effective_total) |
| `percent` | Overall progress 0-99 |
| `eta_seconds` | Estimated time remaining (current node + remaining nodes) |
| `step_rate` | Steps per second (rolling 10-step average) |
| `preview_seq` | Preview image sequence number (increments with each new preview) |
| `node_outputs` | Map of node ID to output data produced so far |

To distinguish progress messages from event messages, check for the `prompt_id` field (present only in progress messages).

#### 2. Event Objects (Text)

JSON objects from the EventBus. Same format as `GET /api/admin/events` responses.

```json
{
  "id": "evt_a1b2c3d4",
  "type": "job.completed",
  "timestamp": "2026-03-24T14:33:15",
  "severity": "success",
  "message": "Job completed in 142s",
  "data": {
    "prompt_id": "abc12345-...",
    "workflow_id": "wan-i2v-14b",
    "duration": 142
  }
}
```

To distinguish event messages from progress messages, check for the `type` field (present only in event messages).

#### 3. Preview Frames (Binary)

Raw JPEG or PNG image data from ComfyUI during generation. These are live preview frames showing the image being generated.

Detect the image format by magic bytes:
- **JPEG**: starts with `FF D8` (hex)
- **PNG**: starts with `89 50 4E 47` (hex `\x89PNG`)

```javascript
ws.onmessage = (event) => {
  if (event.data instanceof Blob) {
    // Binary: preview frame (JPEG or PNG)
    const url = URL.createObjectURL(event.data);
    previewImage.src = url;
  } else {
    // Text: parse as JSON
    const msg = JSON.parse(event.data);
    if (msg.prompt_id) {
      // Progress state
      updateProgressBar(msg);
    } else if (msg.type) {
      // Event from EventBus
      showActivityEvent(msg);
    }
  }
};
```

### Update Frequency

- **Progress state**: checked every 150ms, only sent when the state has changed (compared by hash)
- **Events**: sent as they occur (emitted through EventBus)
- **Preview frames**: sent as they arrive from ComfyUI (during sampler execution)

### Multiple Jobs

The WebSocket sends progress for all active jobs. If multiple jobs are running concurrently, the client receives progress states for each one, identified by their `prompt_id`.

### Connection Lifecycle

1. Client connects to `wss://host/api/run/ws`
2. Server verifies session cookie
3. If valid, server accepts the connection
4. Server begins pushing progress, events, and previews
5. Client should implement auto-reconnect on close with a 2-second delay
6. The server does not send pings -- connection health is maintained by the regular data flow

### Usage Pattern by Page

| Page | Usage |
|------|-------|
| Queue (`/admin/queue`) | Primary progress source. Poll `GET /api/admin/queue` only for card list refresh. |
| All pages (Activity Panel) | Live event notifications via the same WebSocket connection. |
| Runner (`/run/<id>`) | Progress during workflow execution. |

### Curl Example

WebSocket connections cannot be established with basic curl. Use `websocat` or a similar tool:

```bash
# Using websocat (install: cargo install websocat)
websocat "wss://your-pod.runpod.io/api/run/ws" \
  --header "Cookie: session=<your-session-cookie>"
```
