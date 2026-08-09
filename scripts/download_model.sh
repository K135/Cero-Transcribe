#!/usr/bin/env bash
# Download whisper.cpp ggml models for Cero-Transcribe.
# Usage:
#   ./scripts/download_model.sh              # tiny.en + base.en (defaults)
#   ./scripts/download_model.sh small.en     # one model id
#   ./scripts/download_model.sh all          # every catalog model (several GB)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODELS_DIR="${ROOT}/models"
USER_DIR="${HOME}/Library/Application Support/cerotrans/models"
BASE_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main"

mkdir -p "${MODELS_DIR}" "${USER_DIR}"

download_one() {
  local id="$1"
  local file=""
  case "$id" in
    tiny.en) file=ggml-tiny.en.bin ;;
    tiny) file=ggml-tiny.bin ;;
    base.en) file=ggml-base.en.bin ;;
    base) file=ggml-base.bin ;;
    small.en) file=ggml-small.en.bin ;;
    small) file=ggml-small.bin ;;
    medium.en) file=ggml-medium.en.bin ;;
    medium) file=ggml-medium.bin ;;
    large) file=ggml-large-v3.bin ;;
    turbo) file=ggml-large-v3-turbo.bin ;;
    *)
      echo "Unknown model id: $id" >&2
      echo "Known: tiny.en tiny base.en base small.en small medium.en medium large turbo" >&2
      exit 1
      ;;
  esac
  # Defaults land in repo models/; larger ones in Application Support
  local dest
  case "$id" in
    tiny.en|base.en) dest="${MODELS_DIR}/${file}" ;;
    *) dest="${USER_DIR}/${file}" ;;
  esac
  if [[ -f "$dest" ]]; then
    echo "already present: $file"
    return
  fi
  echo "downloading $file → $dest ..."
  mkdir -p "$(dirname "$dest")"
  curl -L --fail --progress-bar -o "${dest}.partial" "${BASE_URL}/${file}"
  mv "${dest}.partial" "$dest"
}

if [[ $# -eq 0 ]]; then
  download_one tiny.en
  download_one base.en
elif [[ "$1" == "all" ]]; then
  for id in tiny.en tiny base.en base small.en small medium.en medium large turbo; do
    download_one "$id"
  done
else
  for id in "$@"; do
    download_one "$id"
  done
fi

echo "done"
