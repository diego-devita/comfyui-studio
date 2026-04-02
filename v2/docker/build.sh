#!/usr/bin/env bash
# Build (o rebuild) l'immagine del dev container v2
cd "$(dirname "$0")"
docker compose build
echo ""
echo "Done. Run ./run.sh to start the container."
