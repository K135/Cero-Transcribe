#!/usr/bin/env bash
# Build Cerotrans.icns from mac/icon-master-1024.png
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${ROOT}/mac/icon-master-1024.png"
ICONSET="${ROOT}/mac/Cerotrans.iconset"
ICNS="${ROOT}/mac/Cerotrans.icns"

[[ -f "${SRC}" ]] || { echo "Missing ${SRC}" >&2; exit 1; }

rm -rf "${ICONSET}" "${ICNS}"
mkdir -p "${ICONSET}"

sizes=(16 32 128 256 512)
for s in "${sizes[@]}"; do
  sips -z "$s" "$s" "${SRC}" --out "${ICONSET}/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2))
  sips -z "$d" "$d" "${SRC}" --out "${ICONSET}/icon_${s}x${s}@2x.png" >/dev/null
done

iconutil -c icns "${ICONSET}" -o "${ICNS}"
echo "Wrote ${ICNS}"
