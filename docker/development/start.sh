#!/usr/bin/env bash
set -e

echo "=== ComfyUI Studio — Development Mode ==="

STUDIO_DIR="${STUDIO_DIR:-/workspace/studio}"
STUDIO_PORT="${STUDIO_PORT:-8000}"
COMFYUI_PORT="${COMFYUI_PORT:-8188}"
COMFYUI_DIR="${COMFYUI_DIR:-/workspace/ComfyUI}"
DATA_DIR="${STUDIO_DIR}/data"
REPO_CATALOGS="/repo-catalogs"

# ── Persistent data directories ──
# These live in DATA_DIR which should be a mounted volume (~/.studio-dev).
# If not mounted, they still work but are lost on container removal.
mkdir -p "${DATA_DIR}/catalogs" \
         "${DATA_DIR}/database" \
         "${DATA_DIR}/assets/input" \
         "${DATA_DIR}/assets/output" \
         "${DATA_DIR}/llm/models"

# ── Fake ComfyUI tree ──
# Mirrors real ComfyUI directory structure so model downloads land correctly.
mkdir -p "${DATA_DIR}/comfyui/models/checkpoints" \
         "${DATA_DIR}/comfyui/models/diffusion_models" \
         "${DATA_DIR}/comfyui/models/loras" \
         "${DATA_DIR}/comfyui/models/vae" \
         "${DATA_DIR}/comfyui/models/clip" \
         "${DATA_DIR}/comfyui/models/text_encoders" \
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

# ── Seed catalogs from repo (first boot only) ──
if [ -d "${REPO_CATALOGS}" ]; then
    for f in models.json loras.json llm.json; do
        if [ ! -f "${DATA_DIR}/catalogs/${f}" ] && [ -f "${REPO_CATALOGS}/${f}" ]; then
            cp "${REPO_CATALOGS}/${f}" "${DATA_DIR}/catalogs/${f}"
            echo "      Seeded ${f} into data dir"
        fi
    done
fi

# ── Symlink persistent dirs into STUDIO_DIR ──
# The backend expects catalogs/, database/, assets/, llm/ under STUDIO_DIR.
# We symlink them from the persistent data volume.
for name in catalogs database assets llm; do
    target="${STUDIO_DIR}/${name}"
    source="${DATA_DIR}/${name}"
    if [ -e "${target}" ] || [ -L "${target}" ]; then
        rm -rf "${target}"
    fi
    ln -sfn "${source}" "${target}"
done

# ── Start ComfyUI stub server (background) ──
echo "[1/3] Starting ComfyUI stub on port ${COMFYUI_PORT}..."
python3 /app/comfyui_stub.py --port "${COMFYUI_PORT}" &

for i in $(seq 1 10); do
    if curl -s "http://127.0.0.1:${COMFYUI_PORT}/system_stats" > /dev/null 2>&1; then
        echo "      Stub ready."
        break
    fi
    sleep 0.5
done

# ── Start Datasette (background, waits for DB to exist) ──
DATASETTE_PORT="${DATASETTE_PORT:-8001}"
echo "[2/3] Starting Datasette on port ${DATASETTE_PORT}..."
(
    # Wait for studio.db to be created by the backend on first boot
    for i in $(seq 1 30); do
        [ -f "${DATA_DIR}/database/studio.db" ] && break
        sleep 1
    done
    datasette "${DATA_DIR}/database/studio.db" \
        --host 0.0.0.0 \
        --port "${DATASETTE_PORT}" \
        --setting base_url /admin/db/ \
        --metadata /app/datasette/metadata.json \
        --static static:/app/datasette/ \
        --setting default_allow_sql true \
        --setting allow_download false \
        --setting sql_time_limit_ms 5000
) &

# ── Start Studio backend with hot reload ──
echo "[3/3] Starting Studio backend on port ${STUDIO_PORT} (hot reload)..."
cd "${STUDIO_DIR}/backend"
uvicorn main:app \
    --host 0.0.0.0 \
    --port "${STUDIO_PORT}" \
    --reload \
    --reload-dir "${STUDIO_DIR}/backend" \
    --reload-dir "${STUDIO_DIR}/frontend"

echo "=== Development server stopped ==="
