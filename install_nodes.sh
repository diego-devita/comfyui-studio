#!/bin/bash
set -e

# Usage: install_nodes.sh <start_marker> <end_marker> <pytorch_index>
# Reads nodes.txt and installs custom nodes between the two section markers.
# Each non-comment, non-empty line has format:
#   repo_url [requirements_file] [post_install_command]

START="$1"
END="$2"
PYTORCH_INDEX="${3:-cu128}"

IN_SECTION=false

while IFS= read -r line; do
  trimmed=$(echo "$line" | sed 's/^[[:space:]]*//')

  # Detect section boundaries
  if echo "$trimmed" | grep -q "^# ── $START"; then
    IN_SECTION=true
    continue
  fi
  if echo "$trimmed" | grep -q "^# ── $END"; then
    break
  fi

  # Skip lines outside our section, empty lines, and comments
  [ "$IN_SECTION" = false ] && continue
  [ -z "$trimmed" ] && continue
  echo "$trimmed" | grep -q "^#" && continue

  # Parse: repo [req_file] [post_cmd]
  # Count fields to avoid cut returning the whole line when <3 fields
  num_fields=$(echo "$trimmed" | awk '{print NF}')
  repo=$(echo "$trimmed" | awk '{print $1}')
  req_file=""
  post_cmd=""
  if [ "$num_fields" -ge 2 ]; then
    req_file=$(echo "$trimmed" | awk '{print $2}')
  fi
  if [ "$num_fields" -ge 3 ]; then
    post_cmd=$(echo "$trimmed" | cut -d' ' -f3-)
  fi
  name=$(basename "$repo" .git)

  echo ""
  echo "=== Installing $name ==="
  git clone --depth 1 "$repo"
  cd "$name"

  # Install Python requirements
  if [ -n "$req_file" ] && [ -f "$req_file" ]; then
    echo "  -> pip install -r $req_file"
    pip install -r "$req_file" --extra-index-url "https://download.pytorch.org/whl/${PYTORCH_INDEX}"
  elif [ -z "$req_file" ] && [ -f requirements.txt ]; then
    echo "  -> pip install -r requirements.txt"
    pip install -r requirements.txt --extra-index-url "https://download.pytorch.org/whl/${PYTORCH_INDEX}"
  fi

  # Run post-install command if specified
  if [ -n "$post_cmd" ] && [ "$post_cmd" != " " ]; then
    echo "  -> Running: $post_cmd"
    eval "$post_cmd"
  fi

  cd ..
done < /tmp/nodes.txt
