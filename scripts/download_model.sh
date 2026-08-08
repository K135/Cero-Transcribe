#!/usr/bin/env bash
# Download ggml whisper.cpp models for cerotrans (English-only builds).
set -euo pipefail

MODELS_DIR="$(cd "$(dirname "$0")/.." && pwd)/models"
BASE_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main"

download() {
  local name="$1"
  local file="ggml-${name}.en.bin"
  local dest="${MODELS_DIR}/${file}"
  if [ -f "$dest" ]; then
    echo "already present: $file"
    return
  fi
  echo "downloading $file ..."
  curl -L --fail --progress-bar -o "$dest" "${BASE_URL}/${file}"
}

download "tiny"   # default, ~75 MB
download "base"   # optional, ~142 MB (menu-switchable)

echo "done -> ${MODELS_DIR}"
