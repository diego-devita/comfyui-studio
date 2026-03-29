# Input Types

Workflow manifests define form inputs using a typed system. Each input type renders a specific form control in the workflow runner.

There are 13 input types available:

| Type | Control | Description |
|------|---------|-------------|
| [text](text.md) | Textarea | Free-form text input for prompts |
| [int](int.md) | Number input | Integer value with optional min/max |
| [float](float.md) | Range slider | Decimal value with slider control |
| [boolean](boolean.md) | Toggle switch | On/off toggle |
| [seed](seed.md) | Number + Random button | Seed value with randomization |
| [select](select.md) | Dropdown | Fixed list of options |
| [image](image.md) | Drag-and-drop zone | Image upload with preview |
| [checkpoint_picker](checkpoint-picker.md) | Dropdown | Downloaded checkpoint models |
| [resolution_picker](resolution-picker.md) | Dropdown | Resolution presets by base model |
| [lora_picker](lora-picker.md) | Dropdown + slider | Paired LoRA selector with strength |
| [lora_picker_dynamic](lora-picker-dynamic.md) | Multi-slot picker | Multiple LoRAs with individual strengths |
| [scene_list](scene-list.md) | Card list | Dynamic list of scene configurations |
| [vae_picker](vae-picker.md) | Dropdown | Downloaded VAE models |
