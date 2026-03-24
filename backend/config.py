"""ComfyUI Studio — Configuration, constants, paths, env vars, app instance."""

import os
from pathlib import Path

from fastapi import FastAPI

# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="ComfyUI Studio")

# ── Configuration ────────────────────────────────────────────────────────────

API_KEY = os.environ.get("API_KEY", "changeme")
CIVITAI_API_KEY = os.environ.get("CIVITAI_API_KEY", "")
HF_TOKEN = os.environ.get("HF_TOKEN", "")
RUNTIME_VERSION = int(os.environ.get("RUNTIME_VERSION", "0"))

# ── Studio directory (single root for all studio files) ──────────────────────

STUDIO_DIR = Path(os.environ.get("STUDIO_DIR", "/workspace/studio"))

# Backend (live code on pod — updated via update mechanism)
BACKEND_DIR = STUDIO_DIR / "backend"
BACKEND_DIR_DEFAULT = Path("/app/backend")  # baked fallback in Docker image

# Frontend
WWW_ROOT = STUDIO_DIR / "www"
WWW_DEFAULT = Path("/app/www")  # baked fallback

# Catalogs
MODELS_JSON = STUDIO_DIR / "catalogs" / "models.json"
MODELS_JSON_DEFAULT = Path("/app/catalogs/models.json")
LORAS_JSON = STUDIO_DIR / "catalogs" / "loras.json"
LORAS_JSON_DEFAULT = Path("/app/catalogs/loras.json")
LLM_MODELS_JSON = STUDIO_DIR / "catalogs" / "llm-models.json"
LLM_MODELS_JSON_DEFAULT = Path("/app/catalogs/llm-models.json")

# Workflows
WORKFLOWS_DIR = STUDIO_DIR / "workflows"
WORKFLOWS_DIR_DEFAULT = Path("/app/workflows")

# Jobs (DB)
DB_DIR = STUDIO_DIR / "db"

# Assets (input/output for ComfyUI)
ASSETS_DIR = STUDIO_DIR / "assets"
ASSETS_INPUT_DIR = ASSETS_DIR / "input"
ASSETS_OUTPUT_DIR = ASSETS_DIR / "output"

# LLM
LLM_DIR = STUDIO_DIR / "llm"
LLM_MODELS_DIR = LLM_DIR / "models"
LLM_CONFIG_PATH = LLM_DIR / "config.json"
LLAMA_SERVER_PATH = Path(os.environ.get("LLAMA_SERVER_PATH", "/workspace/llama-server"))
LLAMA_SERVER_PORT = int(os.environ.get("LLAMA_SERVER_PORT", "8080"))

# Version
VERSION_JSON = STUDIO_DIR / "version.json"
VERSION_JSON_DEFAULT = Path("/app/version.json")

# Auth
SESSION_SECRET_PATH = STUDIO_DIR / ".session_secret"

# Jobs (legacy JSON — to be replaced by DB)
JOBS_DIR = STUDIO_DIR / "jobs"

# ── ComfyUI (external, not ours) ────────────────────────────────────────────

COMFYUI_DIR = os.environ.get("COMFYUI_DIR", "/workspace/ComfyUI")
MODELS_BASE = os.path.join(COMFYUI_DIR, "models")
COMFY_URL = "http://127.0.0.1:" + os.environ.get("COMFYUI_PORT", "8188")

# ── Repo ─────────────────────────────────────────────────────────────────────

REPO_BASE = os.environ.get(
    "REPO_BASE",
    "https://raw.githubusercontent.com/diego-devita/comfyui-studio/main",
)
