# API Reference

ComfyUI Studio exposes a REST API on port 8000. All endpoints except `/api/health` and `/login` require authentication.

## Authentication

Two methods:

1. **Session cookie** — set by `POST /api/auth/login`, renewed on every request
2. **`X-API-Key` header** — for scripts and programmatic access

```bash
# Cookie-based (browser)
POST /api/auth/login {"api_key": "your-password"}

# Header-based (curl/scripts)
curl -H "X-API-Key: your-password" https://pod:8000/api/admin/models
```

## API Sections

- [Authentication](auth.md) — login, logout, session management
- [System](system.md) — status, update, telemetry, settings, events
- [Models](models.md) — model catalog, download, delete, import, metadata
- [LoRAs](loras.md) — LoRA catalog, compatible pairs
- [LLM](llm.md) — LLM models, server control, chat
- [Workflows](workflows.md) — workflow list, readiness, sync
- [Runner](runner.md) — execute, build, upload, status
- [Jobs](jobs.md) — queue, history, delete, retry, package
- [Assets](assets.md) — input/output file management
- [Events](events.md) — activity log
- [Nodes](nodes.md) — custom node management
- [WebSocket](websocket.md) — real-time progress and events

## Conventions

- All endpoints return JSON unless otherwise noted
- Dates use ISO 8601 format: `2026-03-24T15:30:00`
- Errors return `{"detail": "error message"}` with appropriate HTTP status
- `503` during maintenance mode (system updating)
- File uploads use `multipart/form-data`
- Streaming responses (chat, file download) noted per endpoint
