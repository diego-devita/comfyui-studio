"""ComfyUI Studio — Model/LoRA/LLM catalogs, static file helper, version loader."""

import json
import os
from pathlib import Path

from config import (
    MODELS_JSON, LORAS_JSON, LLM_MODELS_JSON,
    MODELS_BASE, WWW_ROOT, VERSION_JSON,
)

# ── Models catalog ───────────────────────────────────────────────────────────


def _load_models() -> dict:
    """Load models.json, preferring /workspace override. Returns empty structure on failure."""
    models_file = MODELS_JSON
    try:
        return json.loads(models_file.read_text())
    except Exception:
        return {"categories": []}


def _load_loras() -> dict:
    """Load loras.json, preferring /workspace override. Returns empty structure on failure."""
    loras_file = LORAS_JSON
    try:
        return json.loads(loras_file.read_text())
    except Exception:
        return {"categories": []}


_models_data: dict = _load_models()
_loras_data: dict = _load_loras()


def _load_llm_models() -> dict:
    """Load llm-models.json, preferring /workspace override. Returns empty structure on failure."""
    f = LLM_MODELS_JSON
    try:
        return json.loads(f.read_text())
    except Exception:
        return {"categories": []}


_llm_models_data: dict = _load_llm_models()


def _reload_models() -> None:
    """Reload models + loras + LLM models catalogs from disk."""
    global _models_data, _loras_data, _llm_models_data
    _models_data = _load_models()
    _loras_data = _load_loras()
    _llm_models_data = _load_llm_models()


def _all_categories() -> list:
    """Merged categories from models + loras catalogs."""
    return _models_data.get("categories", []) + _loras_data.get("categories", [])


def _find_model(filename: str) -> dict | None:
    """Find a model entry by filename across models + loras catalogs.

    Matches exact filename first, then falls back to basename match
    (manifest may use 'subfolder/file.safetensors' while catalog has just 'file.safetensors').
    """
    basename = filename.rsplit("/", 1)[-1] if "/" in filename else None
    for cat in _all_categories():
        for m in cat.get("models", []):
            if m["file"] == filename:
                return m
    if basename:
        for cat in _all_categories():
            for m in cat.get("models", []):
                if m["file"] == basename:
                    return m
    return None


def _find_llm_model(filename: str) -> dict | None:
    """Find an LLM model entry by filename in llm-models catalog."""
    for cat in _llm_models_data.get("categories", []):
        for m in cat.get("models", []):
            if m["file"] == filename:
                return m
    return None


# ── Static files helper ─────────────────────────────────────────────────────


def _www(filename: str) -> Path:
    """Resolve a frontend file from WWW_ROOT (STUDIO_DIR/frontend/).

    Supports subpaths like 'css/styles.css' or 'js/shared.js'.
    For bare filenames (no subdir), checks pages/ subdirectory automatically.
    """
    p = WWW_ROOT / filename
    if p.exists():
        return p
    if '/' not in filename:
        p2 = WWW_ROOT / "pages" / filename
        if p2.exists():
            return p2
    return WWW_ROOT / filename


# ── Version helper ───────────────────────────────────────────────────────────


def _load_version() -> dict:
    """Load version.json — prefers local working copy, falls back to .repo/ copy."""
    from config import STUDIO_DIR, REPO_DIR
    local_ver = STUDIO_DIR / "version.json"
    if local_ver.exists():
        try:
            return json.loads(local_ver.read_text())
        except Exception:
            pass
    repo_ver = REPO_DIR / "version.json"
    try:
        return json.loads(repo_ver.read_text())
    except Exception:
        return {"app_version": "0.0.0", "date": "", "components": {}}


# ── Shared catalog response builder ─────────────────────────────────────────


def _build_catalog_response(catalog_data: dict, base_dir: str | Path, download_state: dict) -> list:
    """Build API response categories for a model/lora/llm catalog with download status and disk presence.

    Args:
        catalog_data: The loaded catalog dict with "categories" key.
        base_dir: Base directory where model files are stored.
        download_state: The shared _download_state dict from download module.

    Returns:
        List of category dicts with model entries enriched with status info.
    """
    base_dir = Path(base_dir)

    # Pre-scan all dest directories once (instead of stat() per model)
    _disk_cache = {}  # "dest/filename" -> size_bytes  OR just "filename" -> size for flat dirs
    scanned_dirs = set()
    is_flat = False

    for cat in catalog_data.get("categories", []):
        for m in cat.get("models", []):
            dest = m.get("dest", "")
            if dest:
                if dest not in scanned_dirs:
                    scanned_dirs.add(dest)
                    scan_path = base_dir / dest
                    if scan_path.is_dir():
                        try:
                            for entry in os.scandir(scan_path):
                                if entry.is_file(follow_symlinks=False):
                                    _disk_cache[f"{dest}/{entry.name}"] = entry.stat().st_size
                        except OSError:
                            pass
            else:
                # Flat dir (e.g. LLM models)
                is_flat = True

    if is_flat and base_dir.is_dir():
        try:
            for entry in os.scandir(base_dir):
                if entry.is_file(follow_symlinks=False):
                    _disk_cache[entry.name] = entry.stat().st_size
        except OSError:
            pass

    result_categories = []
    for cat in catalog_data.get("categories", []):
        models_out = []
        for m in cat.get("models", []):
            filename = m["file"]
            dest = m.get("dest", "")
            disk_key = f"{dest}/{filename}" if dest else filename
            state = download_state.get(filename)

            from download import _get_download_url

            entry = {
                "name": m.get("name", ""),
                "file": filename,
                "dest": dest,
                "url": _get_download_url(m),
                "source": m.get("source", ""),
                "size_gb": m.get("size_gb", 0),
                "hf_repo": m.get("hf_repo", ""),
                "hf_file": m.get("hf_file", ""),
                "civitai_model_id": m.get("civitai_model_id"),
                "civitai_version_id": m.get("civitai_version_id"),
                "civitai_file_id": m.get("civitai_file_id"),
                "civitai_base_model": m.get("civitai_base_model", ""),
                "civitai_version": m.get("civitai_version", ""),
                "civitai_tags": m.get("civitai_tags", []),
                "trainedWords": m.get("trainedWords", []),
                "base_model": m.get("base_model") or m.get("civitai_base_model") or "",
                "tags": m.get("tags", []),
                "trigger_words": m.get("trigger_words", []),
                "author": m.get("author", ""),
                "images": m.get("images", []),
                "quant": m.get("quant", ""),
                "params": m.get("params", ""),
                "context_length": m.get("context_length", 0),
                "context_default": m.get("context_default", 0),
                "context_max": m.get("context_max", 0),
                "companions": m.get("companions", []),
                "status": "missing",
                "progress": 0.0,
                "on_disk_bytes": 0,
                "expected_bytes": int(m.get("size_gb", 0) * 1_000_000_000),
                "speed": 0.0,
                "error": None,
            }

            if state and state.get("status") == "downloading":
                entry["status"] = "downloading"
                entry["on_disk_bytes"] = state["bytes"]
                entry["expected_bytes"] = state["total"] or entry["expected_bytes"]
                entry["speed"] = state.get("speed", 0.0)
                if state["total"] > 0:
                    entry["progress"] = round(state["bytes"] / state["total"] * 100, 1)
                else:
                    entry["progress"] = None

            elif state and state.get("status") == "error":
                entry["status"] = "error"
                entry["error"] = state.get("error", "")

            elif state and state.get("status") == "queued":
                entry["status"] = "queued"

            elif disk_key in _disk_cache:
                on_disk = _disk_cache[disk_key]
                entry["status"] = "present"
                entry["progress"] = 100.0
                entry["on_disk_bytes"] = on_disk
                entry["expected_bytes"] = on_disk

            # Check companion files status
            companions = m.get("companions", [])
            if companions and entry["status"] == "present":
                companions_out = []
                all_present = True
                for comp in companions:
                    comp_file = comp.get("file", "")
                    comp_key = f"{dest}/{comp_file}" if dest else comp_file
                    comp_state = download_state.get(comp_file)
                    comp_entry = {"role": comp.get("role", ""), "file": comp_file, "size_gb": comp.get("size_gb", 0)}
                    if comp_state and comp_state.get("status") == "downloading":
                        comp_entry["status"] = "downloading"
                        all_present = False
                    elif comp_key in _disk_cache:
                        comp_entry["status"] = "present"
                    else:
                        comp_entry["status"] = "missing"
                        all_present = False
                    companions_out.append(comp_entry)
                entry["companions_status"] = companions_out
                if not all_present:
                    entry["status"] = "partial"

            models_out.append(entry)

        result_categories.append({
            "id": cat.get("id", ""),
            "name": cat.get("name", ""),
            "models": models_out,
        })

    return result_categories
