# Nodes API

Endpoints for listing and installing ComfyUI custom node packages. Node information is queried from ComfyUI's `/object_info` endpoint.

---

## GET /api/admin/nodes

List all installed custom node packages and their nodes. Queries ComfyUI's `/object_info` endpoint and groups nodes by their Python module package name.

**Auth:** Required

**Response:** `200 OK`

```json
{
  "packages": [
    {
      "name": "ComfyUI Core",
      "nodes": ["CLIPTextEncode", "KSampler", "LoadImage", "SaveImage", "..."],
      "node_count": 150
    },
    {
      "name": "ComfyUI-WanVideoWrapper",
      "nodes": ["WanVideoSampler", "WanVideoModelLoader", "..."],
      "node_count": 12
    },
    {
      "name": "ComfyUI-VideoHelperSuite",
      "nodes": ["VHS_VideoCombine", "VHS_LoadVideo", "..."],
      "node_count": 25
    }
  ],
  "total_nodes": 487,
  "total_packages": 29
}
```

| Field | Description |
|-------|-------------|
| `packages` | Sorted alphabetically by name |
| `packages[].nodes` | Sorted alphabetically within each package |
| `packages[].node_count` | Number of nodes in the package |
| `total_nodes` | Total node count across all packages |
| `total_packages` | Number of packages (including ComfyUI Core) |

Nodes are classified into packages by their `python_module` field from ComfyUI's `/object_info`. Nodes from `custom_nodes.<package_name>` modules are grouped under that package. Built-in nodes are grouped under `"ComfyUI Core"`.

**Error response:** `503 Service Unavailable`

```json
{
  "detail": "ComfyUI unreachable: ..."
}
```

```bash
curl https://your-pod.runpod.io/api/admin/nodes \
  -H "X-API-Key: your-api-key"
```

---

## POST /api/admin/nodes/install

Install a custom node package from a git repository. Clones the repository into ComfyUI's `custom_nodes/` directory, installs Python dependencies from `requirements.txt` (if present), and runs `install.py` (if present).

**Auth:** Required

**Request body:**

```json
{
  "url": "https://github.com/author/ComfyUI-CustomNode.git"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | Yes | HTTPS git repository URL. Also accepts `repo_url` as an alias. |

**Response (installed):** `200 OK`

```json
{
  "status": "installed",
  "name": "ComfyUI-CustomNode",
  "restart_required": true
}
```

**Response (already installed):** `200 OK`

```json
{
  "status": "already_installed",
  "name": "ComfyUI-CustomNode"
}
```

| Field | Description |
|-------|-------------|
| `name` | Directory name (extracted from the repo URL, `.git` suffix stripped) |
| `restart_required` | Always `true` for new installations -- ComfyUI needs to be restarted to load the new nodes |

**Error responses:**

- `400 Bad Request` -- Invalid or missing URL (must start with `https://`)
- `500 Internal Server Error` -- Git clone failed, pip install failed, or install.py failed (stderr included in detail, truncated to 500 chars)
- `500 Internal Server Error` -- Installation timed out (clone: 120s, pip: 300s, install.py: 300s)

If installation fails, the partially cloned directory is cleaned up.

```bash
curl -X POST https://your-pod.runpod.io/api/admin/nodes/install \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git"}'
```
