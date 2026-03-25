#!/usr/bin/env python3
"""ComfyUI Studio — Bootstrap Script

Clones the repo and sets up the workspace on first boot.

Usage: python3 bootstrap.py
Environment:
  STUDIO_DIR        — where to install (default: /workspace/studio)
  REPO_URL          — git repo URL (default: comfyui-studio)
  RUNTIME_VERSION   — Docker image runtime version (set at build time)
"""

import json
import os
import shutil
import subprocess
import sys

STUDIO_DIR = os.environ.get("STUDIO_DIR", "/workspace/studio")
REPO_URL = os.environ.get(
    "REPO_URL",
    "https://github.com/diego-devita/comfyui-studio.git",
)
RUNTIME_VERSION = int(os.environ.get("RUNTIME_VERSION", "0"))
REPO_BRANCH = os.environ.get("REPO_BRANCH", "main")


def log(msg):
    print(f"[bootstrap] {msg}", flush=True)


def main():
    repo_dir = os.path.join(STUDIO_DIR, ".repo")
    log(f"Studio dir: {STUDIO_DIR}")
    log(f"Repo URL: {REPO_URL}")
    log(f"Runtime version: {RUNTIME_VERSION}")

    # Step 1: Git clone
    if os.path.exists(repo_dir):
        log("Repo already exists — pulling latest...")
        proc = subprocess.run(
            ["git", "fetch", "--depth", "1", "origin", REPO_BRANCH],
            capture_output=True, text=True, timeout=60, cwd=repo_dir
        )
        if proc.returncode != 0:
            # Fetch failed (e.g., history rewritten) — re-clone from scratch
            log(f"Git fetch failed, re-cloning: {proc.stderr}")
            shutil.rmtree(repo_dir)
            proc = subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", REPO_BRANCH, REPO_URL, repo_dir],
                capture_output=True, text=True, timeout=120
            )
            if proc.returncode != 0:
                log(f"Git re-clone failed: {proc.stderr}")
                sys.exit(1)
        else:
            subprocess.run(
                ["git", "reset", "--hard", f"origin/{REPO_BRANCH}"],
                capture_output=True, text=True, timeout=30, cwd=repo_dir
            )
    else:
        log("Cloning repo...")
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", REPO_BRANCH, REPO_URL, repo_dir],
            capture_output=True, text=True, timeout=120
        )
        if proc.returncode != 0:
            log(f"Git clone failed: {proc.stderr}")
            sys.exit(1)

    # Step 2: Read version.json and check runtime compatibility
    version_path = os.path.join(repo_dir, "version.json")
    with open(version_path) as f:
        version = json.load(f)

    min_runtime = version.get("min_runtime", 0)
    if min_runtime > RUNTIME_VERSION:
        log(f"BLOCKED: App requires runtime v{min_runtime} but this image is v{RUNTIME_VERSION}")
        log("Pull the latest Docker image and restart the pod.")
        sys.exit(2)

    app_version = version.get("app_version", "?")
    log(f"App version: {app_version} (min_runtime: {min_runtime})")

    # Step 3: Copy ALL components from .repo/ to working directories
    # .repo/ is only a staging area — the live app runs from working dirs

    # Backend
    src_backend = os.path.join(repo_dir, "backend")
    dst_backend = os.path.join(STUDIO_DIR, "backend")
    if os.path.exists(src_backend):
        if os.path.exists(dst_backend):
            shutil.rmtree(dst_backend)
        shutil.copytree(src_backend, dst_backend)
        log("  Copied backend")

    # Frontend
    src_frontend = os.path.join(repo_dir, "frontend")
    dst_frontend = os.path.join(STUDIO_DIR, "frontend")
    if os.path.exists(src_frontend):
        if os.path.exists(dst_frontend):
            shutil.rmtree(dst_frontend)
        shutil.copytree(src_frontend, dst_frontend)
        log("  Copied frontend")

    # Catalogs (don't overwrite existing — user may have edited on pod)
    catalogs_dir = os.path.join(STUDIO_DIR, "catalogs")
    src_catalogs = os.path.join(repo_dir, "catalogs")
    if os.path.exists(src_catalogs):
        os.makedirs(catalogs_dir, exist_ok=True)
        for fname in os.listdir(src_catalogs):
            src = os.path.join(src_catalogs, fname)
            dst = os.path.join(catalogs_dir, fname)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
                log(f"  Copied catalog: {fname}")
            else:
                log(f"  Catalog exists, skipping: {fname}")

    # Workflows (don't overwrite existing)
    workflows_dir = os.path.join(STUDIO_DIR, "workflows")
    src_workflows = os.path.join(repo_dir, "workflows")
    if os.path.exists(src_workflows) and not os.path.exists(os.path.join(workflows_dir, "index.json")):
        shutil.copytree(src_workflows, workflows_dir, dirs_exist_ok=True)
        log("  Copied workflows")
    else:
        log("  Workflows exist, skipping")

    # Version.json (local working copy)
    local_ver = os.path.join(STUDIO_DIR, "version.json")
    shutil.copy2(version_path, local_ver)
    log("  Copied version.json")

    # Step 4: Create runtime directories
    for d in ["assets/input", "assets/output", "db", "jobs", "llm/models"]:
        os.makedirs(os.path.join(STUDIO_DIR, d), exist_ok=True)

    log(f"Bootstrap complete — app v{app_version}")


if __name__ == "__main__":
    main()
