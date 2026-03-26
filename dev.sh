#!/usr/bin/env bash
# ComfyUI Studio — Dev container manager
# Usage:
#   ./dev.sh          Start (or restart) the dev container
#   ./dev.sh stop     Stop and remove
#   ./dev.sh logs     Tail logs
#   ./dev.sh bash     Open a shell inside the container
#   ./dev.sh build    Rebuild the image
#   ./dev.sh reset    Wipe all data and restart fresh

set -e
cd "$(dirname "$0")"

NAME="studio-dev"
IMAGE="comfyui-studio-dev"

start() {
    # Stop old container if running
    docker stop "$NAME" 2>/dev/null && docker rm "$NAME" 2>/dev/null || true

    docker run -d --name "$NAME" \
        -p 8000:8000 -p 8188:8188 \
        -v "$(pwd)/backend:/workspace/studio/backend" \
        -v "$(pwd)/frontend:/workspace/studio/frontend" \
        -v "$(pwd)/workflows:/workspace/studio/workflows" \
        -v "$(pwd)/version.json:/workspace/studio/version.json" \
        -v "$(pwd)/catalogs:/repo-catalogs:ro" \
        -v "$HOME/.studio-dev:/workspace/studio/data" \
        -e API_KEY=test \
        -e CIVITAI_API_KEY=d920d34df8f1b433e5d31065d501ba19 \
        "$IMAGE"

    echo "Started. http://localhost:8000 (key: test)"
    echo "Logs: ./dev.sh logs"
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
    build)
        docker build -f docker/development/Dockerfile -t "$IMAGE" .
        ;;
    reset)
        docker stop "$NAME" 2>/dev/null && docker rm "$NAME" 2>/dev/null || true
        docker run --rm -v "$HOME/.studio-dev:/data" alpine rm -rf /data/*
        echo "Data wiped."
        start
        ;;
    *)
        echo "Usage: ./dev.sh [start|stop|logs|bash|build|reset]"
        ;;
esac
