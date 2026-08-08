"""Voice editing commands (delete / undo) — not pasted as text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

CommandKind = Literal[
    "delete_last",
    "delete_sentence",
    "delete_word",
    "delete_all",
    "none",
]

# Whisper often mangles "delete" — accept common near-misses as the verb.
_DEL = r"(?:delete|deletes|deleted|delight|delate|the\s+late|did\s+late|dilate|remove|erase|scratch)"

@dataclass(frozen=True)
class VoiceCommand:
    kind: CommandKind
    raw: str = ""


# Whole-utterance commands (after normalize). Order matters: specific first.
_PATTERNS: list[tuple[re.Pattern[str], CommandKind]] = [
    (
        re.compile(
            rf"^(please\s+)?{_DEL}\s+"
            r"(the\s+)?(last\s+)?(sentence|line|para(?:graph)?)\.?$",
            re.I,
        ),
        "delete_sentence",
    ),
    (
        re.compile(
            r"^(please\s+)?(scratch|strike)\s+(the\s+)?(last\s+)?(sentence|line)\.?$",
            re.I,
        ),
        "delete_sentence",
    ),
    (
        re.compile(
            rf"^(please\s+)?{_DEL}\s+"
            r"(the\s+)?(last\s+)?word\.?$",
            re.I,
        ),
        "delete_word",
    ),
    (
        re.compile(
            rf"^(please\s+)?{_DEL}\s+"
            r"(everything|all|all\s+text|the\s+whole\s+thing)\.?$",
            re.I,
        ),
        "delete_all",
    ),
    (
        re.compile(
            r"^(please\s+)?(clear\s+(everything|all|all\s+text)|"
            r"clear\s+the\s+whole\s+thing)\.?$",
            re.I,
        ),
        "delete_all",
    ),
    # Bare delete / undo / scratch that
    (
        re.compile(
            rf"^(please\s+)?(scratch\s+that|undo(\s+that)?|strike\s+that|"
            rf"{_DEL}(\s+that)?|{_DEL}|remove\s+that|erase\s+that)\.?$",
            re.I,
        ),
        "delete_last",
    ),
    # "word delete" / "that delete" — verb at the end
    (
        re.compile(
            rf"^(the\s+)?(last\s+)?(word|that|it|this)\s+{_DEL}\.?$",
            re.I,
        ),
        "delete_word",
    ),
    (
        re.compile(
            rf"^(the\s+)?(last\s+)?(sentence|line)\s+{_DEL}\.?$",
            re.I,
        ),
        "delete_sentence",
    ),
]


def parse_voice_command(text: str) -> VoiceCommand | None:
    """Return a command if the whole phrase is an edit instruction."""
    t = (text or "").strip()
    if not t:
        return None
    # Normalize whisper quirks
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\bfull stop\b", "", t, flags=re.I).strip(" .,!?")
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return None
    for pat, kind in _PATTERNS:
        if pat.match(t):
            return VoiceCommand(kind=kind, raw=t)
    return None
