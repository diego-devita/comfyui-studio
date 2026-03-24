# Dynamic Workflows

Dynamic workflows have no fixed `workflow.json`. Instead, they define reusable **block templates** that the backend assembles at runtime based on user input.

## Why Dynamic?

Static workflows have a fixed graph — every user gets the same node structure. Dynamic workflows solve three problems that static can't:

1. **Variable repetition** — a multi-scene video needs N scene blocks, where N is chosen by the user
2. **Conditional sections** — hires fix and face fix should only run if the user enables them
3. **Reusable composition** — the same "setup" block (checkpoint + CLIP + prompt encoding) can be shared across many workflows

## File Structure

```
workflows/t2i-batch/
├── manifest.yaml
└── blocks/
    ├── setup.json          # Loads checkpoint, encodes prompts
    └── generate.json       # Creates latent, samples, decodes, saves
```

## Pipeline

The manifest defines the assembly order:

```yaml
pipeline:
  - block: setup
    file: "setup.json"
  - block: generate
    file: "generate.json"
```

The backend processes blocks in order:

1. Load `setup.json`, instantiate its nodes, prefix all node IDs with `setup_`
2. Load `generate.json`, instantiate its nodes, prefix with `generate_`
3. Connect `generate`'s imports to `setup`'s exports
4. Substitute all `{{variables}}` with user values
5. Merge all nodes into one flat workflow dict and send to ComfyUI

## Block Connections

Blocks communicate through **imports** and **exports**:

```
setup block                     generate block
┌─────────────────┐            ┌─────────────────┐
│ CheckpointLoader ─── model ──→ KSampler         │
│ CLIPTextEncode   ── positive ──→                 │
│ CLIPTextEncode   ── negative ──→                 │
│ CheckpointLoader ─── vae ────→ VAEDecode         │
└─────────────────┘            └─────────────────┘
     exports:                       imports:
     model, positive,              model, positive,
     negative, vae                 negative, vae
```

The setup block **exports** `model`, `positive`, `negative`, `vae`. The generate block **imports** the same names. The assembler wires them together.

## Repetition

### Fixed Repeat

A block can be instantiated a fixed number of times:

```yaml
pipeline:
  - block: scene_first
    file: "scene_first.json"
    repeat: 1
```

Each instance gets a unique prefix: `scene_first_0_`, `scene_first_1_`, etc.

### Variable Repeat

A block can repeat based on a runtime value:

```yaml
pipeline:
  - block: scene_extend
    file: "scene_extend.json"
    repeat_variable: "extra_scenes"
```

If the user creates 5 scenes, `extra_scenes` = 4 (first scene uses `scene_first`, the remaining 4 use `scene_extend`). The assembler creates 4 instances: `scene_extend_0_`, `scene_extend_1_`, `scene_extend_2_`, `scene_extend_3_`.

Each instance's imports connect to the previous instance's exports (or to the previous block if it's the first instance). This creates a chain:

```
scene_first → scene_extend_0 → scene_extend_1 → scene_extend_2 → scene_extend_3 → output
```

## Node ID Prefixing

To prevent collisions when the same block is instantiated multiple times, the assembler prefixes all node IDs with `{block_name}_{instance_index}_`:

Block definition:
```json
{"nodes": {"sampler": {...}, "vae_decode": {...}}}
```

After assembly (instance 0 of "generate" block):
```json
{"generate_0_sampler": {...}, "generate_0_vae_decode": {...}}
```

References within the block are also updated: `["sampler", 0]` becomes `["generate_0_sampler", 0]`.

## Variable Substitution in Repeated Blocks

When a block repeats, each instance can receive different variables. For the scene system:

- Instance 0 gets `scene_2_prompt`, `scene_2_duration`, `scene_2_seed` (scene 2 because scene 1 is `scene_first`)
- Instance 1 gets `scene_3_prompt`, `scene_3_duration`, `scene_3_seed`
- And so on

The assembler maps per-scene values from the `scene_list` input to per-instance variables.

## Conditional Blocks

The Text to Image dynamic workflow uses booleans to conditionally enable blocks:

```yaml
inputs:
  - id: hires_enabled
    type: boolean
    default: false
  - id: facefix_enabled
    type: boolean
    default: false
```

The assembler checks these booleans and skips the corresponding blocks if disabled. The pipeline still lists them, but they're only instantiated if the condition is true.

## Current Dynamic Workflows

| ID | Blocks | Pipeline |
|----|--------|----------|
| `wan22-svi-dynamic` | setup, scene_first, scene_extend, output | setup → scene_first(1) → scene_extend(N) → output |
| `t2i-dynamic` | setup, generate, hires, face_fix, output | setup → generate → [hires] → [face_fix] → output |
| `t2i-batch` | setup, generate | setup → generate |
| `i2i-batch` | setup, generate | setup → generate(N) |
| `ipa-batch` | setup, generate | setup → generate |
| `faceid-batch` | setup, generate | setup → generate |

Brackets `[...]` indicate conditional blocks. `(N)` indicates repeated blocks.
