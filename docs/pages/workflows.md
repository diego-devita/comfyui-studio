# Workflow Manager

The workflow catalog at `/admin/workflows`. Browse registered workflows, check their readiness (model and node dependencies), and launch them.

## Layout

1. **Header** -- page title
2. **Card grid** -- workflow cards in a responsive grid (min 400px per card)

## Data Loading

```
GET /api/admin/workflows
```

Returns an array of workflow objects, each containing:

- `id`, `name`, `description`, `category`, `version`, `type` (static/dynamic)
- `author`, `updated_at`
- `models_status` -- `{total, present, missing: [filenames]}`
- `nodes_status` -- `{total, installed, missing: [node_names]}`
- `required_models` -- full list of required model filenames
- `required_nodes` -- full list of required node class names

The backend loads `workflows/index.json`, then for each workflow reads its `manifest.yaml` and checks whether every required model file exists on disk and every required node is installed in ComfyUI.

## Workflow Cards

Each workflow is rendered as a card with:

### Top Row

- **Category badge** -- colored pill based on workflow type:
    - T2I = yellow
    - I2V = blue
    - I2I = orange
    - IPA = purple
- **Name** -- workflow display name
- **Version badge** -- e.g., "v9"

### Description

Two-line clamped description text from the manifest.

### Metadata

Date and author (if set), shown in monospace text.

### Dependency Bars

Two rows showing model and node dependency status:

- **Models** -- a row of small dots (one per required model). Green dots for present files, grey dots for missing. A count label like "5/7" with color coding: green if all present, orange if some missing.
- **Nodes** -- same pattern for required node packages.

If models are missing, an "Install Missing" button appears that batch-downloads all missing models.

### Type Badge

A small badge in the bottom-right corner of the card:

- **Static** -- grey, for workflows with a fixed `workflow.json`
- **Dynamic** -- yellow/accent, for workflows assembled from block templates at runtime

### Readiness Indicator

The card border color indicates overall readiness:

- **Green border** -- all models present and all nodes installed (ready to run)
- **Orange border** -- some models missing (can be downloaded)
- **Red border** -- some nodes missing (requires Docker image update)

### Expandable Details

Clicking a card toggles an expanded section showing:

- **Required Models** -- list of all model filenames as pills, each colored green (present) or grey (missing)
- **Required Nodes** -- same treatment for node packages

### Actions

- **Run** button -- navigates to `/run/{workflow_id}` to open the Workflow Runner form

## Related Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/admin/workflows` | GET | List workflows with readiness status |
| `/api/admin/models/batch-download` | POST | Download missing models for a workflow |
