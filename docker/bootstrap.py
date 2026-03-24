#!/usr/bin/env python3
"""ComfyUI Studio — Bootstrap Script

Downloads the application from the GitHub repo on first boot.
Checks runtime compatibility before downloading.

Usage: python3 bootstrap.py
Environment:
  STUDIO_DIR    — where to install (default: /workspace/studio)
  REPO_BASE     — raw GitHub URL (default: comfyui-studio main branch)
  RUNTIME_VERSION — Docker image runtime version (set at build time)
"""

import json
import os
import sys
import urllib.request
import urllib.error
import re

STUDIO_DIR = os.environ.get("STUDIO_DIR", "/workspace/studio")
REPO_BASE = os.environ.get(
    "REPO_BASE",
    "https://raw.githubusercontent.com/diego-devita/comfyui-studio/main",
)
RUNTIME_VERSION = int(os.environ.get("RUNTIME_VERSION", "0"))


def log(msg):
    print(f"[bootstrap] {msg}", flush=True)


def fetch_json(url):
    """Fetch a JSON URL and return parsed data."""
    req = urllib.request.Request(url, headers={"User-Agent": "ComfyUI-Studio-Bootstrap"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def fetch_text(url):
    """Fetch a URL and return text content."""
    req = urllib.request.Request(url, headers={"User-Agent": "ComfyUI-Studio-Bootstrap"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def github_api_url(repo_base, path):
    """Convert raw.githubusercontent.com URL to GitHub API contents URL."""
    m = re.match(r"https?://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)", repo_base)
    if m:
        owner, repo, branch = m.groups()
        return f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
    return None


def download_dir(repo_base, repo_path, dest_dir):
    """Recursively download all files from a GitHub directory."""
    api_url = github_api_url(repo_base, repo_path)
    if not api_url:
        log(f"  Cannot build API URL for {repo_path}")
        return 0

    try:
        items = fetch_json(api_url)
    except Exception as e:
        log(f"  Failed to list {repo_path}: {e}")
        return 0

    os.makedirs(dest_dir, exist_ok=True)
    count = 0

    for item in items:
        if item.get("type") == "file":
            name = item["name"]
            dl_url = item.get("download_url") or f"{repo_base}/{repo_path}/{name}"
            try:
                content = fetch_text(dl_url)
                with open(os.path.join(dest_dir, name), "w") as f:
                    f.write(content)
                count += 1
            except Exception as e:
                log(f"  Failed to download {name}: {e}")
        elif item.get("type") == "dir":
            count += download_dir(repo_base, f"{repo_path}/{item['name']}", os.path.join(dest_dir, item["name"]))

    return count


def download_file(url, dest_path):
    """Download a single file."""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    content = fetch_text(url)
    with open(dest_path, "w") as f:
        f.write(content)


def main():
    log(f"Studio dir: {STUDIO_DIR}")
    log(f"Repo base: {REPO_BASE}")
    log(f"Runtime version: {RUNTIME_VERSION}")

    # Step 1: Fetch version.json
    log("Fetching version.json...")
    try:
        version = fetch_json(f"{REPO_BASE}/version.json")
    except Exception as e:
        log(f"FATAL: Cannot fetch version.json: {e}")
        sys.exit(1)

    # Step 2: Check runtime compatibility
    min_runtime = version.get("min_runtime", 0)
    if min_runtime > RUNTIME_VERSION:
        log(f"BLOCKED: App requires runtime v{min_runtime} but this image is v{RUNTIME_VERSION}")
        log("Pull the latest Docker image and restart the pod.")
        # Write a minimal error page
        www_dir = os.path.join(STUDIO_DIR, "www", "pages")
        os.makedirs(www_dir, exist_ok=True)
        with open(os.path.join(www_dir, "error.html"), "w") as f:
            f.write(
                f'<html><body style="background:#0a0a0f;color:#ff4466;font-family:monospace;'
                f'display:flex;align-items:center;justify-content:center;height:100vh;text-align:center;">'
                f'<div><h1>Runtime Incompatible</h1>'
                f'<p>App requires Docker image runtime v{min_runtime}<br>You have v{RUNTIME_VERSION}</p>'
                f'<p style="color:#888;">Pull the latest Docker image and restart the pod.</p>'
                f'</div></body></html>'
            )
        sys.exit(2)

    app_version = version.get("app_version", "?")
    log(f"App version: {app_version} (min_runtime: {min_runtime})")

    # Step 3: Download components
    components = version.get("components", {})

    # Backend
    if "backend" in components:
        comp = components["backend"]
        repo_dir = comp.get("dir", "backend/").rstrip("/")
        dest = os.path.join(STUDIO_DIR, "backend")
        log(f"Downloading backend from {repo_dir}/...")
        n = download_dir(REPO_BASE, repo_dir, dest)
        log(f"  {n} files")

    # Frontend
    if "frontend" in components:
        comp = components["frontend"]
        repo_dir = comp.get("dir", "frontend/").rstrip("/")
        dest = os.path.join(STUDIO_DIR, "www")
        log(f"Downloading frontend from {repo_dir}/...")
        n = download_dir(REPO_BASE, repo_dir, dest)
        log(f"  {n} files")

    # Catalogs (file components)
    dest_map = {
        "catalogs/models.json": "catalogs/models.json",
        "catalogs/loras.json": "catalogs/loras.json",
        "catalogs/llm-models.json": "catalogs/llm-models.json",
    }
    for comp_name in ("models", "loras", "llm_models"):
        if comp_name not in components:
            continue
        comp = components[comp_name]
        repo_path = comp.get("file", "")
        if not repo_path:
            continue
        dest_rel = dest_map.get(repo_path, repo_path)
        dest_path = os.path.join(STUDIO_DIR, dest_rel)
        log(f"Downloading {comp_name}: {repo_path}")
        try:
            download_file(f"{REPO_BASE}/{repo_path}", dest_path)
        except Exception as e:
            log(f"  Failed: {e}")

    # Workflows
    if "workflows" in components:
        log("Downloading workflows...")
        try:
            idx_url = f"{REPO_BASE}/workflows/index.json"
            idx_data = fetch_json(idx_url)
            wf_dir = os.path.join(STUDIO_DIR, "workflows")
            os.makedirs(wf_dir, exist_ok=True)
            with open(os.path.join(wf_dir, "index.json"), "w") as f:
                json.dump(idx_data, f, indent=2)
            for wf in idx_data.get("workflows", []):
                wf_id = wf["id"]
                wf_dest = os.path.join(wf_dir, wf_id)
                os.makedirs(wf_dest, exist_ok=True)
                # Manifest
                try:
                    manifest_text = fetch_text(f"{REPO_BASE}/workflows/{wf_id}/manifest.yaml")
                    with open(os.path.join(wf_dest, "manifest.yaml"), "w") as f:
                        f.write(manifest_text)
                    # Check if dynamic
                    import yaml
                    mdata = yaml.safe_load(manifest_text) or {}
                    if mdata.get("type") == "dynamic":
                        bdir = mdata.get("blocks_dir", "blocks")
                        blocks_dest = os.path.join(wf_dest, bdir)
                        os.makedirs(blocks_dest, exist_ok=True)
                        for stage in mdata.get("pipeline", []):
                            bf = stage.get("file", "")
                            if bf:
                                try:
                                    bt = fetch_text(f"{REPO_BASE}/workflows/{wf_id}/{bdir}/{bf}")
                                    with open(os.path.join(blocks_dest, bf), "w") as f:
                                        f.write(bt)
                                except Exception:
                                    pass
                    else:
                        try:
                            wf_text = fetch_text(f"{REPO_BASE}/workflows/{wf_id}/workflow.json")
                            with open(os.path.join(wf_dest, "workflow.json"), "w") as f:
                                f.write(wf_text)
                        except Exception:
                            pass
                    log(f"  {wf_id}")
                except Exception as e:
                    log(f"  {wf_id}: failed ({e})")
        except Exception as e:
            log(f"  Failed: {e}")

    # Save version.json
    version_path = os.path.join(STUDIO_DIR, "version.json")
    os.makedirs(os.path.dirname(version_path), exist_ok=True)
    with open(version_path, "w") as f:
        json.dump(version, f, indent=2)

    log(f"Bootstrap complete — app v{app_version}")


if __name__ == "__main__":
    main()
