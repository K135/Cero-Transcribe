"""Paths and user settings for Cero-Transcribe."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

SUPPORT = Path.home() / "Library" / "Application Support" / "cerotrans"
VOCAB_FILE = SUPPORT / "vocabulary.txt"
CONFIG_FILE = SUPPORT / "config.json"
LOG_FILE = SUPPORT / "app.log"

# Live engine timing — tuned for warm whisper-server + short phrases
POLL_S = 0.08
MIN_PHRASE_S = 0.45
MAX_PHRASE_S = 2.4
COMMIT_SILENCE_S = 0.22
AUTO_STOP_SILENCE_S = 6.0
ENABLE_AUTO_STOP = False
VOICE_RMS = 0.012

DEFAULT_VOCAB = """# Custom vocabulary for Cero-Transcribe (one tip per line)
# Plain words/phrases are added to Whisper's prompt.
# Use wrong=right to auto-correct after transcription.
Cero-Transcribe
cerotrans=Cero-Transcribe
cero=Cero
email
Cursor
Chrome
"""

DEFAULT_SETTINGS: dict[str, Any] = {
    "wake_enabled": False,  # opt-in — avoids false starts from “bye Cero” etc.
    "toggle_shortcut": "alt_r",  # Right Option
    "undo_shortcut": "cmd+shift+u",
}

log = logging.getLogger("cerotrans.config")


def ensure_support_dir() -> None:
    SUPPORT.mkdir(parents=True, exist_ok=True)
    if not VOCAB_FILE.exists():
        VOCAB_FILE.write_text(DEFAULT_VOCAB, encoding="utf-8")


def load_settings() -> dict[str, Any]:
    ensure_support_dir()
    data = dict(DEFAULT_SETTINGS)
    if CONFIG_FILE.is_file():
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data.update({k: raw[k] for k in DEFAULT_SETTINGS if k in raw})
        except Exception:
            log.exception("Failed reading settings")
    return data


def save_settings(settings: dict[str, Any]) -> None:
    ensure_support_dir()
    current = load_settings()
    current.update(settings)
    CONFIG_FILE.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")


def load_vocabulary() -> tuple[list[str], dict[str, str]]:
    """Return (prompt_terms, replacements)."""
    ensure_support_dir()
    terms: list[str] = []
    replacements: dict[str, str] = {}
    for raw in VOCAB_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            wrong, right = line.split("=", 1)
            wrong, right = wrong.strip(), right.strip()
            if wrong and right:
                replacements[wrong] = right
                terms.append(right)
        else:
            terms.append(line)
    seen: set[str] = set()
    unique: list[str] = []
    for t in terms:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return unique, replacements
