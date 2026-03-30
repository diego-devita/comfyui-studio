"""ComfyUI Studio — LLM server process manager (multi-instance llama-server)."""

import json
import subprocess
import threading
from pathlib import Path

from config import LLM_MODELS_DIR, LLM_CONFIG_PATH, LLAMA_SERVER_PATH, LLAMA_SERVER_PORT, DEV_MODE, _now_rome

# ── LLM Multi-Instance Registry ─────────────────────────────────────────────
# key = instance_id  (format: "{model_file}:{port}")
# value = {"process": Popen|None, "port": int, "model": str, "config": dict,
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


def _is_running(instance_id: str) -> bool:
    """Check if a specific instance is alive."""
    inst = _instances.get(instance_id)
    if inst is None:
        return False
    if DEV_MODE:
        return True  # dev instances are always "running" while in registry
    proc = inst.get("process")
    if proc is None:
        return False
    return proc.poll() is None


def _has_running_instances(model_file: str) -> bool:
    """Return True if ANY instance of the given model file is running."""
    with _instances_lock:
        for inst_id, inst in _instances.items():
            if inst.get("model") != model_file:
                continue
            if DEV_MODE:
                return True
            proc = inst.get("process")
            if proc and proc.poll() is None:
                return True
    return False


def _get_running_instances() -> list[dict]:
    """Return list of running instances with instance_id, port, model, started_at."""
    result = []
    with _instances_lock:
        dead = []
        for instance_id, inst in _instances.items():
            if DEV_MODE or (inst.get("process") and inst["process"].poll() is None):
                result.append({
                    "instance_id": instance_id,
                    "model": inst["model"],
                    "port": inst["port"],
                    "started_at": inst.get("started_at", ""),
                    "config": {k: v for k, v in inst.get("config", {}).items() if not k.startswith("_")},
                })
            else:
                dead.append(instance_id)
        # Clean up dead instances
        for iid in dead:
            del _instances[iid]
    return result


def _start_llama_server(model_file: str, config: dict) -> tuple[str, int]:
    """Start a NEW llama-server instance. Returns (instance_id, port)."""
    from events import _events

    with _instances_lock:
        model_path = LLM_MODELS_DIR / model_file
        if not model_path.exists():
            raise FileNotFoundError(f"Model file not found: {model_path}")

        port = _next_port()
        instance_id = f"{model_file}:{port}"
        started_at = _now_rome()

        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = _LOG_DIR / f"{instance_id.replace(':', '_')}.log"

        if DEV_MODE:
            _instances[instance_id] = {
                "process": None,
                "model": model_file,
                "port": port,
                "config": config,
                "log_path": log_path,
                "started_at": started_at,
            }
            # Write a fake log line
            log_path.write_text(f"[DEV MODE] llama-server stub started for {model_file} on port {port}\n")
            _events.emit("llm.server.started", f"LLM instance started (dev stub): {instance_id}",
                         data={"instance_id": instance_id, "model": model_file, "port": port})
            return instance_id, port

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

        _instances[instance_id] = {
            "process": process,
            "model": model_file,
            "port": port,
            "config": config,
            "log_path": log_path,
            "started_at": started_at,
            "_log_file": log_file,
        }

        _events.emit("llm.server.started", f"LLM instance started: {instance_id}",
                     data={"instance_id": instance_id, "model": model_file, "port": port})
        return instance_id, port


def _stop_llama_server(instance_id: str) -> None:
    """Stop a specific instance by instance_id."""
    from events import _events

    with _instances_lock:
        inst = _instances.pop(instance_id, None)
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

        _events.emit("llm.server.stopped", f"LLM instance stopped: {instance_id}",
                     data={"instance_id": instance_id, "model": inst.get("model", "")})


def _stop_all() -> None:
    """Stop all running instances."""
    with _instances_lock:
        instance_ids = list(_instances.keys())
    for iid in instance_ids:
        _stop_llama_server(iid)


def _get_instance_log(instance_id: str, tail: int = 50) -> str:
    """Read last N lines of a specific instance's log."""
    inst = _instances.get(instance_id)
    if inst and inst.get("log_path"):
        log_path = inst["log_path"]
    else:
        # Fallback: try to find by constructed name
        log_path = _LOG_DIR / f"{instance_id.replace(':', '_')}.log"
    if not log_path.exists():
        return ""
    try:
        lines = log_path.read_text().splitlines()
        return "\n".join(lines[-tail:])
    except Exception:
        return ""


def _get_instance_port(instance_id: str) -> int | None:
    """Get the port for a running instance."""
    inst = _instances.get(instance_id)
    if inst is None:
        return None
    return inst["port"]
