# v2 Dev Container

Lightweight container for testing the v2 CLI and modules.
No CUDA, no ComfyUI, no FastAPI — just Python + the v2 app.

## Quick start

```bash
cd v2/docker
docker compose up -d --build
docker exec -it studio-v2-dev bash
```

Inside the container:
```bash
cd /workspace/studio
python3 -m v2.app.cli --help
python3 -m v2.app.cli db tables
python3 -m v2.app.cli media stats
python3 -m v2.app.cli config list
```

## Layout

```
Host                                          Container
~/Projects/.../comfyui-studio/          →     /workspace/studio/        (code, live)
~/.studio2-dev/                         →     /workspace/studio/v2/data/ (persistent)
```

Inside the container, symlinks connect v2/ dirs to the data volume:
```
/workspace/studio/v2/db/          →  data/db/          (SQLite)
/workspace/studio/v2/media/       →  data/media/       (media store)
/workspace/studio/v2/models/      →  data/models/      (model store)
/workspace/studio/v2/downloads/   →  data/downloads/   (temp downloads)
```

## Paths

| Variable | Value |
|----------|-------|
| WORKSPACE | /workspace |
| STUDIO_DIR | /workspace/studio |
| V2_DIR | /workspace/studio/v2 |
| DB_PATH | /workspace/studio/v2/db/studio.db |

## Rebuild

```bash
# Rebuild image (after changing Dockerfile)
docker compose up -d --build

# Restart (picks up code changes — usually not needed, code is mounted live)
docker restart studio-v2-dev
```

## Reset data

```bash
# Delete all persistent data (DB, media, models, downloads)
rm -rf ~/.studio2-dev
docker restart studio-v2-dev
```

## Dependencies in image

- Python 3.12
- httpx (HTTP client)
- Pillow (image processing, thumbnails)
- inotify (filesystem watch for download scheduler)
- ffmpeg + ffprobe (video thumbnails, media analysis)
