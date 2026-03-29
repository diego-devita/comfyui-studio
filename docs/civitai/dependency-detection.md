# Dependency Detection

When analyzing CivitAI image generation data, the backend detects hidden dependencies that are not in the structured `resources` array but are embedded in the prompt text.

## LoRA Tags in Prompts

LoRA references in positive prompts use the syntax `<lora:Name:weight>`. The `_parse_lora_tags()` function:

1. Extracts all `<lora:Name:weight>` patterns from the prompt
2. Returns a list of `{name, weight, source: "prompt"}` objects
3. Also returns a clean prompt with all LoRA tags removed and whitespace collapsed

**Example:**

```
a portrait of a woman <lora:DetailTweaker:0.8> <lora:FilmGrain:0.5>, soft lighting
```

Produces:

- LoRAs: `[{name: "DetailTweaker", weight: 0.8}, {name: "FilmGrain", weight: 0.5}]`
- Clean prompt: `"a portrait of a woman, soft lighting"`

## Embeddings in Negative Prompts

Embeddings (textual inversions) are detected in the negative prompt by matching against the `meta.resources` array. The `_parse_embeddings()` function:

1. Splits the negative prompt into lines
2. Matches single tokens (alphanumeric with underscores/hyphens) against known resource names
3. Returns detected embeddings with their hash if available

## Resolution Pipeline

After detecting LoRAs and embeddings, the backend resolves each dependency:

1. **Hash lookup** -- `_resolve_by_hash()` calls `https://civitai.com/api/v1/model-versions/by-hash/{hash}` using the SHA256 hash from `meta.resources`
2. **Name search fallback** -- `_resolve_by_name()` searches `https://civitai.com/api/v1/models` by name with a 60% word overlap threshold
3. **Catalog cross-reference** -- each resolved dependency is checked against the local CivitAI map for catalog status

The enriched dependency objects include:

| Field | Description |
|-------|-------------|
| `name` | Original name from prompt/negative |
| `source` | Where it was found: `"prompt"`, `"negative_prompt"`, or `"meta_resources"` |
| `hash` | SHA256 hash from meta.resources (if available) |
| `civitai_model_id` | Resolved CivitAI model ID |
| `civitai_version_id` | Resolved CivitAI version ID |
| `civitai_model_name` | Model name on CivitAI |
| `civitai_file` | Primary file name |
| `civitai_download_url` | Direct download URL |
| `catalog_status` | `"present"`, `"missing"`, `"not_found"`, or `"unknown"` |
