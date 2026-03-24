# LoRA Manager

The style LoRA catalog at `/admin/loras`. Same UI pattern as the Model Manager but backed by the separate `catalogs/loras.json` catalog.

## Purpose

The LoRA Manager handles style LoRAs that are kept in a separate catalog from the main model catalog. The main models catalog (`models.json`) includes technical LoRAs (accelerators, distillation, SVI Pro), while this catalog (`loras.json`) is reserved for artistic/style LoRAs that users can curate independently.

## Layout

Identical structure to the Model Manager:

1. **Header** -- page title (no Import JSON or Fetch Metadata buttons)
2. **Status bar** -- downloading/queued/present counters, disk usage, parallel download selector
3. **Filter panel** -- base model filters, status filters, sort controls, view mode, text search
4. **Model cards** -- LoRA entries with download/delete actions

The category filter row is hidden since the LoRA catalog typically has a single category or flat structure.

## Data Loading

```
GET /api/admin/loras
```

Returns the LoRA catalog with the same format as the models endpoint: categories containing model entries, each with disk presence status and download state merged in.

## Filters and Sorting

Same controls as the Model Manager:

- **Base Model** -- filter by compatible base model
- **Status** -- present, missing, queued, downloading, error
- **Sort** -- by name, size, or status
- **View** -- extended or compact
- **Search** -- text filter across name and file

## LoRA Cards

Each LoRA card shows the same information as a model card:

- Status icon, name, filename, size, base model badge
- Download and delete action buttons
- Progress bar during downloads

## Shared Download Queue

LoRA downloads share the same download queue and concurrent download limit as models. The parallel download selector in the status bar controls the same global setting.

## Related Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/admin/loras` | GET | List all LoRAs with status |
| `/api/admin/loras/download/{filename}` | POST | Start download |
| `/api/admin/loras/{filename}` | DELETE | Delete from disk |
| `/api/admin/loras/compatible/{base_model}` | GET | Get LoRAs compatible with a base model |
