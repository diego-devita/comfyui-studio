# Block Format

Blocks are the building units of dynamic workflows. Each block is a JSON file containing ComfyUI nodes, connection points (imports/exports), and variable declarations.

## Complete Example

Here's the `generate.json` block from the T2I Batch workflow:

```json
{
  "nodes": {
    "empty_latent": {
      "inputs": {
        "width": "{{width}}",
        "height": "{{height}}",
        "batch_size": "{{batch_size}}"
      },
      "class_type": "EmptyLatentImage",
      "_meta": {"title": "Empty Latent"}
    },
    "sampler": {
      "inputs": {
        "seed": "{{seed}}",
        "steps": "{{steps}}",
        "cfg": "{{cfg}}",
        "sampler_name": "{{sampler_name}}",
        "scheduler": "{{scheduler}}",
        "denoise": "{{denoise}}",
        "model": ["model", 0],
        "positive": ["positive", 0],
        "negative": ["negative", 0],
        "latent_image": ["empty_latent", 0]
      },
      "class_type": "KSampler",
      "_meta": {"title": "Sampler"}
    },
    "vae_decode": {
      "inputs": {
        "samples": ["sampler", 0],
        "vae": ["vae", 0]
      },
      "class_type": "VAEDecode",
      "_meta": {"title": "VAE Decode"}
    },
    "save": {
      "inputs": {
        "filename_prefix": "{{output_prefix}}",
        "images": ["vae_decode", 0]
      },
      "class_type": "SaveImage",
      "_meta": {"title": "Save Image"}
    }
  },
  "imports": ["model", "positive", "negative", "vae"],
  "exports": {
    "image": {"node": "vae_decode", "output": 0}
  },
  "variables": [
    "width", "height", "batch_size",
    "seed", "steps", "cfg", "sampler_name", "scheduler", "denoise",
    "output_prefix"
  ]
}
```

## Structure

A block JSON has four top-level keys:

### `nodes`

A dictionary of ComfyUI nodes. Keys are **local node IDs** (strings, not numbers). These are scoped to the block — the assembler prefixes them to avoid collisions.

Each node has:

| Field | Required | Description |
|-------|----------|-------------|
| `inputs` | **Yes** | Dictionary of input name → value. Values can be literals, variables, or node references. |
| `class_type` | **Yes** | The ComfyUI node class name (e.g., `"KSampler"`, `"CheckpointLoaderSimple"`). |
| `_meta` | No | Metadata object with `title` field. Used for display in ComfyUI UI export. |

### Node Input Values

Node inputs can be one of four types:

**String literal:**
```json
"sampler_name": "euler_ancestral"
```
Passed to ComfyUI as-is.

**Number literal:**
```json
"steps": 20
```
Passed as-is.

**Variable reference:**
```json
"text": "{{positive_prompt}}"
```
The `{{...}}` placeholder is replaced with the user's form value at assembly time. The variable name must appear in the block's `variables` list.

**Node reference:**
```json
"model": ["checkpoint", 0]
```
Connects to another node's output. Format: `[node_id, output_index]`.

- **Local references** use a node ID defined in the same block: `["sampler", 0]`
- **Import references** use an import name: `["model", 0]` — the assembler resolves this to the exporting node from the previous block

The output index is a zero-based integer corresponding to the node's output slots. For example, `CheckpointLoaderSimple` has three outputs: 0 = model, 1 = clip, 2 = vae.

### `imports`

A list of named connection points that this block expects from a previous block:

```json
"imports": ["model", "positive", "negative", "vae"]
```

When the assembler wires blocks together, it takes the previous block's exports and maps them to this block's imports. Inside the block, import names are used as if they were local nodes:

```json
"model": ["model", 0]
```

This references the "model" import at output index 0.

If a block has no imports (like a `setup` block that starts the pipeline), this field can be omitted or set to an empty list.

### `exports`

Named outputs that this block provides to the next block:

```json
"exports": {
  "model": {"node": "checkpoint", "output": 0},
  "positive": {"node": "pos_prompt", "output": 0},
  "negative": {"node": "neg_prompt", "output": 0},
  "vae": {"node": "checkpoint", "output": 2}
}
```

Each export has:

| Field | Description |
|-------|-------------|
| `node` | The local node ID that produces this output |
| `output` | The output index of that node |

The next block in the pipeline can import these by name.

### `variables`

A list of variable names used in `"{{...}}"` placeholders:

```json
"variables": ["seed", "steps", "cfg", "sampler_name", "scheduler"]
```

This is a declaration — the assembler checks that all declared variables have values from the form parameters. If a variable is missing, the assembler raises an error.

Variables not in this list but present as `"{{...}}"` in node inputs will still be substituted (the list is advisory, not enforced as a strict whitelist in all implementations), but best practice is to declare them all.

## Assembly Process

When the backend builds a dynamic workflow:

1. **Load each block** in pipeline order
2. **Prefix node IDs** with `{block}_{instance}_` to avoid collisions
3. **Resolve imports**: for each import, find the matching export from the previous block (or previous instance in a repeating chain) and replace import references with the actual prefixed node ID
4. **Substitute variables**: replace all `"{{var}}"` placeholders with form values, converting types as needed
5. **Merge all nodes** into one flat dictionary — this becomes the ComfyUI API-format workflow
6. **Patch outputs**: redirect all SaveImage/VHS_VideoCombine nodes to the job output directory

The result is a standard ComfyUI API-format JSON that looks exactly like what you'd get from exporting a graph in ComfyUI, but assembled programmatically from modular pieces.
