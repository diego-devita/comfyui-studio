---
name: schema
description: Show database table schema, row counts, and indexes. Usage: /schema [group|table|all]
---

Show the SQLite database schema for the requested tables.

## How to resolve the argument

- No argument or `all` → show all tables with row counts (summary)
- A group name → show full schema for all tables in that group
- A table name → show full schema for that single table

## Known groups

- `media` → tables: media, media_thumbs
- `jobs` → tables: jobs, downloads
- `events` → tables: events
- `settings` → tables: settings
- `workflows` → tables: workflows
- `prompts` → tables: saved_prompts
- `gallery` → tables: gallery_images, image_versions, civitai_tags, gallery_previews (in gallery.db)
- `telegram` → tables: contacts (in telegram.db)
- `llm` → tables: chat_presets, chat_preset_examples, conversations, pipeline_runs (in llm.db)
- `models` → tables: model_categories, model_groups, models, model_files (planned, may not exist yet)

## How to get the info

1. Connect to the appropriate DB file:
   - Default: `STUDIO_DIR/database/studio.db`
   - Gallery: `STUDIO_DIR/assets/images/gallery.db`
   - Telegram: `STUDIO_DIR/database/telegram.db`
   - LLM: `STUDIO_DIR/database/llm.db`
   - If running locally, check the current directory for `database/studio.db`

2. For summary (no arg or `all`):
   ```sql
   SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;
   SELECT COUNT(*) FROM <table>;
   ```

3. For full schema of a table:
   ```sql
   SELECT sql FROM sqlite_master WHERE type='table' AND name='<table>';
   SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='<table>';
   PRAGMA table_info(<table>);
   SELECT COUNT(*) FROM <table>;
   ```

## Output format

For summary:
```
studio.db:
  media              1,050 rows
  media_thumbs       2,890 rows
  jobs                 342 rows
  ...
```

For full schema:
```
media (1,050 rows)
  id              TEXT     PK
  file_path       TEXT     NOT NULL
  thumb_path      TEXT
  type            TEXT     NOT NULL
  ...

  Indexes:
    idx_media_hash    ON media(hash)
    idx_media_type    ON media(type)

  Foreign keys: none
```

If the DB file doesn't exist or a table doesn't exist, say so clearly.
