"""ComfyUI Studio — System status, update, remote version, health, telemetry, settings, env, events."""

import asyncio
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import httpx
import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import (
    app, COMFY_URL, COMFYUI_DIR, MODELS_BASE, REPO_BASE, RUNTIME_VERSION,
    VERSION_JSON, WORKFLOWS_DIR, STUDIO_DIR, WWW_ROOT, BACKEND_DIR,
)
from catalogs import _load_version, _reload_models, _all_categories, _loras_data, _llm_models_data
from download import _download_state, _max_concurrent, _queue_lock, _schedule_downloads
from events import _events
from workflows import _load_workflows_index, _load_workflows_index_raw
import auth
import download

router = APIRouter()


# ── Request schemas ──────────────────────────────────────────────────────────


class SettingsUpdate(BaseModel):
    max_concurrent: int = None


# ── Disk usage helpers ───────────────────────────────────────────────────────

_cached_volume_size = 0
_cached_disk_used = 0
_cached_disk_time = 0.0


async def _get_volume_size_gb() -> int:
    """Get network volume size from RunPod API (cached)."""
    global _cached_volume_size
    if _cached_volume_size > 0:
        return _cached_volume_size
    try:
        pod_id = os.environ.get("RUNPOD_POD_ID", "")
        api_key = os.environ.get("RUNPOD_API_KEY", "")
        if not pod_id or not api_key:
            return 0
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post(
                "https://api.runpod.io/graphql",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"query": f'{{ pod(input: {{ podId: "{pod_id}" }}) {{ networkVolume {{ size }} }} }}'},
            )
            if r.status_code == 200:
                size = r.json().get("data", {}).get("pod", {}).get("networkVolume", {}).get("size", 0)
                if size:
                    _cached_volume_size = size
                    return size
    except Exception:
        pass
    return 0


def _get_pod_ram_bytes() -> int:
    """Get pod RAM limit from cgroup (not host total)."""
    try:
        with open("/sys/fs/cgroup/memory.max") as f:
            val = f.read().strip()
            if val != "max":
                return int(val)
    except Exception:
        pass
    try:
        with open("/sys/fs/cgroup/memory/memory.limit_in_bytes") as f:
            return int(f.read().strip())
    except Exception:
        pass
    mem_gb = os.environ.get("RUNPOD_MEM_GB", "")
    if mem_gb:
        return int(mem_gb) * 1024 * 1024 * 1024
    return 0


def _github_api_url(repo_base: str, path: str) -> str:
    """Convert raw.githubusercontent.com URL to GitHub API contents URL."""
    m = re.match(r'https?://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)', repo_base)
    if m:
        owner, repo, branch = m.groups()
        return f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
    return None


# ── Health endpoint ──────────────────────────────────────────────────────────


@router.get("/api/health")
async def health():
    return {"status": "ok"}


# ── Events endpoint ─────────────────────────────────────────────────────────


@router.get("/api/admin/events")
async def list_events(limit: int = 100, types: str = None, severity: str = None):
    """List recent events from the activity log."""
    type_list = types.split(",") if types else None
    return _events.get_log(limit=limit, types=type_list, severity=severity)


# ── Remote version ──────────────────────────────────────────────────────────


@router.get("/api/admin/system/remote-version")
async def remote_version():
    """Fetch version.json from repo."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{REPO_BASE}/version.json")
            r.raise_for_status()
            return {"remote": r.json(), "local": _load_version()}
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch: {str(e)}")


# ── System status ───────────────────────────────────────────────────────────


@router.get("/api/admin/system/status")
async def system_status():
    ver = _load_version()
    _reload_models()

    total_models = sum(len(c.get("models", [])) for c in _all_categories())
    present_models = 0
    for cat in _all_categories():
        for m in cat.get("models", []):
            dest_path = Path(MODELS_BASE) / m["dest"] / m["file"]
            if dest_path.exists():
                present_models += 1

    wf_index = _load_workflows_index()
    total_workflows = len(wf_index)

    comfyui_status = "unknown"
    total_packages = 0
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{COMFY_URL}/system_stats")
            comfyui_status = "running" if r.status_code == 200 else "error"
            if comfyui_status == "running":
                try:
                    r2 = await client.get(f"{COMFY_URL}/object_info")
                    if r2.status_code == 200:
                        obj = r2.json()
                        pkgs = set()
                        for ni in obj.values():
                            if isinstance(ni, dict):
                                mod = ni.get("python_module", "")
                                if "custom_nodes" in mod:
                                    parts = mod.split(".")
                                    idx = parts.index("custom_nodes") if "custom_nodes" in parts else -1
                                    if idx >= 0 and idx + 1 < len(parts):
                                        pkgs.add(parts[idx + 1])
                        total_packages = len(pkgs)
                except Exception:
                    pass
    except Exception:
        comfyui_status = "unreachable"

    try:
        vol_gb = await _get_volume_size_gb()
        vol_size = vol_gb * 1024 * 1024 * 1024 if vol_gb > 0 else 0
        global _cached_disk_used
        if _cached_disk_used == 0:
            du = subprocess.run(["du", "-sb", "/workspace"], capture_output=True, text=True, timeout=30)
            if du.returncode == 0:
                _cached_disk_used = int(du.stdout.split()[0])
        free_bytes = max(0, vol_size - _cached_disk_used) if vol_size > 0 else 0
    except Exception:
        vol_size = 0
        free_bytes = 0

    return {
        "app_version": ver.get("app_version", "0.0.0"),
        "date": ver.get("date", ""),
        "repo_base": REPO_BASE,
        "runtime_version": RUNTIME_VERSION,
        "min_runtime": ver.get("min_runtime", 0),
        "components": {
            "runtime": {
                "version": RUNTIME_VERSION,
                "date": ver.get("components", {}).get("runtime", {}).get("date", ""),
                "status": f"Docker image v{RUNTIME_VERSION}",
                "updatable": False,
            },
            "backend": {
                "version": ver.get("components", {}).get("backend", {}).get("version", "0.0.0"),
                "date": ver.get("components", {}).get("backend", {}).get("date", ""),
                "status": "running",
            },
            "frontend": {
                "version": ver.get("components", {}).get("frontend", {}).get("version", "0.0.0"),
                "date": ver.get("components", {}).get("frontend", {}).get("date", ""),
                "status": "loaded",
            },
            "models": {
                "version": ver.get("components", {}).get("models", {}).get("version", 0),
                "date": ver.get("components", {}).get("models", {}).get("date", ""),
                "status": f"{total_models} models",
                "count": total_models,
                "present": present_models,
            },
            "loras": {
                "version": ver.get("components", {}).get("loras", {}).get("version", 0),
                "date": ver.get("components", {}).get("loras", {}).get("date", ""),
                "status": f"{sum(len(c.get('models', [])) for c in _loras_data.get('categories', []))} loras",
            },
            "llm_models": {
                "version": ver.get("components", {}).get("llm_models", {}).get("version", 0),
                "date": ver.get("components", {}).get("llm_models", {}).get("date", ""),
                "status": f"{sum(len(c.get('models', [])) for c in _llm_models_data.get('categories', []))} llm models",
            },
            "workflows": {
                "version": ver.get("components", {}).get("workflows", {}).get("version", 0),
                "date": ver.get("components", {}).get("workflows", {}).get("date", ""),
                "status": f"{total_workflows} workflows",
                "count": total_workflows,
            },
        },
        "comfyui": {"status": comfyui_status},
        "nodes": {"total_packages": total_packages},
        "disk": {"total_bytes": vol_size, "used_bytes": _cached_disk_used, "free_bytes": free_bytes},
    }


# ── System update ───────────────────────────────────────────────────────────


@router.post("/api/admin/system/update")
async def system_update(request: Request):
    """Fetch latest version.json from repo and update changed components."""
    try:
        skip_components = set()
        try:
            body = await request.json()
            skip_components = set(body.get("skip_components", []))
        except Exception:
            pass

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{REPO_BASE}/version.json")
            r.raise_for_status()
            remote_ver = r.json()

        local_ver = _load_version()

        # Check runtime compatibility
        remote_min_runtime = remote_ver.get("min_runtime", 0)
        if remote_min_runtime > RUNTIME_VERSION:
            return {
                "updated": [],
                "restart_needed": False,
                "blocked": True,
                "message": f"Update requires Docker image runtime v{remote_min_runtime} (you have v{RUNTIME_VERSION}). Pull the latest image and restart the pod.",
                "remote_min_runtime": remote_min_runtime,
                "local_runtime": RUNTIME_VERSION,
            }

        def _parse_ver(v):
            if isinstance(v, str):
                try:
                    return tuple(int(x) for x in v.split("."))
                except (ValueError, AttributeError):
                    return v
            return v

        to_update = {}
        for comp_name, comp_info in remote_ver.get("components", {}).items():
            if comp_name in skip_components:
                continue
            local_comp = local_ver.get("components", {}).get(comp_name, {})
            remote_v = comp_info.get("version", 0)
            local_v = local_comp.get("version", 0)
            if type(remote_v) != type(local_v):
                to_update[comp_name] = comp_info
            elif _parse_ver(remote_v) > _parse_ver(local_v):
                to_update[comp_name] = comp_info

        if not to_update:
            return {
                "updated": [],
                "restart_needed": False,
                "message": "Everything up to date",
                "debug": {"local_version_json": local_ver, "remote_version_json": remote_ver},
            }

        auth._maintenance_mode = True
        updated = []
        restart_needed = False

        async def _download_dir(repo_subdir: str, dest_dir: Path, dl_client):
            """Recursively download all files from a GitHub directory."""
            count = 0
            api_url = _github_api_url(REPO_BASE, repo_subdir)
            if not api_url:
                return 0
            api_r = await dl_client.get(api_url)
            if api_r.status_code != 200:
                return 0
            dest_dir.mkdir(parents=True, exist_ok=True)
            for item in api_r.json():
                if item.get("type") == "file":
                    dl_url = item.get("download_url") or f"{REPO_BASE}/{repo_subdir}/{item['name']}"
                    fr = await dl_client.get(dl_url)
                    if fr.status_code == 200:
                        (dest_dir / item["name"]).write_text(fr.text)
                        count += 1
                elif item.get("type") == "dir":
                    count += await _download_dir(f"{repo_subdir}/{item['name']}", dest_dir / item["name"], dl_client)
            return count

        def _atomic_swap(new_dir: Path, target_dir: Path):
            """Swap new_dir into target_dir atomically. Old target becomes .old."""
            old_dir = target_dir.with_name(target_dir.name + ".old")
            if old_dir.exists():
                shutil.rmtree(old_dir)
            if target_dir.exists():
                target_dir.rename(old_dir)
            new_dir.rename(target_dir)

        def _cleanup_old():
            """Remove .old directories left by atomic swaps."""
            for name in ("backend.old", "www.old"):
                old = STUDIO_DIR / name
                if old.exists():
                    shutil.rmtree(old)

        try:
            # Phase 1: FRONTEND — download to .new, then swap
            if "frontend" in to_update:
                frontend_repo_dir = to_update["frontend"].get("dir", "frontend/").rstrip("/")
                www_new = WWW_ROOT.with_name("www.new")
                if www_new.exists():
                    shutil.rmtree(www_new)
                async with httpx.AsyncClient(timeout=30) as dl_client:
                    count = await _download_dir(frontend_repo_dir, www_new, dl_client)
                if count > 0:
                    _atomic_swap(www_new, WWW_ROOT)
                    updated.append("frontend")
                elif www_new.exists():
                    shutil.rmtree(www_new)

            # Phase 2: Catalogs (single files — direct overwrite, no swap needed)
            from config import MODELS_JSON, LORAS_JSON, LLM_MODELS_JSON
            catalog_dest_map = {
                "catalogs/models.json": MODELS_JSON,
                "catalogs/loras.json": LORAS_JSON,
                "catalogs/llm-models.json": LLM_MODELS_JSON,
            }
            for comp_name in ("models", "loras", "llm_models"):
                if comp_name not in to_update:
                    continue
                comp_info = to_update[comp_name]
                if "file" not in comp_info:
                    continue
                repo_path = comp_info["file"]
                dest = catalog_dest_map.get(repo_path)
                if not dest:
                    continue
                async with httpx.AsyncClient(timeout=30) as dl_client:
                    fr = await dl_client.get(f"{REPO_BASE}/{repo_path}")
                if fr.status_code == 200:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(fr.text)
                    updated.append(comp_name)

            # Phase 3: Workflows
            if "workflows" in to_update:
                wf_base = f"{REPO_BASE}/workflows"
                async with httpx.AsyncClient(timeout=30) as dl_client:
                    idx_r = await dl_client.get(f"{wf_base}/index.json")
                    if idx_r.status_code == 200:
                        remote_index = idx_r.json().get("workflows", [])
                        local_wf_index = {e["id"]: e for e in _load_workflows_index()}
                        for rwf in remote_index:
                            wf_id = rwf["id"]
                            lwf = local_wf_index.get(wf_id)
                            rwf_v = rwf.get("version", 0)
                            lwf_v = lwf.get("version", 0) if lwf else None
                            if not lwf or type(rwf_v) != type(lwf_v) or rwf_v > lwf_v:
                                wf_dir = WORKFLOWS_DIR / wf_id
                                wf_dir.mkdir(parents=True, exist_ok=True)
                                mr = await dl_client.get(f"{wf_base}/{wf_id}/manifest.yaml")
                                if mr.status_code == 200:
                                    (wf_dir / "manifest.yaml").write_text(mr.text)
                                    mdata = yaml.safe_load(mr.text) if mr.text else {}
                                    if mdata.get("type") == "dynamic":
                                        bdir_name = mdata.get("blocks_dir", "blocks")
                                        bdir = wf_dir / bdir_name
                                        bdir.mkdir(parents=True, exist_ok=True)
                                        for stage in mdata.get("pipeline", []):
                                            bf = stage.get("file", "")
                                            if bf:
                                                br = await dl_client.get(f"{wf_base}/{wf_id}/{bdir_name}/{bf}")
                                                if br.status_code == 200:
                                                    (bdir / bf).write_text(br.text)
                                    else:
                                        wr = await dl_client.get(f"{wf_base}/{wf_id}/workflow.json")
                                        if wr.status_code == 200:
                                            (wf_dir / "workflow.json").write_text(wr.text)
                        WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
                        (WORKFLOWS_DIR / "index.json").write_text(idx_r.text)
                updated.append("workflows")

            # Phase 4: BACKEND — download to .new, swap, restart (LAST)
            if "backend" in to_update:
                backend_repo_dir = to_update["backend"].get("dir", "backend/").rstrip("/")
                backend_new = BACKEND_DIR.with_name("backend.new")
                if backend_new.exists():
                    shutil.rmtree(backend_new)
                async with httpx.AsyncClient(timeout=30) as dl_client:
                    count = await _download_dir(backend_repo_dir, backend_new, dl_client)
                if count > 0:
                    _atomic_swap(backend_new, BACKEND_DIR)
                    updated.append("backend")
                    restart_needed = True
                elif backend_new.exists():
                    shutil.rmtree(backend_new)

            # Save version.json
            VERSION_JSON.parent.mkdir(parents=True, exist_ok=True)
            VERSION_JSON.write_text(json.dumps(remote_ver, indent=2))
            if "models" in updated or "loras" in updated or "llm_models" in updated:
                _reload_models()

        except Exception:
            # If anything fails, clean up .new dirs
            for name in ("www.new", "backend.new"):
                p = STUDIO_DIR / name
                if p.exists():
                    shutil.rmtree(p)
            raise
        finally:
            if not restart_needed:
                # No restart — clean up .old now and exit maintenance
                _cleanup_old()
                auth._maintenance_mode = False

        if updated:
            _events.emit("system.updated", f"Updated: {', '.join(updated)}", severity="success",
                         data={"components": updated, "restart_needed": restart_needed})

        result = {
            "updated": updated,
            "restart_needed": restart_needed,
            "message": f"Updated: {', '.join(updated)}" if updated else "Everything up to date",
            "debug": {"local_version_json": local_ver, "remote_version_json": remote_ver},
        }

        if restart_needed:
            async def _restart():
                await asyncio.sleep(1)
                os.execv(
                    shutil.which("uvicorn"),
                    ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"],
                )
            asyncio.get_event_loop().create_task(_restart())

        return result
    except Exception as e:
        auth._maintenance_mode = False
        raise HTTPException(500, f"Update failed: {str(e)}")


# ── Telemetry ────────────────────────────────────────────────────────────────


@router.get("/api/admin/telemetry")
async def telemetry():
    result = {
        "gpu": None,
        "cpu_percent": None,
        "ram_total": 0,
        "ram_used": 0,
        "ram_percent": 0,
        "disk_total": 0,
        "disk_used": 0,
        "disk_percent": 0,
    }

    ram_total = _get_pod_ram_bytes()
    if ram_total > 0:
        try:
            with open("/sys/fs/cgroup/memory.current") as f:
                ram_used = int(f.read().strip())
        except Exception:
            try:
                with open("/sys/fs/cgroup/memory/memory.stat") as f:
                    for line in f:
                        if line.startswith("total_rss "):
                            ram_used = int(line.split()[1])
                            break
                    else:
                        ram_used = 0
            except Exception:
                ram_used = 0
        result["ram_total"] = ram_total
        result["ram_used"] = ram_used
        result["ram_percent"] = round(ram_used / ram_total * 100, 1) if ram_total > 0 else 0

    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{COMFY_URL}/system_stats")
            if r.status_code == 200:
                stats = r.json()
                devices = stats.get("devices", [])
                if devices:
                    dev = devices[0]
                    vram_total = dev.get("vram_total", 0)
                    vram_free = dev.get("vram_free", 0)
                    vram_used = vram_total - vram_free
                    result["gpu"] = {
                        "name": dev.get("name", "").split(" : ")[0].replace("cuda:0 ", ""),
                        "vram_total": vram_total,
                        "vram_used": vram_used,
                        "vram_percent": round(vram_used / vram_total * 100, 1) if vram_total > 0 else 0,
                    }
    except Exception:
        pass

    try:
        nvsmi = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
        )
        if nvsmi.returncode == 0:
            parts = nvsmi.stdout.strip().split(", ")
            if len(parts) >= 2 and result["gpu"]:
                result["gpu"]["util_percent"] = int(parts[0])
                result["gpu"]["temp_c"] = int(parts[1])
    except Exception:
        pass

    try:
        with open("/proc/loadavg") as f:
            load1 = float(f.read().split()[0])
        cpu_count = os.cpu_count() or 1
        result["cpu_percent"] = round(load1 / cpu_count * 100, 1)
    except Exception:
        pass

    global _cached_disk_used, _cached_disk_time
    vol_gb = await _get_volume_size_gb()
    if vol_gb > 0:
        disk_total = vol_gb * 1024 * 1024 * 1024
        if time.time() - _cached_disk_time > 60:
            _cached_disk_time = time.time()
            def _bg_du():
                global _cached_disk_used, _cached_disk_time
                try:
                    du = subprocess.run(["du", "-sb", "/workspace"], capture_output=True, text=True, timeout=60)
                    if du.returncode == 0:
                        _cached_disk_used = int(du.stdout.split()[0])
                except Exception:
                    pass
            threading.Thread(target=_bg_du, daemon=True).start()
        result["disk_total"] = disk_total
        result["disk_used"] = _cached_disk_used
        result["disk_percent"] = round(_cached_disk_used / disk_total * 100, 1) if disk_total > 0 else 0

    return result


# ── Settings ─────────────────────────────────────────────────────────────────


@router.get("/api/admin/settings")
async def get_settings():
    return {"max_concurrent": download._max_concurrent}


@router.put("/api/admin/settings")
async def update_settings(body: SettingsUpdate):
    if body.max_concurrent is not None:
        download._max_concurrent = max(1, min(10, body.max_concurrent))
        with _queue_lock:
            _schedule_downloads()
    return {"max_concurrent": download._max_concurrent}


@router.get("/api/admin/settings/env")
async def get_env_vars():
    """Return environment variables relevant to the app (sensitive values masked)."""
    def _mask(val):
        if not val or val == "changeme":
            return val
        if len(val) <= 8:
            return "***"
        return val[:4] + "***" + val[-4:]

    env_keys = [
        ("API_KEY", True),
        ("CIVITAI_API_KEY", True),
        ("HF_TOKEN", True),
        ("RUNPOD_API_KEY", True),
        ("COMFYUI_DIR", False),
        ("COMFYUI_PORT", False),
        ("REPO_BASE", False),
        ("MAX_CONCURRENT_DOWNLOADS", False),
        ("RUNPOD_POD_ID", False),
        ("RUNPOD_DC_ID", False),
        ("RUNPOD_VOLUME_ID", False),
        ("PUBLIC_KEY", False),
    ]
    result = []
    for key, sensitive in env_keys:
        val = os.environ.get(key, "")
        result.append({
            "key": key,
            "value": _mask(val) if sensitive else val,
            "sensitive": sensitive,
            "set": bool(val),
        })
    return result
