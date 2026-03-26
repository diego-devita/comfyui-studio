#!/usr/bin/env bash
set -e

echo "=== ComfyUI Studio — Development Mode ==="

STUDIO_DIR="${STUDIO_DIR:-/workspace/studio}"
STUDIO_PORT="${STUDIO_PORT:-8000}"
COMFYUI_PORT="${COMFYUI_PORT:-8188}"
COMFYUI_DIR="${COMFYUI_DIR:-/workspace/ComfyUI}"
DATA_DIR="${STUDIO_DIR}/data"
REPO_CATALOGS="/repo-catalogs"

# ── Data directories (persisted in ~/.studio-dev on host) ──
mkdir -p "${DATA_DIR}/catalogs" \
         "${DATA_DIR}/assets/input" \
         "${DATA_DIR}/assets/output" \
         "${DATA_DIR}/db" \
         "${DATA_DIR}/llm/models"

# ── Fake ComfyUI tree (persisted, models survive container restart) ──
# Mirrors the real ComfyUI directory structure so downloads work.
# All dest values from catalogs (checkpoints, loras, vae, etc.) go here.
mkdir -p "${DATA_DIR}/comfyui/models/checkpoints" \
         "${DATA_DIR}/comfyui/models/loras" \
         "${DATA_DIR}/comfyui/models/vae" \
         "${DATA_DIR}/comfyui/models/clip" \
         "${DATA_DIR}/comfyui/models/controlnet" \
         "${DATA_DIR}/comfyui/models/ipadapter" \
         "${DATA_DIR}/comfyui/models/upscale_models" \
         "${DATA_DIR}/comfyui/models/insightface" \
         "${DATA_DIR}/comfyui/custom_nodes" \
         "${DATA_DIR}/comfyui/input" \
         "${DATA_DIR}/comfyui/output"

# Symlink ComfyUI dir so the backend finds it at the expected path
if [ -e "${COMFYUI_DIR}" ] || [ -L "${COMFYUI_DIR}" ]; then
    rm -rf "${COMFYUI_DIR}"
fi
ln -sfn "${DATA_DIR}/comfyui" "${COMFYUI_DIR}"

# ── Seed catalogs from repo (first run only) ──
if [ -d "${REPO_CATALOGS}" ]; then
    for f in models.json loras.json llm.json; do
        if [ ! -f "${DATA_DIR}/catalogs/${f}" ] && [ -f "${REPO_CATALOGS}/${f}" ]; then
            cp "${REPO_CATALOGS}/${f}" "${DATA_DIR}/catalogs/${f}"
            echo "      Seeded ${f} into data dir"
        fi
    done
fi

# ── Symlink runtime dirs into locations the backend expects ──
for name in catalogs assets db llm; do
    target="${STUDIO_DIR}/${name}"
    source="${DATA_DIR}/${name}"
    if [ -e "${target}" ] || [ -L "${target}" ]; then
        rm -rf "${target}"
    fi
    ln -sfn "${source}" "${target}"
done

# ── Start ComfyUI stub server (background) ──
echo "[1/2] Starting ComfyUI stub on port ${COMFYUI_PORT}..."
python3 /app/comfyui_stub.py --port "${COMFYUI_PORT}" &

for i in $(seq 1 10); do
    if curl -s "http://127.0.0.1:${COMFYUI_PORT}/system_stats" > /dev/null 2>&1; then
        echo "      Stub ready."
        break
    fi
    sleep 0.5
done

# ── Start Studio backend with hot reload ──
echo "[2/2] Starting Studio backend on port ${STUDIO_PORT} (hot reload)..."
cd "${STUDIO_DIR}/backend"
uvicorn main:app \
    --host 0.0.0.0 \
    --port "${STUDIO_PORT}" \
    --reload \
    --reload-dir "${STUDIO_DIR}/backend" \
    --reload-dir "${STUDIO_DIR}/frontend"

echo "=== Development server stopped ==="
