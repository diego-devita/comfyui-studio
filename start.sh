#!/usr/bin/env bash
set -e

echo "=== ComfyUI Studio — starting ==="

COMFYUI_IMAGE="/comfyui"
COMFYUI_VOLUME="/workspace/ComfyUI"
WORKFLOWS_REPO="${WORKFLOWS_REPO:-https://raw.githubusercontent.com/diego-devita/comfyui-studio/main/workflows}"
MODELS_REPO="${MODELS_REPO:-https://raw.githubusercontent.com/diego-devita/comfyui-studio/main/app/models.json}"

# ── STEP 0a: Fetch models catalog from repo ──────────────────────
# The models.json catalog is NOT baked into the Docker image.
# It is fetched from the configured repo and stored in /workspace.
if [ ! -f "/workspace/models.json" ]; then
    echo "[0a] First boot — fetching models catalog from repo..."
    if curl -sf "${MODELS_REPO}" -o /workspace/models.json; then
        echo "      OK — models catalog fetched"
    else
        echo "      WARNING: Could not fetch models catalog. Using baked-in default."
    fi
else
    echo "[0a] Models catalog already present — skipping fetch"
fi

# ── STEP 0b: Fetch workflows from repo ───────────────────────────
# Workflows are NOT baked into the Docker image. They are fetched
# from the configured repo on first boot and updated via Sync.
if [ ! -f "/workspace/workflows/index.json" ]; then
    echo "[0b] First boot — fetching workflows from repo..."
    mkdir -p /workspace/workflows
    if curl -sf "${WORKFLOWS_REPO}/index.json" -o /workspace/workflows/index.json; then
        # Parse index and download each workflow
        for wf_id in $(python3 -c "import json,sys; [print(w['id']) for w in json.load(open('/workspace/workflows/index.json')).get('workflows',[])]" 2>/dev/null); do
            mkdir -p "/workspace/workflows/${wf_id}"
            curl -sf "${WORKFLOWS_REPO}/${wf_id}/manifest.yaml" -o "/workspace/workflows/${wf_id}/manifest.yaml" || true
            curl -sf "${WORKFLOWS_REPO}/${wf_id}/workflow.json" -o "/workspace/workflows/${wf_id}/workflow.json" || true
            echo "      Fetched workflow: ${wf_id}"
        done
        echo "      OK — workflows fetched"
    else
        echo "      WARNING: Could not fetch workflows from repo. Use Sync in the UI later."
    fi
else
    echo "[0b] Workflows already present — skipping fetch"
fi

# ── STEP 1: First boot — copy ComfyUI from image to volume ──────
# /workspace is the RunPod persistent Network Volume.
# On first boot /workspace/ComfyUI does not exist yet.
if [ ! -d "${COMFYUI_VOLUME}" ]; then
    echo "[1/3] First boot — copying ComfyUI to /workspace..."

    cp -r "${COMFYUI_IMAGE}" "${COMFYUI_VOLUME}"
    echo "      OK — ComfyUI copied to ${COMFYUI_VOLUME}"
else
    echo "[1/3] ComfyUI already present in ${COMFYUI_VOLUME} — skipping"
fi

# ── STEP 2: Start ComfyUI ────────────────────────────────────────
# Environment variables:
#   COMFYUI_FLAGS      — vram management (default: --highvram)
#                        Use --lowvram or --normalvram for smaller GPUs
#   COMFYUI_EXTRA_ARGS — any additional flags to pass to ComfyUI
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

# Wait for ComfyUI to be ready (max 120 seconds)
echo "      Waiting for ComfyUI..."
for i in $(seq 1 60); do
    if curl -s http://127.0.0.1:8188/system_stats > /dev/null 2>&1; then
        echo "      ComfyUI ready after $((i * 2)) seconds."
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "      WARNING: ComfyUI did not respond within 120 seconds."
        echo "      Check /var/log/comfyui.log for errors."
    fi
    sleep 2
done

# ── STEP 3: Start model management backoffice ─────────────────────
# Environment variables:
#   API_KEY        — password for HTTP Basic Auth (default: changeme)
#   CIVITAI_API_KEY — CivitAI API token for model downloads
#   HF_TOKEN       — HuggingFace token for model downloads
echo "[3/3] Starting model manager on port 8000..."
cd /app
uvicorn main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    > /var/log/admin.log 2>&1 &

ADMIN_PID=$!
echo "      Model manager PID: ${ADMIN_PID}"

echo "=== Services started ==="
echo "    ComfyUI:       https://PODID-8188.proxy.runpod.net"
echo "    Models:        https://PODID-8000.proxy.runpod.net/admin/models"
echo "    Workflows:     https://PODID-8000.proxy.runpod.net/admin/workflows"
echo "    Nodes:         https://PODID-8000.proxy.runpod.net/admin/nodes"

# Keep the container alive — exit if ComfyUI dies
wait ${COMFY_PID}
