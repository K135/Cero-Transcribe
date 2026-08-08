#!/bin/bash
# Cerotrans — menu-bar agent launcher (LSUIElement; no Dock icon).
set -uo pipefail

CONTENTS="$(cd "$(dirname "$0")/.." && pwd)"
RESOURCES="${CONTENTS}/Resources"
PROJECT="${RESOURCES}/project"
VENV_PY="${RESOURCES}/venv/bin/python"
WHISPER_BIN="${RESOURCES}/whisper/bin/whisper-cli"
WHISPER_SERVER="${RESOURCES}/whisper/bin/whisper-server"
MODELS="${RESOURCES}/models"
SUPPORT="${HOME}/Library/Application Support/cerotrans"
mkdir -p "${SUPPORT}"

LOG="${SUPPORT}/launch.log"
: > "${LOG}" || true

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "${LOG}"; }
die() {
  log "FATAL: $*"
  /usr/bin/osascript -e "display dialog \"GoTranscribe could not start.\n\n$*\n\nLog: ${LOG}\" with title \"GoTranscribe\" buttons {\"OK\"} default button 1 with icon stop" 2>/dev/null || true
  exit 1
}

export CEROTRANS_APP_BUNDLE="$(cd "${CONTENTS}/../.." && pwd)"
export PYTHONUNBUFFERED=1
export CEROTRANS_MODELS_DIR="${MODELS}"
export CEROTRANS_WHISPER_CLI="${WHISPER_BIN}"
if [[ -x "${WHISPER_SERVER}" ]]; then
  export CEROTRANS_WHISPER_SERVER="${WHISPER_SERVER}"
fi
# Bundled whisper-cli loads ggml backends from the same directory (bin/).
export DYLD_LIBRARY_PATH="${RESOURCES}/whisper/lib${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
export DYLD_FALLBACK_LIBRARY_PATH="${RESOURCES}/whisper/lib${DYLD_FALLBACK_LIBRARY_PATH:+:$DYLD_FALLBACK_LIBRARY_PATH}"

log "CONTENTS=${CONTENTS}"
log "ARCH=$(uname -m)"

[[ -x "${VENV_PY}" ]] || die "Missing embedded Python at Resources/venv."
[[ -d "${PROJECT}" ]] || die "App is damaged: missing Resources/project."
[[ -x "${WHISPER_BIN}" ]] || die "Missing bundled whisper-cli. Rebuild the DMG."
[[ -d "${MODELS}" ]] || die "Missing bundled models."

cd "${PROJECT}" || die "Cannot enter project: ${PROJECT}"
log "Launching menu bar agent…"
exec "${VENV_PY}" "${PROJECT}/run.py" >>"${LOG}" 2>&1
