# llama-server

The Docker image optionally includes a compiled llama.cpp server binary for GPU-accelerated LLM inference. The binary is installed at `/opt/llama-server` and managed at runtime by ComfyUI Studio's LLM module.

## Overview

llama-server is a standalone HTTP server from the [llama.cpp](https://github.com/ggerganov/llama.cpp) project. It loads GGUF-format language models and serves an OpenAI-compatible chat/completion API. In the Docker image, it is compiled from source with CUDA support so that inference runs on the GPU.

The binary is used by ComfyUI Studio's LLM page (`/admin/llm`) to:

- Start/stop an LLM server with a selected GGUF model
- Run chat conversations directly on the pod GPU
- Provide AI-assisted prompt generation for image/video workflows

## Compilation

The llama-server build step in the Dockerfile:

```dockerfile
RUN if [ "${ENABLE_LLM}" = "true" ]; then \
      CUDA_ARCHS="75;80;86;89;90;100" && \
      if [ "$LLAMA_CPP_VERSION" = "latest" ]; then \
        git clone --depth 1 https://github.com/ggerganov/llama.cpp.git /tmp/llama.cpp; \
      else \
        git clone --depth 1 --branch "$LLAMA_CPP_VERSION" \
          https://github.com/ggerganov/llama.cpp.git /tmp/llama.cpp; \
      fi && \
      cd /tmp/llama.cpp && \
      cmake -B build \
          -DGGML_CUDA=ON \
          -DGGML_NATIVE=OFF \
          -DCMAKE_BUILD_TYPE=Release \
          -DCMAKE_CUDA_ARCHITECTURES="$CUDA_ARCHS" \
          -DLLAMA_BUILD_TESTS=OFF \
          -DCMAKE_EXE_LINKER_FLAGS=-Wl,--allow-shlib-undefined && \
      cmake --build build --config Release -j$(nproc) --target llama-server && \
      cp build/bin/llama-server /opt/llama-server && \
      rm -rf /tmp/llama.cpp; \
    fi
```

## Build Flags

The CMake flags are based on the [llama.cpp official CUDA Dockerfile](https://github.com/ggml-org/llama.cpp/blob/master/.devops/cuda.Dockerfile):

| Flag | Value | Purpose |
|------|-------|---------|
| `GGML_CUDA` | `ON` | Enable CUDA backend for GPU-accelerated inference |
| `GGML_NATIVE` | `OFF` | Disable native CPU detection -- the build machine's CPU is not the runtime CPU |
| `CMAKE_BUILD_TYPE` | `Release` | Optimized release build |
| `CMAKE_CUDA_ARCHITECTURES` | `75;80;86;89;90;100` | Compile CUDA kernels for all supported GPU architectures |
| `LLAMA_BUILD_TESTS` | `OFF` | Skip test compilation to reduce build time |
| `CMAKE_EXE_LINKER_FLAGS` | `-Wl,--allow-shlib-undefined` | Allow unresolved shared library symbols at link time |

### CUDA Architecture Targets

The `CMAKE_CUDA_ARCHITECTURES` value covers every GPU generation from Turing through Blackwell:

| SM | GPU Generation | Example GPUs |
|----|---------------|-------------|
| 75 | Turing | RTX 2080 Ti, RTX 2070, T4 |
| 80 | Ampere | A100 |
| 86 | Ampere | A6000, A5000, RTX 3090, RTX 3060 |
| 89 | Ada Lovelace | L40S, L4, RTX 4090, RTX 4060 |
| 90 | Hopper | H100, H200 |
| 100 | Blackwell | B100, B200 |

Each target architecture adds compilation time because nvcc must generate PTX and SASS code for that specific SM version. This is why building for all 6 architectures takes significantly longer than building for a single one.

### The --allow-shlib-undefined Linker Flag

This flag deserves special explanation. During the Docker build, the CUDA toolkit provides stub libraries (e.g., `libcuda.so`) for linking. However, these stubs do not include the versioned soname (`libcuda.so.1`) that the linker expects when resolving dependencies.

At runtime, the NVIDIA Container Toolkit mounts the real GPU driver libraries from the host into the container. These real libraries provide the correct soname. The `--allow-shlib-undefined` flag tells the linker to accept unresolved symbols at link time, deferring resolution to runtime when the real driver is available.

Without this flag, the build would fail with:

```
/usr/bin/ld: cannot find -lcuda
```

or produce a binary that fails symbol resolution checks.

## Version Pinning

The `LLAMA_CPP_VERSION` build argument controls which llama.cpp release is built:

| Value | Behavior |
|-------|----------|
| `b8505` (default) | Clones the `b8505` git tag -- a known-good release pinned on 2026-03-24 |
| `latest` | Clones HEAD without a tag (`--depth 1`, no `--branch`) |
| Custom tag | Clones the specified tag (e.g., `b8400`) |

The default is pinned to ensure reproducible builds. The llama.cpp project moves fast -- using `latest` provides the newest features but risks build failures from upstream changes.

To update the pinned version, change the `ARG LLAMA_CPP_VERSION=b8505` default in the Dockerfile.

## Build Time

Compilation time depends on the build environment:

| Environment | Time | Reason |
|-------------|------|--------|
| Machine with target GPU | ~10 min | Compiler can auto-detect GPU, fewer kernel variants needed |
| CI runner without GPU (e.g., GitHub Actions) | ~60 min | Must compile CUDA kernels for all 6 architectures |

The build uses all available cores (`-j$(nproc)`) and only compiles the `llama-server` target (not the full llama.cpp suite).

### Skipping the Build

Set `ENABLE_LLM=false` to skip llama-server compilation entirely:

```bash
docker build -f docker/Dockerfile -t comfyui-studio \
  --build-arg ENABLE_LLM=false \
  .
```

This saves ~60 minutes on CI builds. The LLM page in ComfyUI Studio will show an error if `llama-server` is not found at the configured path.

## Layer Caching

The llama-server build step is intentionally placed **before** the custom node installation in the Dockerfile:

```dockerfile
# llama-server compilation (expensive, ~60 min)
RUN if [ "${ENABLE_LLM}" = "true" ]; then ...

# Custom nodes (cheaper, ~15 min)
COPY docker/nodes.txt /tmp/nodes.txt
COPY docker/install_nodes.sh /tmp/install_nodes.sh
RUN /tmp/install_nodes.sh ...
```

This means changing `nodes.txt` (adding or removing a custom node) does **not** invalidate the llama-server layer. The expensive 60-minute compilation is cached and reused. Only changes to the Dockerfile lines above the node installation -- such as changing `LLAMA_CPP_VERSION`, `ENABLE_LLM`, or the CUDA/PyTorch versions -- trigger a recompilation.

## Runtime

At runtime, the llama-server binary is managed by `backend/llm_server.py`:

- **Start:** Launches the binary as a subprocess with the selected GGUF model, binding to `127.0.0.1` on the configured port (default 8080)
- **Stop:** Sends SIGTERM, waits 10 seconds, then SIGKILL if needed
- **Status:** Checks if the subprocess is alive via `poll()`

Configuration is stored at `STUDIO_DIR/llm/config.json` and includes:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `n_gpu_layers` | 99 | Number of model layers to offload to GPU (99 = all) |
| `ctx_size` | 8192 | Context window size in tokens |
| `threads` | 4 | Number of CPU threads for non-GPU operations |

GGUF model files are stored in `STUDIO_DIR/llm/models/` and downloaded via the LLM page from HuggingFace.

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLAMA_SERVER_PATH` | `/opt/llama-server` | Path to the compiled binary |
| `LLAMA_SERVER_PORT` | `8080` | Port the server listens on |
