#!/usr/bin/env bash
set -e

echo "=== Studio v2 Dev Container ==="

STUDIO_V2="/workspace/studio/v2"
DATA_DIR="${STUDIO_V2}/data"

# ── Create data directories (persistent volume) ──────────────────
echo "[1/3] Setting up data directories..."
for dir in db media models downloads; do
    mkdir -p "${DATA_DIR}/${dir}"
done

# ── Symlink data dirs into v2/ so app code finds them ────────────
# app/core/settings.py expects: V2_DIR/db, V2_DIR/media, etc.
# The actual data lives in data/ (persistent volume mount).
echo "[2/3] Creating symlinks..."
for dir in db media models downloads; do
    target="${STUDIO_V2}/${dir}"
    source="${DATA_DIR}/${dir}"
    if [ -L "$target" ]; then
        rm "$target"
    elif [ -d "$target" ]; then
        # Real dir exists (first boot before volume mount) — remove it
        rmdir "$target" 2>/dev/null || true
    fi
    ln -s "$source" "$target"
    echo "  ${dir}/ → data/${dir}/"
done

# ── PATH and aliases ──────────────────────────────────────────────
echo "[3/3] Setting up PATH and aliases..."
export PATH="${STUDIO_V2}/app/bin:${PATH}"
export PYTHONPATH="/workspace/studio"

# Write to bashrc so interactive shells get them too
cat >> /root/.bashrc << 'BASHEOF'
export PATH="/workspace/studio/v2/app/bin:${PATH}"
export PYTHONPATH="/workspace/studio"
cd /workspace/studio
BASHEOF

echo ""
echo "  ══════════════════════════════════════════"
echo "  Studio v2 Dev Container ready"
echo "  ══════════════════════════════════════════"
echo ""
echo "  Commands:"
echo "    studio --help"
echo "    studio db tables"
echo "    studio media stats"
echo "    studio-downloader"
echo ""
echo "  Paths:"
echo "    WORKSPACE:  /workspace"
echo "    STUDIO_DIR: /workspace/studio"
echo "    V2_DIR:     /workspace/studio/v2"
echo "    Data:       /workspace/studio/v2/data/"
echo ""

# Keep container alive, start in repo root
cd /workspace/studio
exec bash
