"""Model Store — physical file storage for AI model files.

Every model file (safetensors, gguf, onnx, etc.) enters the system through
this module. Files are stored in a sharded flat directory, validated, hashed,
and registered in SQLite.

The store knows intrinsic file properties: format, precision, pruning, hash, size.
It does NOT know about the catalog (models, versions, categories, CivitAI).
It does NOT decide where symlinks go — the catalog tells it.

Store layout
────────────
  MODEL_STORE_DIR/
    ab/cd/<uuid>.safetensors      ← original file (sharded)

Symlinks are created on demand by the catalog layer, pointing from
ComfyUI model dirs to files in this store.

Tables (inside studio.db):
  model_store_files  ← one row per physical file
  file_formats       ← lookup: safetensors, gguf, onnx, ...
  precisions         ← lookup: fp16, Q4_K_M, bf16, ...
"""

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path

from v2.app.db import get_conn, register_schema
from v2.app.settings import MODEL_STORE_DIR, now_iso


# ── Schema ───────────────────────────────────────────────────────────────────

def _init_schema(conn: sqlite3.Connection):
    """Create model store tables. Called by db.init_db()."""
    MODEL_STORE_DIR.mkdir(parents=True, exist_ok=True)

    conn.executescript("""

        -- ── Lookup tables ─────────────────────────────────────────────

        CREATE TABLE IF NOT EXISTS file_formats (
            id          TEXT PRIMARY KEY,
            description TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS precisions (
            id          TEXT PRIMARY KEY,
            description TEXT DEFAULT ''
        );

        -- ── Store table ───────────────────────────────────────────────

        CREATE TABLE IF NOT EXISTS model_store_files (
            id            TEXT PRIMARY KEY,
            file_path     TEXT NOT NULL,                                 -- relative to MODEL_STORE_DIR
            original_name TEXT,                                          -- filename at source
            file_size     INTEGER NOT NULL DEFAULT 0,
            hash          TEXT,                                          -- SHA-256
            format        TEXT NOT NULL REFERENCES file_formats(id),     -- safetensors, gguf, ...
            precision     TEXT REFERENCES precisions(id),                -- fp16, Q4_K_M, ... (nullable)
            pruning       TEXT CHECK (pruning IN ('full', 'pruned')),    -- nullable
            created_at    TEXT NOT NULL                                  -- ISO 8601 UTC
        );

        CREATE INDEX IF NOT EXISTS idx_msf_hash   ON model_store_files(hash);
        CREATE INDEX IF NOT EXISTS idx_msf_format ON model_store_files(format);
    """)

    _seed_lookups(conn)


def _seed_lookups(conn: sqlite3.Connection):
    """Populate lookup tables with known values. Idempotent."""

    _seed(conn, "file_formats", [
        ("safetensors", "Safe serialization by HuggingFace. Standard for modern AI models. No code execution risk."),
        ("gguf",        "GPT-Generated Unified Format. Quantized models for llama.cpp. Self-contained metadata."),
        ("onnx",        "Open Neural Network Exchange. Cross-framework interop."),
        ("pt",          "PyTorch native (pickle-based). Used by YOLO, older LoRAs."),
        ("pth",         "PyTorch checkpoint (pickle-based). Used by upscalers."),
        ("ckpt",        "Stable Diffusion original checkpoint (pickle-based). Legacy, security risk."),
        ("bin",         "Generic binary. Used by IP-Adapter, CLIP, sentence-transformers."),
        ("pt2",         "PyTorch 2 compiled format (torch.export)."),
        ("engine",      "TensorRT compiled engine. GPU-specific, not portable."),
        ("h5",          "HDF5/Keras format."),
        ("pb",          "TensorFlow frozen graph (Protocol Buffers)."),
        ("tflite",      "TensorFlow Lite. Mobile/edge inference."),
        ("xml",         "OpenVINO IR format (paired with .bin)."),
        ("mlmodel",     "Apple CoreML format."),
        ("torchscript", "TorchScript serialized model."),
        ("npz",         "NumPy compressed archive."),
        ("msgpack",     "MessagePack serialized weights (Flax/JAX)."),
    ])

    _seed(conn, "precisions", [
        ("fp64",     "64-bit float. Full precision."),
        ("fp32",     "32-bit float. Full training precision."),
        ("tf32",     "TensorFloat-32. NVIDIA Ampere+ internal format."),
        ("bf16",     "Brain Float 16. Same range as fp32, less mantissa."),
        ("fp16",     "16-bit float. Standard for inference."),
        ("fp8_e4m3", "8-bit float (4-bit exponent, 3-bit mantissa). Ada/Hopper."),
        ("fp8_e5m2", "8-bit float (5-bit exponent, 2-bit mantissa)."),
        ("fp8",      "Generic 8-bit float (unspecified variant)."),
        ("fp4",      "4-bit float. Experimental."),
        ("int8",     "8-bit integer quantization."),
        ("int4",     "4-bit integer quantization."),
        ("Q2_K",     "GGUF 2-bit K-quant. Very aggressive."),
        ("Q3_K_S",   "GGUF 3-bit K-quant small."),
        ("Q3_K_M",   "GGUF 3-bit K-quant medium."),
        ("Q3_K_L",   "GGUF 3-bit K-quant large."),
        ("Q4_0",     "GGUF 4-bit legacy."),
        ("Q4_1",     "GGUF 4-bit legacy with offsets."),
        ("Q4_K_S",   "GGUF 4-bit K-quant small."),
        ("Q4_K_M",   "GGUF 4-bit K-quant medium. Popular balance point."),
        ("Q5_0",     "GGUF 5-bit legacy."),
        ("Q5_1",     "GGUF 5-bit legacy with offsets."),
        ("Q5_K_S",   "GGUF 5-bit K-quant small."),
        ("Q5_K_M",   "GGUF 5-bit K-quant medium. High quality."),
        ("Q6_K",     "GGUF 6-bit K-quant. Near-lossless."),
        ("Q8_0",     "GGUF 8-bit. Highest GGUF quality."),
        ("IQ1_S",    "GGUF importance-matrix 1-bit."),
        ("IQ1_M",    "GGUF importance-matrix 1-bit medium."),
        ("IQ2_XXS",  "GGUF importance-matrix 2-bit extra-extra-small."),
        ("IQ2_XS",   "GGUF importance-matrix 2-bit extra-small."),
        ("IQ2_S",    "GGUF importance-matrix 2-bit small."),
        ("IQ2_M",    "GGUF importance-matrix 2-bit medium."),
        ("IQ3_XXS",  "GGUF importance-matrix 3-bit extra-extra-small."),
        ("IQ3_XS",   "GGUF importance-matrix 3-bit extra-small."),
        ("IQ3_S",    "GGUF importance-matrix 3-bit small."),
        ("IQ3_M",    "GGUF importance-matrix 3-bit medium."),
        ("IQ4_NL",   "GGUF importance-matrix 4-bit non-linear."),
        ("IQ4_XS",   "GGUF importance-matrix 4-bit extra-small."),
        ("nf4",      "NormalFloat 4-bit. QLoRA/bitsandbytes."),
        ("awq",      "Activation-aware Weight Quantization."),
        ("gptq",     "GPTQ quantization."),
        ("exl2",     "EXL2 format for ExLlamaV2. Variable bits-per-weight."),
        ("none",     "No specific precision. Raw weights as stored."),
    ])

    conn.commit()


def _seed(conn: sqlite3.Connection, table: str, rows: list[tuple]):
    """Insert seed rows. Skips existing (INSERT OR IGNORE)."""
    conn.executemany(
        f"INSERT OR IGNORE INTO {table} (id, description) VALUES (?, ?)",
        rows,
    )


register_schema("model_store", _init_schema)


# ── Path helpers ─────────────────────────────────────────────────────────────

def _shard_dir(store_id: str) -> str:
    """Return shard path: first 2 + next 2 chars → 'ab/cd'."""
    return f"{store_id[:2]}/{store_id[2:4]}"


def _rel_path(store_id: str, ext: str) -> str:
    """Relative path inside the store."""
    ext = ext if ext.startswith(".") else f".{ext}"
    return f"{_shard_dir(store_id)}/{store_id}{ext}"


def _abs_path(rel: str) -> Path:
    """Absolute path from relative store path."""
    return MODEL_STORE_DIR / rel


def _ensure_dir(rel: str):
    """Create parent directory for a relative path."""
    _abs_path(rel).parent.mkdir(parents=True, exist_ok=True)


# ── Hash ─────────────────────────────────────────────────────────────────────

def compute_hash(path: Path) -> str:
    """Compute SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ── Core operations ──────────────────────────────────────────────────────────

def store(
    source_path: Path,
    format: str,
    precision: str | None = None,
    pruning: str | None = None,
    original_name: str | None = None,
) -> str:
    """Validate, hash, dedup, and store a model file.

    The file at source_path is MOVED into the store (not copied).
    Returns the store ID (UUID).

    Args:
        source_path: Path to the file to ingest.
        format: File format (must exist in file_formats lookup).
        precision: Weight precision (must exist in precisions lookup, or None).
        pruning: 'full', 'pruned', or None.
        original_name: Original filename (defaults to source_path.name).

    Returns:
        Store ID (UUID string).

    Raises:
        ValueError: If format/precision not in lookup, or file doesn't exist.
    """
    if not source_path.exists():
        raise ValueError(f"File not found: {source_path}")
    if original_name is None:
        original_name = source_path.name

    # Validate format against lookup
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM file_formats WHERE id = ?", (format,)).fetchone():
        raise ValueError(f"Unknown format '{format}'. Check file_formats lookup.")
    if precision and not conn.execute("SELECT 1 FROM precisions WHERE id = ?", (precision,)).fetchone():
        raise ValueError(f"Unknown precision '{precision}'. Check precisions lookup.")

    # Hash and dedup
    file_hash = compute_hash(source_path)
    existing = get_by_hash(file_hash)
    if existing:
        source_path.unlink()
        return existing["id"]

    # Generate ID and move file
    store_id = uuid.uuid4().hex
    ext = source_path.suffix
    rel = _rel_path(store_id, ext)
    _ensure_dir(rel)
    dest = _abs_path(rel)
    source_path.rename(dest)

    # Insert DB record
    conn.execute("""
        INSERT INTO model_store_files (
            id, file_path, original_name, file_size, hash,
            format, precision, pruning, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        store_id, rel, original_name, dest.stat().st_size, file_hash,
        format, precision, pruning, now_iso(),
    ))
    conn.commit()
    return store_id


# ── Queries ──────────────────────────────────────────────────────────────────

def get(store_id: str) -> dict | None:
    """Get store file record by ID."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM model_store_files WHERE id = ?", (store_id,)).fetchone()
    return dict(row) if row else None


def get_by_hash(file_hash: str) -> dict | None:
    """Find store file by SHA-256 hash (for dedup)."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM model_store_files WHERE hash = ?", (file_hash,)).fetchone()
    return dict(row) if row else None


def exists(store_id: str) -> bool:
    """Check if a store file exists in DB."""
    conn = get_conn()
    return conn.execute("SELECT 1 FROM model_store_files WHERE id = ?", (store_id,)).fetchone() is not None


def hash_exists(file_hash: str) -> bool:
    """Check if a file with this hash is already in the store."""
    conn = get_conn()
    return conn.execute("SELECT 1 FROM model_store_files WHERE hash = ?", (file_hash,)).fetchone() is not None


# ── Serve ────────────────────────────────────────────────────────────────────

def serve_path(store_id: str) -> Path | None:
    """Get absolute path of a stored file."""
    record = get(store_id)
    if not record:
        return None
    p = _abs_path(record["file_path"])
    return p if p.exists() else None


# ── Symlinks ─────────────────────────────────────────────────────────────────
#
# Symlinks are created by the catalog layer, not by the store itself.
# But the store provides the helper to create them, since it knows the
# physical file path.

def create_symlink(store_id: str, link_path: Path) -> bool:
    """Create a symlink from link_path pointing to the stored file.

    The catalog decides WHERE the symlink goes (e.g. ComfyUI/models/loras/).
    The store knows WHERE the real file is.

    Args:
        store_id: Store file ID.
        link_path: Absolute path where the symlink should be created.

    Returns:
        True if created, False if store file not found.
    """
    real_path = serve_path(store_id)
    if not real_path:
        return False
    link_path.parent.mkdir(parents=True, exist_ok=True)
    # Remove existing symlink or file at target
    if link_path.exists() or link_path.is_symlink():
        link_path.unlink()
    link_path.symlink_to(real_path)
    return True


def remove_symlink(link_path: Path) -> bool:
    """Remove a symlink. Does NOT touch the store file.

    Args:
        link_path: Absolute path of the symlink.

    Returns:
        True if removed, False if didn't exist.
    """
    if link_path.is_symlink():
        link_path.unlink()
        return True
    return False


# ── Delete ───────────────────────────────────────────────────────────────────

def delete(store_id: str) -> bool:
    """Delete a file from the store: remove from disk and DB.

    Does NOT remove symlinks — the catalog is responsible for that.

    Args:
        store_id: Store file ID.

    Returns:
        True if deleted, False if not found.
    """
    record = get(store_id)
    if not record:
        return False

    # Delete from disk
    p = _abs_path(record["file_path"])
    if p.exists():
        p.unlink()

    # Delete from DB
    conn = get_conn()
    conn.execute("DELETE FROM model_store_files WHERE id = ?", (store_id,))
    conn.commit()

    # Try to clean empty shard dirs
    shard = _abs_path(_shard_dir(store_id))
    try:
        shard.rmdir()
        shard.parent.rmdir()
    except OSError:
        pass

    return True


# ── Stats ────────────────────────────────────────────────────────────────────

def total_size() -> int:
    """Total bytes of all stored model files."""
    conn = get_conn()
    row = conn.execute("SELECT COALESCE(SUM(file_size), 0) FROM model_store_files").fetchone()
    return row[0]


def count() -> int:
    """Total number of stored model files."""
    conn = get_conn()
    return conn.execute("SELECT COUNT(*) FROM model_store_files").fetchone()[0]
