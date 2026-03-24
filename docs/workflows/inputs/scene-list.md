# Scene List Input Type

The `scene_list` input type renders a dynamic scene editor for multi-scene video generation. It is used exclusively by the WAN SVI Pro multi-scene workflow to let the user build a sequence of scenes, each with its own prompt, duration, and seed. Scenes are chained together in the backend -- each scene continues from the last frame of the previous one, creating a coherent multi-part video.

## YAML Example

From the `wan22-svi-dynamic` manifest:

```yaml
inputs:
  - id: scenes
    name: "Scenes"
    type: scene_list
    tooltip: "Build your video scene by scene. Each scene generates a clip that continues from where the previous one ended."
    per_scene:
      - id: prompt
        name: "Prompt"
        type: text
        required: true
        tooltip: "Describe the motion for this specific scene."
      - id: duration
        name: "Duration (seconds)"
        type: select
        options:
          - {label: "3 seconds", value: 3}
          - {label: "5 seconds", value: 5}
          - {label: "6 seconds", value: 6}
          - {label: "8 seconds", value: 8}
          - {label: "10 seconds", value: 10}
        default: 5
        tooltip: "Length of this individual scene clip."
      - id: seed
        name: "Seed"
        type: seed
        default: -1
        tooltip: "Seed for this specific scene. Use -1 for random."
```

## Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | yes | -- | Unique identifier. Convention is `"scenes"`. |
| `name` | string | yes | -- | Human-readable label displayed above the scene editor. |
| `type` | string | yes | -- | Must be `scene_list`. |
| `tooltip` | string | no | -- | Help text explaining how multi-scene video works. |
| `per_scene` | list | yes | -- | Array of input definitions that appear within each scene card. These define the fields that repeat per scene. |

### Per-scene field definitions

The `per_scene` array contains input definitions using the same format as top-level inputs, but they are rendered inside each scene card. Supported sub-types:

| per_scene field | Type | Purpose |
|----------------|------|---------|
| `prompt` | `text` | Describes the motion/action for this scene. Each scene gets its own prompt. |
| `duration` | `select` | How long this scene lasts. Options defined as label/value pairs. |
| `seed` | `seed` | Random seed for this scene's generation. -1 = random. |

## Frontend Behavior

When the runner page encounters a `type: scene_list` input, the `buildSceneList()` function creates a container with add/remove scene functionality.

### Container structure

- A `<div>` with class `scene-list` and `data-input-id` set to the input's id.
- Scene cards are rendered inside this container.
- An "+ Add Scene" button is appended at the bottom.

### Scene card structure

Each scene card (`<div class="scene-card">`) contains:

1. **Header row**: "Scene N" label (with class `scene-num`) and a remove button (X). Scene 1 cannot be removed -- the minimum is always 1 scene.

2. **Prompt textarea** (`<textarea class="scene-prompt">`): Placeholder text "Describe what happens in this scene...". Maps to the `prompt` per-scene field.

3. **Duration row**: A "Duration:" label and a `<select>` dropdown (class `scene-duration`). Options come from the `per_scene` field with `id: "duration"`. Each option shows the label and submits the value.

4. **Seed row**: A "Seed:" label, a number input (class `scene-seed`, width 160px), and a "Random" button. The Random button sets the value to -1 (not a random integer -- the backend resolves -1 to an actual random seed).

### Scene management

- **Initial state**: One scene card is added automatically on load.
- **Adding scenes**: The "+ Add Scene" button calls `addScene()` with default values (empty prompt, default duration, seed -1). A new card is inserted before the add button.
- **Removing scenes**: Each card (except scene 1) has an X button that removes it and calls `renumber()` to update all remaining scene numbers.
- **Renumbering**: The `renumber()` function iterates over all `.scene-card` elements and updates their `.scene-num` text to "Scene 1", "Scene 2", etc.
- **Scene limit**: There is no hard limit in the frontend code, but the tooltip mentions 1-10 scenes as the practical range. The actual limit depends on VRAM and processing time.

### Value gathering

The `getSceneListValue()` function collects all scene data:

```javascript
function getSceneListValue(inputId) {
    var scenes = [];
    container.querySelectorAll('.scene-card').forEach(function(card) {
        var prompt = card.querySelector('.scene-prompt').value || '';
        var dur = card.querySelector('.scene-duration');
        var seedEl = card.querySelector('.scene-seed');
        var seed = seedEl ? Number(seedEl.value) : -1;
        scenes.push({
            prompt: prompt,
            duration: dur ? Number(dur.value) : 5,
            seed: seed
        });
    });
    return scenes;
}
```

The result is an array of scene objects, each with:
- `prompt`: the scene's text description (string)
- `duration`: the scene's length in seconds (integer)
- `seed`: the scene's random seed (-1 for random, or a specific number)

### Re-run prefill

The `prefillSceneList()` function restores scenes from saved job data:

1. Removes all existing scene cards
2. Iterates over the saved scenes array
3. Calls `container.addScene()` for each with the saved prompt, duration, and seed
4. If the job record contains resolved seeds (from `job.seeds`), those are merged into the scene data so the user can see and reuse the exact seeds from the previous run
5. Calls `container.renumber()` to fix scene numbering

### Seed display after execution

After a successful job execution, the backend returns resolved seeds in the response. The frontend shows "Used: 1234567890" hints below each scene's seed input:

```javascript
var match = key.match(/^scene_(\d+)$/);
if (match) {
    var sceneIdx = parseInt(match[1]) - 1;
    var sceneCards = document.querySelectorAll('.scene-card');
    if (sceneCards[sceneIdx]) {
        var seedInput = sceneCards[sceneIdx].querySelector('.scene-seed');
        if (seedInput && Number(seedInput.value) === -1) {
            // Show "Used: <seed>" hint
        }
    }
}
```

## Backend Behavior

### Scene list processing

The backend receives the `scenes` parameter as a JSON array. If it arrives as a string (from form encoding), it is parsed with `json.loads()`:

```python
if isinstance(form_params.get("scenes"), str):
    form_params["scenes"] = json.loads(form_params["scenes"])
```

### Scene-by-scene assembly

The SVI Pro dynamic workflow assembler processes scenes sequentially:

```python
for i in range(num_scenes):
    scene = scenes[i]
    duration_sec = int(scene.get("duration", 5))
    duration_frames = duration_sec * 16 + 1
    scene_seed = int(scene.get("seed", -1))
    if scene_seed == -1:
        scene_seed = random.randint(0, 2**53)
    resolved_seeds[f"scene_{i+1}"] = scene_seed
```

For each scene:

1. **Duration conversion**: The duration in seconds is converted to frame count using `duration_sec * 16 + 1` (WAN generates at 16fps, +1 for the start frame).

2. **Seed resolution**: If -1, a random seed is generated. The resolved seed is stored as `scene_1`, `scene_2`, etc.

3. **Block instantiation**:
   - **Scene 1**: Uses the `scene_first` block template. Receives the input image and setup exports (model, clip, vae, sampler, sigmas).
   - **Scenes 2+**: Use the `scene_extend` block template. Additionally receives the previous scene's outputs (`prev_samples`, `prev_images`) for latent continuation.

### Latent continuation

The key feature of multi-scene generation is latent continuation. Each `scene_extend` block takes the previous scene's latent samples and images as input:

```python
if i == 0:
    tmpl = block_templates["scene_first"]
    scene_exports = instantiate_block(f"scene_{i}", tmpl, scene_vars, imports_map)
else:
    tmpl = block_templates["scene_extend"]
    imports_map["prev_samples"] = prev_scene_exports["samples"]
    imports_map["prev_images"] = prev_scene_exports["images"]
    scene_exports = instantiate_block(f"scene_{i}", tmpl, scene_vars, imports_map)
```

This creates a chain: scene 1's last frame becomes scene 2's starting point, scene 2's last frame becomes scene 3's starting point, and so on. The result is a continuous video where scenes flow naturally into each other, with overlap frames for smooth transitions (`ImageBatchExtendWithOverlap` node).

### Per-scene seed storage

Each scene's resolved seed is stored separately in the job record:

```json
{
  "seeds": {
    "scene_1": 4827391056,
    "scene_2": 9182736450,
    "scene_3": 2738194562
  }
}
```

This enables per-scene reproducibility. A user can set scene 1 to a specific seed (to lock in a good starting motion) while keeping scenes 2 and 3 random (to explore variations).

## Notes

- The `scene_list` type is designed exclusively for the WAN SVI Pro multi-scene workflow. It is not a general-purpose list input.
- Scene 1 is mandatory and cannot be removed. Attempting to close it has no effect because the remove button is only added for scenes with index > 0.
- Each scene's prompt describes the motion for that specific scene, not the overall video. Prompts can change between scenes (e.g. scene 1: "she walks forward", scene 2: "she turns and smiles").
- Duration options are defined per-workflow in the `per_scene` field, not hardcoded. The SVI Pro workflow offers 3, 5, 6, 8, and 10 second options. Other workflows could define different options.
- The total video length is the sum of all scene durations minus overlap frames. A 3-scene video with 5s each produces roughly 15 seconds of footage (minus a few seconds of overlap at the transitions).
- Longer scenes (8-10s) give the model more time for complex actions but may lose coherence. Shorter scenes (3-5s) are more stable and the transitions help reset coherence.
- When re-running a multi-scene job, the resolved seeds from the original job are used instead of -1, so the exact same video can be reproduced.
