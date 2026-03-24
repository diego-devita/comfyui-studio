# Custom Nodes

The Docker image ships with 38 custom nodes pre-installed, organized into 6 categories. Nodes are defined in `docker/nodes.txt` and installed during the Docker build by `docker/install_nodes.sh`.

## Categories

### Fundamentals / QoL (10 nodes)

Core utilities, node management, and workflow quality-of-life improvements.

| Node | Repository | Purpose |
|------|-----------|---------|
| ComfyUI-Manager | [ltdrdata/ComfyUI-Manager](https://github.com/ltdrdata/ComfyUI-Manager) | Install/update nodes and models from the ComfyUI UI |
| ComfyUI-Login | [liusida/ComfyUI-Login](https://github.com/liusida/ComfyUI-Login) | Basic password login for the ComfyUI web UI |
| ComfyUI_essentials | [cubiq/ComfyUI_essentials](https://github.com/cubiq/ComfyUI_essentials) | Math, resize, batch, image info -- universal utilities |
| rgthree-comfy | [rgthree/rgthree-comfy](https://github.com/rgthree/rgthree-comfy) | Seed control, mute/bypass, reroute, context switching |
| cg-use-everywhere | [chrisgoringe/cg-use-everywhere](https://github.com/chrisgoringe/cg-use-everywhere) | Implicit link routing (Anything Everywhere, Prompts Everywhere) |
| ComfyLiterals | [M1kep/ComfyLiterals](https://github.com/M1kep/ComfyLiterals) | Constant nodes (Float, Int, String) |
| ComfyUI-Custom-Scripts | [pythongosssss/ComfyUI-Custom-Scripts](https://github.com/pythongosssss/ComfyUI-Custom-Scripts) | Auto-arrange, enhanced preview, colored notes |
| ComfyUI-KJNodes | [kijai/ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes) | Mega-utility -- conditions, merge, batch; widely used in CivitAI workflows |
| was-node-suite-comfyui | [WASasquatch/was-node-suite-comfyui](https://github.com/WASasquatch/was-node-suite-comfyui) | Text ops, image ops, file ops |
| ComfyUI-Easy-Use | [yolain/ComfyUI-Easy-Use](https://github.com/yolain/ComfyUI-Easy-Use) | Simplified all-in-one nodes for quick workflows |

### Image Generation (14 nodes)

ControlNet, IP-Adapter, face processing, upscaling, and model loading.

| Node | Repository | Purpose |
|------|-----------|---------|
| ComfyUI-Advanced-ControlNet | [Kosinkadink/ComfyUI-Advanced-ControlNet](https://github.com/Kosinkadink/ComfyUI-Advanced-ControlNet) | ControlNet with scheduling, multi-apply, weight types |
| ComfyUI_IPAdapter_plus | [cubiq/ComfyUI_IPAdapter_plus](https://github.com/cubiq/ComfyUI_IPAdapter_plus) | IP-Adapter -- style/face/composition reference from images |
| ComfyUI_InstantID | [cubiq/ComfyUI_InstantID](https://github.com/cubiq/ComfyUI_InstantID) | Face transfer from a single reference image |
| ComfyUI-ReActor | [Gourieff/ComfyUI-ReActor](https://github.com/Gourieff/ComfyUI-ReActor) | Face swap using InsightFace |
| ComfyUI_FaceAnalysis | [cubiq/ComfyUI_FaceAnalysis](https://github.com/cubiq/ComfyUI_FaceAnalysis) | Face analysis, landmarks, embeddings |
| ComfyUI-Impact-Pack | [ltdrdata/ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) | Detailer (face/hand fix), SAM segmentation, batch ops |
| ComfyUI-Impact-Subpack | [ltdrdata/ComfyUI-Impact-Subpack](https://github.com/ltdrdata/ComfyUI-Impact-Subpack) | Ultralytics detectors (face_yolov8m, etc.) -- required by FaceDetailer |
| ComfyUI-Inspire-Pack | [ltdrdata/ComfyUI-Inspire-Pack](https://github.com/ltdrdata/ComfyUI-Inspire-Pack) | Regional prompting, wildcards, LoRA stacking |
| ComfyUI_UltimateSDUpscale | [ssitu/ComfyUI_UltimateSDUpscale](https://github.com/ssitu/ComfyUI_UltimateSDUpscale) | Tiled upscale for high-resolution output |
| comfyui_controlnet_aux | [Fannovel16/comfyui_controlnet_aux](https://github.com/Fannovel16/comfyui_controlnet_aux) | ControlNet preprocessors (OpenPose, Canny, Depth, etc.) |
| ComfyUI-layerdiffuse | [huchenlei/ComfyUI-layerdiffuse](https://github.com/huchenlei/ComfyUI-layerdiffuse) | Transparent background / layer composition |
| ComfyUI-BRIA_AI-RMBG | [ZHO-ZHO-ZHO/ComfyUI-BRIA_AI-RMBG](https://github.com/ZHO-ZHO-ZHO/ComfyUI-BRIA_AI-RMBG) | Background removal (BRIA RMBG-2.0) |
| ComfyUI-GGUF | [city96/ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF) | Load quantized GGUF models (UNet, CLIP) |
| ComfyUI-mxToolkit | [Smirnov75/ComfyUI-mxToolkit](https://github.com/Smirnov75/ComfyUI-mxToolkit) | Slider widgets and utilities |

### Performance Optimization (1 node)

| Node | Repository | Purpose |
|------|-----------|---------|
| Comfy-WaveSpeed | [chengzeyi/Comfy-WaveSpeed](https://github.com/chengzeyi/Comfy-WaveSpeed) | FBCache + torch.compile, 1.5-2x speedup, works with LoRA |

### Segmentation (2 nodes)

| Node | Repository | Purpose |
|------|-----------|---------|
| ComfyUI-segment-anything-2 | [kijai/ComfyUI-segment-anything-2](https://github.com/kijai/ComfyUI-segment-anything-2) | SAM2 -- Segment Anything Model 2 for images and video |
| ComfyUI_Florence2SAM2 | [rdancer/ComfyUI_Florence2SAM2](https://github.com/rdancer/ComfyUI_Florence2SAM2) | Florence2 + SAM2 -- text-driven segmentation ("select the person") |

### Video Generation (8 nodes)

| Node | Repository | Purpose |
|------|-----------|---------|
| ComfyUI-VideoHelperSuite | [Kosinkadink/ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite) | Load/save video, VHS_VideoCombine -- required for any video workflow |
| ComfyUI-Frame-Interpolation | [Fannovel16/ComfyUI-Frame-Interpolation](https://github.com/Fannovel16/ComfyUI-Frame-Interpolation) | RIFE frame interpolation -- smooth video from low-fps to high-fps |
| ComfyUI-AnimateDiff-Evolved | [Kosinkadink/ComfyUI-AnimateDiff-Evolved](https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved) | AnimateDiff for SD1.5/SDXL video generation |
| ComfyUI-WanVideoWrapper | [kijai/ComfyUI-WanVideoWrapper](https://github.com/kijai/ComfyUI-WanVideoWrapper) | WAN 2.1/2.2 video wrapper -- most popular WAN node on CivitAI |
| ComfyUI-HunyuanVideoWrapper | [kijai/ComfyUI-HunyuanVideoWrapper](https://github.com/kijai/ComfyUI-HunyuanVideoWrapper) | HunyuanVideo wrapper |
| ComfyUI-LTXVideo | [Lightricks/ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo) | LTX Video -- Lightricks video model, fastest generation |
| ComfyUI-CogVideoXWrapper | [kijai/ComfyUI-CogVideoXWrapper](https://github.com/kijai/ComfyUI-CogVideoXWrapper) | CogVideoX -- best I2V quality, T2V, runs on 8-24 GB VRAM |
| ComfyUI-MochiWrapper | [kijai/ComfyUI-MochiWrapper](https://github.com/kijai/ComfyUI-MochiWrapper) | Mochi 1 -- best photorealistic T2V quality |

### CivitAI Integration (3 nodes)

| Node | Repository | Purpose |
|------|-----------|---------|
| civitai_comfy_nodes | [civitai/civitai_comfy_nodes](https://github.com/civitai/civitai_comfy_nodes) | Official CivitAI nodes -- load models by CivitAI ID, auto-detect resources on image upload |
| ComfyUI-EasyCivitai-XTNodes | [X-T-E-R/ComfyUI-EasyCivitai-XTNodes](https://github.com/X-T-E-R/ComfyUI-EasyCivitai-XTNodes) | Load models from CivitAI URL with image preview |
| ComfyUI-Civitai-Toolkit | [BAIKEMARK/ComfyUI-Civitai-Toolkit](https://github.com/BAIKEMARK/ComfyUI-Civitai-Toolkit) | Full CivitAI browser inside ComfyUI -- search, trends, recipes |

## File Format: nodes.txt

`docker/nodes.txt` is a plain text file with one node per line. Each line has the format:

```
repo_url [requirements_file] [post_install_command]
```

**Fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `repo_url` | Yes | Git clone URL (HTTPS) |
| `requirements_file` | No | Name of the pip requirements file. If omitted, `requirements.txt` is used automatically if it exists in the repo. |
| `post_install_command` | No | Shell command to run after pip install (e.g., `python install.py`) |

**Examples:**

```bash
# Standard node (auto-detects requirements.txt):
https://github.com/ltdrdata/ComfyUI-Manager.git

# Node with explicit requirements file:
https://github.com/ltdrdata/ComfyUI-Impact-Subpack.git requirements.txt

# Node with requirements file AND post-install command:
https://github.com/ltdrdata/ComfyUI-Impact-Pack.git requirements.txt python install.py

# Node with non-standard requirements file:
https://github.com/Fannovel16/ComfyUI-Frame-Interpolation.git requirements-no-cupy.txt
```

Lines starting with `#` are comments. Empty lines are ignored.

### Section Markers

Nodes are grouped by section markers:

```
# -- Section Name --
```

The `install_nodes.sh` script uses these markers to install nodes in separate Docker layers, enabling layer caching. Each Dockerfile `RUN` command specifies a start and end marker:

```dockerfile
RUN /tmp/install_nodes.sh "Fundamentals" "Image Generation" "${PYTORCH_INDEX}"
RUN /tmp/install_nodes.sh "Image Generation" "Video Generation" "${PYTORCH_INDEX}"
RUN /tmp/install_nodes.sh "Video Generation" "CivitAI Integration" "${PYTORCH_INDEX}"
RUN /tmp/install_nodes.sh "CivitAI Integration" "ENDOFFILE" "${PYTORCH_INDEX}"
```

The script reads `nodes.txt` from top to bottom, only processing lines between its start marker and end marker. The `ENDOFFILE` sentinel handles the last section.

!!! note "Layer caching"
    The section-based installation means adding a node to the last section (CivitAI Integration) only rebuilds that one layer. Nodes installed in earlier sections remain cached. This keeps incremental rebuilds fast.

## How install_nodes.sh Works

The installer script at `docker/install_nodes.sh` takes three arguments:

```bash
install_nodes.sh <start_marker> <end_marker> <pytorch_index>
```

For each node between the markers, it:

1. Clones the repository with `git clone --depth 1`
2. Installs Python requirements:
    - Uses the explicitly specified requirements file if one is given
    - Falls back to `requirements.txt` if it exists in the repo and no file was specified
    - Adds `--extra-index-url https://download.pytorch.org/whl/${PYTORCH_INDEX}` to ensure PyTorch-compatible dependencies
3. Runs the post-install command if specified (e.g., `python install.py`)

The script also removes any broken cmake pip wrapper before processing nodes. Some nodes (notably was-node-suite) install a cmake Python wrapper that shadows the system cmake, which breaks compilation of dlib and other C++ extensions.

## Adding a Node

### At build time (permanent)

1. Add the git URL to `docker/nodes.txt` in the appropriate section
2. If the node needs a non-standard requirements file or a post-install command, add them on the same line
3. Commit and push

!!! warning "Triggers Docker rebuild"
    Any change to `docker/nodes.txt` triggers a full Docker image rebuild via CI/CD. The layer caching strategy means only the section containing your new node (and all subsequent sections) will be rebuilt.

### At runtime (per-pod)

Nodes can also be installed on a running pod through the `/admin/nodes` page in ComfyUI Studio. Runtime-installed nodes live in `/workspace/ComfyUI/custom_nodes/` on the network volume and persist across pod restarts, but they are not included in the Docker image.

This is useful for testing nodes before adding them to the image, or for nodes that are only needed on specific pods.

## Removing a Node

To remove a node from the image, delete its line from `docker/nodes.txt` and push. The next build will produce an image without that node.

To remove a runtime-installed node, use the `/admin/nodes` page or delete its directory from `/workspace/ComfyUI/custom_nodes/`.
