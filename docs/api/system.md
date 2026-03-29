# System API

Endpoints for health checks, system status, updates, telemetry, and settings.

---

## GET /api/health

Public health check endpoint. No authentication required.

**Auth:** None

**Response:** `200 OK`

```json
{
  "status": "ok"
}
```

```bash
curl https://your-pod.runpod.io/api/health
```

---

## GET /api/admin/system/status

Dashboard data including component versions, ComfyUI status, node count, and disk usage.

**Auth:** Required

**Response:** `200 OK`

```json
{
  "app_version": "20.4.2",
  "date": "2026-03-30 10:00",
  "repo_url": "https://github.com/diego-devita/comfyui-studio.git",
  "runtime_version": 3,
  "min_runtime": 0,
  "components": {
    "runtime": {
      "version": 3,
      "date": "2026-03-28 14:00",
      "status": "Docker image v3",
      "updatable": false
    },
    "backend": {
      "version": "20.4.2",
      "date": "2026-03-30 10:00",
      "status": "running"
    },
    "frontend": {
      "version": "20.2.0",
      "date": "2026-03-29 15:00",
      "status": "loaded"
    },
    "models": {
      "version": 28,
      "date": "2026-03-29 12:00",
      "status": "126 models",
      "count": 126,
      "present": 15
    },
    "loras": {
      "version": 5,
      "date": "2026-03-28 10:00",
      "status": "8 loras"
    },
    "llm_models": {
      "version": 3,
      "date": "2026-03-21 08:00",
      "status": "3 llm models"
    },
    "workflows": {
      "version": 44,
      "date": "2026-03-29 17:00",
      "status": "12 workflows",
      "count": 12
    }
  },
  "comfyui": {
    "status": "running"
  },
  "nodes": {
    "total_packages": 38
  },
  "disk": {
    "total_bytes": 107374182400,
    "used_bytes": 53687091200,
    "free_bytes": 53687091200
  },
  "database": {
    "tables": {
      "jobs": 150,
      "events": 500,
      "settings": 5,
      "saved_prompts": 3
    },
    "browser_url": null
  },
  "telegram_bot": {
    "running": true,
    "name": "MyStudioBot"
  }
}
```

| Field | Description |
|-------|-------------|
| `comfyui.status` | `"running"`, `"error"`, or `"unreachable"` |
| `disk.total_bytes` | Network volume size from RunPod API (0 if unavailable) |
| `database.tables` | Row counts for each SQLite table |
| `database.browser_url` | URL to the database browser (only in DEV_MODE) |
| `telegram_bot.running` | Whether the Telegram bot token is configured |
| `telegram_bot.name` | Telegram bot display name |

```bash
curl https://your-pod.runpod.io/api/admin/system/status \
  -H "X-API-Key: your-api-key"
```

---

## GET /api/admin/system/remote-version

Fetch the remote `version.json` from the git repository and compare with the local version. This performs a `git fetch` in the `.repo/` staging directory.

**Auth:** Required

**Response:** `200 OK`

```json
{
  "remote": {
    "app_version": "12.3.0",
    "min_runtime": 0,
    "components": {
      "backend": {"version": "12.3.0", "date": "2026-03-25 10:00"},
      "frontend": {"version": "12.0.3", "date": "2026-03-25 10:00"}
    }
  },
  "local": {
    "app_version": "12.2.0",
    "min_runtime": 0,
    "components": {
      "backend": {"version": "12.2.0", "date": "2026-03-24 09:56"},
      "frontend": {"version": "12.0.2", "date": "2026-03-22 11:30"}
    }
  }
}
```

**Error response:** `500 Internal Server Error`

```json
{
  "detail": "Cannot fetch remote version"
}
```

```bash
curl https://your-pod.runpod.io/api/admin/system/remote-version \
  -H "X-API-Key: your-api-key"
```

---

## POST /api/admin/system/update

Perform a git-based update. Fetches the latest code from the remote repository and selectively deploys changed components.

**Auth:** Required

**Request body:**

```json
{
  "skip_components": ["models", "loras"]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `skip_components` | string[] | No | Component names to skip during update |

Valid component names: `backend`, `frontend`, `models`, `loras`, `llm_models`, `workflows`. The `runtime` component is always skipped (requires a new Docker image).

**Response (updates applied):** `200 OK`

```json
{
  "updated": ["backend", "frontend", "workflows"],
  "restart_needed": true,
  "message": "Updated: backend, frontend, workflows",
  "debug": {
    "local_version_json": { "...": "..." },
    "remote_version_json": { "...": "..." }
  }
}
```

**Response (already up to date):** `200 OK`

```json
{
  "updated": [],
  "restart_needed": false,
  "message": "Everything up to date",
  "debug": {
    "local_version_json": { "...": "..." },
    "remote_version_json": { "...": "..." }
  }
}
```

**Response (runtime blocked):** `200 OK`

```json
{
  "updated": [],
  "restart_needed": false,
  "blocked": true,
  "message": "Update requires Docker image runtime v3 (you have v2)",
  "remote_min_runtime": 3,
  "local_runtime": 2
}
```

When `restart_needed` is `true`, the backend will restart itself after a 1-second delay by spawning a new uvicorn process via `subprocess.Popen` and calling `os._exit(0)`. The frontend should expect the connection to drop and auto-reconnect.

```bash
# Update all components
curl -X POST https://your-pod.runpod.io/api/admin/system/update \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{}'

# Update but skip models and loras catalogs
curl -X POST https://your-pod.runpod.io/api/admin/system/update \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"skip_components": ["models", "loras"]}'
```

---

## GET /api/admin/telemetry

Returns real-time GPU, CPU, RAM, and disk usage metrics.

**Auth:** Required

**Response:** `200 OK`

```json
{
  "gpu": {
    "name": "NVIDIA RTX 4090",
    "vram_total": 25769803776,
    "vram_used": 8589934592,
    "vram_percent": 33.3,
    "util_percent": 85,
    "temp_c": 72
  },
  "cpu_percent": 45.2,
  "ram_total": 64424509440,
  "ram_used": 32212254720,
  "ram_percent": 50.0,
  "disk_total": 107374182400,
  "disk_used": 53687091200,
  "disk_percent": 50.0
}
```

| Field | Description |
|-------|-------------|
| `gpu` | `null` if GPU info unavailable |
| `gpu.vram_total` / `vram_used` | Bytes |
| `gpu.util_percent` | GPU utilization from `nvidia-smi` |
| `gpu.temp_c` | GPU temperature in Celsius |
| `cpu_percent` | Load average divided by CPU count |
| `ram_total` / `ram_used` | Bytes, from cgroup limits (pod-accurate) |
| `disk_total` / `disk_used` | Bytes, from RunPod volume API + `du` (cached 60s) |

```bash
curl https://your-pod.runpod.io/api/admin/telemetry \
  -H "X-API-Key: your-api-key"
```

---

## GET /api/admin/settings

Get current application settings.

**Auth:** Required

**Response:** `200 OK`

```json
{
  "max_concurrent": 3
}
```

| Field | Description |
|-------|-------------|
| `max_concurrent` | Maximum number of simultaneous downloads |

```bash
curl https://your-pod.runpod.io/api/admin/settings \
  -H "X-API-Key: your-api-key"
```

---

## PUT /api/admin/settings

Update application settings.

**Auth:** Required

**Request body:**

```json
{
  "max_concurrent": 5
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `max_concurrent` | integer | No | Max simultaneous downloads, clamped to 1-10 |

**Response:** `200 OK`

```json
{
  "max_concurrent": 5
}
```

```bash
curl -X PUT https://your-pod.runpod.io/api/admin/settings \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"max_concurrent": 5}'
```

---

## GET /api/admin/system/uptime

Get the backend start time and uptime.

**Auth:** Required

**Response:** `200 OK`

```json
{
  "started_at": "2026-03-30 14:30:00",
  "uptime_seconds": 3600
}
```

| Field | Description |
|-------|-------------|
| `started_at` | Backend start time in Italian timezone (Europe/Rome) |
| `uptime_seconds` | Seconds since the backend started |

```bash
curl https://your-pod.runpod.io/api/admin/system/uptime \
  -H "X-API-Key: your-api-key"
```

---

## POST /api/admin/system/restart

Restart the uvicorn backend process. Flushes SQLite databases (WAL checkpoint) before restarting.

**Auth:** Required

**Response:** `200 OK`

```json
{
  "message": "Restarting..."
}
```

After responding, the backend spawns a new uvicorn process and exits. The connection will drop; clients should auto-reconnect after ~2 seconds.

```bash
curl -X POST https://your-pod.runpod.io/api/admin/system/restart \
  -H "X-API-Key: your-api-key"
```

---

## GET /api/admin/system/chrome-extension

Download the Chrome extension as a ZIP file.

**Auth:** Required

**Response:** `200 OK` with `application/zip` content type and `Content-Disposition: attachment` header.

The ZIP contains the extension source files from `chrome-extension/src/` packaged for loading as an unpacked Chrome extension.

**Error:** `404 Not Found` if the chrome-extension directory does not exist.

```bash
curl -o extension.zip https://your-pod.runpod.io/api/admin/system/chrome-extension \
  -H "X-API-Key: your-api-key"
```

---

## GET /api/admin/settings/env

List environment variables relevant to the application, grouped by category. Sensitive values are masked.

**Auth:** Required

**Response:** `200 OK`

```json
{
  "groups": [
    {
      "id": "auth",
      "label": "Authentication & API Tokens",
      "vars": [
        {
          "key": "API_KEY",
          "value": "chan***geme",
          "sensitive": true,
          "set": true,
          "default": "changeme",
          "description": "Web UI password and X-API-Key header",
          "editable": true
        }
      ]
    }
  ]
}
```

| Field | Description |
|-------|-------------|
| `value` | Masked (first 4 + `***` + last 4) if `sensitive` is true |
| `sensitive` | Whether the value is a secret |
| `set` | Whether the env var has a non-empty value |
| `editable` | Whether this variable can be changed at runtime via `PUT /api/admin/settings/env` |
| `default` | Default value |
| `description` | Human-readable description |

Variables are organized into groups: authentication, configurable, read-only, and RunPod-specific (only shown on RunPod).

Editable variables: `API_KEY`, `CIVITAI_API_KEY`, `HF_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_NAME`.

```bash
curl https://your-pod.runpod.io/api/admin/settings/env \
  -H "X-API-Key: your-api-key"
```

---

## PUT /api/admin/settings/env

Update an editable environment variable at runtime. The value is saved to both `os.environ` and the SQLite database.

**Auth:** Required

**Request body:**

```json
{
  "key": "CIVITAI_API_KEY",
  "value": "your-new-key"
}
```

**Response:** `200 OK`

```json
{
  "key": "CIVITAI_API_KEY",
  "value": "your-new-key"
}
```

**Error:** `400 Bad Request` if the variable is not editable.

```bash
curl -X PUT https://your-pod.runpod.io/api/admin/settings/env \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"key": "CIVITAI_API_KEY", "value": "your-new-key"}'
```

---

## POST /api/admin/settings/reveal

Reveal the full unmasked values of all sensitive environment variables. Requires the API key as a second authentication factor.

**Auth:** Required

**Request body:**

```json
{
  "api_key": "your-api-key"
}
```

**Response:** `200 OK`

```json
{
  "API_KEY": "your-full-api-key",
  "CIVITAI_API_KEY": "your-full-civitai-key",
  "HF_TOKEN": "your-full-hf-token"
}
```

**Error:** `403 Forbidden` if the provided API key does not match.

```bash
curl -X POST https://your-pod.runpod.io/api/admin/settings/reveal \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"api_key": "your-api-key"}'
```
