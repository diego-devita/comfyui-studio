"""Model Catalog — the knowledge layer above the stores.

Knows what models exist, how they're organized (parent → version → file),
where they come from (CivitAI, HuggingFace, manual), and which files are
downloaded (via store_id link to model_store).

Three-level hierarchy (calque of CivitAI):
  models          → parent/group ("SD XL", "Realistic Vision")
  model_versions  → release ("v3.0 - High", "V5.1 Hyper VAE")
  model_files     → catalog entry for a physical file (linked to model_store via store_id)

The catalog does NOT store physical files — that's model_store's job.
The catalog does NOT store media — that's media_store's job.
The catalog DOES manage symlinks by telling model_store where to link.

Tables (inside studio.db):
  model_categories     — logical types: checkpoints, loras, vae, ...
  file_types           — what a file represents: model, config, vae, ...
  version_file_roles   — role in a release: weights, config, vae, ...
  models               — parent/group
  model_versions       — releases
  model_files          — catalog entries (linked to store via store_id)
  version_files        — join: version contains these files
  source_mappings      — external IDs: CivitAI, HuggingFace, ...
"""

import json
import sqlite3
import uuid as _uuid

from v2.app.core.db import get_conn, register_schema
from v2.app.core.settings import now_iso


# ── Schema ───────────────────────────────────────────────────────────────────

def _init_schema(conn: sqlite3.Connection):
    """Create catalog tables. Called by db.init_db()."""

    conn.executescript("""

        -- ── Lookup tables ─────────────────────────────────────────────

        CREATE TABLE IF NOT EXISTS model_categories (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            description TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS file_types (
            id          TEXT PRIMARY KEY,
            description TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS version_file_roles (
            id          TEXT PRIMARY KEY,
            description TEXT DEFAULT ''
        );

        -- ── Core entities ─────────────────────────────────────────────

        CREATE TABLE IF NOT EXISTS models (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            category    TEXT REFERENCES model_categories(id),
            type        TEXT,                                   -- CivitAI type: LORA, Checkpoint, ...
            creator     TEXT,
            description TEXT,
            nsfw        INTEGER DEFAULT 0 CHECK (nsfw IN (0, 1)),
            tags        TEXT,                                   -- JSON array
            preview_id  TEXT,                                   -- FK → media.id (nullable)
            created_at  TEXT NOT NULL,
            updated_at  TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_models_category ON models(category);
        CREATE INDEX IF NOT EXISTS idx_models_type     ON models(type);

        CREATE TABLE IF NOT EXISTS model_versions (
            id              TEXT PRIMARY KEY,
            model_id        TEXT REFERENCES models(id) ON DELETE SET NULL,
            name            TEXT NOT NULL,
            base_model      TEXT,
            trained_words   TEXT,                                -- JSON array
            description     TEXT,
            published_at    TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_mv_model ON model_versions(model_id);

        CREATE TABLE IF NOT EXISTS model_files (
            id              TEXT PRIMARY KEY,
            file            TEXT NOT NULL,                       -- filename (display/original)
            dest            TEXT NOT NULL,                       -- ComfyUI models subdir (free text)
            file_type       TEXT NOT NULL REFERENCES file_types(id),
            store_id        TEXT,                                -- FK → model_store_files.id (null = not downloaded)
            created_at      TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_mf_file     ON model_files(file);
        CREATE INDEX IF NOT EXISTS idx_mf_store_id ON model_files(store_id);

        -- ── Join tables ───────────────────────────────────────────────

        CREATE TABLE IF NOT EXISTS version_files (
            version_id  TEXT NOT NULL REFERENCES model_versions(id) ON DELETE CASCADE,
            file_id     TEXT NOT NULL REFERENCES model_files(id) ON DELETE CASCADE,
            role        TEXT REFERENCES version_file_roles(id),
            PRIMARY KEY (version_id, file_id)
        );

        CREATE INDEX IF NOT EXISTS idx_vf_file ON version_files(file_id);

        CREATE TABLE IF NOT EXISTS source_mappings (
            entity_type TEXT NOT NULL
                        CHECK (entity_type IN ('model', 'version', 'file')),
            entity_id   TEXT NOT NULL,
            source      TEXT NOT NULL,          -- 'civitai', 'huggingface', 'manual'
            source_id   TEXT NOT NULL,
            source_url  TEXT,
            source_meta TEXT,                   -- JSON
            PRIMARY KEY (entity_type, entity_id, source)
        );

        CREATE INDEX IF NOT EXISTS idx_sm_source ON source_mappings(source, source_id);
        CREATE INDEX IF NOT EXISTS idx_sm_entity ON source_mappings(entity_type, entity_id);

        -- ── Media join tables ─────────────────────────────────────────
        -- Connect media store items to catalog entities.

        CREATE TABLE IF NOT EXISTS model_media (
            media_id    TEXT NOT NULL,
            model_id    TEXT NOT NULL REFERENCES models(id) ON DELETE CASCADE,
            sort_order  INTEGER DEFAULT 0,
            PRIMARY KEY (media_id, model_id)
        );

        CREATE TABLE IF NOT EXISTS version_media (
            media_id    TEXT NOT NULL,
            version_id  TEXT NOT NULL REFERENCES model_versions(id) ON DELETE CASCADE,
            source      TEXT DEFAULT '',
            sort_order  INTEGER DEFAULT 0,
            PRIMARY KEY (media_id, version_id)
        );
    """)

    _seed_lookups(conn)


def _seed_lookups(conn: sqlite3.Connection):
    """Populate lookup tables. Idempotent."""

    _seed3(conn, "model_categories", [
        ("checkpoints",      "Checkpoints",      "Complete models (UNet+VAE+CLIP fused)"),
        ("diffusion_models", "Diffusion Models",  "Standalone UNet/DiT without VAE or text encoder"),
        ("loras",            "LoRAs",             "Low-Rank Adaptation weights"),
        ("vae",              "VAE",               "Variational Auto-Encoder"),
        ("text_encoders",    "Text Encoders",     "Convert text to embeddings (T5, CLIP-L, UMT5)"),
        ("clip_vision",      "CLIP Vision",       "Convert images to embeddings"),
        ("controlnet",       "ControlNet",        "Conditional control (depth, canny, pose)"),
        ("ipadapter",        "IP-Adapter",        "Image prompt adapter"),
        ("upscalers",        "Upscalers",         "Image upscaling models"),
        ("embeddings",       "Embeddings",        "Textual inversion tokens"),
        ("animatediff",      "AnimateDiff",       "Motion modules for animation"),
        ("segmentation",     "Segmentation",      "Object detection and masking"),
        ("faceswap",         "Face Swap",         "Face swapping models"),
    ])

    _seed2(conn, "file_types", [
        ("model",         "AI model weights — the primary artifact loaded for inference."),
        ("config",        "Configuration file (YAML/JSON) defining model architecture."),
        ("vae",           "VAE weights bundled separately from the main model."),
        ("training_data", "Training dataset, captions, or related assets (ZIP)."),
        ("workflow",      "Workflow file (JSON) bundled with the release."),
        ("text_encoder",  "Text encoder weights bundled separately."),
        ("clip",          "CLIP model weights bundled separately."),
        ("negative",      "Negative embedding companion file."),
        ("other",         "Uncategorized file."),
    ])

    _seed2(conn, "version_file_roles", [
        ("weights",        "Model weights file — the main artifact."),
        ("weights_pruned", "Model weights, pruned (reduced size)."),
        ("vae",            "VAE included in the release."),
        ("config",         "Architecture configuration (YAML/JSON)."),
        ("training_data",  "Training dataset or material."),
        ("negative",       "Negative embedding companion."),
        ("archive",        "Generic archive (ZIP)."),
    ])

    conn.commit()


def _seed2(conn, table, rows):
    """Seed a 2-column lookup table (id, description)."""
    conn.executemany(f"INSERT OR IGNORE INTO {table} (id, description) VALUES (?, ?)", rows)

def _seed3(conn, table, rows):
    """Seed a 3-column lookup table (id, name, description)."""
    conn.executemany(f"INSERT OR IGNORE INTO {table} (id, name, description) VALUES (?, ?, ?)", rows)


register_schema("catalog", _init_schema)


# ── CRUD: models (parent) ───────────────────────────────────────────────────

def create_model(
    name: str,
    category: str | None = None,
    type: str | None = None,
    creator: str | None = None,
    description: str | None = None,
    nsfw: bool = False,
    tags: list[str] | None = None,
) -> str:
    """Create a parent model. Returns model ID."""
    model_id = _uuid.uuid4().hex
    conn = get_conn()
    conn.execute("""
        INSERT INTO models (id, name, category, type, creator, description, nsfw, tags, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (model_id, name, category, type, creator, description,
          1 if nsfw else 0, json.dumps(tags) if tags else None, now_iso()))
    conn.commit()
    return model_id


def get_model(model_id: str) -> dict | None:
    """Get a model with version count and file count."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM models WHERE id = ?", (model_id,)).fetchone()
    if not row:
        return None
    m = dict(row)
    m["version_count"] = conn.execute(
        "SELECT COUNT(*) FROM model_versions WHERE model_id = ?", (model_id,)
    ).fetchone()[0]
    return m


def find_models(
    name: str | None = None,
    category: str | None = None,
    type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Search models with filters."""
    clauses, params = [], []
    if name:
        clauses.append("name LIKE ?")
        params.append(f"%{name}%")
    if category:
        clauses.append("category = ?")
        params.append(category)
    if type:
        clauses.append("type = ?")
        params.append(type)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = get_conn()
    rows = conn.execute(
        f"SELECT * FROM models {where} ORDER BY name LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    return [dict(r) for r in rows]


def update_model(model_id: str, **kwargs) -> bool:
    """Update model fields. Only provided kwargs are changed.

    Allowed: name, category, type, creator, description, nsfw, tags, preview_id.
    """
    allowed = {"name", "category", "type", "creator", "description", "nsfw", "tags", "preview_id"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False
    if "tags" in updates and isinstance(updates["tags"], list):
        updates["tags"] = json.dumps(updates["tags"])
    if "nsfw" in updates:
        updates["nsfw"] = 1 if updates["nsfw"] else 0
    updates["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn = get_conn()
    conn.execute(f"UPDATE models SET {set_clause} WHERE id = ?",
                 list(updates.values()) + [model_id])
    conn.commit()
    return True


def delete_model(model_id: str) -> bool:
    """Delete model. Versions CASCADE (ON DELETE SET NULL sets model_id to null)."""
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM models WHERE id = ?", (model_id,)).fetchone()
    if not row:
        return False
    conn.execute("DELETE FROM models WHERE id = ?", (model_id,))
    conn.commit()
    return True


# ── CRUD: model_versions ─────────────────────────────────────────────────────

def create_version(
    model_id: str | None,
    name: str,
    base_model: str | None = None,
    trained_words: list[str] | None = None,
    description: str | None = None,
    published_at: str | None = None,
) -> str:
    """Create a model version. Returns version ID."""
    version_id = _uuid.uuid4().hex
    conn = get_conn()
    conn.execute("""
        INSERT INTO model_versions (id, model_id, name, base_model, trained_words, description, published_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (version_id, model_id, name, base_model,
          json.dumps(trained_words) if trained_words else None,
          description, published_at, now_iso()))
    conn.commit()
    return version_id


def get_version(version_id: str) -> dict | None:
    """Get a version with its files."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM model_versions WHERE id = ?", (version_id,)).fetchone()
    if not row:
        return None
    v = dict(row)
    v["files"] = [dict(r) for r in conn.execute("""
        SELECT mf.*, vf.role FROM model_files mf
        JOIN version_files vf ON mf.id = vf.file_id
        WHERE vf.version_id = ?
    """, (version_id,)).fetchall()]
    return v


def get_versions_by_model(model_id: str) -> list[dict]:
    """Get all versions for a parent model."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM model_versions WHERE model_id = ? ORDER BY published_at DESC, created_at DESC",
        (model_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def update_version(version_id: str, **kwargs) -> bool:
    """Update version fields.

    Allowed: name, base_model, trained_words, description, published_at.
    """
    allowed = {"name", "base_model", "trained_words", "description", "published_at"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False
    if "trained_words" in updates and isinstance(updates["trained_words"], list):
        updates["trained_words"] = json.dumps(updates["trained_words"])
    updates["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn = get_conn()
    conn.execute(f"UPDATE model_versions SET {set_clause} WHERE id = ?",
                 list(updates.values()) + [version_id])
    conn.commit()
    return True


def delete_version(version_id: str) -> bool:
    """Delete version. version_files CASCADE."""
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM model_versions WHERE id = ?", (version_id,)).fetchone()
    if not row:
        return False
    conn.execute("DELETE FROM model_versions WHERE id = ?", (version_id,))
    conn.commit()
    return True


# ── CRUD: model_files ────────────────────────────────────────────────────────

def create_file(
    file: str,
    dest: str,
    file_type: str,
    store_id: str | None = None,
) -> str:
    """Create a catalog file entry. Returns file ID.

    The file may or may not be downloaded (store_id null = not downloaded).
    """
    file_id = _uuid.uuid4().hex
    conn = get_conn()
    conn.execute("""
        INSERT INTO model_files (id, file, dest, file_type, store_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (file_id, file, dest, file_type, store_id, now_iso()))
    conn.commit()
    return file_id


def get_file(file_id: str) -> dict | None:
    """Get a catalog file entry."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM model_files WHERE id = ?", (file_id,)).fetchone()
    return dict(row) if row else None


def find_files(
    file: str | None = None,
    dest: str | None = None,
    file_type: str | None = None,
    downloaded_only: bool = False,
) -> list[dict]:
    """Search catalog files."""
    clauses, params = [], []
    if file:
        clauses.append("file LIKE ?")
        params.append(f"%{file}%")
    if dest:
        clauses.append("dest = ?")
        params.append(dest)
    if file_type:
        clauses.append("file_type = ?")
        params.append(file_type)
    if downloaded_only:
        clauses.append("store_id IS NOT NULL")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = get_conn()
    rows = conn.execute(f"SELECT * FROM model_files {where} ORDER BY file", params).fetchall()
    return [dict(r) for r in rows]


def set_file_store_id(file_id: str, store_id: str | None):
    """Link or unlink a catalog file to/from the model store.

    This is how a file goes from 'cataloged' to 'downloaded':
      - Download completes → model_store.store() returns store_id
      - Catalog calls set_file_store_id(file_id, store_id)
      - Now store_id IS NOT NULL → file is available

    To mark as not downloaded (e.g. file deleted from store):
      - set_file_store_id(file_id, None)
    """
    conn = get_conn()
    conn.execute("UPDATE model_files SET store_id = ? WHERE id = ?", (store_id, file_id))
    conn.commit()


def delete_file(file_id: str) -> bool:
    """Delete a catalog file entry. version_files CASCADE."""
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM model_files WHERE id = ?", (file_id,)).fetchone()
    if not row:
        return False
    conn.execute("DELETE FROM model_files WHERE id = ?", (file_id,))
    conn.commit()
    return True


# ── Join: version_files ──────────────────────────────────────────────────────

def link_file_to_version(version_id: str, file_id: str, role: str | None = None):
    """Add a file to a version."""
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO version_files (version_id, file_id, role) VALUES (?, ?, ?)",
        (version_id, file_id, role),
    )
    conn.commit()


def unlink_file_from_version(version_id: str, file_id: str):
    """Remove a file from a version."""
    conn = get_conn()
    conn.execute(
        "DELETE FROM version_files WHERE version_id = ? AND file_id = ?",
        (version_id, file_id),
    )
    conn.commit()


# ── Source mappings ──────────────────────────────────────────────────────────

def map_source(
    entity_type: str,
    entity_id: str,
    source: str,
    source_id: str,
    source_url: str | None = None,
    source_meta: dict | None = None,
):
    """Link an entity to an external source. Upsert."""
    conn = get_conn()
    conn.execute("""
        INSERT INTO source_mappings (entity_type, entity_id, source, source_id, source_url, source_meta)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(entity_type, entity_id, source)
        DO UPDATE SET source_id = excluded.source_id,
                      source_url = excluded.source_url,
                      source_meta = excluded.source_meta
    """, (entity_type, entity_id, source, source_id, source_url,
          json.dumps(source_meta) if source_meta else None))
    conn.commit()


def get_by_source(source: str, source_id: str, entity_type: str | None = None) -> dict | None:
    """Find our entity from an external source ID.

    Args:
        source: 'civitai', 'huggingface', etc.
        source_id: ID at the source.
        entity_type: Optional filter ('model', 'version', 'file').

    Returns:
        Source mapping dict, or None.
    """
    conn = get_conn()
    if entity_type:
        row = conn.execute(
            "SELECT * FROM source_mappings WHERE source = ? AND source_id = ? AND entity_type = ?",
            (source, source_id, entity_type),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM source_mappings WHERE source = ? AND source_id = ?",
            (source, source_id),
        ).fetchone()
    return dict(row) if row else None


def get_by_source_entity(entity_type: str, entity_id: str, source: str = "civitai") -> dict | None:
    """Find external source mapping for one of our entities.

    Reverse of get_by_source: given OUR entity, find its external ID.

    Args:
        entity_type: 'model', 'version', 'file'.
        entity_id: Our internal UUID.
        source: Source name (default: 'civitai').

    Returns:
        Source mapping dict, or None.
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM source_mappings WHERE entity_type = ? AND entity_id = ? AND source = ?",
        (entity_type, entity_id, source),
    ).fetchone()
    return dict(row) if row else None


def get_sources(entity_type: str, entity_id: str) -> list[dict]:
    """Get all external source mappings for an entity."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM source_mappings WHERE entity_type = ? AND entity_id = ?",
        (entity_type, entity_id),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Import from CivitAI (upsert) ────────────────────────────────────────────

def import_from_civitai(
    civitai_data: dict,
    version_ids: list[int] | None = None,
    category: str | None = None,
) -> dict:
    """Catalog a CivitAI model with selected versions. Upsert logic.

    If the parent model already exists (by civitai_model_id in source_mappings),
    updates its metadata. If not, creates it.

    For versions: only creates versions not already in the catalog. Never deletes.
    If version_ids is None, catalogs ALL versions. If a list, only those.

    Does NOT download any files — only creates catalog entries with store_id=NULL.

    Args:
        civitai_data: Full model dict from civitai_client.get_model().
        version_ids: List of CivitAI version IDs to catalog, or None for all.
        category: Override category (e.g. 'loras'). If None, inferred from type.

    Returns:
        Dict with: model_id, versions_created, versions_skipped, files_created.
    """
    conn = get_conn()
    civitai_model_id = str(civitai_data.get("id", ""))
    model_name = civitai_data.get("name", "Unknown")
    model_type = civitai_data.get("type", "")
    creator = (civitai_data.get("creator") or {})
    if isinstance(creator, dict):
        creator = creator.get("username", "")
    tags = civitai_data.get("tags", [])
    if tags and isinstance(tags[0], dict):
        tags = [t.get("name", "") for t in tags]
    nsfw = bool(civitai_data.get("nsfw", False))

    # Infer category from CivitAI type if not provided
    if not category:
        type_to_cat = {
            "Checkpoint": "checkpoints", "LORA": "loras", "LoCon": "loras",
            "DoRA": "loras", "TextualInversion": "embeddings", "VAE": "vae",
            "Controlnet": "controlnet", "Upscaler": "upscalers",
            "MotionModule": "animatediff",
        }
        category = type_to_cat.get(model_type)

    # ── Upsert parent model ──

    existing = get_by_source("civitai", civitai_model_id, "model")
    if existing:
        model_id = existing["entity_id"]
        update_model(model_id, name=model_name, type=model_type,
                     creator=creator, tags=tags, nsfw=nsfw, category=category)
    else:
        model_id = create_model(
            name=model_name, category=category, type=model_type,
            creator=creator, nsfw=nsfw, tags=tags,
        )
        map_source("model", model_id, "civitai", civitai_model_id,
                    source_url=f"https://civitai.com/models/{civitai_model_id}")

    # ── Upsert versions ──

    versions_created = 0
    versions_skipped = 0
    files_created = 0

    for v in civitai_data.get("modelVersions", []):
        civitai_version_id = str(v.get("id", ""))

        # Filter by requested version_ids
        if version_ids is not None and int(civitai_version_id) not in version_ids:
            continue

        # Check if already cataloged
        existing_v = get_by_source("civitai", civitai_version_id, "version")
        if existing_v:
            versions_skipped += 1
            continue

        # Create version
        version_id = create_version(
            model_id=model_id,
            name=v.get("name", ""),
            base_model=v.get("baseModel"),
            trained_words=v.get("trainedWords"),
            description=v.get("description"),
            published_at=v.get("publishedAt"),
        )
        map_source("version", version_id, "civitai", civitai_version_id,
                    source_url=f"https://civitai.com/models/{civitai_model_id}?modelVersionId={civitai_version_id}")
        versions_created += 1

        # Create files for this version
        for f in v.get("files", []):
            civitai_file_id = str(f.get("id", ""))
            filename = f.get("name", "")
            file_type_raw = f.get("type", "Model")
            meta = f.get("metadata", {}) or {}

            # Map CivitAI file type to our file_types
            type_map = {
                "Model": "model", "Pruned Model": "model",
                "VAE": "vae", "Config": "config",
                "Training Data": "training_data", "Negative": "negative",
                "Archive": "other",
            }
            file_type = type_map.get(file_type_raw, "other")

            # Map CivitAI file type to version_file_role
            role_map = {
                "Model": "weights", "Pruned Model": "weights_pruned",
                "VAE": "vae", "Config": "config",
                "Training Data": "training_data", "Negative": "negative",
                "Archive": "archive",
            }
            role = role_map.get(file_type_raw, None)

            # Determine dest from category
            dest = category or "other"

            # Create catalog file entry (no store_id — not downloaded)
            file_id = create_file(
                file=filename,
                dest=dest,
                file_type=file_type,
                store_id=None,
            )
            map_source("file", file_id, "civitai", civitai_file_id,
                        source_url=f"https://civitai.com/api/download/models/{civitai_version_id}",
                        source_meta={
                            "sizeKB": f.get("sizeKB"),
                            "fp": meta.get("fp"),
                            "size": meta.get("size"),
                            "format": meta.get("format"),
                            "hashes": f.get("hashes", {}),
                        })

            # Link file to version
            link_file_to_version(version_id, file_id, role=role)
            files_created += 1

    return {
        "model_id": model_id,
        "versions_created": versions_created,
        "versions_skipped": versions_skipped,
        "files_created": files_created,
    }


# ── Stats ────────────────────────────────────────────────────────────────────

def stats() -> dict:
    """Catalog statistics."""
    conn = get_conn()
    models_count = conn.execute("SELECT COUNT(*) FROM models").fetchone()[0]
    versions_count = conn.execute("SELECT COUNT(*) FROM model_versions").fetchone()[0]
    files_count = conn.execute("SELECT COUNT(*) FROM model_files").fetchone()[0]
    downloaded = conn.execute("SELECT COUNT(*) FROM model_files WHERE store_id IS NOT NULL").fetchone()[0]
    return {
        "models": models_count,
        "versions": versions_count,
        "files": files_count,
        "downloaded": downloaded,
        "not_downloaded": files_count - downloaded,
    }
