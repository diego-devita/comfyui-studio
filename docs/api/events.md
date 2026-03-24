# Events API

The EventBus is the central event system for ComfyUI Studio. Events are stored in a ring buffer (last 1000 in memory) and persisted to `STUDIO_DIR/events.jsonl` (with 5MB log rotation). Events are also pushed to WebSocket clients in real time.

---

## GET /api/admin/events

Query the event log.

**Auth:** Required

**Query parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `limit` | `100` | Maximum number of events to return |
| `types` | (all) | Comma-separated list of event types to filter |
| `severity` | (all) | Filter by severity level |

**Response:** `200 OK`

```json
[
  {
    "id": "evt_a1b2c3d4",
    "type": "system.backend.started",
    "timestamp": "2026-03-24T14:30:00",
    "severity": "info",
    "message": "Backend started",
    "data": {
      "version": "12.2.0"
    }
  },
  {
    "id": "evt_e5f6g7h8",
    "type": "job.completed",
    "timestamp": "2026-03-24T14:33:15",
    "severity": "success",
    "message": "Job completed in 142s",
    "data": {
      "prompt_id": "abc12345-...",
      "workflow_id": "wan-i2v-14b",
      "duration": 142
    }
  },
  {
    "id": "evt_i9j0k1l2",
    "type": "model.download.completed",
    "timestamp": "2026-03-24T14:25:00",
    "severity": "success",
    "message": "Downloaded: juggernautXL_v9.safetensors",
    "data": {
      "filename": "juggernautXL_v9.safetensors"
    }
  }
]
```

Events are returned newest-last (chronological order), limited to the most recent `limit` entries after filtering.

### Event object fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique event ID (format: `evt_<8-char-hex>`) |
| `type` | string | Dot-separated event type |
| `timestamp` | string | ISO 8601 timestamp in Italian timezone (Europe/Rome) |
| `severity` | string | `"info"`, `"success"`, `"warning"`, or `"error"` |
| `message` | string | Human-readable description |
| `data` | object | Event-specific payload |

### Event types

| Type | Severity | Description |
|------|----------|-------------|
| `system.backend.started` | info | Backend process started |
| `system.updated` | success | System update completed |
| `system.migration` | info | Data migration performed |
| `system.startup` | warning | Startup task (e.g., marking stalled jobs) |
| `job.queued` | info | Job submitted to ComfyUI |
| `job.started` | info | Job execution began |
| `job.completed` | success | Job finished successfully |
| `job.failed` | error | Job failed with error |
| `job.retried` | info | Job retried from a previous attempt |
| `job.deleted` | info | Job record and outputs deleted |
| `model.deleted` | info | Model file deleted from disk |
| `model.metadata.fetched` | success/info | Metadata fetched for a model |
| `model.metadata.failed` | error | Metadata fetch failed |
| `model.metadata.batch.completed` | success/warning | Batch metadata fetch finished |
| `llm.model.deleted` | info | LLM model file deleted |
| `assets.uploaded` | info | Input files uploaded |
| `assets.deleted` | info | Asset files deleted |

### Filtering examples

```bash
# Get last 50 events
curl "https://your-pod.runpod.io/api/admin/events?limit=50" \
  -H "X-API-Key: your-api-key"

# Get only job events
curl "https://your-pod.runpod.io/api/admin/events?types=job.completed,job.failed,job.started" \
  -H "X-API-Key: your-api-key"

# Get only errors
curl "https://your-pod.runpod.io/api/admin/events?severity=error" \
  -H "X-API-Key: your-api-key"

# Combine filters
curl "https://your-pod.runpod.io/api/admin/events?types=job.failed,model.metadata.failed&severity=error&limit=20" \
  -H "X-API-Key: your-api-key"
```

### Persistence

Events are appended to `STUDIO_DIR/events.jsonl` as JSONL (one JSON object per line). When the file exceeds 5MB, it is automatically rotated to keep only the most recent 1000 entries. On startup, events are loaded from this file into the in-memory ring buffer.
