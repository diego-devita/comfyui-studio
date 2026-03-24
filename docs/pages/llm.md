# LLM Assistant

The LLM management page at `/admin/llm`. Download GGUF language models, control the llama-server process, and chat with a locally running LLM.

## Layout

The page has three main sections:

1. **Server control panel** -- start/stop the LLM server, select model and configuration
2. **Model catalog** -- list of available GGUF models with download/delete
3. **Chat area** -- interactive chat interface (visible when the server is running)

## Server Control Panel

A bordered panel at the top with:

### Status Indicator

A colored dot with text showing the server state:

- **Green dot** + "Running" + model name -- server is active
- **Grey dot** + "Stopped" -- server is not running

### Model Selector

A dropdown populated with only downloaded models (those with `status: present`). Users select which model to load before starting the server.

### Configuration Fields

- **GPU Layers** (`n_gpu_layers`) -- number of layers offloaded to GPU (default: 99, meaning all layers)
- **Context Size** (`ctx_size`) -- context window in tokens (default: 8192)
- **Threads** -- CPU threads for inference (default: 4)

Configuration is persisted to `STUDIO_DIR/llm/config.json` on start.

### Server Actions

- **Start** button -- calls `POST /api/admin/llm/start` with the selected model and config. The backend spawns a `llama-server` subprocess with the specified parameters.
- **Stop** button -- calls `POST /api/admin/llm/stop` to terminate the subprocess.

On page load, the frontend checks server status via `GET /api/admin/llm/status` and updates the indicator accordingly. If the server is already running, the panel shows which model is loaded and the server port.

## Model Catalog

Below the server panel, a list of LLM model cards loaded from:

```
GET /api/admin/llm/models
```

Each card shows:

- **Model name** -- display name from the catalog
- **File size** -- in GB
- **Quantization type** -- e.g., Q8_0, Q4_K_M (shown as a tag)
- **Status badge** -- present (green), missing (grey), downloading (yellow with animation)
- **Actions**:
    - **Download** -- `POST /api/admin/llm/models/download/{filename}` to queue the download
    - **Delete** -- `DELETE /api/admin/llm/models/{filename}` with confirm dialog

Download progress is shown with a progress bar on the card. Downloads use the same shared download queue as model/LoRA downloads.

Models are stored in `STUDIO_DIR/llm/models/`.

## Chat Area

Visible when the server is running. Provides a simple chat interface:

- **Message history** -- scrollable area showing user and assistant messages in alternating styles (user messages have a yellow-tinted background, assistant messages have a subtle border)
- **Input field** -- a textarea for typing messages
- **Send button** -- submits the message to the LLM

Chat calls `POST /api/admin/llm/chat` with the conversation history. The response streams back from the llama-server running on `127.0.0.1:LLAMA_SERVER_PORT`. Messages are rendered with monospace font and preserve whitespace.

Error responses (server not running, model not loaded) are displayed in red-tinted message bubbles.

## Architecture Notes

The llama-server binary is baked into the Docker image at `/opt/llama-server`, compiled with CUDA support for GPU inference. It runs as a subprocess managed by `llm_server.py`, listening on `127.0.0.1:8080` by default (not exposed externally).

Only one model can be loaded at a time. Starting the server with a new model automatically stops the previous instance.

## Related Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/admin/llm/models` | GET | List LLM model catalog with status |
| `/api/admin/llm/models/download/{filename}` | POST | Queue model download |
| `/api/admin/llm/models/{filename}` | DELETE | Delete model from disk |
| `/api/admin/llm/status` | GET | Server running status |
| `/api/admin/llm/start` | POST | Start llama-server with model |
| `/api/admin/llm/stop` | POST | Stop llama-server |
| `/api/admin/llm/chat` | POST | Send chat message |
