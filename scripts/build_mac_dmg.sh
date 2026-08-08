#!/usr/bin/env bash
# Build a fully self-contained Cero-Transcribe.app + installable DMG.
#
# End users need: Install → grant permissions → use.
# No Homebrew, Python, or whisper-cpp on the target Mac.
#
# Bundles:
#   - relocatable CPython (python-build-standalone) + venv with deps
#   - whisper-cli + whisper-server + ggml dylibs/backends
#   - ggml Tiny EN + Base EN models
#   - app icon + LSUIElement Info.plist (menu bar only, no Dock)
#
# Build machine needs: brew install whisper-cpp portaudio
# Usage: bash scripts/build_mac_dmg.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="${ROOT}/dist"
APP_NAME="Cero-Transcribe"
APP="${DIST}/${APP_NAME}.app"
CONTENTS="${APP}/Contents"
RESOURCES="${CONTENTS}/Resources"
DMG="${DIST}/${APP_NAME}-Install.dmg"
ARCH="$(uname -m)"
EXEC_NAME="CeroTranscribe"

PBS_RELEASE="20260414"
case "${ARCH}" in
  x86_64) PBS_TAR="cpython-3.12.13+${PBS_RELEASE}-x86_64-apple-darwin-install_only.tar.gz" ;;
  arm64)  PBS_TAR="cpython-3.12.13+${PBS_RELEASE}-aarch64-apple-darwin-install_only.tar.gz" ;;
  *) echo "Unsupported arch: ${ARCH}" >&2; exit 1 ;;
esac
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_RELEASE}/${PBS_TAR}"

echo "═ Building ${APP_NAME}.app (${ARCH}) ═"

# --- icon ---
bash "${ROOT}/scripts/build_icons.sh"
[[ -f "${ROOT}/mac/Cerotrans.icns" ]] || { echo "Missing icns" >&2; exit 1; }

# --- models (both Tiny + Base for a complete offline install) ---
echo "Ensuring models…"
bash "${ROOT}/scripts/download_model.sh"
[[ -f "${ROOT}/models/ggml-tiny.en.bin" ]] || { echo "tiny.en model missing" >&2; exit 1; }
[[ -f "${ROOT}/models/ggml-base.en.bin" ]] || { echo "base.en model missing" >&2; exit 1; }

# --- brew whisper (build machine only) ---
WHISPER_PREFIX="$(brew --prefix whisper-cpp 2>/dev/null || true)"
GGML_PREFIX="$(brew --prefix ggml 2>/dev/null || true)"
[[ -n "${WHISPER_PREFIX}" && -x "${WHISPER_PREFIX}/bin/whisper-cli" ]] || {
  echo "Install whisper-cpp first: brew install whisper-cpp" >&2
  exit 1
}
[[ -x "${WHISPER_PREFIX}/bin/whisper-server" ]] || {
  echo "whisper-server missing from whisper-cpp. Update: brew upgrade whisper-cpp" >&2
  exit 1
}
[[ -n "${GGML_PREFIX}" ]] || {
  echo "Install ggml (whisper-cpp dependency): brew install ggml" >&2
  exit 1
}

rm -rf "${APP}" "${DMG}" "${DIST}/${APP_NAME}.app" "${DIST}/Cerotrans.app" 2>/dev/null || true
mkdir -p "${CONTENTS}/MacOS" "${RESOURCES}"

# --- Info.plist (patch executable / icon names for this bundle) ---
python3 - <<PY
from pathlib import Path
import plistlib
src = Path("${ROOT}/mac/Info.plist")
dst = Path("${CONTENTS}/Info.plist")
data = plistlib.loads(src.read_bytes())
data["CFBundleExecutable"] = "${EXEC_NAME}"
data["CFBundleIconFile"] = "${EXEC_NAME}"
data["CFBundleName"] = "${APP_NAME}"
data["CFBundleDisplayName"] = "${APP_NAME}"
data["CFBundleIdentifier"] = "app.cerotranscribe.dictation"
data["CFBundleShortVersionString"] = "1.2.0"
data["CFBundleVersion"] = "3"
dst.write_bytes(plistlib.dumps(data))
print("Wrote Info.plist")
PY
cp "${ROOT}/mac/Cerotrans.icns" "${RESOURCES}/${EXEC_NAME}.icns"
install -m 755 "${ROOT}/mac/launcher.sh" "${CONTENTS}/MacOS/${EXEC_NAME}"

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
cp "${ROOT}/models/ggml-base.en.bin" "${RESOURCES}/models/"

# --- whisper-cli + whisper-server + libs ---
WDEST="${RESOURCES}/whisper"
mkdir -p "${WDEST}/bin" "${WDEST}/lib" "${WDEST}/libexec"
cp "${WHISPER_PREFIX}/bin/whisper-cli" "${WDEST}/bin/"
cp "${WHISPER_PREFIX}/bin/whisper-server" "${WDEST}/bin/"
cp "${WHISPER_PREFIX}/lib/libwhisper"*.dylib "${WDEST}/lib/" 2>/dev/null || true
cp "${GGML_PREFIX}/lib/libggml"*.dylib "${WDEST}/lib/" 2>/dev/null || true
# Backends live next to binaries so ggml's executable-dir search finds them.
cp "${GGML_PREFIX}/libexec/"*.so "${WDEST}/bin/" 2>/dev/null || true
cp "${GGML_PREFIX}/libexec/"*.so "${WDEST}/libexec/" 2>/dev/null || true

# Bundle libomp (required by ggml CPU backends on Intel Homebrew builds).
OMP_PREFIX="$(brew --prefix libomp 2>/dev/null || true)"
if [[ -n "${OMP_PREFIX}" && -f "${OMP_PREFIX}/lib/libomp.dylib" ]]; then
  cp "${OMP_PREFIX}/lib/libomp.dylib" "${WDEST}/lib/"
fi

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

for BIN_NAME in whisper-cli whisper-server; do
  CLI="${WDEST}/bin/${BIN_NAME}"
  [[ -x "${CLI}" ]] || continue
  chmod +x "${CLI}"
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

# Neutralize Homebrew's baked-in GGML_BACKEND_DIR
WDEST="${WDEST}" RESOURCES="${RESOURCES}" python3 - <<'PY'
from pathlib import Path
import os, re
libdir = Path(os.environ["WDEST"]) / "lib"
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
    lib.chmod(0o755)
    lib.write_bytes(data)
    print(f"Patched backend dir in {lib.name}")
PY

# Smoke-test bundled whisper-cli
export DYLD_LIBRARY_PATH="${WDEST}/lib"
WDEST="${WDEST}" RESOURCES="${RESOURCES}" python3 - <<'PY'
import wave, subprocess, os, sys
from pathlib import Path
wdest = Path(os.environ["WDEST"])
resources = Path(os.environ["RESOURCES"])
wav = Path("/tmp/cerotranscribe-smoke.wav")
with wave.open(str(wav), "w") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
    w.writeframes(b"\x00\x00" * 16000)
env = os.environ.copy()
env["DYLD_LIBRARY_PATH"] = str(wdest / "lib")
r = subprocess.run(
    [str(wdest / "bin" / "whisper-cli"),
     "-m", str(resources / "models" / "ggml-tiny.en.bin"),
     "-f", str(wav), "-nt", "-np", "-ng", "-l", "en"],
    capture_output=True, text=True, env=env,
)
print("smoke rc", r.returncode)
if r.returncode != 0:
    print(r.stderr)
    sys.exit(1)
if "loaded CPU backend from" not in r.stderr or "/bin/libggml-cpu" not in r.stderr:
    print(r.stderr)
    sys.exit("CPU backend did not load from app bundle")
print("whisper bundle smoke OK")
assert (wdest / "bin" / "whisper-server").is_file()
print("whisper-server present OK")
PY

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

"${RESOURCES}/venv/bin/python" - <<'PY'
import rumps, pynput, sounddevice, numpy, pyperclip
print("venv imports ok")
# Confirm sounddevice ships a portaudio binary (no Homebrew needed at runtime)
from pathlib import Path
import _sounddevice_data
root = Path(_sounddevice_data.__file__).parent / "portaudio-binaries"
dylibs = list(root.glob("libportaudio*"))
assert dylibs, "sounddevice missing bundled PortAudio"
print("bundled PortAudio:", dylibs[0].name)
PY

# Make the runtime interpreter show up as "Cero-Transcribe" in macOS
# Privacy prompts (not "python3.12"). Use a symlink so @rpath still works.
echo "Linking Cero-Transcribe-named Python for permission dialogs…"
VENV_BIN="${RESOURCES}/venv/bin"
(
  cd "${VENV_BIN}"
  # Resolve which pythonX.Y exists in this venv
  TARGET=""
  for cand in python3.12 python3.11 python3.10 python3; do
    if [[ -e "${cand}" ]]; then
      TARGET="${cand}"
      break
    fi
  done
  [[ -n "${TARGET}" ]] || { echo "No python3.* in venv" >&2; exit 1; }
  ln -sfn "${TARGET}" "Cero-Transcribe"
  ln -sfn "${TARGET}" "CeroTranscribe"
  ls -la "Cero-Transcribe" "CeroTranscribe"
)
# Ensure launcher can find libpython when DYLD path is set for whisper
# (python lib must come first — see launcher.sh)
"${VENV_BIN}/Cero-Transcribe" -c "import sys; print('named interpreter ok', sys.version.split()[0])"

# Ad-hoc sign
codesign --force --deep --sign - "${APP}" 2>/dev/null || true
xattr -cr "${APP}" 2>/dev/null || true

# --- DMG with install instructions ---
echo "Creating DMG…"
STAGE="${DIST}/dmg_stage"
rm -rf "${STAGE}"
mkdir -p "${STAGE}"
ditto "${APP}" "${STAGE}/${APP_NAME}.app"
ln -sf /Applications "${STAGE}/Applications"

cat > "${STAGE}/Install & Permissions.txt" <<'EOF'
Cero-Transcribe — Install guide
================================

1. Drag "Cero-Transcribe" into the Applications folder.
2. Open Applications → Cero-Transcribe
   (First open: Right-click → Open if macOS warns about an unidentified developer.)
3. Look for the 🎙️ icon in the menu bar (top-right). There is no Dock icon.
4. Grant permissions when prompted (or use 🎙️ → Grant Permissions…):

   • Microphone          — hear your voice
   • Accessibility       — type into other apps (required)
   • Input Monitoring    — global hotkeys

5. Click into any text field, then click 🎙️ (or press Right Option) and speak.

Fully offline. No Homebrew, Python, or internet needed after install.

Need help? https://github.com/K135/Cero-Transcribe
EOF

hdiutil create \
  -volname "${APP_NAME}" \
  -srcfolder "${STAGE}" \
  -ov \
  -format UDZO \
  "${DMG}" >/dev/null
rm -rf "${STAGE}"

xattr -cr "${APP}" 2>/dev/null || true
xattr -cr "${DMG}" 2>/dev/null || true
codesign --force --sign - "${DMG}" 2>/dev/null || true

SIZE="$(du -sh "${DMG}" | awk '{print $1}')"
echo ""
echo "Done."
echo "  App: ${APP}"
echo "  DMG: ${DMG}  (${SIZE})"
echo ""
echo "Install: open the DMG → drag ${APP_NAME} to Applications → launch."
echo "Grant Microphone, Accessibility, and Input Monitoring when prompted."
