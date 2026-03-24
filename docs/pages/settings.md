# Settings

The configuration page at `/admin/settings`. Displays environment variables relevant to the application. Accessible via the gear icon in the navigation bar.

## Layout

A single section:

1. **Environment Variables table** -- read-only display of configured env vars

## Data Loading

```
GET /api/admin/settings/env
```

Returns an array of environment variable objects, each with:

- `key` -- variable name
- `value` -- the value (masked if sensitive)
- `sensitive` -- boolean, whether the value is masked
- `set` -- boolean, whether the variable has a value

## Environment Variables Table

A two-column table (Variable, Value) showing relevant environment variables:

| Variable | Sensitive | Purpose |
|----------|-----------|---------|
| `API_KEY` | Yes | Authentication API key |
| `CIVITAI_API_KEY` | Yes | CivitAI API access for downloads and metadata |
| `HF_TOKEN` | Yes | HuggingFace access token for gated model downloads |
| `RUNPOD_API_KEY` | Yes | RunPod API key for volume size queries |
| `COMFYUI_DIR` | No | Path to ComfyUI installation |
| `COMFYUI_PORT` | No | Port ComfyUI listens on |
| `REPO_URL` | No | Git repository URL for updates |
| `MAX_CONCURRENT_DOWNLOADS` | No | Maximum parallel downloads |
| `RUNPOD_POD_ID` | No | RunPod pod identifier |
| `RUNPOD_DC_ID` | No | RunPod datacenter identifier |
| `RUNPOD_VOLUME_ID` | No | RunPod network volume identifier |
| `PUBLIC_KEY` | No | SSH public key (if configured) |

### Value Display

Each row has a status dot before the variable name:

- **Green dot** -- variable is set (has a value)
- **Grey dot** -- variable is not set

Value rendering depends on the variable state:

- **Set, non-sensitive** -- displayed as-is
- **Set, sensitive** -- masked: first 4 characters + `***` + last 4 characters (e.g., `sk-p***q8xR`). Values 8 characters or shorter show only `***`.
- **Not set** -- shown as "(not set)" in italic grey text

Sensitive values are masked server-side before transmission. The frontend never receives the full value of API keys or tokens.

## Related Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/admin/settings/env` | GET | List environment variables |
| `/api/admin/settings` | GET | Get download settings |
| `/api/admin/settings` | PUT | Update download settings |
