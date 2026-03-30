#!/usr/bin/env bash
set -e

echo "=== ComfyUI Studio — starting ==="

COMFYUI_IMAGE="/comfyui"
COMFYUI_VOLUME="/workspace/ComfyUI"
STUDIO_DIR="${STUDIO_DIR:-/workspace/studio}"
STUDIO_PORT="${STUDIO_PORT:-8000}"

# ── STEP 0: Bootstrap Studio app if not present ──────────────────
if [ ! -f "${STUDIO_DIR}/backend/main.py" ]; then
    echo "[0/3] First boot — bootstrapping application..."
    python3 /app/bootstrap.py
    if [ $? -ne 0 ]; then
        echo "      Bootstrap failed. Check logs."
        # If runtime incompatible, serve error page
        if [ -f "${STUDIO_DIR}/frontend/pages/error.html" ]; then
            echo "      Serving error page on port 8000..."
            cd "${STUDIO_DIR}/frontend/pages"
            python3 -m http.server 8000 &
            wait $!
        fi
        exit 1
    fi
    echo "      Bootstrap complete."
else
    echo "[0/3] Studio already present — skipping bootstrap"
fi

# ── STEP 1: First boot — copy ComfyUI from image to volume ──────
if [ ! -d "${COMFYUI_VOLUME}" ]; then
    echo "[1/3] First boot — copying ComfyUI to /workspace..."
    cp -r "${COMFYUI_IMAGE}" "${COMFYUI_VOLUME}"
    echo "      OK"
else
    echo "[1/3] ComfyUI already present — skipping"
fi

# ── STEP 2: Start ComfyUI ────────────────────────────────────────
# Create asset directories
mkdir -p "${STUDIO_DIR}/assets/input" "${STUDIO_DIR}/assets/output"

echo "[2/3] Starting ComfyUI on port 8188..."
cd "${COMFYUI_VOLUME}"
python main.py \
    --listen 0.0.0.0 \
    --port 8188 \
    --disable-auto-launch \
    --input-directory "${STUDIO_DIR}/assets/input" \
    --output-directory "${STUDIO_DIR}/assets/output" \
    ${COMFYUI_FLAGS:---highvram} \
    ${COMFYUI_EXTRA_ARGS:-} \
    2>&1 | tee -a /var/log/comfyui.log &

echo "      Waiting for ComfyUI..."
for i in $(seq 1 60); do
    if curl -s http://127.0.0.1:8188/system_stats > /dev/null 2>&1; then
        echo "      ComfyUI ready after $((i * 2)) seconds."
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "      WARNING: ComfyUI did not respond within 120 seconds."
    fi
    sleep 2
done

# ── STEP 3: Start Studio backend (auto-restart loop) ─────────────
echo "[3/3] Starting Studio backend on port ${STUDIO_PORT}..."

_studio_loop() {
    while true; do
        echo "[studio] Backend starting..."
        cd "${STUDIO_DIR}/backend"
        uvicorn main:app \
            --host 0.0.0.0 \
            --port ${STUDIO_PORT} \
            --workers 1 \
            2>&1 | tee -a /var/log/admin.log
        echo "[studio] Backend exited — restarting in 2s..."
        sleep 2
    done
}
_studio_loop &

echo "=== Services started ==="
echo "    ComfyUI Studio: https://PODID-${STUDIO_PORT}.proxy.runpod.net"
echo "    ComfyUI:        https://PODID-8188.proxy.runpod.net"

# Keep the container alive while any service is running
wait
