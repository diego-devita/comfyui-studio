#!/usr/bin/env bash
set -e

echo "=== ComfyUI Studio — starting ==="

COMFYUI_IMAGE="/comfyui"
COMFYUI_VOLUME="/workspace/ComfyUI"
REPO_BASE="${REPO_BASE:-https://raw.githubusercontent.com/diego-devita/comfyui-studio/main}"

# ── STEP 0: Bootstrap app + catalogs from repo ──────────────────
# The app code, model catalog, and workflows are NOT baked into the
# Docker image (only a baseline fallback in /app). On first boot we
# copy the baseline to /workspace and then fetch latest from the repo.

# 0a: App code (main.py + www/)
if [ ! -f "/workspace/app/main.py" ]; then
    echo "[0a] First boot — copying app baseline to /workspace..."
    cp -r /app /workspace/app
    echo "      OK"
else
    echo "[0a] App already present in /workspace — skipping"
fi

# 0b: Version manifest
if [ ! -f "/workspace/version.json" ]; then
    echo "[0b] Fetching version.json from repo..."
    curl -sf "${REPO_BASE}/version.json" -o /workspace/version.json || \
        cp /app/version.json /workspace/version.json 2>/dev/null || true
fi

# 0c: Models catalog
if [ ! -f "/workspace/models.json" ]; then
    echo "[0c] Fetching models catalog from repo..."
    curl -sf "${REPO_BASE}/app/models.json" -o /workspace/models.json || \
        echo "      WARNING: Could not fetch. Using baked-in default."
else
    echo "[0c] Models catalog already present — skipping"
fi

# 0d: Workflows
if [ ! -f "/workspace/workflows/index.json" ]; then
    echo "[0d] Fetching workflows from repo..."
    mkdir -p /workspace/workflows
    if curl -sf "${REPO_BASE}/workflows/index.json" -o /workspace/workflows/index.json; then
        for wf_id in $(python3 -c "import json; [print(w['id']) for w in json.load(open('/workspace/workflows/index.json')).get('workflows',[])]" 2>/dev/null); do
            mkdir -p "/workspace/workflows/${wf_id}"
            curl -sf "${REPO_BASE}/workflows/${wf_id}/manifest.yaml" -o "/workspace/workflows/${wf_id}/manifest.yaml" || true
            curl -sf "${REPO_BASE}/workflows/${wf_id}/workflow.json" -o "/workspace/workflows/${wf_id}/workflow.json" || true
            echo "      Fetched workflow: ${wf_id}"
        done
    else
        echo "      WARNING: Could not fetch workflows. Use Sync in the UI."
    fi
else
    echo "[0d] Workflows already present — skipping"
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
echo "[2/3] Starting ComfyUI on port 8188..."
cd "${COMFYUI_VOLUME}"
python main.py \
    --listen 0.0.0.0 \
    --port 8188 \
    --disable-auto-launch \
    ${COMFYUI_FLAGS:---highvram} \
    ${COMFYUI_EXTRA_ARGS:-} \
    > /var/log/comfyui.log 2>&1 &

COMFY_PID=$!
echo "      ComfyUI PID: ${COMFY_PID}"

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

# ── STEP 3: Start web application ────────────────────────────────
# Runs from /workspace/app/ (hot-updatable), not from /app/ (baked).
echo "[3/3] Starting web application on port 8000..."
cd /workspace/app
uvicorn main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    > /var/log/admin.log 2>&1 &

ADMIN_PID=$!
echo "      Web app PID: ${ADMIN_PID}"

echo "=== Services started ==="
echo "    ComfyUI Studio: https://PODID-8000.proxy.runpod.net"
echo "    ComfyUI:        https://PODID-8188.proxy.runpod.net"

# Keep the container alive — exit if ComfyUI dies
wait ${COMFY_PID}
