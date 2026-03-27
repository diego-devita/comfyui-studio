"""ComfyUI Studio — LLM server process manager (llama-server subprocess)."""

import json
import subprocess
import threading

from config import LLM_MODELS_DIR, LLM_CONFIG_PATH, LLAMA_SERVER_PATH, LLAMA_SERVER_PORT, DEV_MODE

# ── LLM Server Process Manager ──────────────────────────────────────────────

_llama_process: subprocess.Popen | None = None
_llama_process_lock = threading.Lock()
_dev_mode_running = False  # fake running state for DEV_MODE


def _load_llm_config() -> dict:
    """Load LLM config from disk with defaults."""
    defaults = {
        "n_gpu_layers": 99,
        "ctx_size": 8192,
        "threads": 4,
        "temp": 0.7,
        "top_p": 0.9,
        "top_k": 40,
        "repeat_penalty": 1.1,
    }
    if LLM_CONFIG_PATH.exists():
        try:
            saved = json.loads(LLM_CONFIG_PATH.read_text())
            defaults.update(saved)
        except Exception:
            pass
    return defaults


def _save_llm_config(config: dict) -> None:
    """Write LLM config to disk."""
    LLM_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LLM_CONFIG_PATH.write_text(json.dumps(config, indent=2))


def _llama_server_running() -> bool:
    """Check if the llama-server subprocess is alive."""
    global _llama_process, _dev_mode_running
    if DEV_MODE:
        return _dev_mode_running
    if _llama_process is None:
        return False
    return _llama_process.poll() is None


def _start_llama_server(model_file: str, config: dict) -> None:
    """Start llama-server subprocess with the given model and config."""
    from events import _events

    global _llama_process, _dev_mode_running
    with _llama_process_lock:
        if _llama_server_running():
            _stop_llama_server()

        model_path = LLM_MODELS_DIR / model_file
        if not model_path.exists():
            raise FileNotFoundError(f"Model file not found: {model_path}")

        if DEV_MODE:
            _dev_mode_running = True
            config["_active_model"] = model_file
            _save_llm_config(config)
            _events.emit("llm.server.started", f"LLM server started (dev stub) with {model_file}",
                          data={"model": model_file, "port": LLAMA_SERVER_PORT})
            return

        if not LLAMA_SERVER_PATH.exists():
            raise FileNotFoundError(f"llama-server binary not found: {LLAMA_SERVER_PATH}")

        cmd = [
            str(LLAMA_SERVER_PATH),
            "--model", str(model_path),
            "--port", str(LLAMA_SERVER_PORT),
            "--host", "127.0.0.1",
            "--n-gpu-layers", str(config.get("n_gpu_layers", 99)),
            "--ctx-size", str(config.get("ctx_size", 8192)),
            "--threads", str(config.get("threads", 4)),
        ]

        _llama_process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        # Save which model is loaded
        config["_active_model"] = model_file
        _save_llm_config(config)
        _events.emit("llm.server.started", f"LLM server started with {model_file}",
                      data={"model": model_file, "port": LLAMA_SERVER_PORT})


def _stop_llama_server() -> None:
    """Terminate the llama-server subprocess."""
    from events import _events

    global _llama_process, _dev_mode_running
    with _llama_process_lock:
        if DEV_MODE:
            if _dev_mode_running:
                _dev_mode_running = False
                config = _load_llm_config()
                config.pop("_active_model", None)
                _save_llm_config(config)
                _events.emit("llm.server.stopped", "LLM server stopped (dev stub)")
            return

        if _llama_process is not None:
            try:
                _llama_process.terminate()
                _llama_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _llama_process.kill()
                _llama_process.wait(timeout=5)
            except Exception:
                pass
            _llama_process = None
            # Clear active model from config
            config = _load_llm_config()
            config.pop("_active_model", None)
            _save_llm_config(config)
            _events.emit("llm.server.stopped", "LLM server stopped")
