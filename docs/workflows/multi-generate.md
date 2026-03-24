# Multi-Generate

The stepper control next to the Generate button lets users run the same workflow multiple times in sequence, each with a different random seed.

## How It Works

Next to the **Generate** button on the runner page, there's a stepper control: `[- N +]`

- Default: `1`
- Range: `1` to `99`
- The minus button decreases N, the plus button increases it

When the user clicks Generate with N > 1:

1. The frontend sends N **sequential** `POST /api/run/{workflow_id}/execute` requests
2. Each request uses the **same parameters** (prompt, model, settings) but with a **fresh random seed**
3. If the seed field was set to `-1` (random), each request gets a different random seed
4. If the seed field was set to a specific number (e.g., `42`), all N requests use that same seed — they produce identical results

## Each Generation is Independent

Each of the N requests creates:

- A separate job record in the database
- A separate output directory (`comfyui-studio/{jobid}/`)
- A separate entry in the Queue and History pages
- Its own progress tracking and preview

They execute sequentially — ComfyUI processes one at a time. The Queue page shows all queued/running jobs.

## Seed Behavior

| Seed Setting | Multi-Generate Behavior |
|-------------|------------------------|
| `-1` (random) | Each generation gets a unique random seed. Maximum diversity. |
| Specific number (e.g., `42`) | All N generations use seed `42`. Produces identical outputs. Useful for testing other parameter changes. |

The resolved seeds are saved in each job record, so you can reproduce any specific result later by setting that seed explicitly.

## Use Cases

- **Exploration**: Set seed to -1, generate 10 images, pick the best one. Each will be different.
- **Comparison**: Change one parameter (e.g., CFG scale), set a fixed seed, generate N variations. The only difference is the parameter you changed.
- **Batch production**: Once you have a prompt you like, generate many variations quickly.

## Technical Detail

The frontend implements multi-generate as a simple loop:

```javascript
for (let i = 0; i < N; i++) {
    await fetch(`/api/run/${workflowId}/execute`, {
        method: 'POST',
        body: formData
    });
}
```

Each call is awaited — the next request is sent only after the previous one is accepted by the backend (not after it completes). This means all N jobs are queued almost immediately, and ComfyUI processes them one by one.
