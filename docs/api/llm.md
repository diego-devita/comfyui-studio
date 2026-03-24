# LLM API

Endpoints for managing LLM (Large Language Model) GGUF models and the llama.cpp server. The LLM server binary is baked into the Docker image at `/opt/llama-server` and compiled with CUDA support.

---

## GET /api/admin/llm/models

List LLM models from the catalog with download/presence status.

**Auth:** Required

**Response:** `200 OK`

```json
{
  "version": 3,
  "date": "2026-03-21 08:00",
  "categories": [
    {
      "id": "general",
      "name": "General",
      "models": [
        {
          "name": "Qwen2.5 7B Instruct Q4_K_M",
          "file": "qwen2.5-7b-instruct-q4_k_m.gguf",
          "dest": ".",
          "size_gb": 4.4,
          "status": "present",
          "on_disk_bytes": 4724464640,
          "source": "huggingface",
          "hf_repo": "Qwen/Qwen2.5-7B-Instruct-GGUF"
        }
      ]
    }
  ],
  "summary": {
    "total": 5,
    "present": 2
  }
}
```

```bash
curl https://your-pod.runpod.io/api/admin/llm/models \
  -H "X-API-Key: your-api-key"
```

---

## POST /api/admin/llm/models/download/{filename}

Queue an LLM model for download.

**Auth:** Required

**Path parameters:**

| Parameter | Description |
|-----------|-------------|
| `filename` | The GGUF model filename from the catalog |

**Response:** `200 OK`

```json
{
  "status": "queued",
  "file": "qwen2.5-7b-instruct-q4_k_m.gguf"
}
```

If already downloading or queued:

```json
{
  "status": "downloading",
  "file": "qwen2.5-7b-instruct-q4_k_m.gguf"
}
```

**Error response:** `404 Not Found`

```json
{
  "detail": "LLM model 'nonexistent.gguf' not found in catalog"
}
```

```bash
curl -X POST https://your-pod.runpod.io/api/admin/llm/models/download/qwen2.5-7b-instruct-q4_k_m.gguf \
  -H "X-API-Key: your-api-key"
```

---

## DELETE /api/admin/llm/models/{filename}

Delete an LLM model file from disk.

**Auth:** Required

**Path parameters:**

| Parameter | Description |
|-----------|-------------|
| `filename` | The GGUF model filename |

**Response:** `200 OK`

```json
{
  "status": "deleted",
  "file": "qwen2.5-7b-instruct-q4_k_m.gguf"
}
```

**Error response:** `404 Not Found`

```json
{
  "detail": "LLM model 'nonexistent.gguf' not found in catalog"
}
```

```bash
curl -X DELETE https://your-pod.runpod.io/api/admin/llm/models/qwen2.5-7b-instruct-q4_k_m.gguf \
  -H "X-API-Key: your-api-key"
```

---

## GET /api/admin/llm/status

Get the LLM server status, active model, configuration, and health.

**Auth:** Required

**Response:** `200 OK`

```json
{
  "running": true,
  "active_model": "qwen2.5-7b-instruct-q4_k_m.gguf",
  "config": {
    "n_gpu_layers": 99,
    "ctx_size": 8192,
    "threads": 4,
    "temp": 0.7,
    "top_p": 0.9,
    "top_k": 40,
    "repeat_penalty": 1.1
  },
  "health": {
    "status": "ok"
  },
  "port": 8080,
  "binary_exists": true
}
```

| Field | Description |
|-------|-------------|
| `running` | Whether the llama-server process is alive |
| `active_model` | Currently loaded model filename, or `null` |
| `config` | Server configuration (internal keys starting with `_` are excluded) |
| `health` | Health check response from llama-server `/health`, or `null` if not running |
| `port` | The port llama-server is listening on |
| `binary_exists` | Whether `/opt/llama-server` binary exists |

```bash
curl https://your-pod.runpod.io/api/admin/llm/status \
  -H "X-API-Key: your-api-key"
```

---

## POST /api/admin/llm/start

Start the llama-server with a specific model and optional config overrides.

**Auth:** Required

**Request body:**

```json
{
  "model": "qwen2.5-7b-instruct-q4_k_m.gguf",
  "n_gpu_layers": 99,
  "ctx_size": 8192,
  "threads": 4,
  "temp": 0.7,
  "top_p": 0.9,
  "top_k": 40,
  "repeat_penalty": 1.1
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model` | string | Yes | GGUF model filename to load |
| `n_gpu_layers` | integer | No | Number of layers to offload to GPU |
| `ctx_size` | integer | No | Context window size in tokens |
| `threads` | integer | No | Number of CPU threads |
| `temp` | float | No | Sampling temperature |
| `top_p` | float | No | Top-p sampling |
| `top_k` | integer | No | Top-k sampling |
| `repeat_penalty` | float | No | Repetition penalty |

**Response:** `200 OK`

```json
{
  "status": "started",
  "model": "qwen2.5-7b-instruct-q4_k_m.gguf",
  "port": 8080
}
```

**Error responses:**

- `400 Bad Request` -- Missing `model` field or invalid JSON
- `404 Not Found` -- Model file not found on disk
- `500 Internal Server Error` -- Failed to start llama-server

```bash
curl -X POST https://your-pod.runpod.io/api/admin/llm/start \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"model": "qwen2.5-7b-instruct-q4_k_m.gguf", "ctx_size": 8192}'
```

---

## POST /api/admin/llm/stop

Stop the running llama-server process.

**Auth:** Required

**Request body:** None

**Response:** `200 OK`

```json
{
  "status": "stopped"
}
```

If the server is already stopped:

```json
{
  "status": "already_stopped"
}
```

```bash
curl -X POST https://your-pod.runpod.io/api/admin/llm/stop \
  -H "X-API-Key: your-api-key"
```

---

## POST /api/admin/llm/config

Update the LLM server configuration without restarting. The config is persisted to `STUDIO_DIR/llm/config.json`.

**Auth:** Required

**Request body:**

```json
{
  "n_gpu_layers": 99,
  "ctx_size": 16384,
  "temp": 0.8
}
```

Accepts the same fields as `POST /api/admin/llm/start` (except `model`).

**Response:** `200 OK`

```json
{
  "status": "saved",
  "config": {
    "n_gpu_layers": 99,
    "ctx_size": 16384,
    "threads": 4,
    "temp": 0.8,
    "top_p": 0.9,
    "top_k": 40,
    "repeat_penalty": 1.1
  }
}
```

```bash
curl -X POST https://your-pod.runpod.io/api/admin/llm/config \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"ctx_size": 16384, "temp": 0.8}'
```

---

## POST /api/admin/llm/chat

Chat completion via the llama-server. Proxies to the llama.cpp `/v1/chat/completions` endpoint. Supports both streaming and non-streaming modes.

**Auth:** Required

**Request body:**

```json
{
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello!"}
  ],
  "stream": true,
  "temperature": 0.7,
  "top_p": 0.9,
  "top_k": 40,
  "repeat_penalty": 1.1,
  "max_tokens": 2048
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `messages` | array | Yes | Array of `{role, content}` objects |
| `stream` | boolean | No | Enable streaming (default: `false`) |
| `temperature` | float | No | Overrides server config |
| `top_p` | float | No | Overrides server config |
| `top_k` | integer | No | Overrides server config |
| `repeat_penalty` | float | No | Overrides server config |
| `max_tokens` | integer | No | Maximum tokens to generate |

**Response (non-streaming):** `200 OK`

Returns the standard OpenAI-compatible chat completion response from llama.cpp.

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "Hello! How can I help you?"},
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 20,
    "completion_tokens": 8,
    "total_tokens": 28
  }
}
```

**Response (streaming):** `200 OK` with `text/event-stream`

Returns a Server-Sent Events stream in OpenAI-compatible format:

```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"delta":{"content":"Hello"},"index":0}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"delta":{"content":"!"},"index":0}]}

data: [DONE]
```

**Error responses:**

- `400 Bad Request` -- Invalid JSON body
- `503 Service Unavailable` -- LLM server is not running or unreachable

```bash
# Non-streaming
curl -X POST https://your-pod.runpod.io/api/admin/llm/chat \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello!"}]}'

# Streaming
curl -N -X POST https://your-pod.runpod.io/api/admin/llm/chat \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello!"}], "stream": true}'
```
