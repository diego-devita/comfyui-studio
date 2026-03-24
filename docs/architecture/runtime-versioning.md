# Runtime Versioning

The system that prevents the live-updated application from running on an incompatible Docker image.

## The Problem

The application code updates live from Git, but the Docker image (CUDA, Python, PyTorch, custom nodes) only changes when rebuilt. If the application starts requiring a Python package or custom node that doesn't exist in the Docker image, it breaks.

## The Solution

Two numbers are compared:

| Number | Where it lives | Who sets it |
|--------|---------------|-------------|
| `RUNTIME_VERSION` | `ENV` in the Dockerfile | Set at Docker build time. Currently `3`. |
| `min_runtime` | `version.json` in the Git repo | Set by the developer when the app needs a newer image. Currently `0`. |

The check is simple: if `min_runtime > RUNTIME_VERSION`, the operation is **blocked**.

## Where the Check Happens

### At Bootstrap (First Boot)

`bootstrap.py` clones the repo, reads `version.json`, and compares:

```python
if min_runtime > RUNTIME_VERSION:
    log("BLOCKED: App requires runtime vN but this image is vM")
    sys.exit(2)
```

If blocked, the container exits. The user must pull a newer Docker image.

### At Update (Check for Updates Button)

`system_api.py` fetches the remote `version.json` and compares before applying any changes:

```python
if remote_min_runtime > RUNTIME_VERSION:
    return {"blocked": True, "message": "Update requires Docker image runtime vN"}
```

If blocked, no changes are made. The frontend shows the message to the user.

## Where the Numbers Live

### RUNTIME_VERSION (Docker Image)

Set in the Dockerfile:

```dockerfile
ENV RUNTIME_VERSION=3
```

This number is baked into the image at build time. Every container started from this image has `RUNTIME_VERSION=3` in its environment.

### components.runtime.version (version.json)

```json
{
  "components": {
    "runtime": {"version": 3, "date": "2026-03-24 15:47"}
  }
}
```

This is the **tracked** version in the repo. It must match the Dockerfile's `ENV RUNTIME_VERSION`. They are maintained in sync manually.

### min_runtime (version.json)

```json
{
  "min_runtime": 0
}
```

This is the **minimum** Docker image version the application requires. It starts at 0 (any image works) and only gets bumped when the application needs something new from the Docker image.

## When to Bump

### Bump `RUNTIME_VERSION` (Dockerfile) when:

- A new Python dependency is added to the `pip install` command
- A new custom node is added to `nodes.txt`
- The base CUDA or PyTorch version changes
- A new system package is needed
- llama-server is updated or recompiled

Both `ENV RUNTIME_VERSION=N` in the Dockerfile **and** `components.runtime.version` in `version.json` must be updated together.

### Bump `min_runtime` (version.json) when:

The application code starts **requiring** something from a newer image. For example:

- Backend code imports a Python package that was added in runtime v3
- A workflow requires a custom node that was added in runtime v3

Set `min_runtime` to the runtime version that includes the requirement.

!!! note "min_runtime is conservative"
    `min_runtime` stays at 0 as long as the application doesn't strictly require newer image features. Even if the image is at v3, `min_runtime` can stay at 0 if the app still works on v1 images. Only bump it when it would actually break.

## Example Scenario

1. Docker image v2 is deployed on a pod
2. Developer adds a new Python package to the Dockerfile and bumps to v3
3. Developer pushes backend code that imports the new package and sets `min_runtime: 3`
4. User on the old pod clicks "Check for Updates"
5. Update sees `min_runtime: 3 > RUNTIME_VERSION: 2` → blocked
6. User sees: "Update requires Docker image runtime v3 (you have v2)"
7. User pulls the new Docker image (v3) and restarts the pod
8. Now `RUNTIME_VERSION: 3 >= min_runtime: 3` → update proceeds
