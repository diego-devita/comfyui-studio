# Presets Page

The preset management page at `/admin/presets`. Lists all saved presets with actions to run, edit, export, and delete.

## Layout

1. **Header** -- page title and preset count
2. **Preset cards** -- grid of preset cards with details and action buttons

## Preset Cards

Each card shows:

- **Name** -- preset display name
- **Description** -- optional description text
- **Workflow** -- associated workflow name and ID
- **Privacy badge** -- "Private" label if the preset is marked private
- **Source badge** -- "CivitAI" badge with link if the preset was created from a CivitAI image

## Actions

| Action | Description |
|--------|-------------|
| **Run** | Loads the preset parameters into the workflow runner via sessionStorage and navigates to `/run/{workflow_id}` |
| **Edit** | Edit the preset name, description, ID, and privacy setting |
| **Export** | Download the preset as a JSON file |
| **Delete** | Delete the preset (with confirmation dialog) |

## Data Loading

```
GET /api/admin/presets
```

Returns an array of preset summary objects. The page renders one card per preset.

## Related Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/admin/presets` | GET | List all presets |
| `/api/admin/presets/{id}` | GET | Get preset details |
| `/api/admin/presets` | POST | Save a new preset |
| `/api/admin/presets/{id}/rename` | PUT | Update preset metadata |
| `/api/admin/presets/{id}` | DELETE | Delete a preset |
| `/api/admin/presets/{id}/export` | GET | Download preset JSON |
