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
  "app_version": "12.2.0",
  "date": "2026-03-24 09:56",
  "repo_url": "https://github.com/diego-devita/comfyui-studio.git",
  "runtime_version": 2,
  "min_runtime": 0,
  "components": {
    "runtime": {
      "version": 2,
      "date": "2026-03-20 14:00",
      "status": "Docker image v2",
      "updatable": false
    },
    "backend": {
      "version": "12.2.0",
      "date": "2026-03-24 09:56",
      "status": "running"
    },
    "frontend": {
      "version": "12.0.2",
      "date": "2026-03-22 11:30",
      "status": "loaded"
    },
    "models": {
      "version": 21,
      "date": "2026-03-23 15:00",
      "status": "85 models",
      "count": 85,
      "present": 12
    },
    "loras": {
      "version": 2,
      "date": "2026-03-20 10:00",
      "status": "15 loras"
    },
    "llm_models": {
      "version": 3,
      "date": "2026-03-21 08:00",
      "status": "5 llm models"
    },
    "workflows": {
      "version": 32,
      "date": "2026-03-24 09:00",
      "status": "12 workflows",
      "count": 12
    }
  },
  "comfyui": {
    "status": "running"
  },
  "nodes": {
    "total_packages": 28
  },
  "disk": {
    "total_bytes": 107374182400,
    "used_bytes": 53687091200,
    "free_bytes": 53687091200
  }
}
```

| Field | Description |
|-------|-------------|
| `comfyui.status` | `"running"`, `"error"`, or `"unreachable"` |
| `disk.total_bytes` | Network volume size from RunPod API (0 if unavailable) |

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

When `restart_needed` is `true`, the backend will restart itself via `os.execv` after a 1-second delay. The frontend should expect the connection to drop and auto-reconnect.

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

## GET /api/admin/settings/env

List environment variables relevant to the application. Sensitive values are masked.

**Auth:** Required

**Response:** `200 OK`

```json
[
  {
    "key": "API_KEY",
    "value": "chan***geme",
    "sensitive": true,
    "set": true
  },
  {
    "key": "CIVITAI_API_KEY",
    "value": "",
    "sensitive": true,
    "set": false
  },
  {
    "key": "COMFYUI_DIR",
    "value": "/workspace/ComfyUI",
    "sensitive": false,
    "set": true
  }
]
```

| Field | Description |
|-------|-------------|
| `value` | Masked (first 4 + `***` + last 4) if `sensitive` is true |
| `sensitive` | Whether the value is a secret |
| `set` | Whether the env var has a non-empty value |

Tracked environment variables: `API_KEY`, `CIVITAI_API_KEY`, `HF_TOKEN`, `RUNPOD_API_KEY`, `COMFYUI_DIR`, `COMFYUI_PORT`, `REPO_URL`, `MAX_CONCURRENT_DOWNLOADS`, `RUNPOD_POD_ID`, `RUNPOD_DC_ID`, `RUNPOD_VOLUME_ID`, `PUBLIC_KEY`.

```bash
curl https://your-pod.runpod.io/api/admin/settings/env \
  -H "X-API-Key: your-api-key"
```
