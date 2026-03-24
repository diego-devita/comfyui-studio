# ============================================================
# ComfyUI Studio — General-Purpose RunPod Template
# Configurable for any NVIDIA GPU via build args.
# Ports: 8188 (ComfyUI) | 8000 (Model Manager)
#
# ARCHITECTURE:
# - ComfyUI + custom nodes installed in /comfyui (image)
# - On first boot, start.sh copies /comfyui → /workspace/ComfyUI
# - Everything runs from /workspace (RunPod Network Volume)
# - Models downloaded on-demand via web backoffice on port 8000
# ============================================================

# ── BUILD ARGUMENTS ────────────────────────────────────────
#
# CUDA_VERSION — NVIDIA CUDA base image version.
#   Must match the GPU architecture you're targeting.
#   Blackwell/Hopper (B200, H200, H100): 12.8.1
#   Ampere/Ada Lovelace (A100, RTX 30xx/40xx, L40, L4): 12.4.1
#   Turing/Volta (RTX 20xx, T4, V100): 12.1.1
#
ARG CUDA_VERSION=12.8.1

# PYTORCH_INDEX — PyTorch wheel index tag.
#   Must correspond to the CUDA version above.
#   cu128 → CUDA 12.8, cu124 → CUDA 12.4, cu121 → CUDA 12.1
#
ARG PYTORCH_INDEX=cu128

# PYTHON_VERSION — Python interpreter version.
#   3.12 is the recommended version for ComfyUI as of 2026.
#   Change only if a specific node requires a different version.
#
ARG PYTHON_VERSION=3.12

# ENABLE_SAGE_ATTENTION — Install SageAttention 2 + Triton.
#   Provides 2-3x faster attention on supported GPUs.
#   Requires Ampere (SM 80) or newer. On Hopper/Blackwell
#   it enables FP8 attention (SageAttention v2).
#   Set to "false" for Turing (RTX 20xx, T4) or Volta (V100).
#
ARG ENABLE_SAGE_ATTENTION=true

# ENABLE_FLASH_ATTENTION — Install FlashAttention.
#   Memory-efficient fused attention kernels.
#   v2 on Ampere/Ada Lovelace, v3 on Hopper/Blackwell.
#   Requires Ampere (SM 80) or newer.
#   Set to "false" for Turing (RTX 20xx, T4) or Volta (V100).
#   NOTE: Builds from source — may take 20-30 minutes.
#
ARG ENABLE_FLASH_ATTENTION=true

# ── GPU COMPATIBILITY TABLE ────────────────────────────────
#
# Use this table to pick the right build args for your GPU.
#
# ┌─────────────────┬────────┬────────┬──────────────┬───────────────┬───────────┬────────────┐
# │ GPU             │ VRAM   │ Arch   │ CUDA_VERSION │ PYTORCH_INDEX │ SAGE_ATTN │ FLASH_ATTN │
# ├─────────────────┼────────┼────────┼──────────────┼───────────────┼───────────┼────────────┤
# │ B200            │ 192 GB │ SM 100 │ 12.8.1       │ cu128         │ v2 (fp8)  │ v3         │
# │ B100            │  80 GB │ SM 100 │ 12.8.1       │ cu128         │ v2 (fp8)  │ v3         │
# │ H200            │ 141 GB │ SM 90  │ 12.8.1       │ cu128         │ v2 (fp8)  │ v3         │
# │ H100            │  80 GB │ SM 90  │ 12.8.1       │ cu128         │ v2 (fp8)  │ v3         │
# │ H100 NVL        │  94 GB │ SM 90  │ 12.8.1       │ cu128         │ v2 (fp8)  │ v3         │
# ├─────────────────┼────────┼────────┼──────────────┼───────────────┼───────────┼────────────┤
# │ A100 (80 GB)    │  80 GB │ SM 80  │ 12.4.1       │ cu124         │ v1        │ v2         │
# │ A100 (40 GB)    │  40 GB │ SM 80  │ 12.4.1       │ cu124         │ v1        │ v2         │
# │ A6000           │  48 GB │ SM 86  │ 12.4.1       │ cu124         │ v1        │ v2         │
# │ A5000           │  24 GB │ SM 86  │ 12.4.1       │ cu124         │ v1        │ v2         │
# │ A4000           │  16 GB │ SM 86  │ 12.4.1       │ cu124         │ v1        │ v2         │
# ├─────────────────┼────────┼────────┼──────────────┼───────────────┼───────────┼────────────┤
# │ L40S            │  48 GB │ SM 89  │ 12.4.1       │ cu124         │ v1        │ v2         │
# │ L40             │  48 GB │ SM 89  │ 12.4.1       │ cu124         │ v1        │ v2         │
# │ L4              │  24 GB │ SM 89  │ 12.4.1       │ cu124         │ v1        │ v2         │
# ├─────────────────┼────────┼────────┼──────────────┼───────────────┼───────────┼────────────┤
# │ RTX 4090        │  24 GB │ SM 89  │ 12.4.1       │ cu124         │ v1        │ v2         │
# │ RTX 4080 SUPER  │  16 GB │ SM 89  │ 12.4.1       │ cu124         │ v1        │ v2         │
# │ RTX 4080        │  16 GB │ SM 89  │ 12.4.1       │ cu124         │ v1        │ v2         │
# │ RTX 4070 Ti     │  12 GB │ SM 89  │ 12.4.1       │ cu124         │ v1        │ v2         │
# │ RTX 4070        │  12 GB │ SM 89  │ 12.4.1       │ cu124         │ v1        │ v2         │
# │ RTX 4060 Ti     │  16 GB │ SM 89  │ 12.4.1       │ cu124         │ v1        │ v2         │
# │ RTX 4060        │   8 GB │ SM 89  │ 12.4.1       │ cu124         │ v1        │ v2         │
# ├─────────────────┼────────┼────────┼──────────────┼───────────────┼───────────┼────────────┤
# │ RTX 3090        │  24 GB │ SM 86  │ 12.4.1       │ cu124         │ v1        │ v2         │
# │ RTX 3090 Ti     │  24 GB │ SM 86  │ 12.4.1       │ cu124         │ v1        │ v2         │
# │ RTX 3080 Ti     │  12 GB │ SM 86  │ 12.4.1       │ cu124         │ v1        │ v2         │
# │ RTX 3080        │  10 GB │ SM 86  │ 12.4.1       │ cu124         │ v1        │ v2         │
# │ RTX 3070 Ti     │   8 GB │ SM 86  │ 12.4.1       │ cu124         │ v1        │ v2         │
# │ RTX 3070        │   8 GB │ SM 86  │ 12.4.1       │ cu124         │ v1        │ v2         │
# │ RTX 3060        │  12 GB │ SM 86  │ 12.4.1       │ cu124         │ v1        │ v2         │
# ├─────────────────┼────────┼────────┼──────────────┼───────────────┼───────────┼────────────┤
# │ RTX 2080 Ti     │  11 GB │ SM 75  │ 12.1.1       │ cu121         │ no        │ no         │
# │ RTX 2080 SUPER  │   8 GB │ SM 75  │ 12.1.1       │ cu121         │ no        │ no         │
# │ RTX 2080        │   8 GB │ SM 75  │ 12.1.1       │ cu121         │ no        │ no         │
# │ RTX 2070        │   8 GB │ SM 75  │ 12.1.1       │ cu121         │ no        │ no         │
# │ T4              │  16 GB │ SM 75  │ 12.1.1       │ cu121         │ no        │ no         │
# ├─────────────────┼────────┼────────┼──────────────┼───────────────┼───────────┼────────────┤
# │ V100 (32 GB)    │  32 GB │ SM 70  │ 12.1.1       │ cu121         │ no        │ no         │
# │ V100 (16 GB)    │  16 GB │ SM 70  │ 12.1.1       │ cu121         │ no        │ no         │
# └─────────────────┴────────┴────────┴──────────────┴───────────────┴───────────┴────────────┘
#
# NOTES:
# - SageAttention v2 (FP8 kernels): Hopper/Blackwell only (SM 90+)
# - SageAttention v1: Ampere and newer (SM 80+), includes Ada Lovelace (RTX 40xx)
# - FlashAttention v3: Hopper and newer (SM 90+)
# - FlashAttention v2: Ampere and newer (SM 80+)
# - Turing (RTX 20xx, T4) and Volta (V100): neither SageAttention nor FlashAttention
# - xformers: works on all GPUs listed above
# - torch.compile: works on all GPUs, most effective on Ampere+
#
# EXAMPLES:
#   Default (B200):
#     docker build -t comfyui-studio .
#
#   A100 / RTX 3090 / RTX 4090:
#     docker build -t comfyui-studio \
#       --build-arg CUDA_VERSION=12.4.1 \
#       --build-arg PYTORCH_INDEX=cu124 .
#
#   T4 / V100 (no attention optimizations):
#     docker build -t comfyui-studio \
#       --build-arg CUDA_VERSION=12.1.1 \
#       --build-arg PYTORCH_INDEX=cu121 \
#       --build-arg ENABLE_SAGE_ATTENTION=false \
#       --build-arg ENABLE_FLASH_ATTENTION=false .
#

FROM nvidia/cuda:${CUDA_VERSION}-cudnn-devel-ubuntu24.04

# Re-declare ARGs after FROM (Docker scoping rule)
ARG PYTHON_VERSION
ARG PYTORCH_INDEX
ARG ENABLE_SAGE_ATTENTION
ARG ENABLE_FLASH_ATTENTION

# ── environment variables ──────────────────────────────────
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PIP_PREFER_BINARY=1
ENV PIP_NO_CACHE_DIR=1
ENV HF_HUB_ENABLE_HF_TRANSFER=1

# ── system dependencies ───────────────────────────────────
# build-essential + cmake + gfortran + ninja: compile dlib, C++ extensions
# libopenblas-dev + liblapack-dev: BLAS/LAPACK for dlib, scipy, numpy
# ffmpeg: video encode/decode for VideoHelperSuite
# libgl1 + libglib2.0-0 + libsm6 + libxext6 + libxrender1: OpenCV runtime
RUN apt-get update && apt-get install -y \
    python${PYTHON_VERSION} \
    python${PYTHON_VERSION}-venv \
    python${PYTHON_VERSION}-dev \
    python3-pip \
    build-essential \
    cmake \
    gfortran \
    ninja-build \
    pkg-config \
    libopenblas-dev \
    liblapack-dev \
    git \
    wget \
    curl \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && ln -sf /usr/bin/python${PYTHON_VERSION} /usr/bin/python3 \
    && ln -sf /usr/bin/python${PYTHON_VERSION} /usr/bin/python \
    && apt-get autoremove -y \
    && apt-get clean -y \
    && rm -rf /var/lib/apt/lists/*

# ── virtual environment ───────────────────────────────────
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# ── PyTorch (matched to CUDA via PYTORCH_INDEX) ──────────
# cmake pip package: ensures the Python cmake wrapper works correctly.
# Some nodes (was-node-suite) install cmake via pip which can create
# a broken wrapper; installing it explicitly here prevents that.
RUN pip install --upgrade pip setuptools wheel cmake && \
    pip install \
        torch \
        torchvision \
        torchaudio \
        --index-url https://download.pytorch.org/whl/${PYTORCH_INDEX}

# ── xformers (always installed — works on all GPUs) ──────
RUN pip install xformers

# ── SageAttention (conditional — Ampere+ only) ───────────
# SageAttention v2 on Hopper/Blackwell provides FP8 attention.
# SageAttention v1 on Ampere/Ada Lovelace provides optimized kernels.
# Triton is required as a dependency.
RUN if [ "${ENABLE_SAGE_ATTENTION}" = "true" ]; then \
      echo "=== Installing SageAttention + Triton ===" && \
      pip install triton sageattention; \
    else \
      echo "=== Skipping SageAttention (disabled) ==="; \
    fi

# ── FlashAttention (conditional — Ampere+ only) ──────────
# Builds from source — this step can take 20-30 minutes.
# v3 on Hopper/Blackwell, v2 on Ampere/Ada Lovelace.
RUN if [ "${ENABLE_FLASH_ATTENTION}" = "true" ]; then \
      echo "=== Installing FlashAttention ===" && \
      pip install flash-attn --no-build-isolation; \
    else \
      echo "=== Skipping FlashAttention (disabled) ==="; \
    fi

# ── ComfyUI core in /comfyui ─────────────────────────────
# NOT in /workspace — that is the Network Volume, mounted at
# runtime and overwrites anything placed there during build.
WORKDIR /comfyui
RUN git clone https://github.com/comfyanonymous/ComfyUI.git . && \
    pip install -r requirements.txt

# ── Custom nodes: install helper ──────────────────────────
# install_nodes.sh reads nodes.txt and installs nodes between
# section markers. COPY as a real file instead of generating
# inline to avoid shell escaping issues.
COPY nodes.txt /tmp/nodes.txt
COPY install_nodes.sh /tmp/install_nodes.sh
RUN chmod +x /tmp/install_nodes.sh

# ── Custom nodes: Fundamentals / QoL ─────────────────────
WORKDIR /comfyui/custom_nodes
RUN /tmp/install_nodes.sh "Fundamentals" "Image Generation" "${PYTORCH_INDEX}"

# ── Custom nodes: Image Generation ───────────────────────
RUN /tmp/install_nodes.sh "Image Generation" "Video Generation" "${PYTORCH_INDEX}"

# ── Custom nodes: Video Generation ───────────────────────
RUN /tmp/install_nodes.sh "Video Generation" "CivitAI Integration" "${PYTORCH_INDEX}"

# ── Custom nodes: CivitAI Integration ────────────────────
RUN /tmp/install_nodes.sh "CivitAI Integration" "ENDOFFILE" "${PYTORCH_INDEX}"

# ── Clean up ──────────────────────────────────────────────
RUN rm -rf /root/.cache/pip /tmp/nodes.txt /tmp/install_nodes.sh

# ── FastAPI + backoffice dependencies ─────────────────────
RUN pip install \
    fastapi \
    "uvicorn[standard]" \
    httpx \
    python-multipart \
    huggingface_hub \
    aiofiles \
    requests \
    pyyaml

# ── App files ─────────────────────────────────────────────
COPY app/ /app/
COPY version.json /app/version.json

# ── Startup script ────────────────────────────────────────
COPY start.sh /start.sh
RUN chmod +x /start.sh

WORKDIR /
EXPOSE 8188 8000

CMD ["/start.sh"]
