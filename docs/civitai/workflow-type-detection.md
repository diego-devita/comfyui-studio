# Workflow Type Detection

The `_detect_workflow_type()` function heuristically determines the generation workflow type from CivitAI generation data. This is used to map CivitAI images to the appropriate Studio workflow when creating presets.

## Detection Signals

The function examines multiple signals in priority order:

1. **Content type** (`type` field) -- `"video"` vs `"image"`
2. **Meta workflow** (`meta.workflow`) -- the most reliable signal when present (e.g., `"img2vid"`, `"txt2vid"`)
3. **Techniques** (`techniques` array) -- `"img2vid"`, `"txt2vid"`, `"txt2img"`, `"img2img"`
4. **Resource base models** (`resources[].baseModel`) -- look for `"i2v"` or `"t2v"` in base model names (e.g., `"Wan Video 14B i2v 720p"`)
5. **Process** (`process` field) -- `"txt2img"`, `"img2img"`

## Detection Results

| Result | Meaning |
|--------|---------|
| `t2i` | Text to image |
| `i2i` | Image to image |
| `i2v` | Image to video |
| `t2v` | Text to video |
| `unknown` | Could not determine |

## Logic Flow

```
if type == "video":
    check meta.workflow for "img2vid"/"i2v" → i2v
    check meta.workflow for "txt2vid"/"t2v" → t2v
    check techniques for "img2vid" → i2v
    check techniques for "txt2vid" → t2v
    check resource baseModels for "i2v" → i2v
    check resource baseModels for "t2v" → t2v
    default → t2v

if process == "txt2img" or "txt2img" in techniques → t2i
if "img2img" in process → i2i

default → unknown
```

For video content, `meta.workflow` is the most reliable signal because CivitAI populates it from the actual ComfyUI workflow metadata. The `techniques` array and resource base models serve as fallbacks when `meta.workflow` is empty.
