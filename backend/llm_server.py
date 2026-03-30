"""ComfyUI Studio — LLM server process manager (multi-instance llama-server)."""

import json
import subprocess
import threading
from pathlib import Path

from config import LLM_MODELS_DIR, LLM_CONFIG_PATH, LLAMA_SERVER_PATH, LLAMA_SERVER_PORT, DEV_MODE, _now_rome

# ── LLM Multi-Instance Registry ─────────────────────────────────────────────
# key = model filename
# value = {"process": Popen|None, "port": int, "config": dict,
#          "log_path": Path, "started_at": str}

_instances: dict[str, dict] = {}
_instances_lock = threading.Lock()

_LOG_DIR = LLM_MODELS_DIR.parent / "logs"


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


def _next_port() -> int:
    """Find next available port starting from LLAMA_SERVER_PORT."""
    used = {inst["port"] for inst in _instances.values()}
    port = LLAMA_SERVER_PORT
    while port in used:
        port += 1
    return port


def _is_running(model_file: str) -> bool:
    """Check if a specific model instance is alive."""
    inst = _instances.get(model_file)
    if inst is None:
        return False
    if DEV_MODE:
        return True  # dev instances are always "running" while in registry
    proc = inst.get("process")
    if proc is None:
        return False
    return proc.poll() is None


def _get_running_instances() -> list[dict]:
    """Return list of running instances with port, model, started_at."""
    result = []
    with _instances_lock:
        dead = []
        for model_file, inst in _instances.items():
            if DEV_MODE or (inst.get("process") and inst["process"].poll() is None):
                result.append({
                    "model": model_file,
                    "port": inst["port"],
                    "started_at": inst.get("started_at", ""),
                    "config": {k: v for k, v in inst.get("config", {}).items() if not k.startswith("_")},
                })
            else:
                dead.append(model_file)
        # Clean up dead instances
        for m in dead:
            del _instances[m]
    return result


def _start_llama_server(model_file: str, config: dict) -> int:
    """Start a NEW llama-server instance. Returns the assigned port."""
    from events import _events

    with _instances_lock:
        # If already running, raise
        if model_file in _instances:
            if DEV_MODE or (_instances[model_file].get("process") and _instances[model_file]["process"].poll() is None):
                raise RuntimeError(f"Model '{model_file}' is already running on port {_instances[model_file]['port']}")
            else:
                # Dead process, clean up
                del _instances[model_file]

        model_path = LLM_MODELS_DIR / model_file
        if not model_path.exists():
            raise FileNotFoundError(f"Model file not found: {model_path}")

        port = _next_port()
        started_at = _now_rome()

        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = _LOG_DIR / f"{model_file}.log"

        if DEV_MODE:
            _instances[model_file] = {
                "process": None,
                "port": port,
                "config": config,
                "log_path": log_path,
                "started_at": started_at,
            }
            # Write a fake log line
            log_path.write_text(f"[DEV MODE] llama-server stub started for {model_file} on port {port}\n")
            _events.emit("llm.server.started", f"LLM instance started (dev stub): {model_file} on port {port}",
                         data={"model": model_file, "port": port})
            return port

        if not LLAMA_SERVER_PATH.exists():
            raise FileNotFoundError(f"llama-server binary not found: {LLAMA_SERVER_PATH}")

        cmd = [
            str(LLAMA_SERVER_PATH),
            "--model", str(model_path),
            "--port", str(port),
            "--host", "127.0.0.1",
            "--n-gpu-layers", str(config.get("n_gpu_layers", 99)),
            "--ctx-size", str(config.get("ctx_size", 8192)),
            "--threads", str(config.get("threads", 4)),
        ]

        log_file = open(log_path, "w")
        process = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)

        _instances[model_file] = {
            "process": process,
            "port": port,
            "config": config,
            "log_path": log_path,
            "started_at": started_at,
            "_log_file": log_file,
        }

        _events.emit("llm.server.started", f"LLM instance started: {model_file} on port {port}",
                     data={"model": model_file, "port": port})
        return port


def _stop_llama_server(model_file: str) -> None:
    """Stop a specific model instance."""
    from events import _events

    with _instances_lock:
        inst = _instances.pop(model_file, None)
        if inst is None:
            return

        if not DEV_MODE and inst.get("process"):
            try:
                inst["process"].terminate()
                inst["process"].wait(timeout=10)
            except subprocess.TimeoutExpired:
                inst["process"].kill()
                inst["process"].wait(timeout=5)
            except Exception:
                pass
            # Close log file handle if present
            lf = inst.get("_log_file")
            if lf:
                try:
                    lf.close()
                except Exception:
                    pass

        _events.emit("llm.server.stopped", f"LLM instance stopped: {model_file}",
                     data={"model": model_file})


def _stop_all() -> None:
    """Stop all running instances."""
    with _instances_lock:
        models = list(_instances.keys())
    for m in models:
        _stop_llama_server(m)


def _get_instance_log(model_file: str, tail: int = 50) -> str:
    """Read last N lines of a specific instance's log."""
    log_path = _LOG_DIR / f"{model_file}.log"
    if not log_path.exists():
        return ""
    try:
        lines = log_path.read_text().splitlines()
        return "\n".join(lines[-tail:])
    except Exception:
        return ""


def _get_instance_port(model_file: str) -> int | None:
    """Get the port for a running model instance."""
    inst = _instances.get(model_file)
    if inst is None:
        return None
    return inst["port"]
