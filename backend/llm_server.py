"""ComfyUI Studio — LLM server process manager (multi-instance llama-server).

Persists instance registry to llm/instances.json so running llama-server
processes survive backend restarts.  On boot, we reload the registry and
probe each port to determine if the orphaned process is still alive.
"""

import json
import re
import socket
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
_INSTANCES_PATH = LLM_MODELS_DIR.parent / "instances.json"


# ── Persistence ──────────────────────────────────────────────────────────────

def _persist() -> None:
    """Write current registry to disk. Must be called with _instances_lock held."""
    data = {}
    for iid, inst in _instances.items():
        data[iid] = {
            "model": inst["model"],
            "port": inst["port"],
            "started_at": inst.get("started_at", ""),
            "config": {k: v for k, v in inst.get("config", {}).items() if not k.startswith("_")},
            "log_path": str(inst.get("log_path", "")),
        }
    try:
        _INSTANCES_PATH.parent.mkdir(parents=True, exist_ok=True)
        _INSTANCES_PATH.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def _port_alive(port: int) -> bool:
    """Check if something is listening on localhost:port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except (OSError, ConnectionRefusedError):
        return False


def _restore() -> None:
    """Reload registry from disk on boot. Probe ports to detect alive processes."""
    if not _INSTANCES_PATH.exists():
        return
    try:
        data = json.loads(_INSTANCES_PATH.read_text())
    except Exception:
        return

    with _instances_lock:
        for iid, info in data.items():
            port = info.get("port")
            if port is None:
                continue
            _instances[iid] = {
                "process": None,  # orphaned — no Popen handle
                "model": info.get("model", ""),
                "port": port,
                "config": info.get("config", {}),
                "log_path": Path(info["log_path"]) if info.get("log_path") else _LOG_DIR / f"{iid.replace(':', '_')}.log",
                "started_at": info.get("started_at", ""),
                "_orphan": True,  # we don't own the process
            }


# Run restore on import (module load = backend boot)
_restore()


# ── Config ───────────────────────────────────────────────────────────────────

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


# ── Instance helpers ─────────────────────────────────────────────────────────

def _normalize_model_name(model_file: str) -> str:
    """Normalize model filename to URL-safe slug: [a-zA-Z0-9] → keep, rest → _."""
    slug = re.sub(r'[^a-zA-Z0-9]', '_', model_file)
    slug = re.sub(r'_+', '_', slug).strip('_').lower()
    return slug


def _next_port() -> int:
    """Find next available port starting from LLAMA_SERVER_PORT."""
    used = {inst["port"] for inst in _instances.values()}
    port = LLAMA_SERVER_PORT
    while port in used:
        port += 1
    return port


def _instance_alive(inst: dict) -> bool:
    """Check if an instance is alive (process or port probe for orphans)."""
    if DEV_MODE:
        return True
    proc = inst.get("process")
    if proc is not None:
        return proc.poll() is None
    # Orphan (restored from disk) — probe the port
    return _port_alive(inst["port"])


def _is_running(instance_id: str) -> bool:
    """Check if a specific instance is alive."""
    inst = _instances.get(instance_id)
    if inst is None:
        return False
    return _instance_alive(inst)


def _has_running_instances(model_file: str) -> bool:
    """Return True if ANY instance of the given model file is running."""
    with _instances_lock:
        for inst in _instances.values():
            if inst.get("model") != model_file:
                continue
            if _instance_alive(inst):
                return True
    return False


def _get_gpu_mem_by_pid() -> dict[int, int]:
    """Query nvidia-smi for per-process GPU memory (MiB). Returns {pid: mib}."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        result = {}
        for line in r.stdout.strip().splitlines():
            parts = line.split(",")
            if len(parts) >= 2:
                pid = int(parts[0].strip())
                mem = int(parts[1].strip())
                result[pid] = mem
        return result
    except Exception:
        return {}


def _get_running_instances() -> list[dict]:
    """Return ALL registered instances (alive or exited) with status flag + VRAM."""
    gpu_mem = _get_gpu_mem_by_pid() if not DEV_MODE else {}
    port_pids = _get_llama_pids_by_port() if (not DEV_MODE and gpu_mem) else {}
    result = []
    with _instances_lock:
        for instance_id, inst in _instances.items():
            alive = _instance_alive(inst)
            entry = {
                "instance_id": instance_id,
                "model": inst["model"],
                "port": inst["port"],
                "started_at": inst.get("started_at", ""),
                "config": {k: v for k, v in inst.get("config", {}).items() if not k.startswith("_")},
                "alive": alive,
            }
            # Attach VRAM from nvidia-smi
            proc = inst.get("process")
            pid = proc.pid if proc else port_pids.get(inst["port"])
            if pid and pid in gpu_mem:
                entry["vram_mb"] = gpu_mem[pid]
            if DEV_MODE and alive:
                entry["vram_mb"] = 5326  # fake for dev
            result.append(entry)
    return result


def _get_llama_pids_by_port() -> dict[int, int]:
    """Scan /proc for llama-server processes, return {port: pid}."""
    import os
    result = {}
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                cmdline = Path(f"/proc/{entry}/cmdline").read_bytes().decode("utf-8", errors="replace")
                args = cmdline.split("\0")
                if not any("llama-server" in a or "llama_server" in a for a in args):
                    continue
                for i, a in enumerate(args):
                    if a == "--port" and i + 1 < len(args) and args[i + 1].isdigit():
                        result[int(args[i + 1])] = int(entry)
                        break
            except (OSError, PermissionError, ValueError):
                continue
    except OSError:
        pass
    return result


def _dismiss_instance(instance_id: str) -> None:
    """Remove an instance from the registry (e.g. after it exited)."""
    with _instances_lock:
        _instances.pop(instance_id, None)
        _persist()


# ── Start / Stop ─────────────────────────────────────────────────────────────

def _find_catalog_entry(model_file: str) -> dict | None:
    """Look up a model in the LLM catalog by filename."""
    try:
        import catalogs as _cat
        for cat in _cat._llm_models_data.get("categories", []):
            for m in cat.get("models", []):
                if m.get("file") == model_file:
                    return m
    except Exception:
        pass
    return None


def _start_llama_server(model_file: str, config: dict) -> tuple[str, int]:
    """Start a NEW llama-server instance. Returns (instance_id, port)."""
    from events import _events

    with _instances_lock:
        if not DEV_MODE:
            model_path = LLM_MODELS_DIR / model_file
            if not model_path.exists():
                raise FileNotFoundError(f"Model file not found: {model_path}")

        port = _next_port()
        slug = _normalize_model_name(model_file)
        instance_id = f"{slug}_{port}"
        started_at = _now_rome().strftime("%Y-%m-%d %H:%M")

        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = _LOG_DIR / f"{instance_id}.log"

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
            _persist()
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
            "--parallel", "1",
        ]

        # Add --mmproj for vision-language models
        catalog_entry = _find_catalog_entry(model_file)
        if catalog_entry:
            for comp in catalog_entry.get("companions", []):
                if comp.get("role") == "mmproj":
                    mmproj_path = LLM_MODELS_DIR / comp["file"]
                    if mmproj_path.exists():
                        cmd.extend(["--mmproj", str(mmproj_path)])

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
        _persist()

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

        if not DEV_MODE:
            proc = inst.get("process")
            if proc:
                # We own the process — terminate it
                try:
                    proc.terminate()
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
            elif inst.get("_orphan"):
                # Orphan process — try to kill via port (find PID listening on port)
                _kill_by_port(inst["port"])

            # Close log file handle if present
            lf = inst.get("_log_file")
            if lf:
                try:
                    lf.close()
                except Exception:
                    pass

        _persist()
        _events.emit("llm.server.stopped", f"LLM instance stopped: {instance_id}",
                     data={"instance_id": instance_id, "model": inst.get("model", "")})


def _kill_by_port(port: int) -> None:
    """Best-effort kill of process listening on a port (for orphaned instances)."""
    import os
    import signal
    try:
        port_pids = _get_llama_pids_by_port()
        pid = port_pids.get(port)
        if pid:
            os.kill(pid, signal.SIGTERM)
    except Exception:
        pass


def _stop_all() -> None:
    """Stop all running instances."""
    with _instances_lock:
        instance_ids = list(_instances.keys())
    for iid in instance_ids:
        _stop_llama_server(iid)


# ── Log / Port accessors ────────────────────────────────────────────────────

def _get_instance_log(instance_id: str, tail: int = 50) -> str:
    """Read last N lines of a specific instance's log."""
    inst = _instances.get(instance_id)
    if inst and inst.get("log_path"):
        log_path = inst["log_path"]
    else:
        # Fallback: try to find by constructed name
        log_path = _LOG_DIR / f"{instance_id.replace(':', '_')}.log"
    if not isinstance(log_path, Path):
        log_path = Path(log_path)
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
