"""ComfyUI Studio — Configuration, constants, paths, env vars, app instance."""

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_TZ_ROME = ZoneInfo("Europe/Rome")

def _now_rome():
    """Current time in Italian timezone (handles CET/CEST automatically)."""
    return datetime.now(_TZ_ROME)

from fastapi import FastAPI

# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="ComfyUI Studio")

# ── Configuration ────────────────────────────────────────────────────────────

API_KEY = os.environ.get("API_KEY", "changeme")
DEV_MODE = os.environ.get("DEV_MODE", "false").lower() == "true"
DEV_DOWNLOAD_DELAY = int(os.environ.get("DEV_DOWNLOAD_DELAY", "5"))
CIVITAI_API_KEY = os.environ.get("CIVITAI_API_KEY", "")
HF_TOKEN = os.environ.get("HF_TOKEN", "")
RUNTIME_VERSION = int(os.environ.get("RUNTIME_VERSION", "0"))
HOSTING = os.environ.get("HOSTING", "").lower().strip()
if not HOSTING and os.environ.get("RUNPOD_POD_ID"):
    HOSTING = "runpod"

# ── Studio directory ─────────────────────────────────────────────────────────

STUDIO_DIR = Path(os.environ.get("STUDIO_DIR", "/workspace/studio"))

# Git repo clone (staging area for updates only)
REPO_DIR = STUDIO_DIR / ".repo"
REPO_URL = os.environ.get(
    "REPO_URL",
    "https://github.com/diego-devita/comfyui-studio.git",
)
REPO_BRANCH = os.environ.get("REPO_BRANCH", "main")

# Backend — working copy
BACKEND_DIR = STUDIO_DIR / "backend"

# Frontend — working copy
WWW_ROOT = STUDIO_DIR / "frontend"

# Version — local working copy
VERSION_JSON = STUDIO_DIR / "version.json"

# Catalogs — working copies outside git (editable on pod)
CATALOGS_DIR = STUDIO_DIR / "catalogs"
MODELS_JSON = CATALOGS_DIR / "models.json"
LORAS_JSON = CATALOGS_DIR / "loras.json"
LLM_MODELS_JSON = CATALOGS_DIR / "llm.json"

# Workflows — working copy outside git (editable on pod)
WORKFLOWS_DIR = STUDIO_DIR / "workflows"

# Presets — saved job templates
PRESETS_DIR = STUDIO_DIR / "presets"

# Assets (input/output for ComfyUI)
ASSETS_DIR = STUDIO_DIR / "assets"
ASSETS_INPUT_DIR = ASSETS_DIR / "input"
ASSETS_OUTPUT_DIR = ASSETS_DIR / "output"

# LLM
LLM_DIR = STUDIO_DIR / "llm"
LLM_MODELS_DIR = LLM_DIR / "models"
LLM_CONFIG_PATH = LLM_DIR / "config.json"
LLAMA_SERVER_PATH = Path(os.environ.get("LLAMA_SERVER_PATH", "/opt/llama-server"))
LLAMA_SERVER_PORT = int(os.environ.get("LLAMA_SERVER_PORT", "8080"))

# DB
DB_DIR = STUDIO_DIR / "database"

# Auth
SESSION_SECRET_PATH = STUDIO_DIR / ".session_secret"

# ── ComfyUI (external, not ours) ────────────────────────────────────────────

COMFYUI_DIR = os.environ.get("COMFYUI_DIR", "/workspace/ComfyUI")
MODELS_BASE = os.path.join(COMFYUI_DIR, "models")
COMFY_URL = "http://127.0.0.1:" + os.environ.get("COMFYUI_PORT", "8188")
