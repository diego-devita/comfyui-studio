FROM python:3.12-slim

# No interactive prompts, no pip cache
ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

# System deps: ffmpeg (thumbnails/video), ffprobe (media analysis)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Python deps
RUN pip install \
    httpx \
    Pillow \
    inotify

# Workspace structure (matches production layout)
ENV WORKSPACE=/workspace \
    PYTHONPATH=/workspace/studio \
    PATH="/workspace/studio/v2/app/bin:${PATH}"
RUN mkdir -p /workspace/studio/v2

# Entrypoint
COPY start.sh /start.sh
RUN chmod +x /start.sh

WORKDIR /workspace/studio/v2

CMD ["/start.sh"]
