#!/usr/bin/env bash
# Lancia il dev container e apri la shell
cd "$(dirname "$0")"

# Avvia se non è già running
if ! docker ps --format '{{.Names}}' | grep -q studio-v2-dev; then
    docker compose up -d
    sleep 1
fi

# Entra nella shell
docker exec -it studio-v2-dev bash -c "cd /workspace/studio && exec bash"
