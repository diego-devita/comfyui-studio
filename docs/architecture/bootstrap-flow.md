# Bootstrap Flow

What happens when the container starts for the first time.

## When Does Bootstrap Run?

The entrypoint script (`start.sh`) checks if `STUDIO_DIR/backend/main.py` exists:

- **File does not exist** → first boot, run bootstrap
- **File exists** → subsequent boot, skip bootstrap, start services directly

This means bootstrap runs only **once** per persistent volume. If you destroy the volume or delete the backend directory, bootstrap will run again.

## Boot Sequence

```
start.sh
│
├── STEP 0: Bootstrap (first boot only)
│   ├── Run /app/bootstrap.py
│   │   ├── Git clone repo → STUDIO_DIR/.repo/
│   │   ├── Check runtime compatibility (min_runtime vs RUNTIME_VERSION)
│   │   ├── Copy backend/ → STUDIO_DIR/backend/
│   │   ├── Copy frontend/ → STUDIO_DIR/frontend/
│   │   ├── Copy catalogs/*.json → STUDIO_DIR/catalogs/ (skip existing)
│   │   ├── Copy workflows/ → STUDIO_DIR/workflows/ (skip if index exists)
│   │   ├── Copy version.json → STUDIO_DIR/version.json
│   │   └── Create directories: assets/input, assets/output, db, jobs, llm/models
│   └── Exit if bootstrap fails
│
├── STEP 1: Copy ComfyUI (first boot only)
│   ├── Check if /workspace/ComfyUI exists
│   └── If not: cp -r /comfyui → /workspace/ComfyUI
│
├── STEP 2: Start ComfyUI
│   ├── Create asset directories
│   ├── cd /workspace/ComfyUI
│   ├── python main.py --listen 0.0.0.0 --port 8188 ...
│   │   Output: stdout + /var/log/comfyui.log (via tee)
│   └── Wait for ComfyUI ready (poll /system_stats every 2s, max 120s)
│
├── STEP 3: Start Studio backend
│   ├── cd STUDIO_DIR/backend
│   └── uvicorn main:app --host 0.0.0.0 --port STUDIO_PORT
│       Output: stdout + /var/log/admin.log (via tee)
│
└── wait (keep container alive)
```

## Bootstrap Details

### Git Clone

```python
git clone --depth 1 REPO_URL STUDIO_DIR/.repo/
```

The clone is shallow (depth 1) to minimize download size. If `.repo/` already exists (from a previous pod using the same volume), bootstrap does `git fetch --depth 1` + `git reset --hard origin/main` instead.

If the fetch fails (for example, after a history rewrite), bootstrap deletes `.repo/` and re-clones from scratch. This self-healing behavior ensures the pod can always recover.

### Runtime Compatibility Check

After cloning, bootstrap reads `version.json` from the clone and checks:

```
min_runtime > RUNTIME_VERSION → BLOCKED
```

- `RUNTIME_VERSION` is an environment variable baked into the Docker image (`ENV RUNTIME_VERSION=3`)
- `min_runtime` is a field in `version.json` that the application sets when it requires a newer Docker image

If blocked, bootstrap exits with code 2 and the container stops. The user must pull a newer Docker image.

### Component Copying

Bootstrap copies components from `.repo/` to working directories with different strategies:

| Component | Strategy | Reason |
|-----------|----------|--------|
| `backend/` | Always overwrite (rmtree + copytree) | Must match the repo version exactly |
| `frontend/` | Always overwrite (rmtree + copytree) | Must match the repo version exactly |
| `catalogs/*.json` | Copy only if file doesn't exist | Preserves user edits on the pod |
| `workflows/` | Copy only if index.json doesn't exist | Preserves user-added workflows |
| `version.json` | Always overwrite | Must reflect the current state |

### Directory Creation

Bootstrap creates these directories if they don't exist:

- `assets/input/` — where uploaded images are stored
- `assets/output/` — where generated outputs land
- `db/` — SQLite database
- `jobs/` — job history (legacy, migrating to SQLite)
- `llm/models/` — downloaded LLM GGUF files

## Subsequent Boots

On subsequent boots (when `backend/main.py` exists), start.sh skips bootstrap entirely and goes straight to starting ComfyUI and the Studio backend. This means:

- The backend runs from whatever code is in `STUDIO_DIR/backend/`
- Updates between reboots are handled by the [Update Mechanism](update-mechanism.md), not by bootstrap
- If someone deletes `STUDIO_DIR/backend/main.py`, the next boot will re-run bootstrap

## Logging

All bootstrap output is prefixed with `[bootstrap]` and goes to stdout, which is visible in RunPod container logs:

```
[bootstrap] Studio dir: /workspace/studio
[bootstrap] Repo URL: https://github.com/diego-devita/comfyui-studio.git
[bootstrap] Runtime version: 3
[bootstrap] Cloning repo...
[bootstrap] App version: 12.3.0 (min_runtime: 0)
[bootstrap]   Copied backend
[bootstrap]   Copied frontend
[bootstrap]   Copied catalog: models.json
[bootstrap]   Copied catalog: loras.json
[bootstrap]   Copied catalog: llm.json
[bootstrap]   Copied workflows
[bootstrap]   Copied version.json
[bootstrap] Bootstrap complete — app v12.3.0
```

ComfyUI and Studio backend output is also visible in container logs via `tee`, and saved to `/var/log/comfyui.log` and `/var/log/admin.log` respectively.
