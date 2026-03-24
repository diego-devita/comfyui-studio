# Your First Generation

This guide walks you through downloading a model and generating your first image.

## Step 1: Download a Model

Go to **Models** in the navigation bar. You'll see the model catalog organized by category.

For your first generation, you need at minimum:

- A **checkpoint** (the base model)
- The checkpoint's **VAE** (if not built-in)
- The checkpoint's **CLIP/text encoder**

The simplest option is **Stable Diffusion v1.5** — it's a single checkpoint file that includes its own VAE and CLIP. It's small (2 GB) and works on any GPU.

1. In the Models page, find **"Stable Diffusion v1.5 [EMA FP16]"** in the Checkpoints category
2. Click the download button
3. Wait for the download to complete (the progress bar shows in the download status area)

!!! tip "For better quality"
    If you have more VRAM (24+ GB), download **FLUX.1-dev FP8** instead. It produces significantly better images but requires the FLUX VAE (`ae.safetensors`), CLIP-L (`clip_l.safetensors`), and T5-XXL text encoder (`t5xxl_fp8_e4m3fn.safetensors`) — four files total.

## Step 2: Pick a Workflow

Go to **Workflows** in the navigation bar. You'll see the available workflows with readiness badges:

- **Green badge** — all required models are downloaded, ready to run
- **Red badge** — some models are missing

For your first generation, pick **"Text to Image (Batch)"**. This is the simplest workflow: enter a prompt, pick a checkpoint, click generate.

Click the **Run** button on the workflow card.

## Step 3: Fill the Form

The runner page shows a form with all the workflow's inputs:

1. **Checkpoint** — select the model you downloaded (Stable Diffusion v1.5 or FLUX.1-dev)
2. **Positive Prompt** — describe what you want to generate. Example: `a photograph of a mountain lake at sunset, dramatic clouds, golden light, 4k`
3. **Negative Prompt** — describe what to avoid. The default (`bad quality, worst quality, low quality`) works for most cases.
4. **Resolution** — the options change based on your checkpoint:
    - SD 1.5: use 512x512 or 512x768
    - SDXL/Flux: use 1024x1024 or 832x1216
5. **Steps** — 19 is a good default. More steps = more detail but slower.
6. **CFG Scale** — how strictly the model follows your prompt. 4.0 for Pony/Illustrious, 7.0 for SD 1.5.
7. **Seed** — leave at -1 for random. Set a specific number to reproduce a result.

## Step 4: Generate

Click the **Generate** button. You can also use the stepper `[- N +]` next to the button to generate multiple images at once — each with a different random seed.

## Step 5: Watch Progress

After clicking Generate, you'll be redirected to the **Queue** page. Your job appears as a card with:

- Current status (queued → running → completed)
- Progress bar with percentage
- Current node being processed
- ETA (estimated time remaining)
- Live preview (the image forming in real-time)

## Step 6: See Results

When the job completes:

- Go to **History** to see your completed jobs
- Click a job to expand and see the generated images
- Go to **Assets** → Output to browse all generated files

From the history page you can:

- **Retry** a failed job with the same parameters
- **Delete** jobs and their output files
- **Export** a job as a ZIP (includes the workflow JSON and all outputs)

## What's Next

- Try a different workflow: **IP-Adapter** for style transfer from a reference image
- Try **WAN 2.2 Image to Video** to animate a generated image
- Download LoRAs from the Models page to add styles to your generations
- Explore the [Workflow Guide](../workflows/overview.md) to understand all the options
