# ============================================================
# ComfyUI Studio — Development Image
# Lightweight image for local development. No CUDA, no PyTorch,
# no ComfyUI, no custom nodes. Just Python + backend deps +
# a ComfyUI stub server for fake responses.
#
# Source code is mounted read-only from the host repo.
# Runtime data (catalogs, db, assets, gallery) lives in a
# separate volume so it doesn't pollute the git repo.
#
# Build:
#   docker build -f docker/development/Dockerfile -t comfyui-studio-dev .
#
# Run:
#   docker run -d --name studio-dev \
#     -p 8000:8000 -p 8188:8188 \
#     -v $(pwd)/backend:/workspace/studio/backend \
#     -v $(pwd)/frontend:/workspace/studio/frontend \
#     -v $(pwd)/workflows:/workspace/studio/workflows \
#     -v $(pwd)/version.json:/workspace/studio/version.json \
#     -v ~/.studio-dev:/workspace/studio/data \
#     -e API_KEY=test \
#     comfyui-studio-dev
# ============================================================

FROM python:3.12-slim

# System dependencies (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Backend Python dependencies (same as production, minus PyTorch/ML)
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    httpx \
    python-multipart \
    huggingface_hub \
    aiofiles \
    requests \
    pyyaml \
    aiohttp \
    Pillow

# ComfyUI stub server
COPY docker/development/comfyui_stub.py /app/comfyui_stub.py

# Entrypoint
COPY docker/development/start.sh /start.sh
RUN chmod +x /start.sh

ENV STUDIO_DIR=/workspace/studio
ENV API_KEY=changeme
ENV COMFYUI_PORT=8188
ENV STUDIO_PORT=8000
ENV DEV_MODE=true

EXPOSE 8000 8188

WORKDIR /workspace/studio

CMD ["/start.sh"]
