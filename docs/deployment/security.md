# Security

How ComfyUI Studio protects access to the web UI and APIs.

## Authentication Overview

ComfyUI Studio uses **cookie-based session authentication** for the web UI and **API key header** for programmatic access. Both use the same secret: the `API_KEY` environment variable.

## Cookie-Based Session Auth

### Login Flow

1. User navigates to any page
2. `AuthMiddleware` checks for a valid session cookie
3. If no valid cookie → redirect to `/login`
4. User enters `API_KEY` on the login page
5. `POST /api/auth/login` validates the key
6. If correct → set a signed session cookie

### Cookie Details

| Property | Value |
|----------|-------|
| Name | `session` |
| HttpOnly | `true` — JavaScript cannot read the cookie |
| Secure | `true` — only sent over HTTPS |
| SameSite | `Strict` — never sent in cross-site requests |
| Max-Age | 24 hours |
| Payload | `authenticated:<unix_timestamp>` |
| Signing | HMAC-SHA256 with a persistent secret |

### Session Secret

A random secret is generated on first boot and persisted at `STUDIO_DIR/.session_secret`. This secret signs all session cookies using HMAC-SHA256. If the secret is lost (volume wiped), all existing sessions are invalidated and users must log in again.

### Sliding Expiration

Every authenticated request renews the cookie. If you use the application within the 24-hour window, your session never expires. If you're inactive for more than 24 hours, you'll need to log in again.

## API Key Header

For programmatic access (scripts, curl, automation), include the API key in the `X-API-Key` header:

```bash
curl -H "X-API-Key: your-api-key" https://pod:8000/api/admin/models
```

The `X-API-Key` header is checked **before** the session cookie. If the header is present and matches `API_KEY`, the request is authenticated regardless of cookies.

## Public Routes

These routes do NOT require authentication:

| Path | Purpose |
|------|---------|
| `/login` | Login page |
| `/api/auth/login` | Login API endpoint |
| `/api/health` | Health check (returns `{"status": "ok"}`) |
| `/static/*` | CSS, JS, and other static assets |

All other routes require authentication.

## WebSocket Authentication

The WebSocket endpoint (`ws://host/api/run/ws`) verifies the session cookie from the WebSocket handshake headers **before** accepting the connection. If the cookie is missing or invalid, the connection is rejected.

The `SameSite=Strict` cookie flag prevents Cross-Site WebSocket Hijacking (CSWSH) at the browser level — a malicious website cannot initiate a WebSocket connection to your pod because the browser won't send the cookie for cross-site requests.

## Maintenance Mode

During application updates, the backend enters **maintenance mode**:

- All API calls return `503 {"detail": "System is updating, please wait..."}`
- All page requests return an HTML page with "Updating..." message and auto-reload script (every 3 seconds)
- Maintenance mode is automatically exited after the update completes (or after a restart)

## ComfyUI Access

ComfyUI (port 8188) has **no built-in authentication**. The ComfyUI project has explicitly declined to add auth features.

### Recommendations

| Approach | Security | Effort |
|----------|----------|--------|
| **Don't expose port 8188** | Best — ComfyUI only accessible on localhost | Zero — just don't map the port |
| SSH tunnel for graph editor | Good — requires SSH access | Minimal — `ssh -L 8188:localhost:8188 pod@ssh.runpod.io` |
| ComfyUI-Login custom node | Basic — password middleware | Low — pre-installed, but has limitations |

ComfyUI-Login is included in the Docker image (38th custom node) but must be configured manually (set password on first access via browser). It intercepts all HTTP/WS requests to ComfyUI but has limitations: no rate limiting, token printed in logs, CSS/JS always public.

### ComfyUI Manager Security

ComfyUI Manager has a `security_level` setting in its config:

| Level | What's Blocked |
|-------|---------------|
| `strong` | Git URL installs, pip installs, third-party nodes, uninstall, update, snapshots, restart |
| `normal` | Git URL installs, pip installs, third-party nodes |
| `weak` | Nothing blocked |

For public deployments, `strong` is recommended to prevent users from installing arbitrary code through the ComfyUI Manager interface.

## Best Practices

1. **Use a strong API_KEY** — not `changeme`, not a common password
2. **Don't expose port 8188** unless you need the graph editor externally
3. **Set CIVITAI_API_KEY and HF_TOKEN** on the pod, not in shared configuration
4. **Use HTTPS** — RunPod proxy handles this automatically; on custom servers, put a reverse proxy in front
5. **Rotate the session secret** periodically by deleting `.session_secret` and restarting (invalidates all sessions)
