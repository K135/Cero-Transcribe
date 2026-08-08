"""Soft start/stop feedback sounds."""

from __future__ import annotations

import subprocess
from pathlib import Path

_SOUNDS = {
    "start": Path("/System/Library/Sounds/Tink.aiff"),
    "stop": Path("/System/Library/Sounds/Pop.aiff"),
    "undo": Path("/System/Library/Sounds/Funk.aiff"),
}


def play(name: str) -> None:
    path = _SOUNDS.get(name)
    if not path or not path.exists():
        return
    subprocess.Popen(
        ["afplay", str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
