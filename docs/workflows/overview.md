# Workflow Overview

## What is a Workflow?

A workflow is a predefined ComfyUI generation pipeline packaged with a form definition. Instead of connecting nodes in the ComfyUI graph editor, the user fills in a form (prompt, model, settings) and clicks "Generate". The backend assembles the ComfyUI workflow from the form values and sends it to ComfyUI for execution.

Each workflow has:

- A **manifest** (`manifest.yaml`) that defines metadata, inputs, outputs, and required models
- Either a **workflow file** (`workflow.json`) for static workflows, or **block templates** (`blocks/*.json`) for dynamic workflows
- An entry in the **index** (`workflows/index.json`) for version tracking

## Two Types of Workflows

### Static Workflows

A static workflow has a single `workflow.json` file in ComfyUI API format. The backend reads this file, substitutes user parameters into specific node inputs (marked with `{{variable_name}}` placeholders), and sends the result to ComfyUI.

```
workflows/wan22-i2v-fp8/
├── manifest.yaml
└── workflow.json          ← fixed graph, params substituted at runtime
```

**When to use static workflows:**

- The graph structure never changes regardless of user input
- The workflow was exported from ComfyUI and adapted for Studio
- You want a direct 1:1 mapping between a ComfyUI graph and a Studio form
- The number of nodes is fixed (no repeating or conditional sections)

**Current static workflows:** WAN 2.2 I2V (FP8, Kijai, LightX2V) -- 3 workflows

### Dynamic Workflows

A dynamic workflow has no `workflow.json`. Instead, it has block templates in a `blocks/` directory that the backend assembles at runtime based on user input.

```
workflows/t2i-batch/
├── manifest.yaml
└── blocks/
    ├── setup.json         ← block template
    └── generate.json      ← block template
```

**When to use dynamic workflows:**

- The graph structure changes based on user input (e.g., number of scenes)
- Parts of the graph can be conditionally enabled/disabled (e.g., hires fix, face fix)
- Sections of the graph repeat N times (e.g., multiple scenes, batch processing)
- You want to compose reusable building blocks

**Current dynamic workflows (9):**

| ID | Name | Group |
|----|------|-------|
| `wan22-svi-dynamic` | SVI Pro Multi-Scene | Original |
| `t2i-dynamic` | Text to Image | Original |
| `t2i-batch` | T2I Batch | Original |
| `t2i-unified` | T2I Unified | Unified |
| `i2i-batch` | I2I Batch | Original |
| `inpainting` | Inpainting | Original |
| `ipa-batch` | IP-Adapter Batch | Original |
| `ipa-unified` | IP-Adapter Unified | Unified |
| `faceid-batch` | FaceID Batch | Original |

Workflow groups: **Original** workflows were built first. **Unified** workflows consolidate multiple generation modes into a single form with conditional inputs.

## How They're Stored

### Index (`workflows/index.json`)

The workflow registry lists all available workflows with their versions:

```json
{
  "version": 44,
  "date": "2026-03-29 17:00",
  "workflows": [
    {"id": "wan22-i2v-fp8", "version": 4, "date": "2026-03-23 01:40"},
    {"id": "t2i-batch", "version": 3, "date": "2026-03-23 01:05"},
    {"id": "inpainting", "version": 1, "date": "2026-03-28 10:00"}
  ]
}
```

- The top-level `version` is the index version — bumped when any workflow changes
- Each workflow entry has its own `version` — bumped when that specific workflow changes
- These versions are mirrored in `version.json` for the update mechanism

### Workflow Directory

Each workflow lives in `workflows/<id>/` where `<id>` is a unique identifier used in URLs (`/run/<id>`) and API calls.

The directory always contains `manifest.yaml`. It also contains either `workflow.json` (static) or a `blocks/` directory (dynamic).

## How the Frontend Discovers Workflows

1. The Workflow Manager page calls `GET /api/admin/workflows`
2. The backend reads `workflows/index.json` and each `manifest.yaml`
3. For each workflow, it checks readiness: are all `required_models` present on disk? Are all `required_nodes` available in ComfyUI?
4. The response includes name, description, type, category, version, and readiness status
5. The frontend renders cards with badges: type badge (Static/Dynamic), category badge (T2I/I2V/I2I/IPA), and readiness indicator (green/red)

## How the Runner Executes a Workflow

1. User navigates to `/run/<workflow_id>`
2. Frontend calls `GET /api/run/<workflow_id>` to get the manifest and render the form
3. User fills in the form and clicks Generate
4. Frontend sends `POST /api/run/<workflow_id>/execute` with form data (and optional image file)
5. Backend calls `_build_workflow()`:
    - **Static:** loads `workflow.json`, substitutes `{{variables}}` from form params
    - **Dynamic:** loads block templates, assembles them according to the pipeline, substitutes variables
6. Backend patches all output nodes to write into the job's output directory
7. Backend sends the assembled workflow to ComfyUI's `/prompt` endpoint
8. Backend starts a WebSocket listener thread for real-time progress
9. Progress, preview frames, and completion events are pushed to connected clients via Studio's WebSocket

See [Execution Flow](execution-flow.md) for the complete detail.
