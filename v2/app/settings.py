"""Temporary settings file — collects all paths and variables for app/.

This file exists as a reference until app/config.py is properly built
with the full get_config() chain (DB > ENV > default).

Nothing else in app/ reads os.environ directly — everything goes through here.
"""

import os
from pathlib import Path

# ── Base paths (from env vars) ───────────────────────────────────────────────

WORKSPACE   = Path(os.environ.get("WORKSPACE", "/workspace"))
STUDIO_DIR  = WORKSPACE / "studio"
COMFYUI_DIR = WORKSPACE / "ComfyUI"

# ── Database ─────────────────────────────────────────────────────────────────

DB_DIR  = STUDIO_DIR / "db"
DB_PATH = DB_DIR / "studio.db"

# ── Stores ───────────────────────────────────────────────────────────────────

MEDIA_STORE_DIR = STUDIO_DIR / "media"
MODEL_STORE_DIR = STUDIO_DIR / "models"

# ── ComfyUI ──────────────────────────────────────────────────────────────────

COMFYUI_MODELS  = COMFYUI_DIR / "models"
COMFYUI_INPUT   = COMFYUI_DIR / "input"
COMFYUI_OUTPUT  = COMFYUI_DIR / "output"
COMFYUI_PORT    = os.environ.get("COMFYUI_PORT", "8188")
COMFYUI_URL     = f"http://127.0.0.1:{COMFYUI_PORT}"

# ── Studio server ────────────────────────────────────────────────────────────

STUDIO_PORT = os.environ.get("STUDIO_PORT", "8000")

# ── Infrastructure (env only, never DB) ──────────────────────────────────────

RUNTIME_VERSION = int(os.environ.get("RUNTIME_VERSION", "0"))
DEV_MODE        = os.environ.get("DEV_MODE", "false").lower() == "true"
REPO_URL        = os.environ.get("REPO_URL", "https://github.com/diego-devita/comfyui-studio.git")
REPO_BRANCH     = os.environ.get("REPO_BRANCH", "main")

# ── Application settings (will move to DB via get_config()) ──────────────────
# These are placeholders. In the final config.py they will be resolved
# via get_config(key, default) which checks DB first, then ENV, then default.

API_KEY                  = os.environ.get("API_KEY", "changeme")
CIVITAI_API_KEY          = os.environ.get("CIVITAI_API_KEY", "")
HF_TOKEN                 = os.environ.get("HF_TOKEN", "")
MAX_CONCURRENT_DOWNLOADS = int(os.environ.get("MAX_CONCURRENT_DOWNLOADS", "3"))
LLAMA_SERVER_PATH        = Path(os.environ.get("LLAMA_SERVER_PATH", "/opt/llama-server"))
LLAMA_SERVER_PORT        = int(os.environ.get("LLAMA_SERVER_PORT", "8080"))
HOSTING                  = os.environ.get("HOSTING", "")
DOCS_URL                 = os.environ.get("DOCS_URL", "")
TELEGRAM_BOT_TOKEN       = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID         = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── Timezone ─────────────────────────────────────────────────────────────────

from datetime import datetime, timezone

def now() -> datetime:
    """Current time in UTC."""
    return datetime.now(timezone.utc)

def now_iso() -> str:
    """Current time as ISO 8601 UTC string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
