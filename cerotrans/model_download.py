"""Download whisper.cpp ggml models into Application Support on demand."""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from .models_catalog import (
    USER_MODELS_DIR,
    get_model,
    hf_url,
    model_is_available,
    resolve_model_path,
)

log = logging.getLogger("cerotrans.download")

ProgressCb = Callable[[str, int, int], None]  # label, bytes_done, bytes_total


def ensure_model(
    label: str,
    *,
    bundled_dir: Path | None = None,
    on_progress: ProgressCb | None = None,
) -> Path:
    """Return local path to the model, downloading into USER_MODELS_DIR if needed."""
    existing = resolve_model_path(label, bundled_dir)
    if existing is not None:
        return existing

    info = get_model(label)
    USER_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    dest = USER_MODELS_DIR / info.filename
    partial = dest.with_suffix(dest.suffix + ".partial")
    url = hf_url(info.filename)

    log.info("Downloading %s from %s → %s", label, url, dest)
    if on_progress:
        on_progress(label, 0, max(info.approx_mb * 1024 * 1024, 1))

    try:
        _stream_download(url, partial, label, on_progress)
        partial.replace(dest)
    except Exception:
        if partial.is_file():
            try:
                partial.unlink()
            except OSError:
                pass
        raise

    if not dest.is_file():
        raise FileNotFoundError(f"Download finished but file missing: {dest}")
    log.info("Downloaded %s (%s bytes)", label, dest.stat().st_size)
    return dest


def _stream_download(
    url: str,
    dest: Path,
    label: str,
    on_progress: ProgressCb | None,
) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Cero-Transcribe/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        chunk = 1024 * 256
        with open(dest, "wb") as out:
            while True:
                block = resp.read(chunk)
                if not block:
                    break
                out.write(block)
                done += len(block)
                if on_progress:
                    on_progress(label, done, total or done)


def format_progress(label: str, done: int, total: int) -> str:
    if total > 0:
        pct = min(100, int(100 * done / total))
        mb = done / (1024 * 1024)
        return f"↓ {label} {pct}% ({mb:.0f} MB)"
    mb = done / (1024 * 1024)
    return f"↓ {label} {mb:.0f} MB…"
