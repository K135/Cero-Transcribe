"""Fast paste / type / undo into the focused app."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

import pyperclip
from pynput import keyboard

from .textproc import is_junk

log = logging.getLogger("cerotrans.output")


def paste_text(text: str) -> bool:
    """Paste text via clipboard + Cmd+V (fast)."""
    if not text or is_junk(text):
        return False
    try:
        previous = pyperclip.paste()
    except Exception:
        previous = None
    try:
        pyperclip.copy(text)
        time.sleep(0.02)
        ctl = keyboard.Controller()
        with ctl.pressed(keyboard.Key.cmd):
            ctl.tap(keyboard.KeyCode.from_char("v"))
        if previous is not None:
            time.sleep(0.12)
            try:
                pyperclip.copy(previous)
            except Exception:
                pass
        return True
    except Exception as exc:
        log.warning("paste failed: %s", exc)
        return type_text(text)


def type_text(text: str) -> bool:
    if not text or is_junk(text):
        return False
    try:
        keyboard.Controller().type(text)
        return True
    except Exception as exc:
        log.warning("type failed: %s", exc)
        return False


def delete_chars(n: int) -> bool:
    if n <= 0:
        return True
    n = min(n, 4000)
    try:
        ctl = keyboard.Controller()
        # Faster: select backward isn't universal; burst backspaces
        for _ in range(n):
            ctl.tap(keyboard.Key.backspace)
        return True
    except Exception as exc:
        log.warning("delete failed: %s", exc)
        return False


def insert_text(text: str) -> None:
    paste_text(text if text.endswith(" ") or not text else text + " ")


@dataclass
class TypedHistory:
    """Tracks pasted chunks so voice 'delete' commands know what to erase."""

    chunks: list[str] = field(default_factory=list)
    draft: str = ""

    def add(self, text: str) -> None:
        if text:
            self.chunks.append(text)

    def undo_last(self) -> int:
        """Delete last chunk (last pasted phrase)."""
        if self.draft:
            n = len(self.draft)
            self.draft = ""
            return n
        if self.chunks:
            return len(self.chunks.pop())
        return 0

    def undo_last_word(self) -> int:
        if not self.chunks:
            return 0
        last = self.chunks[-1]
        stripped = last.rstrip()
        if not stripped:
            return len(self.chunks.pop())
        m = re.search(r"\S+\s*$", stripped)
        if not m:
            return len(self.chunks.pop())
        word = m.group(0)
        # Include trailing spaces after the word in the chunk
        start = m.start()
        removed = last[start:]
        kept = last[:start]
        if kept.strip():
            self.chunks[-1] = kept
        else:
            self.chunks.pop()
        return len(removed)

    def undo_last_sentence(self) -> int:
        """Remove characters for the last sentence across recent chunks."""
        if not self.chunks:
            return 0
        full = "".join(self.chunks)
        # Find last sentence boundary before the end
        body = full.rstrip()
        if not body:
            n = len(full)
            self.chunks.clear()
            return n
        # Split on .?! while keeping trailing spaces in count via full length
        parts = re.split(r"(?<=[.!?])\s+", body)
        if len(parts) <= 1:
            # No sentence punct — delete last 1–2 chunks as a "sentence"
            n = 0
            for _ in range(min(2, len(self.chunks))):
                n += len(self.chunks.pop())
            return n
        last_sent = parts[-1]
        # Characters to remove = from start of last sentence to end of full
        idx = body.rfind(last_sent)
        if idx < 0:
            return self.undo_last()
        remove_from = idx
        # In `full`, account for any trailing whitespace after body
        remove_n = len(full) - remove_from
        # Rebuild chunks truncated to remove_from
        self._truncate_to(len(full) - remove_n)
        return remove_n

    def undo_all(self) -> int:
        n = sum(len(c) for c in self.chunks) + len(self.draft)
        self.chunks.clear()
        self.draft = ""
        return n

    def _truncate_to(self, keep_len: int) -> None:
        if keep_len <= 0:
            self.chunks.clear()
            return
        new_chunks: list[str] = []
        used = 0
        for c in self.chunks:
            if used >= keep_len:
                break
            if used + len(c) <= keep_len:
                new_chunks.append(c)
                used += len(c)
            else:
                new_chunks.append(c[: keep_len - used])
                used = keep_len
                break
        self.chunks = new_chunks

    def reset(self) -> None:
        self.chunks.clear()
        self.draft = ""
