#!/usr/bin/env bash
set -e

echo "=== ComfyUI Studio — Development Mode ==="

STUDIO_DIR="${STUDIO_DIR:-/workspace/studio}"
STUDIO_PORT="${STUDIO_PORT:-8000}"
COMFYUI_PORT="${COMFYUI_PORT:-8188}"

# Create directories the backend expects
mkdir -p "${STUDIO_DIR}/assets/input" \
         "${STUDIO_DIR}/assets/output" \
         "${STUDIO_DIR}/db" \
         "${STUDIO_DIR}/jobs" \
         "${STUDIO_DIR}/llm/models"

# Start ComfyUI stub server (background)
echo "[1/2] Starting ComfyUI stub on port ${COMFYUI_PORT}..."
python3 /app/comfyui_stub.py --port "${COMFYUI_PORT}" &
STUB_PID=$!

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
