#!/usr/bin/env bash
# Build a self-contained Cerotrans.app (menu-bar agent) + installable DMG.
#
# Bundles:
#   - relocatable CPython (python-build-standalone) + venv with deps
#   - whisper-cli + ggml dylibs/backends from Homebrew
#   - ggml models (tiny.en required; base.en if present)
#   - app icon + LSUIElement Info.plist (top menu bar only, no Dock)
#
# Prerequisites: brew install whisper-cpp portaudio
# Usage: bash scripts/build_mac_dmg.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="${ROOT}/dist"
APP="${DIST}/Cerotrans.app"
CONTENTS="${APP}/Contents"
RESOURCES="${CONTENTS}/Resources"
DMG="${DIST}/Cerotrans-Install.dmg"
ARCH="$(uname -m)"

PBS_RELEASE="20260414"
case "${ARCH}" in
  x86_64) PBS_TAR="cpython-3.12.13+${PBS_RELEASE}-x86_64-apple-darwin-install_only.tar.gz" ;;
  arm64)  PBS_TAR="cpython-3.12.13+${PBS_RELEASE}-aarch64-apple-darwin-install_only.tar.gz" ;;
  *) echo "Unsupported arch: ${ARCH}" >&2; exit 1 ;;
esac
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_RELEASE}/${PBS_TAR}"

echo "═ Building Cerotrans.app (${ARCH}) ═"

# --- icon ---
bash "${ROOT}/scripts/build_icons.sh"
[[ -f "${ROOT}/mac/Cerotrans.icns" ]] || { echo "Missing icns" >&2; exit 1; }

# --- models ---
if [[ ! -f "${ROOT}/models/ggml-tiny.en.bin" ]]; then
  echo "Downloading models…"
  bash "${ROOT}/scripts/download_model.sh"
fi
[[ -f "${ROOT}/models/ggml-tiny.en.bin" ]] || { echo "tiny.en model missing" >&2; exit 1; }

# --- brew whisper ---
WHISPER_PREFIX="$(brew --prefix whisper-cpp 2>/dev/null || true)"
GGML_PREFIX="$(brew --prefix ggml 2>/dev/null || true)"
[[ -n "${WHISPER_PREFIX}" && -x "${WHISPER_PREFIX}/bin/whisper-cli" ]] || {
  echo "Install whisper-cpp first: brew install whisper-cpp" >&2
  exit 1
}
[[ -n "${GGML_PREFIX}" ]] || {
  echo "Install ggml (whisper-cpp dependency): brew install ggml" >&2
  exit 1
}

rm -rf "${APP}" "${DMG}"
mkdir -p "${CONTENTS}/MacOS" "${RESOURCES}"

# --- Info.plist / icon / launcher ---
cp "${ROOT}/mac/Info.plist" "${CONTENTS}/Info.plist"
cp "${ROOT}/mac/Cerotrans.icns" "${RESOURCES}/Cerotrans.icns"
install -m 755 "${ROOT}/mac/launcher.sh" "${CONTENTS}/MacOS/Cerotrans"

# --- project code ---
PROJECT_DST="${RESOURCES}/project"
mkdir -p "${PROJECT_DST}"
rsync -a \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude 'dist/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.DS_Store' \
  --exclude 'mac/' \
  --exclude 'scripts/' \
  --exclude 'models/' \
  --exclude 'assets/' \
  "${ROOT}/" "${PROJECT_DST}/"

# --- models into Resources ---
mkdir -p "${RESOURCES}/models"
cp "${ROOT}/models/ggml-tiny.en.bin" "${RESOURCES}/models/"
if [[ -f "${ROOT}/models/ggml-base.en.bin" ]]; then
  cp "${ROOT}/models/ggml-base.en.bin" "${RESOURCES}/models/"
fi

# --- whisper-cli + whisper-server + libs ---
WDEST="${RESOURCES}/whisper"
mkdir -p "${WDEST}/bin" "${WDEST}/lib" "${WDEST}/libexec"
cp "${WHISPER_PREFIX}/bin/whisper-cli" "${WDEST}/bin/"
if [[ -x "${WHISPER_PREFIX}/bin/whisper-server" ]]; then
  cp "${WHISPER_PREFIX}/bin/whisper-server" "${WDEST}/bin/"
fi
cp "${WHISPER_PREFIX}/lib/libwhisper"*.dylib "${WDEST}/lib/" 2>/dev/null || true
cp "${GGML_PREFIX}/lib/libggml"*.dylib "${WDEST}/lib/" 2>/dev/null || true
# Backends live next to whisper-cli so ggml's executable-dir search finds them.
cp "${GGML_PREFIX}/libexec/"*.so "${WDEST}/bin/" 2>/dev/null || true
cp "${GGML_PREFIX}/libexec/"*.so "${WDEST}/libexec/" 2>/dev/null || true

# Bundle libomp (required by ggml CPU backends on Intel Homebrew builds).
OMP_PREFIX="$(brew --prefix libomp 2>/dev/null || true)"
if [[ -n "${OMP_PREFIX}" && -f "${OMP_PREFIX}/lib/libomp.dylib" ]]; then
  cp "${OMP_PREFIX}/lib/libomp.dylib" "${WDEST}/lib/"
fi

# Rewrite install names so the bundled binary loads sibling dylibs.
fix_id() {
  local lib="$1"
  local base
  base="$(basename "${lib}")"
  install_name_tool -id "@loader_path/${base}" "${lib}" 2>/dev/null || true
}
for lib in "${WDEST}/lib/"*.dylib; do
  [[ -f "${lib}" ]] || continue
  fix_id "${lib}"
done

# Point whisper-cli / whisper-server @rpath / absolute Homebrew paths at @loader_path/../lib
for BIN_NAME in whisper-cli whisper-server; do
  CLI="${WDEST}/bin/${BIN_NAME}"
  [[ -x "${CLI}" ]] || continue
  install_name_tool -add_rpath "@loader_path/../lib" "${CLI}" 2>/dev/null || true
  while IFS= read -r dep; do
    case "${dep}" in
      /usr/local/*|/opt/homebrew/*|@rpath/libwhisper*)
        base="$(basename "${dep}")"
        if [[ -f "${WDEST}/lib/${base}" ]]; then
          install_name_tool -change "${dep}" "@loader_path/../lib/${base}" "${CLI}" 2>/dev/null || true
        fi
        ;;
    esac
  done < <(otool -L "${CLI}" | awk 'NR>1 {print $1}')
done

# Remap deps inside each dylib toward @loader_path siblings
for lib in "${WDEST}/lib/"*.dylib; do
  [[ -f "${lib}" ]] || continue
  while IFS= read -r dep; do
    case "${dep}" in
      /usr/local/*|/opt/homebrew/*|@rpath/*)
        base="$(basename "${dep}")"
        if [[ -f "${WDEST}/lib/${base}" ]]; then
          install_name_tool -change "${dep}" "@loader_path/${base}" "${lib}" 2>/dev/null || true
        fi
        ;;
    esac
  done < <(otool -L "${lib}" | awk 'NR>1 {print $1}')
done

# Remap backend .so libs to bundled libggml-base + libomp
for so in "${WDEST}/bin/"libggml-*.so; do
  [[ -f "${so}" ]] || continue
  install_name_tool -add_rpath "@loader_path/../lib" "${so}" 2>/dev/null || true
  while IFS= read -r dep; do
    case "${dep}" in
      /usr/local/*|/opt/homebrew/*|@rpath/*)
        base="$(basename "${dep}")"
        if [[ -f "${WDEST}/lib/${base}" ]]; then
          install_name_tool -change "${dep}" "@loader_path/../lib/${base}" "${so}" 2>/dev/null || true
        fi
        ;;
    esac
  done < <(otool -L "${so}" | awk 'NR>1 {print $1}')
done

chmod +x "${CLI}"

# Neutralize Homebrew's baked-in GGML_BACKEND_DIR so discovery uses the
# executable directory (where we placed libggml-*.so) on any Mac.
python3 - <<'PY'
from pathlib import Path
import re
libdir = Path("${WDEST}/lib")
# Nonexistent path, shorter than the Cellar string it replaces.
new = b"/var/empty/cerotrans-xx"
for lib in libdir.glob("libggml*.dylib"):
    data = bytearray(lib.read_bytes())
    m = re.search(rb"/usr/local/Cellar/ggml/[^\x00]+/libexec", data)
    if not m:
        m = re.search(rb"/opt/homebrew/Cellar/ggml/[^\x00]+/libexec", data)
    if not m:
        continue
    old = m.group(0)
    if len(new) > len(old):
        raise SystemExit(f"replacement too long for {lib.name}")
    data[m.start():m.end()] = new + b"\x00" * (len(old) - len(new))
    lib.write_bytes(data)
    print(f"Patched backend dir in {lib.name}")
PY

# Smoke-test bundled whisper-cli (no reliance on Homebrew cellar backends)
export DYLD_LIBRARY_PATH="${WDEST}/lib"
python3 - <<'PY'
import wave, subprocess, os, sys
from pathlib import Path
wdest = Path("${WDEST}")
wav = Path("/tmp/cerotrans-smoke.wav")
with wave.open(str(wav), "w") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
    w.writeframes(b"\x00\x00" * 16000)
env = os.environ.copy()
env["DYLD_LIBRARY_PATH"] = str(wdest / "lib")
r = subprocess.run(
    [str(wdest / "bin" / "whisper-cli"),
     "-m", str(Path("${RESOURCES}/models/ggml-tiny.en.bin")),
     "-f", str(wav), "-nt", "-np", "-ng", "-l", "en"],
    capture_output=True, text=True, env=env,
)
print(r.stderr.splitlines()[:4])
print("smoke rc", r.returncode)
if r.returncode != 0:
    sys.exit(1)
if "loaded CPU backend from" not in r.stderr or "/bin/libggml-cpu" not in r.stderr:
    print(r.stderr)
    sys.exit("CPU backend did not load from app bundle")
print("whisper bundle smoke OK")
PY
echo "Bundled whisper-cli deps:"
otool -L "${CLI}" | head -10

# --- embedded Python + venv ---
echo "Fetching relocatable CPython…"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
curl -fsSL "${PBS_URL}" -o "${TMP}/python.tar.gz"
tar -xzf "${TMP}/python.tar.gz" -C "${TMP}"
PY_SRC=""
for d in "${TMP}"/*; do
  if [[ -d "${d}" && -x "${d}/bin/python3" ]]; then
    PY_SRC="${d}"
    break
  fi
done
[[ -n "${PY_SRC}" ]] || { echo "Failed to unpack python-build-standalone" >&2; exit 1; }

ditto "${PY_SRC}" "${RESOURCES}/python"
PY="${RESOURCES}/python/bin/python3"
"${PY}" -m ensurepip --upgrade >/dev/null
"${PY}" -m pip install --upgrade pip setuptools wheel -q
echo "Creating app venv + installing deps…"
"${PY}" -m venv "${RESOURCES}/venv"
"${RESOURCES}/venv/bin/pip" install --upgrade pip -q
"${RESOURCES}/venv/bin/pip" install -r "${ROOT}/requirements.txt" -q

# Quick import check
"${RESOURCES}/venv/bin/python" - <<'PY'
import rumps, pynput, sounddevice, numpy, pyperclip
print("venv imports ok")
PY

# Ad-hoc sign so Gatekeeper is happier on local installs (not notarized).
codesign --force --deep --sign - "${APP}" 2>/dev/null || true
xattr -cr "${APP}" 2>/dev/null || true

# --- DMG ---
echo "Creating DMG…"
STAGE="${DIST}/dmg_stage"
rm -rf "${STAGE}"
mkdir -p "${STAGE}"
ditto "${APP}" "${STAGE}/Cerotrans.app"
ln -sf /Applications "${STAGE}/Applications"

# Simple background-less drag-to-Applications DMG
hdiutil create \
  -volname "Cerotrans" \
  -srcfolder "${STAGE}" \
  -ov \
  -format UDZO \
  "${DMG}" >/dev/null
rm -rf "${STAGE}"

# Clear quarantine on local build artifact so double-click works from Finder
xattr -cr "${APP}" 2>/dev/null || true
xattr -cr "${DMG}" 2>/dev/null || true
codesign --force --sign - "${DMG}" 2>/dev/null || true

SIZE="$(du -sh "${DMG}" | awk '{print $1}')"
echo ""
echo "Done."
echo "  App: ${APP}"
echo "  DMG: ${DMG}  (${SIZE})"
echo ""
echo "Install: open the DMG → drag Cerotrans to Applications → launch."
echo "The app runs in the background with a 🎙️ icon in the menu bar (no Dock icon)."
echo "Grant Microphone, Accessibility, and Input Monitoring when prompted."
echo "Tip: click 🎙️ to start/stop; right-click for the menu. Hotkey: Right Option."
