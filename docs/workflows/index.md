# Workflows

Workflows are the core of ComfyUI Studio. They define generation pipelines that users execute through simple forms instead of building node graphs.

This section covers every aspect of the workflow system:

- [Overview](overview.md) — what workflows are, why two types, when to use each
- [Manifest Reference](manifest-reference.md) — complete field reference for `manifest.yaml`
- [Static Workflows](static-workflows.md) — single JSON file, parameter substitution
- [Dynamic Workflows](dynamic-workflows.md) — block templates, pipeline assembly
- [Block Format](block-format.md) — anatomy of a block: nodes, imports, exports, variables
- **Inputs** — the 13 input types that define the user form:
    - [Overview](inputs/index.md) — input system, common fields
    - [Text](inputs/text.md), [Integer](inputs/int.md), [Float](inputs/float.md), [Boolean](inputs/boolean.md), [Seed](inputs/seed.md), [Select](inputs/select.md), [Image](inputs/image.md)
    - [Checkpoint Picker](inputs/checkpoint-picker.md), [Resolution Picker](inputs/resolution-picker.md), [VAE Picker](inputs/vae-picker.md)
    - [LoRA Picker (Dynamic)](inputs/lora-picker-dynamic.md), [LoRA Picker (Paired)](inputs/lora-picker.md)
    - [Scene List](inputs/scene-list.md)
- [Outputs](outputs.md) — output types, directory patching, .incomplete markers
- [Execution Flow](execution-flow.md) — submit → build → ComfyUI → progress → result
- [Multi-Generate](multi-generate.md) — the N stepper for batch generation
- [Creating a Workflow](creating-a-workflow.md) — step-by-step guide
