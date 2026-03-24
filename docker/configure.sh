#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# ComfyUI Studio — Docker Build Configurator
# Interactive script that builds the right docker build command
# (or a customized Dockerfile) based on your GPU and preferences.
# ============================================================

# ── GPU database ─────────────────────────────────────────────
# Format: "name|vram|sm|cuda|pytorch|sage|flash"
GPUS=(
  # Blackwell / Hopper
  "B200|192 GB|SM 100|12.8.1|cu128|true|true"
  "B100|80 GB|SM 100|12.8.1|cu128|true|true"
  "H200|141 GB|SM 90|12.8.1|cu128|true|true"
  "H100|80 GB|SM 90|12.8.1|cu128|true|true"
  "H100 NVL|94 GB|SM 90|12.8.1|cu128|true|true"
  # Ampere (datacenter)
  "A100 80 GB|80 GB|SM 80|12.4.1|cu124|true|true"
  "A100 40 GB|40 GB|SM 80|12.4.1|cu124|true|true"
  "A6000|48 GB|SM 86|12.4.1|cu124|true|true"
  "A5000|24 GB|SM 86|12.4.1|cu124|true|true"
  "A4000|16 GB|SM 86|12.4.1|cu124|true|true"
  # Ada Lovelace (datacenter)
  "L40S|48 GB|SM 89|12.4.1|cu124|true|true"
  "L40|48 GB|SM 89|12.4.1|cu124|true|true"
  "L4|24 GB|SM 89|12.4.1|cu124|true|true"
  # Ada Lovelace (consumer)
  "RTX 4090|24 GB|SM 89|12.4.1|cu124|true|true"
  "RTX 4080 SUPER|16 GB|SM 89|12.4.1|cu124|true|true"
  "RTX 4080|16 GB|SM 89|12.4.1|cu124|true|true"
  "RTX 4070 Ti|12 GB|SM 89|12.4.1|cu124|true|true"
  "RTX 4070|12 GB|SM 89|12.4.1|cu124|true|true"
  "RTX 4060 Ti|16 GB|SM 89|12.4.1|cu124|true|true"
  "RTX 4060|8 GB|SM 89|12.4.1|cu124|true|true"
  # Ampere (consumer)
  "RTX 3090 / 3090 Ti|24 GB|SM 86|12.4.1|cu124|true|true"
  "RTX 3080 Ti|12 GB|SM 86|12.4.1|cu124|true|true"
  "RTX 3080|10 GB|SM 86|12.4.1|cu124|true|true"
  "RTX 3070 Ti|8 GB|SM 86|12.4.1|cu124|true|true"
  "RTX 3070|8 GB|SM 86|12.4.1|cu124|true|true"
  "RTX 3060|12 GB|SM 86|12.4.1|cu124|true|true"
  # Turing
  "RTX 2080 Ti|11 GB|SM 75|12.1.1|cu121|false|false"
  "RTX 2080 SUPER|8 GB|SM 75|12.1.1|cu121|false|false"
  "RTX 2080|8 GB|SM 75|12.1.1|cu121|false|false"
  "RTX 2070|8 GB|SM 75|12.1.1|cu121|false|false"
  "T4|16 GB|SM 75|12.1.1|cu121|false|false"
  # Volta
  "V100 32 GB|32 GB|SM 70|12.1.1|cu121|false|false"
  "V100 16 GB|16 GB|SM 70|12.1.1|cu121|false|false"
)

# Group boundaries (indices into GPUS array)
GROUP_NAMES=("Blackwell / Hopper" "Ampere (datacenter)" "Ada Lovelace (datacenter)" "Ada Lovelace (consumer)" "Ampere (consumer)" "Turing" "Volta")
GROUP_START=(0 5 10 13 20 26 31)
GROUP_END=(  5 10 13 20 26 31 33)

# Dockerfile defaults
DEF_CUDA="12.8.1"
DEF_PYTORCH="cu128"
DEF_PYTHON="3.12"
DEF_SAGE="true"
DEF_FLASH="true"

# SageAttention version labels
sage_label() {
  local sm=$1
  if [ "$sm" -ge 90 ]; then echo "v2 (FP8 kernels)";
  elif [ "$sm" -ge 80 ]; then echo "v1";
  else echo "not supported"; fi
}

flash_label() {
  local sm=$1
  if [ "$sm" -ge 90 ]; then echo "v3";
  elif [ "$sm" -ge 80 ]; then echo "v2";
  else echo "not supported"; fi
}

# ── Helpers ──────────────────────────────────────────────────

bold()  { [ -t 1 ] && printf '\033[1m%s\033[0m' "$1" || printf '%s' "$1"; }
dim()   { [ -t 1 ] && printf '\033[2m%s\033[0m' "$1" || printf '%s' "$1"; }
green() { [ -t 1 ] && printf '\033[32m%s\033[0m' "$1" || printf '%s' "$1"; }

field() { echo "$1" | cut -d'|' -f"$2"; }

# ── Step 1: GPU selection ────────────────────────────────────

select_gpu() {
  echo ""
  bold "=== ComfyUI Studio — Docker Build Configurator ==="; echo ""
  echo ""
  echo "Which GPU will you run ComfyUI on?"
  echo ""
  dim "  This determines the CUDA version, PyTorch build, and which"; echo ""
  dim "  attention optimizations (SageAttention, FlashAttention) are"; echo ""
  dim "  compatible with your hardware."; echo ""
  echo ""

  local n=1
  for g in "${!GROUP_NAMES[@]}"; do
    bold "  ${GROUP_NAMES[$g]}"; echo ""
    for (( i=${GROUP_START[$g]}; i<${GROUP_END[$g]}; i++ )); do
      local entry="${GPUS[$i]}"
      local name=$(field "$entry" 1)
      local vram=$(field "$entry" 2)
      local sm=$(field "$entry" 3)
      printf "    %2d) %-22s %7s   %s\n" "$n" "$name" "$vram" "$sm"
      n=$((n+1))
    done
    echo ""
  done

  while true; do
    read -rp "  GPU [1-${#GPUS[@]}]: " choice
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#GPUS[@]} ]; then
      GPU_IDX=$((choice-1))
      break
    fi
    echo "  Invalid choice, try again."
  done

  local entry="${GPUS[$GPU_IDX]}"
  GPU_NAME=$(field "$entry" 1)
  GPU_VRAM=$(field "$entry" 2)
  GPU_SM_STR=$(field "$entry" 3)
  GPU_SM=${GPU_SM_STR#SM }
  SEL_CUDA=$(field "$entry" 4)
  SEL_PYTORCH=$(field "$entry" 5)
  SEL_SAGE=$(field "$entry" 6)
  SEL_FLASH=$(field "$entry" 7)
  SEL_PYTHON="$DEF_PYTHON"
}

# ── Step 2: Confirm parameters ───────────────────────────────

confirm_params() {
  echo ""
  bold "  Configuration for $GPU_NAME ($GPU_VRAM, $GPU_SM_STR):"; echo ""
  echo ""
  echo "    CUDA_VERSION           = $SEL_CUDA"
  echo "    PYTORCH_INDEX          = $SEL_PYTORCH"
  echo "    PYTHON_VERSION         = $SEL_PYTHON"
  echo ""

  if [ "$SEL_SAGE" = "true" ]; then
    green "    ENABLE_SAGE_ATTENTION  = true"; echo "  — $(sage_label "$GPU_SM")"
    echo ""
    dim "      SageAttention replaces the default attention computation with"; echo ""
    dim "      optimized CUDA kernels. 2-3x faster image/video generation."; echo ""
  else
    echo "    ENABLE_SAGE_ATTENTION  = false  (not supported on this GPU)"
  fi
  echo ""

  if [ "$SEL_FLASH" = "true" ]; then
    green "    ENABLE_FLASH_ATTENTION = true"; echo "  — $(flash_label "$GPU_SM")"
    echo ""
    dim "      FlashAttention provides memory-efficient fused attention. Lets you"; echo ""
    dim "      run larger batches or higher resolutions without running out of VRAM."; echo ""
    dim "      Builds from source — adds ~20-30 min to build time."; echo ""
  else
    echo "    ENABLE_FLASH_ATTENTION = false  (not supported on this GPU)"
  fi
  echo ""

  read -rp "  Proceed with these settings? [Y/n] " yn
  if [[ "${yn,,}" == "n" ]]; then
    echo ""
    echo "  Override values (press Enter to keep default):"
    read -rp "    CUDA_VERSION [$SEL_CUDA]: " v; [ -n "$v" ] && SEL_CUDA="$v"
    read -rp "    PYTORCH_INDEX [$SEL_PYTORCH]: " v; [ -n "$v" ] && SEL_PYTORCH="$v"
    read -rp "    PYTHON_VERSION [$SEL_PYTHON]: " v; [ -n "$v" ] && SEL_PYTHON="$v"
    read -rp "    ENABLE_SAGE_ATTENTION [$SEL_SAGE]: " v; [ -n "$v" ] && SEL_SAGE="$v"
    read -rp "    ENABLE_FLASH_ATTENTION [$SEL_FLASH]: " v; [ -n "$v" ] && SEL_FLASH="$v"
  fi
}

# ── Step 3: LLM support ─────────────────────────────────────

ask_llm() {
  echo ""
  bold "  Include llama-server for local LLM inference?"; echo ""
  echo ""
  dim "    llama-server lets you run large language models (Qwen, Llama, etc.)"; echo ""
  dim "    directly on the pod GPU — useful for prompt generation, chat, or"; echo ""
  dim "    AI-assisted workflows inside ComfyUI Studio."; echo ""
  echo ""

  read -rp "  Include LLM support? [Y/n] " yn
  if [[ "${yn,,}" == "n" ]]; then
    SEL_LLM="false"
    SEL_BUILD_ENV="na"
    SEL_LLAMA_VERSION="na"
    return
  fi
  SEL_LLM="true"

  # Step 3b: Build environment
  echo ""
  bold "  Where will you build this Docker image?"; echo ""
  echo ""
  echo "    1) On a machine WITH the target GPU"
  echo "    2) On a machine WITHOUT a GPU (GitHub Actions, CI, cloud builder)"
  echo ""
  dim "    Why this matters: llama-server is compiled from source with CUDA."; echo ""
  dim "    If the target GPU is present during the build, the compiler auto-detects"; echo ""
  dim "    it and builds optimized kernels for that specific architecture only (~10 min)."; echo ""
  echo ""
  dim "    Without a GPU (typical for CI runners like GitHub Actions), the compiler"; echo ""
  dim "    cannot auto-detect, so we build kernels for ALL supported architectures"; echo ""
  dim "    (Turing through Blackwell). This produces a universal binary that works"; echo ""
  dim "    on any GPU, but takes significantly longer (~60 min)."; echo ""
  echo ""

  while true; do
    read -rp "  Build environment [1/2]: " be
    case "$be" in
      1) SEL_BUILD_ENV="local"; break;;
      2) SEL_BUILD_ENV="ci"; break;;
      *) echo "  Invalid choice, try again.";;
    esac
  done

  # Step 3c: llama.cpp version
  echo ""
  bold "  Which llama.cpp version?"; echo ""
  echo ""
  echo "    1) b8505 (pinned — recommended)"
  echo "    2) latest (always pulls newest HEAD)"
  echo "    3) Custom tag (e.g., b8400)"
  echo ""
  dim "    The default (b8505) is a known-good release tested with this build."; echo ""
  dim "    Pinning ensures reproducible builds — the same version every time."; echo ""
  echo ""
  dim "    'latest' always clones the newest code from llama.cpp. This gives you"; echo ""
  dim "    the latest features and fixes, but a future commit could introduce"; echo ""
  dim "    breaking changes that fail the build. If that happens, you'll need to"; echo ""
  dim "    either wait for a fix upstream or switch back to a pinned version."; echo ""
  echo ""

  while true; do
    read -rp "  Version [1/2/3]: " lv
    case "$lv" in
      1) SEL_LLAMA_VERSION="b8505"; break;;
      2) SEL_LLAMA_VERSION="latest"; break;;
      3) read -rp "  Enter tag: " custom_tag
         if [ -n "$custom_tag" ]; then
           SEL_LLAMA_VERSION="$custom_tag"; break
         fi
         echo "  Tag cannot be empty.";;
      *) echo "  Invalid choice, try again.";;
    esac
  done
}

# ── Step 4: Custom node categories ───────────────────────────

parse_node_categories() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  local nodes_file="$script_dir/nodes.txt"

  CATEGORIES=()
  CATEGORY_COUNTS=()
  CATEGORY_DESCS=(
    "Manager, essentials, seed control, utilities"
    "ControlNet, IP-Adapter, face swap, upscale, GGUF"
    "WaveSpeed — FBCache + torch.compile, 1.5-2x speedup"
    "SAM2, Florence2 — segment anything by text or click"
    "VHS, AnimateDiff, WAN, Hunyuan, LTX, CogVideo, Mochi"
    "Load models by CivitAI ID, browse trends, apply recipes"
  )
  CATEGORY_SELECTED=()

  if [ ! -f "$nodes_file" ]; then
    echo "  Warning: nodes.txt not found, skipping node selection."
    return
  fi

  local current_section=""
  local count=0
  while IFS= read -r line; do
    if [[ "$line" =~ ^#\ ──\ (.+)\ ── ]]; then
      if [ -n "$current_section" ]; then
        CATEGORIES+=("$current_section")
        CATEGORY_COUNTS+=("$count")
        CATEGORY_SELECTED+=(1)
      fi
      current_section="${BASH_REMATCH[1]}"
      count=0
    elif [ -n "$current_section" ]; then
      local trimmed
      trimmed=$(echo "$line" | sed 's/^[[:space:]]*//')
      [ -z "$trimmed" ] && continue
      [[ "$trimmed" == \#* ]] && continue
      count=$((count+1))
    fi
  done < "$nodes_file"
  # Last section
  if [ -n "$current_section" ]; then
    CATEGORIES+=("$current_section")
    CATEGORY_COUNTS+=("$count")
    CATEGORY_SELECTED+=(1)
  fi
}

select_categories() {
  if [ ${#CATEGORIES[@]} -eq 0 ]; then return; fi

  echo ""
  bold "  Custom node categories to install:"; echo ""
  echo ""
  dim "    Custom nodes extend ComfyUI with new capabilities — image generation,"; echo ""
  dim "    video, face swap, upscaling, etc. All are selected by default."; echo ""
  dim "    Toggle numbers to include/exclude, then press Enter to confirm."; echo ""
  echo ""

  while true; do
    for i in "${!CATEGORIES[@]}"; do
      local mark="x"
      [ "${CATEGORY_SELECTED[$i]}" -eq 0 ] && mark=" "
      local desc=""
      [ "$i" -lt "${#CATEGORY_DESCS[@]}" ] && desc=" — ${CATEGORY_DESCS[$i]}"
      printf "    [%s] %d) %-28s (%d nodes)%s\n" "$mark" $((i+1)) "${CATEGORIES[$i]}" "${CATEGORY_COUNTS[$i]}" "$desc"
    done
    echo ""
    read -rp "  Toggle [1-${#CATEGORIES[@]}, a=all, n=none, Enter=confirm]: " input

    [ -z "$input" ] && break

    if [ "$input" = "a" ]; then
      for i in "${!CATEGORY_SELECTED[@]}"; do CATEGORY_SELECTED[$i]=1; done
      echo ""; continue
    fi
    if [ "$input" = "n" ]; then
      for i in "${!CATEGORY_SELECTED[@]}"; do CATEGORY_SELECTED[$i]=0; done
      echo ""; continue
    fi

    for num in $input; do
      if [[ "$num" =~ ^[0-9]+$ ]] && [ "$num" -ge 1 ] && [ "$num" -le ${#CATEGORIES[@]} ]; then
        local idx=$((num-1))
        if [ "${CATEGORY_SELECTED[$idx]}" -eq 1 ]; then
          CATEGORY_SELECTED[$idx]=0
        else
          CATEGORY_SELECTED[$idx]=1
        fi
      fi
    done
    echo ""
  done
}

# ── Step 5: Output ───────────────────────────────────────────

check_all_categories_selected() {
  for s in "${CATEGORY_SELECTED[@]}"; do
    [ "$s" -eq 0 ] && return 1
  done
  return 0
}

build_time_estimate() {
  echo ""
  bold "  Estimated build time:"; echo ""
  echo ""

  local base_lo=15 base_hi=25
  local total_lo=$base_lo total_hi=$base_hi

  echo "    Base (ComfyUI + nodes + PyTorch):    ~${base_lo}-${base_hi} min"

  if [ "$SEL_FLASH" = "true" ]; then
    echo "    + FlashAttention (from source):      ~20-30 min"
    total_lo=$((total_lo+20)); total_hi=$((total_hi+30))
  fi

  if [ "$SEL_LLM" = "true" ]; then
    if [ "$SEL_BUILD_ENV" = "ci" ]; then
      echo "    + llama.cpp (all GPU architectures): ~60 min"
      total_lo=$((total_lo+50)); total_hi=$((total_hi+70))
    else
      echo "    + llama.cpp (native GPU only):       ~10 min"
      total_lo=$((total_lo+5)); total_hi=$((total_hi+15))
    fi
  fi

  echo "    ──────────────────────────────────────"
  echo "    Total estimate:                      ~${total_lo}-${total_hi} min"
  echo ""
}

emit_build_command() {
  echo ""
  bold "  ──────────────────────────────────────────────"; echo ""
  bold "  Your build command:"; echo ""
  echo ""

  local args=()

  # Only include args that differ from Dockerfile defaults
  [ "$SEL_CUDA" != "$DEF_CUDA" ] && args+=("--build-arg CUDA_VERSION=$SEL_CUDA")
  [ "$SEL_PYTORCH" != "$DEF_PYTORCH" ] && args+=("--build-arg PYTORCH_INDEX=$SEL_PYTORCH")
  [ "$SEL_PYTHON" != "$DEF_PYTHON" ] && args+=("--build-arg PYTHON_VERSION=$SEL_PYTHON")
  [ "$SEL_SAGE" != "$DEF_SAGE" ] && args+=("--build-arg ENABLE_SAGE_ATTENTION=$SEL_SAGE")
  [ "$SEL_FLASH" != "$DEF_FLASH" ] && args+=("--build-arg ENABLE_FLASH_ATTENTION=$SEL_FLASH")
  [ "$SEL_LLM" = "false" ] && args+=("--build-arg ENABLE_LLM=false")
  if [ "$SEL_LLM" = "true" ] && [ "$SEL_LLAMA_VERSION" != "b8505" ]; then
    args+=("--build-arg LLAMA_CPP_VERSION=$SEL_LLAMA_VERSION")
  fi

  if [ ${#args[@]} -eq 0 ]; then
    echo "  docker build -f docker/Dockerfile -t comfyui-studio ."
  else
    echo -n "  docker build -f docker/Dockerfile -t comfyui-studio"
    for arg in "${args[@]}"; do
      echo " \\"
      echo -n "    $arg"
    done
    echo " \\"
    echo "    ."
  fi

  echo ""
  bold "  ──────────────────────────────────────────────"; echo ""
  dim "  Run this from the repository root."; echo ""

  build_time_estimate
}

select_output() {
  local all_selected=true
  if [ ${#CATEGORIES[@]} -gt 0 ]; then
    check_all_categories_selected || all_selected=false
  fi

  if [ "$all_selected" = true ]; then
    echo ""
    echo "  Output format:"
    echo "    1) Docker build command (copy-paste ready)"
    echo "    2) Generate customized Dockerfile"
    echo ""
    read -rp "  Output [1/2]: " mode
    case "$mode" in
      2) emit_dockerfile;;
      *) emit_build_command;;
    esac
  else
    echo ""
    dim "  Custom node filtering requires generating a modified Dockerfile."; echo ""
    echo ""
    emit_dockerfile
  fi
}

emit_dockerfile() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  local src_dockerfile="$script_dir/Dockerfile"
  local src_nodes="$script_dir/nodes.txt"
  local out_dir="${script_dir}"
  local out_dockerfile="$out_dir/Dockerfile.custom"
  local out_nodes="$out_dir/nodes.custom.txt"

  if [ ! -f "$src_dockerfile" ]; then
    echo "  Error: Dockerfile not found at $src_dockerfile"
    return 1
  fi

  # Generate customized Dockerfile
  sed \
    -e "s/^ARG CUDA_VERSION=.*/ARG CUDA_VERSION=$SEL_CUDA/" \
    -e "s/^ARG PYTORCH_INDEX=.*/ARG PYTORCH_INDEX=$SEL_PYTORCH/" \
    -e "s/^ARG PYTHON_VERSION=.*/ARG PYTHON_VERSION=$SEL_PYTHON/" \
    -e "s/^ARG ENABLE_SAGE_ATTENTION=.*/ARG ENABLE_SAGE_ATTENTION=$SEL_SAGE/" \
    -e "s/^ARG ENABLE_FLASH_ATTENTION=.*/ARG ENABLE_FLASH_ATTENTION=$SEL_FLASH/" \
    "$src_dockerfile" > "$out_dockerfile"

  # Generate filtered nodes.txt if needed
  if [ -f "$src_nodes" ] && [ ${#CATEGORIES[@]} -gt 0 ]; then
    local skip_section=false
    local current_idx=-1
    {
      while IFS= read -r line; do
        if [[ "$line" =~ ^#\ ──\ (.+)\ ── ]]; then
          current_idx=$((current_idx+1))
          if [ "$current_idx" -lt "${#CATEGORY_SELECTED[@]}" ] && [ "${CATEGORY_SELECTED[$current_idx]}" -eq 0 ]; then
            skip_section=true
          else
            skip_section=false
          fi
        fi
        [ "$skip_section" = false ] && echo "$line"
      done < "$src_nodes"
    } > "$out_nodes"
    echo ""
    echo "  Generated:"
    echo "    $out_dockerfile"
    echo "    $out_nodes"
    echo ""
    echo "  Build with:"
    echo "    cp $out_nodes $src_nodes  # replace nodes.txt"
    echo "    docker build -f $out_dockerfile -t comfyui-studio ."
  else
    echo ""
    echo "  Generated:"
    echo "    $out_dockerfile"
    echo ""
    echo "  Build with:"
    echo "    docker build -f $out_dockerfile -t comfyui-studio ."
  fi

  build_time_estimate
}

# ── Main ─────────────────────────────────────────────────────

main() {
  select_gpu
  confirm_params
  ask_llm
  parse_node_categories
  select_categories
  select_output
}

main "$@"
