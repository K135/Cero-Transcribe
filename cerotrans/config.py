"""Paths and user settings for cerotrans."""

from __future__ import annotations

from pathlib import Path

SUPPORT = Path.home() / "Library" / "Application Support" / "cerotrans"
VOCAB_FILE = SUPPORT / "vocabulary.txt"
CONFIG_FILE = SUPPORT / "config.json"
LOG_FILE = SUPPORT / "app.log"

# Live engine timing — tuned for warm whisper-server + short phrases
POLL_S = 0.08
MIN_PHRASE_S = 0.45
MAX_PHRASE_S = 2.4           # keep chunks short → faster decode
COMMIT_SILENCE_S = 0.22      # snappy end-of-utterance
AUTO_STOP_SILENCE_S = 6.0
ENABLE_AUTO_STOP = False
VOICE_RMS = 0.012

DEFAULT_VOCAB = """# Custom vocabulary for cerotrans (one tip per line)
# Plain words/phrases are added to Whisper's prompt.
# Use wrong=right to auto-correct after transcription.
Cerotrans
cerotrans=Cerotrans
cero=Cero
email
Cursor
Chrome
"""


def ensure_support_dir() -> None:
    SUPPORT.mkdir(parents=True, exist_ok=True)
    if not VOCAB_FILE.exists():
        VOCAB_FILE.write_text(DEFAULT_VOCAB, encoding="utf-8")


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
