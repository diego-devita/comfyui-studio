# ComfyUI Studio -- Backend

The backend is a FastAPI application split into 16 Python modules. It runs on port 8000 via uvicorn with a single worker. All modules live flat in `backend/` with no subdirectories and no circular imports.

---

## Module Overview

| Module | Lines | Purpose |
|--------|------:|---------|
| `main.py` | 26 | Entry point. Imports all modules, includes all routers. |
| `config.py` | 79 | App instance, environment variables, all path constants. |
| `auth.py` | 153 | Cookie-based auth, HMAC signing, AuthMiddleware, login/logout endpoints. |
| `events.py` | 173 | EventBus with ring buffer + disk persistence, WebSocket pusher, startup tasks. |
| `pages.py` | 85 | HTML page serve routes (`/home`, `/admin/*`, `/run/*`, `/static/*`). |
| `catalogs.py` | 241 | Catalog loaders (models, loras, LLM), static file resolver, version helper. |
| `download.py` | 184 | Thread pool download manager, state tracking, URL construction, auth injection. |
| `models_api.py` | 610 | Model + LoRA API: list, download, batch, delete, import, metadata, sync, compat. |
| `llm_api.py` | 199 | LLM API: model list, download, delete, server control, chat (streaming). |
| `llm_server.py` | 104 | llama-server subprocess manager (start, stop, config). |
| `workflows_api.py` | 184 | Workflow list with readiness check, sync from repo, install missing models. |
| `workflows.py` | 1808 | Workflow loading, manifest parsing, dynamic block assembly, API-to-UI conversion. |
| `runner.py` | 455 | Execution progress tracking, ComfyUI WebSocket listener, workflow builder, job persistence. |
| `runner_api.py` | 349 | Runner API: image upload, build, execute, WS status stream, result proxy. |
| `system_api.py` | 599 | System status, update mechanism, telemetry, settings, env vars, events endpoint. |
| `jobs_api.py` | 629 | Queue, history, retry, assets (input/output), nodes list/install, output download/zip. |
| **Total** | **5878** | |

---

## Dependency Graph

Arrows point from importer to imported module. There are no circular dependencies.

```
main.py
├── config          (app instance)
├── auth            (middleware registration)
├── events          (startup tasks)
├── pages           (page routes)
├── models_api      ─── router
├── llm_api         ─── router
├── workflows_api   ─── router
├── runner_api      ─── router
├── system_api      ─── router
└── jobs_api        ─── router

config.py           (no local imports — leaf module)

auth.py
└── config          (app, API_KEY, SESSION_SECRET_PATH)

events.py
└── config          (app, STUDIO_DIR)

pages.py
├── config          (app)
└── catalogs        (_www)

catalogs.py
└── config          (all catalog/version/www paths)

download.py
└── config          (MODELS_BASE, CIVITAI_API_KEY, HF_TOKEN)

models_api.py
├── config          (MODELS_BASE, MODELS_JSON, REPO_URL)
├── catalogs        (_models_data, _loras_data, _reload_models, _find_model, ...)
├── download        (_download_state, _enqueue_download, _clean_state, ...)
└── events          (_events)

llm_api.py
├── config          (LLM_MODELS_DIR, LLAMA_SERVER_PORT, LLAMA_SERVER_PATH)
├── catalogs        (_llm_models_data, _reload_models, _find_llm_model, ...)
├── download        (_download_state, _enqueue_download)
├── events          (_events)
└── llm_server      (_load_llm_config, _start_llama_server, _stop_llama_server, ...)

llm_server.py
└── config          (LLM_MODELS_DIR, LLM_CONFIG_PATH, LLAMA_SERVER_PATH, LLAMA_SERVER_PORT)

workflows_api.py
├── config          (COMFY_URL, REPO_URL, WORKFLOWS_DIR)
├── catalogs        (_find_model, _reload_models)
├── download        (_enqueue_download)
└── workflows       (_load_workflows_index_raw, _load_manifest, ...)

workflows.py
├── config          (COMFY_URL, COMFYUI_DIR, MODELS_BASE, WORKFLOWS_DIR)
└── catalogs        (_all_categories, _reload_models)

runner.py
├── config          (COMFY_URL, JOBS_DIR, ASSETS_OUTPUT_DIR)
├── catalogs        (_reload_models)
└── workflows       (_load_workflows_index, _load_manifest, _assemble_*, ...)

runner_api.py
├── config          (app, COMFY_URL)
├── auth            (COOKIE_NAME, _verify_cookie)
├── events          (_events)
├── runner          (_exec_progress, _pick_best_output, _start_ws_listener, ...)
└── workflows       (_load_workflows_index, _load_manifest, ...)

system_api.py
├── config          (app, COMFY_URL, COMFYUI_DIR, MODELS_BASE, REPO_URL, REPO_DIR, ...)
├── catalogs        (_load_version, _reload_models, _all_categories, ...)
├── download        (_download_state, _max_concurrent, _queue_lock, ...)
├── events          (_events)
├── workflows       (_load_workflows_index, _load_workflows_index_raw)
├── auth            (_maintenance_mode)
└── download        (module-level access for settings)

jobs_api.py
├── config          (COMFY_URL, COMFYUI_DIR, JOBS_DIR, ASSETS_INPUT_DIR, ASSETS_OUTPUT_DIR)
├── events          (_events)
├── runner          (_exec_progress, _save_job, _pick_best_output, _start_ws_listener)
└── workflows       (_make_input_filename)
```

---

## How to Add a New API Endpoint

1. **Choose the right module** based on domain:
   - Model/LoRA operations: `models_api.py`
   - LLM operations: `llm_api.py`
   - Workflow operations: `workflows_api.py`
   - Runner/execution: `runner_api.py`
   - System/settings/telemetry: `system_api.py`
   - Queue/history/assets/nodes: `jobs_api.py`

2. **Add the route** using the module's existing `router`:
   ```python
   @router.get("/api/admin/your-endpoint")
   async def your_endpoint():
       ...
   ```

3. **Import what you need** from `config`, `catalogs`, `download`, `events`, or `workflows`. Never import from another `*_api` module -- that would risk circular imports.

4. **Emit events** for significant actions:
   ```python
   from events import _events
   _events.emit("your.event.type", "Human-readable message", severity="info", data={...})
   ```

5. The router is already included in `main.py` -- no registration needed.

---

## How to Add a New Component/Catalog

To add a new catalog (like `loras.json` was added alongside `models.json`):

1. **Add the catalog file** to `catalogs/` in the repo.

2. **Add path constants** to `config.py`:
   ```python
   NEW_CATALOG_JSON = CATALOGS_DIR / "new-catalog.json"
   ```

3. **Add loader functions** to `catalogs.py` following the pattern of `_load_models()`:
   ```python
   def _load_new_catalog() -> dict:
       try:
           return json.loads(NEW_CATALOG_JSON.read_text())
       except Exception:
           return {"categories": []}
   ```

4. **Add to `_reload_models()`** in `catalogs.py` so the catalog refreshes after updates.

5. **Add the component** to `version.json`:
   ```json
   "new_catalog": {"version": 1, "date": "...", "file": "catalogs/new-catalog.json"}
   ```

6. **Add to the update mechanism** in `system_api.py`:
   - Add a copy block for the new catalog file (from `.repo/catalogs/` to `STUDIO_DIR/catalogs/`)

7. **Add to bootstrap** in `docker/production/bootstrap.py`:
   - The bootstrap copies all files in `.repo/catalogs/` automatically (no change needed if the file is in catalogs/)

8. **Create API endpoints** in a new `*_api.py` module or an existing one.

9. **Create a frontend page** in `frontend/pages/` and add a route in `pages.py`.

---

## Shared State

Global state lives in specific modules. Access it by importing from the owning module.

| State | Location | Description |
|-------|----------|-------------|
| `app` | `config.py` | FastAPI application instance. Imported everywhere. |
| `_models_data`, `_loras_data`, `_llm_models_data` | `catalogs.py` | Loaded catalog dicts. Refreshed by `_reload_models()`. |
| `_download_state` | `download.py` | `{filename: {status, bytes, total, speed, error}}` -- in-memory, resets on restart. |
| `_pending_queue`, `_active_count` | `download.py` | Download queue state, guarded by `_queue_lock`. |
| `_max_concurrent` | `download.py` | Current download concurrency limit (mutable via settings). |
| `_exec_progress` | `runner.py` | `{prompt_id: {status, node, step, total_steps, percent, ...}}` -- ComfyUI execution tracking. |
| `_events` | `events.py` | Global EventBus instance with ring buffer + disk log. |
| `_ws_pusher` | `events.py` | WebSocket client list for real-time event push. |
| `_maintenance_mode` | `auth.py` | Boolean flag. When True, AuthMiddleware returns 503 to all requests. |
| `_llama_process` | `llm_server.py` | llama-server subprocess handle, guarded by `_llama_process_lock`. |

---

## Event System

The EventBus in `events.py` provides a thread-safe, non-blocking event dispatch system.

### Emitting events

```python
from events import _events

_events.emit(
    "model.download.completed",    # event type (dotted string)
    "Downloaded: model.safetensors",  # human-readable message
    severity="success",              # "info", "success", "warning", "error"
    data={"filename": "model.safetensors", "size": 1234567},  # arbitrary dict
)
```

### How it works

1. `emit()` is thread-safe (uses a `queue.Queue`) -- safe to call from download threads.
2. Events are appended to an in-memory ring buffer (1000 events max).
3. Events are persisted to `db/studio.db` (SQLite events table, trimmed to 1000).
4. A background asyncio task consumes the queue and dispatches to subscribers.
5. The `_WebSocketPusher` subscriber pushes events to all connected WebSocket clients in real-time.

### Subscribing

```python
from events import EventSubscriber, _events

class MySubscriber(EventSubscriber):
    event_types = {"model.download.completed", "model.download.failed"}  # or None for all

    async def on_event(self, event: dict):
        # event has: id, type, timestamp, severity, message, data
        ...

_events.subscribe(MySubscriber())
```

### Querying the log

```python
_events.get_log(limit=100, types=["model.download.completed"], severity="error")
```

Events are also available via the API: `GET /api/admin/events?limit=100&types=model.download.completed&severity=error`.

---

## Config Structure

All paths derive from `STUDIO_DIR` (default: `/workspace/studio`). Defined in `config.py`.

```
STUDIO_DIR (/workspace/studio)
├── backend/             BACKEND_DIR        — live Python code
├── frontend/            WWW_ROOT           — live frontend files
├── catalogs/
│   ├── models.json      MODELS_JSON        — model catalog
│   ├── loras.json       LORAS_JSON         — LoRA catalog
│   └── llm.json         LLM_MODELS_JSON    — LLM model catalog
├── workflows/           WORKFLOWS_DIR      — workflow library
├── assets/
│   ├── input/           ASSETS_INPUT_DIR   — ComfyUI input images
│   └── output/          ASSETS_OUTPUT_DIR  — ComfyUI output files
├── jobs/                JOBS_DIR           — job history JSON files
├── llm/
│   ├── models/          LLM_MODELS_DIR     — downloaded LLM GGUF files
│   └── config.json      LLM_CONFIG_PATH    — llama-server config
├── database/            DB_DIR             — SQLite databases (studio.db)
├── version.json         VERSION_JSON       — component versions
└── .session_secret      SESSION_SECRET_PATH — HMAC signing key
```

The `_www()` helper in `catalogs.py` resolves frontend files from `WWW_ROOT`, checking `pages/` subdirectory for bare filenames.

External (not under STUDIO_DIR):
- `COMFYUI_DIR` = `/workspace/ComfyUI` -- ComfyUI installation
- `MODELS_BASE` = `COMFYUI_DIR/models` -- where models are stored
- `COMFY_URL` = `http://127.0.0.1:8188` -- ComfyUI API

---

## Authentication Flow

### Cookie-based auth with sliding expiration

1. User navigates to any page. `AuthMiddleware` checks for a valid session cookie.
2. If no valid cookie, user is redirected to `/login` (or gets 401 for API calls).
3. User submits API key via `POST /api/auth/login`. If it matches `API_KEY` env var, a signed cookie is set.
4. The cookie payload is `"authenticated:<unix_timestamp>"`, signed with HMAC-SHA256 using a persistent secret stored at `SESSION_SECRET_PATH`.
5. On every authenticated request, the cookie is **renewed** (sliding expiration). Max age: 24 hours.
6. `POST /api/auth/logout` deletes the cookie.

### Programmatic access

```bash
curl -H "X-API-Key: your-key" https://pod:8000/api/admin/models
```

The `X-API-Key` header is checked before the cookie, allowing scripts and tools to authenticate without cookies.

### WebSocket authentication

WebSocket connections (used for real-time progress) verify the session cookie from the WebSocket handshake headers. See `runner_api.py` for the implementation.

### Maintenance mode

During updates, `auth._maintenance_mode` is set to `True`. The middleware returns:
- **API calls**: `503 {"detail": "System is updating, please wait..."}`
- **Page requests**: HTML page with "Updating..." message and auto-reload script (every 3s)

---

## Update Mechanism

The update endpoint `POST /api/admin/system/update` uses git to fetch updates:

### Step 1: Git fetch
- `git fetch --depth 1 origin main` in `STUDIO_DIR/.repo/` (or clone if missing)
- Read remote `version.json` via `git show origin/main:version.json`

### Step 2: Compatibility check
- If `remote.min_runtime > RUNTIME_VERSION`, returns `blocked: true` (Docker image too old)

### Step 3: Compare versions
- Compare each component version between local and remote
- Skip components listed in `skip_components` request body

### Step 4: Apply updates (under maintenance mode)
- `git reset --hard origin/main` in `.repo/`
- **Backend/Frontend**: `rmtree` + `copytree` from `.repo/` to working dirs
- **Catalogs**: `copy2` individual files from `.repo/catalogs/` to `STUDIO_DIR/catalogs/`
- **Workflows**: copy index + each workflow dir from `.repo/workflows/` to `STUDIO_DIR/workflows/`

### Step 5: Finalize
- Merge version.json (keep skipped component versions from local)
- If backend updated → restart via `os.execv(uvicorn)`
- If no restart needed → exit maintenance mode

### Important behaviors
- **Maintenance mode** is enabled before updates and disabled after (or on error). If restart needed, stays on until reboot.
- **Skip components**: Request body `{"skip_components": ["frontend"]}` to skip specific components.
- **Version comparison** handles mixed types (int vs str) — forces update when types differ.
- Response includes `debug` field with both local and remote version.json.

---

## API Endpoint Summary

### Auth (`auth.py`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/login` | Serve login page |
| POST | `/api/auth/login` | Authenticate with API key, set session cookie |
| POST | `/api/auth/logout` | Delete session cookie, redirect to login |

### System (`system_api.py`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check (public, no auth) |
| GET | `/api/admin/events` | List events from activity log (filterable) |
| GET | `/api/admin/system/remote-version` | Fetch version.json from repo |
| GET | `/api/admin/system/status` | Dashboard data: versions, stats, disk, ComfyUI status |
| POST | `/api/admin/system/update` | Check for updates and download changed components |
| GET | `/api/admin/telemetry` | GPU/CPU/RAM/disk telemetry |
| GET | `/api/admin/settings` | Get current settings (download concurrency) |
| PUT | `/api/admin/settings` | Update settings |
| GET | `/api/admin/settings/env` | List relevant environment variables (sensitive values masked) |

### Models (`models_api.py`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/models` | List all models with download status |
| GET | `/api/admin/loras` | List all LoRAs with download status |
| POST | `/api/admin/models/download/{filename}` | Queue a single model download |
| POST | `/api/admin/models/download-batch` | Queue multiple model downloads |
| GET | `/api/admin/models/status` | Download status for all active/recent downloads |
| DELETE | `/api/admin/models/{filename}` | Delete a model from disk |
| POST | `/api/admin/models/import` | Import a model file via upload |
| POST | `/api/admin/models/fetch-metadata` | Fetch CivitAI metadata for a model |
| GET | `/api/admin/models/metadata-status` | Check metadata fetch status |
| GET | `/api/admin/activity-log` | Get model download activity log |
| POST | `/api/admin/activity-log/clear` | Clear activity log |
| POST | `/api/admin/models/sync` | Sync model catalog from repo |
| GET | `/api/admin/loras/compatible/{base_model}` | Get compatible LoRA pairs for a base model |

### LLM (`llm_api.py`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/llm/models` | List LLM models with download status |
| POST | `/api/admin/llm/models/download/{filename}` | Download an LLM model |
| DELETE | `/api/admin/llm/models/{filename}` | Delete an LLM model |
| GET | `/api/admin/llm/status` | Check llama-server running status + loaded model |
| POST | `/api/admin/llm/start` | Start llama-server with a model |
| POST | `/api/admin/llm/stop` | Stop llama-server |
| POST | `/api/admin/llm/config` | Update llama-server configuration |
| POST | `/api/admin/llm/chat` | Chat completion (streaming response) |

### Workflows (`workflows_api.py`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/workflows` | List workflows with readiness status |
| GET | `/api/admin/workflows/{id}` | Get a single workflow's full manifest and status |
| POST | `/api/admin/workflows/{id}/install-models` | Install missing models for a workflow |
| POST | `/api/admin/workflows/sync` | Sync workflows from repo |

### Runner (`runner_api.py`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/run/{workflow_id}` | Get workflow manifest for runner form |
| POST | `/api/run/upload-image` | Upload input image to ComfyUI |
| POST | `/api/run/{workflow_id}/build` | Build workflow (preview params without executing) |
| POST | `/api/run/{workflow_id}/execute` | Execute workflow, return prompt_id |
| WS | `/api/run/ws` | WebSocket for real-time execution progress + preview frames |
| GET | `/api/run/status/{prompt_id}` | Poll execution status + progress |
| GET | `/api/comfyui/view` | Proxy to ComfyUI /view for serving images |
| GET | `/api/run/result/{prompt_id}` | Get execution result (binary video/image) |

### Jobs, Assets, Nodes (`jobs_api.py`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/queue` | List active/queued jobs with real-time progress |
| GET | `/api/admin/history` | List completed/failed jobs |
| POST | `/api/admin/history/delete` | Delete job records |
| POST | `/api/admin/history/retry` | Retry a failed job |
| GET | `/api/admin/history/{prompt_id}/package` | Download a job's inputs + outputs as ZIP |
| POST | `/api/admin/assets/upload-inputs` | Upload input files to assets |
| GET | `/api/admin/assets/{asset_type}` | List input or output assets |
| GET | `/api/admin/outputs-zip` | Download all outputs as ZIP |
| POST | `/api/admin/assets/delete` | Delete asset files |
| GET | `/api/admin/nodes` | List installed custom node packages |
| POST | `/api/admin/nodes/install` | Install a custom node by GitHub URL |

### Pages (`pages.py`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Redirect to /home |
| GET | `/home` | Homepage |
| GET | `/admin/models` | Model Manager |
| GET | `/admin/loras` | LoRA Manager |
| GET | `/admin/workflows` | Workflow Manager |
| GET | `/admin/nodes` | Node Manager |
| GET | `/admin/queue` | Job Queue |
| GET | `/admin/history` | Job History |
| GET | `/admin/assets` | Asset Manager |
| GET | `/admin/settings` | Settings |
| GET | `/admin/llm` | LLM Assistant |
| GET | `/run/{workflow_id}` | Workflow Runner |
| GET | `/static/{path}` | Static files (CSS, JS) |
