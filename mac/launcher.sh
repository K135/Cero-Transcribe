#!/bin/bash
# Cero-Transcribe — menu-bar agent launcher (LSUIElement; no Dock icon).
# Fully self-contained: bundled Python, whisper, models. No Homebrew required.
set -uo pipefail

CONTENTS="$(cd "$(dirname "$0")/.." && pwd)"
RESOURCES="${CONTENTS}/Resources"
PROJECT="${RESOURCES}/project"
# Prefer a Python binary renamed to Cero-Transcribe so macOS permission
# dialogs show "Cero-Transcribe", not "python3.12".
VENV_PY="${RESOURCES}/venv/bin/Cero-Transcribe"
if [[ ! -x "${VENV_PY}" ]]; then
  VENV_PY="${RESOURCES}/venv/bin/python"
fi
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
  /usr/bin/osascript -e "display dialog \"Cero-Transcribe could not start.\n\n$*\n\nLog: ${LOG}\" with title \"Cero-Transcribe\" buttons {\"OK\"} default button 1 with icon stop" 2>/dev/null || true
  exit 1
}

export CEROTRANS_APP_BUNDLE="$(cd "${CONTENTS}/../.." && pwd)"
export PYTHONUNBUFFERED=1
export CEROTRANS_MODELS_DIR="${MODELS}"
export CEROTRANS_WHISPER_CLI="${WHISPER_BIN}"
if [[ -x "${WHISPER_SERVER}" ]]; then
  export CEROTRANS_WHISPER_SERVER="${WHISPER_SERVER}"
fi
# Bundled whisper loads ggml backends from bin/ next to the executable.
# Put Python's lib FIRST so the Cero-Transcribe interpreter finds libpython.
export DYLD_LIBRARY_PATH="${RESOURCES}/python/lib:${RESOURCES}/whisper/lib${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
export DYLD_FALLBACK_LIBRARY_PATH="${RESOURCES}/python/lib:${RESOURCES}/whisper/lib${DYLD_FALLBACK_LIBRARY_PATH:+:$DYLD_FALLBACK_LIBRARY_PATH}"

log "CONTENTS=${CONTENTS}"
log "ARCH=$(uname -m)"
log "BUNDLE=${CEROTRANS_APP_BUNDLE}"
log "PYTHON=${VENV_PY}"

[[ -x "${VENV_PY}" ]] || die "Missing embedded Python at Resources/venv. Reinstall from the DMG."
[[ -d "${PROJECT}" ]] || die "App is damaged: missing Resources/project. Reinstall from the DMG."
[[ -x "${WHISPER_BIN}" ]] || die "Missing bundled whisper-cli. Reinstall from the DMG."
[[ -x "${WHISPER_SERVER}" ]] || die "Missing bundled whisper-server. Reinstall from the DMG."
[[ -f "${MODELS}/ggml-tiny.en.bin" ]] || die "Missing bundled speech model. Reinstall from the DMG."

cd "${PROJECT}" || die "Cannot enter project: ${PROJECT}"
log "Launching menu bar agent as $(basename "${VENV_PY}")…"
# Process name = Cero-Transcribe (not python3.12) for Accessibility / Input Monitoring
exec "${VENV_PY}" "${PROJECT}/run.py" >>"${LOG}" 2>&1
