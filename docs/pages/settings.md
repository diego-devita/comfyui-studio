# Settings

The configuration page at `/admin/settings`. Displays and edits environment variables, controls the Telegram bot, and provides system actions. Accessible via the gear icon in the navigation bar.

## Layout

1. **Environment Variables** -- grouped display of configured env vars, some editable
2. **Telegram Bot** -- start/stop controls and status indicator
3. **Actions** -- restart backend, download Chrome extension

## Environment Variables

Variables are displayed in groups, each with a header label:

### Editable Variables

Some sensitive variables can be edited at runtime from the Settings page without restarting:

| Variable | Description |
|----------|-------------|
| `API_KEY` | Authentication password. Changes take effect immediately. |
| `CIVITAI_API_KEY` | CivitAI API token. Persisted to DB, survives pod restarts. |
| `HF_TOKEN` | HuggingFace access token. Persisted to DB. |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather. Persisted to DB. |
| `TELEGRAM_BOT_NAME` | Display name for the Telegram bot. Persisted to DB. |

Editable variables are marked with an edit icon. When edited, the value is saved to both `os.environ` (current process) and the SQLite database (persists across restarts). On subsequent boots, saved values from the database override the environment variable defaults.

### Read-only Variables

All other environment variables are displayed read-only:

| Variable | Sensitive | Purpose |
|----------|-----------|---------|
| `RUNPOD_API_KEY` | Yes | RunPod API key for volume size queries |
| `COMFYUI_DIR` | No | Path to ComfyUI installation |
| `COMFYUI_PORT` | No | Port ComfyUI listens on |
| `REPO_URL` | No | Git repository URL for updates |
| `MAX_CONCURRENT_DOWNLOADS` | No | Maximum parallel downloads |
| `RUNPOD_POD_ID` | No | RunPod pod identifier |
| `RUNPOD_DC_ID` | No | RunPod datacenter identifier |
| `RUNPOD_VOLUME_ID` | No | RunPod network volume identifier |

RunPod-specific variables are only shown when running on RunPod (detected via `RUNPOD_POD_ID`).

### Value Display

Each row has a status dot before the variable name:

- **Green dot** -- variable is set (has a value)
- **Grey dot** -- variable is not set

Sensitive values are masked server-side: first 4 characters + `***` + last 4 characters (e.g., `sk-p***q8xR`). Values 8 characters or shorter show only `***`.

### Reveal Secrets

A "Reveal" button shows the full unmasked values of all sensitive variables. Revealing requires entering the API key as a second factor. Revealed values are shown for a limited time with a countdown bar, then automatically re-masked.

## Telegram Bot Controls

The Telegram section shows:

- **Status indicator** -- green dot when running, grey when stopped
- **Bot name** -- from `TELEGRAM_BOT_NAME`
- **Started at** -- timestamp when the bot was last started
- **Start/Stop buttons** -- control the bot daemon thread

See [Telegram Bot](../telegram/overview.md) for full details.

## Actions

### Restart Backend

A "Restart" button that calls `POST /api/admin/system/restart`. The backend flushes all SQLite databases (WAL checkpoint), spawns a new uvicorn process, and exits. The page auto-reloads after the restart.

### Download Chrome Extension

A "Download Extension" button that downloads the Chrome extension as a ZIP file via `GET /api/admin/system/chrome-extension`. See [Chrome Extension Installation](../chrome-extension/installation.md).

## Related Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/admin/settings/env` | GET | List environment variables (grouped, masked) |
| `/api/admin/settings/env` | PUT | Update an editable variable |
| `/api/admin/settings/reveal` | POST | Reveal sensitive values (requires API key) |
| `/api/admin/telegram/status` | GET | Telegram bot status |
| `/api/admin/telegram/start` | POST | Start Telegram bot |
| `/api/admin/telegram/stop` | POST | Stop Telegram bot |
| `/api/admin/system/restart` | POST | Restart the backend |
| `/api/admin/system/chrome-extension` | GET | Download Chrome extension ZIP |
