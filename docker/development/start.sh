#!/usr/bin/env bash
set -e

echo "=== ComfyUI Studio — Development Mode ==="

STUDIO_DIR="${STUDIO_DIR:-/workspace/studio}"
STUDIO_PORT="${STUDIO_PORT:-8000}"
COMFYUI_PORT="${COMFYUI_PORT:-8188}"
DATA_DIR="${STUDIO_DIR}/data"
# Repo catalogs mounted read-only at /repo-catalogs for seeding
REPO_CATALOGS="/repo-catalogs"

# Create data directories (persisted in ~/.studio-dev on host)
mkdir -p "${DATA_DIR}/catalogs" \
         "${DATA_DIR}/assets/input" \
         "${DATA_DIR}/assets/output" \
         "${DATA_DIR}/db" \
         "${DATA_DIR}/llm/models"

# Seed catalogs from repo if not already present in data dir.
# Repo catalogs are mounted read-only at /repo-catalogs.
if [ -d "${REPO_CATALOGS}" ]; then
    for f in models.json loras.json llm.json; do
        if [ ! -f "${DATA_DIR}/catalogs/${f}" ] && [ -f "${REPO_CATALOGS}/${f}" ]; then
            cp "${REPO_CATALOGS}/${f}" "${DATA_DIR}/catalogs/${f}"
            echo "      Seeded ${f} into data dir"
        fi
    done
fi

# Symlink runtime dirs into the locations the backend expects.
# Writes go to data/ (persistent volume) instead of the repo.
for name in catalogs assets db llm; do
    target="${STUDIO_DIR}/${name}"
    source="${DATA_DIR}/${name}"
    if [ -e "${target}" ] || [ -L "${target}" ]; then
        rm -rf "${target}"
    fi
    ln -sfn "${source}" "${target}"
done

# Start ComfyUI stub server (background)
echo "[1/2] Starting ComfyUI stub on port ${COMFYUI_PORT}..."
python3 /app/comfyui_stub.py --port "${COMFYUI_PORT}" &

# Wait for stub to be ready
for i in $(seq 1 10); do
    if curl -s "http://127.0.0.1:${COMFYUI_PORT}/system_stats" > /dev/null 2>&1; then
        echo "      Stub ready."
        break
    fi
    sleep 0.5
done

# Start Studio backend with hot reload
echo "[2/2] Starting Studio backend on port ${STUDIO_PORT} (hot reload)..."
cd "${STUDIO_DIR}/backend"
uvicorn main:app \
    --host 0.0.0.0 \
    --port "${STUDIO_PORT}" \
    --reload \
    --reload-dir "${STUDIO_DIR}/backend" \
    --reload-dir "${STUDIO_DIR}/frontend"

echo "=== Development server stopped ==="
