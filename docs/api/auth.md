# Authentication API

ComfyUI Studio uses cookie-based session authentication. A random session secret is generated on first boot and persisted at `STUDIO_DIR/.session_secret`. All routes except public paths require authentication.

**Authentication methods:**

- **Session cookie** -- Set by `POST /api/auth/login`, verified on every request. Sliding expiration (renewed on each authenticated request). 24-hour max age.
- **X-API-Key header** -- For curl/scripts. Pass the `API_KEY` environment variable value.

**Public paths (no auth required):**

- `/login`
- `/api/auth/login`
- `/api/health`
- `/static/*`

---

## GET /login

Serve the login HTML page.

**Auth:** None required

**Response:** `200 OK` with `text/html` body

```bash
curl https://your-pod.runpod.io/login
```

---

## POST /api/auth/login

Authenticate with an API key and receive a session cookie.

**Auth:** None required

**Request body:**

```json
{
  "api_key": "your-api-key",
  "next": "/home"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `api_key` | string | Yes | The API key configured via `API_KEY` env var |
| `next` | string | No | URL to redirect to after login (default: `/home`) |

**Response:** `200 OK`

```json
{
  "status": "ok",
  "redirect": "/home"
}
```

The response includes a `Set-Cookie` header:

```
Set-Cookie: session=<signed-payload>; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=86400
```

**Error response:** `401 Unauthorized`

```json
{
  "detail": "Invalid API key"
}
```

**Examples:**

```bash
# Login and save cookies to a file
curl -X POST https://your-pod.runpod.io/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"api_key": "your-api-key"}' \
  -c cookies.txt

# Use saved cookies in subsequent requests
curl https://your-pod.runpod.io/api/admin/system/status \
  -b cookies.txt

# Alternative: use X-API-Key header instead of cookies
curl https://your-pod.runpod.io/api/admin/system/status \
  -H "X-API-Key: your-api-key"
```

---

## POST /api/auth/logout

Delete the session cookie and redirect to the login page.

**Auth:** Required (cookie or API key)

**Request body:** None

**Response:** `302 Found` redirect to `/login`

The response includes a `Set-Cookie` header that deletes the session cookie.

```bash
curl -X POST https://your-pod.runpod.io/api/auth/logout \
  -b cookies.txt \
  -L
```

---

## Maintenance Mode

During system updates, the backend enters maintenance mode. All routes respond with `503 Service Unavailable`:

- **API routes** (`/api/*`): Return JSON `{"detail": "System is updating, please wait..."}`
- **Page routes**: Return an HTML page that auto-reloads every 3 seconds

Maintenance mode is entered when `POST /api/admin/system/update` begins copying updated components, and exits when the update completes (or when the backend restarts if the backend itself was updated).
