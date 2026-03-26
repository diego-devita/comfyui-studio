#!/usr/bin/env bash
# ComfyUI Studio — Production container manager
# Usage:
#   ./prod.sh                    Start with defaults
#   ./prod.sh stop               Stop and remove
#   ./prod.sh logs               Tail logs
#   ./prod.sh bash               Open a shell inside the container
#   ./prod.sh pull               Pull latest image
#
# Environment variables (override defaults):
#   IMAGE=ghcr.io/diego-devita/comfyui-studio:latest
#   VOLUME=/workspace                    Persistent volume path on host
#   API_KEY=changeme                     Studio login key
#   CIVITAI_API_KEY=                     CivitAI API token
#   HF_TOKEN=                            HuggingFace token
#   STUDIO_PORT=8000                     Studio backend port
#   COMFYUI_PORT=8188                    ComfyUI port
#   GPUS=all                             GPU devices (--gpus flag)

set -e
cd "$(dirname "$0")/.."

NAME="${NAME:-comfyui-studio}"
IMAGE="${IMAGE:-ghcr.io/diego-devita/comfyui-studio:latest}"
VOLUME="${VOLUME:-$HOME/.comfyui-studio}"
API_KEY="${API_KEY:-changeme}"
CIVITAI_API_KEY="${CIVITAI_API_KEY:-}"
HF_TOKEN="${HF_TOKEN:-}"
STUDIO_PORT="${STUDIO_PORT:-8000}"
COMFYUI_PORT="${COMFYUI_PORT:-8188}"
GPUS="${GPUS:-all}"

start() {
    # Stop old container if running
    docker stop "$NAME" 2>/dev/null && docker rm "$NAME" 2>/dev/null || true

    mkdir -p "$VOLUME"

    docker run -d --name "$NAME" \
        --gpus "$GPUS" \
        -p "${STUDIO_PORT}:8000" \
        -p "${COMFYUI_PORT}:8188" \
        -v "${VOLUME}:/workspace" \
        -e API_KEY="$API_KEY" \
        -e CIVITAI_API_KEY="$CIVITAI_API_KEY" \
        -e HF_TOKEN="$HF_TOKEN" \
        "$IMAGE"

    echo "Started. http://localhost:${STUDIO_PORT}"
    echo "Volume: ${VOLUME}"
    echo "Image:  ${IMAGE}"
    echo "Logs:   ./prod.sh logs"
}

case "${1:-start}" in
    start)
        start
        ;;
    stop)
        docker stop "$NAME" 2>/dev/null && docker rm "$NAME" 2>/dev/null || true
        echo "Stopped."
        ;;
    logs)
        docker logs -f "$NAME"
        ;;
    bash)
        docker exec -it "$NAME" bash
        ;;
    pull)
        docker pull "$IMAGE"
        ;;
    build)
        echo "Build production image"
        echo ""
        echo "  1) Use existing Dockerfile as-is (default settings)"
        echo "  2) Configure with interactive wizard (choose GPU, options)"
        echo ""
        read -rp "Choice [1/2]: " choice
        case "$choice" in
            2)
                bash docker/configure.sh
                ;;
            *)
                docker build -f docker/production/Dockerfile -t "$IMAGE" .
                echo ""
                echo "Built as: ${IMAGE}"
                ;;
        esac
        ;;
    *)
        echo "Usage: ./prod.sh [start|stop|logs|bash|pull|build]"
        echo ""
        echo "Override defaults with env vars:"
        echo "  IMAGE=myregistry/myimage:tag ./prod.sh"
        echo "  VOLUME=/data/studio API_KEY=secret ./prod.sh"
        echo "  GPUS='\"device=0\"' ./prod.sh"
        ;;
esac
