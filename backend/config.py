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

# ── Studio directory ─────────────────────────────────────────────────────────

STUDIO_DIR = Path(os.environ.get("STUDIO_DIR", "/workspace/studio"))

# Git repo clone (staging area for updates only)
REPO_DIR = STUDIO_DIR / ".repo"
REPO_URL = os.environ.get(
    "REPO_URL",
    "https://github.com/diego-devita/comfyui-studio.git",
)

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
LLM_MODELS_JSON = CATALOGS_DIR / "llm-models.json"

# Workflows — working copy outside git (editable on pod)
WORKFLOWS_DIR = STUDIO_DIR / "workflows"

# Jobs (legacy JSON — to be replaced by DB)
JOBS_DIR = STUDIO_DIR / "jobs"

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
DB_DIR = STUDIO_DIR / "db"

# Auth
SESSION_SECRET_PATH = STUDIO_DIR / ".session_secret"

# ── ComfyUI (external, not ours) ────────────────────────────────────────────

COMFYUI_DIR = os.environ.get("COMFYUI_DIR", "/workspace/ComfyUI")
MODELS_BASE = os.path.join(COMFYUI_DIR, "models")
COMFY_URL = "http://127.0.0.1:" + os.environ.get("COMFYUI_PORT", "8188")
