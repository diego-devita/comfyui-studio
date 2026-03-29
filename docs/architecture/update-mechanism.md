# Update Mechanism

How the "Check for Updates" button works to update the application without rebuilding the Docker image.

## Overview

The application code, model catalogs, and workflows live in the Git repository and are synced to the pod on demand. When you click "Check for Updates" on the Home page, the backend:

1. Fetches the latest code from GitHub into `.repo/`
2. Compares component versions between local and remote
3. Copies changed components to the working directories
4. Restarts itself if the backend code changed

This allows you to push code changes to GitHub and have them appear on the pod within seconds, without rebuilding or re-pulling the Docker image.

## What Can Be Updated

| Component | Updated by | Restart? | When visible? |
|-----------|-----------|----------|---------------|
| Backend (Python code) | Copied from `.repo/backend/` | **Yes** (auto) | After ~2 second restart |
| Frontend (HTML/CSS/JS) | Copied from `.repo/frontend/` | No | Next page load |
| Model catalog (`models.json`) | Copied from `.repo/catalogs/` | No | Next API call (after `_reload_models()`) |
| LoRA catalog (`loras.json`) | Same | No | Same |
| LLM catalog (`llm.json`) | Same | No | Same |
| Workflows | Copied from `.repo/workflows/` | No | Next API call |
| Runtime (Docker image) | **Cannot** be updated this way | N/A | Must pull new image |

## Update Flow

### Step 1: Git Fetch

```
git fetch --depth 1 origin main
```

Executed in `STUDIO_DIR/.repo/`. This downloads the latest commit from GitHub without modifying the working tree. If the fetch fails (for example, after a history rewrite), the backend deletes `.repo/` and re-clones from scratch.

### Step 2: Read Remote Version

```
git show origin/main:version.json
```

Reads the `version.json` from the fetched commit without checking it out. This gives us the remote component versions to compare against.

### Step 3: Runtime Compatibility Check

If `remote.min_runtime > local.RUNTIME_VERSION`, the update returns `blocked: true` with a message telling the user to pull a newer Docker image. No changes are made.

### Step 4: Compare Versions

For each component in `version.json`, the backend compares the remote version with the local version:

- Integers (models, loras, workflows): remote `>` local → needs update
- Semver strings (backend, frontend): parsed as tuples and compared
- Type mismatch: forces update (handles schema migrations)

Components listed in `skip_components` (unchecked toggles on the Home page) are skipped.

If nothing needs updating, the response says "Everything up to date" and no maintenance mode is triggered.

### Step 5: Maintenance Mode

If updates are needed, the backend enters **maintenance mode**. In this mode:

- All API calls return `503 {"detail": "System is updating, please wait..."}`
- All page requests return an HTML page with "Updating..." message and auto-reload script (every 3 seconds)
- The WebSocket continues to function for connected clients

### Step 6: Git Reset

```
git reset --hard origin/main
```

Updates `.repo/` to match the remote exactly. This is safe because `.repo/` is never modified locally — it's purely a staging area.

### Step 7: Copy Changed Components

The backend copies only the components that need updating:

**Backend:**
```python
shutil.rmtree(BACKEND_DIR)
shutil.copytree(REPO_DIR / "backend", BACKEND_DIR)
```

**Frontend:**
```python
shutil.rmtree(WWW_ROOT)
shutil.copytree(REPO_DIR / "frontend", WWW_ROOT)
```

**Catalogs** (models, loras, llm): individual file copies with `shutil.copy2`.

**Workflows**: copy `index.json` + each workflow directory (rmtree + copytree per workflow).

### Step 8: Merge Version JSON

The local `version.json` is updated with remote versions, **except** for skipped components which keep their local versions. This ensures that skipped components don't appear as "needs update" on the next check.

### Step 9: Reload or Restart

- If catalogs changed: `_reload_models()` refreshes in-memory catalog data
- If backend changed: schedule restart via `subprocess.Popen` + `os._exit(0)` -- spawns a new uvicorn process and terminates the current one
- If no restart needed: exit maintenance mode immediately

!!! note "Restart mechanism"
    The backend restart no longer uses `os.execv`. Instead, it spawns a new uvicorn process with `subprocess.Popen(start_new_session=True)` and then calls `os._exit(0)` to terminate the current process. This avoids issues with `os.execv` and signal handlers in the uvicorn worker.

## Component Update Toggles

The Home page shows toggle switches next to each component. Unchecked components are sent as `skip_components` in the update request:

```json
POST /api/admin/system/update
{
  "skip_components": ["loras", "llm_models"]
}
```

This lets users skip components they don't want to update (for example, keeping a locally modified catalog).

## What Triggers a Docker Rebuild

Certain files in the repository trigger a Docker image rebuild on GitHub Actions when pushed:

| Path | Triggers rebuild? |
|------|------------------|
| `docker/*` (Dockerfile, start.sh, bootstrap.py, nodes.txt) | **Yes** |
| `.github/workflows/*` | **Yes** |
| `backend/**` | No |
| `frontend/**` | No |
| `catalogs/**` | No |
| `workflows/**` | No |
| `version.json` | No |
| `*.md` | No |
| `chrome-extension/**` | No |
| `docs/**` | No |
| `mkdocs.yml` | No |

This means you can push backend, frontend, catalog, and workflow changes all day without waiting for a Docker build. Only infrastructure changes (Dockerfile, custom nodes, startup scripts) trigger a rebuild.
