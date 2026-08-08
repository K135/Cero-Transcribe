"""Pause-based live dictation — accurate phrases, not mid-word scraps."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import numpy as np

from .commands import parse_voice_command
from .config import (
    AUTO_STOP_SILENCE_S,
    COMMIT_SILENCE_S,
    ENABLE_AUTO_STOP,
    MAX_PHRASE_S,
    MIN_PHRASE_S,
    POLL_S,
    VOICE_RMS,
    load_vocabulary,
)
from .output import TypedHistory, delete_chars, paste_text
from .recorder import SAMPLE_RATE, Recorder
from .textproc import (
    ends_with_sentence_end,
    prepare_transcript,
    should_attach_to_previous,
)
from .transcriber import Transcriber

log = logging.getLogger("cerotrans.live")

LevelCb = Callable[[float], None]
StatusCb = Callable[[str], None]
AutoStopCb = Callable[[], None]


class LiveEngine:
    """Accumulate speech until a pause, then transcribe the whole phrase."""

    def __init__(
        self,
        recorder: Recorder,
        transcriber: Transcriber,
        *,
        on_level: LevelCb | None = None,
        on_status: StatusCb | None = None,
        on_auto_stop: AutoStopCb | None = None,
    ) -> None:
        self.recorder = recorder
        self.transcriber = transcriber
        self.on_level = on_level
        self.on_status = on_status
        self.on_auto_stop = on_auto_stop
        self.history = TypedHistory()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cursor = 0
        self._busy = threading.Lock()
        self._context = ""  # recent text for Whisper prompt continuity

    def start(self) -> None:
        self.history.reset()
        self._cursor = 0
        # Keep context across start/stop so sentence flow continues in emails
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="cerotrans-live", daemon=True)
        self._thread.start()

    def stop(self, flush: bool = True) -> None:
        self._stop.set()
        t = self._thread
        self._thread = None
        if t is not None and t is not threading.current_thread():
            # Don't stall stop for a long in-flight decode
            t.join(timeout=1.2)
        if flush:
            self._flush_remaining()

    def undo(self) -> bool:
        n = self.history.undo_last()
        if n <= 0:
            return False
        return delete_chars(n)

    def _run_command(self, kind: str) -> bool:
        if kind == "delete_last":
            n = self.history.undo_last()
        elif kind == "delete_sentence":
            n = self.history.undo_last_sentence()
        elif kind == "delete_word":
            n = self.history.undo_last_word()
        elif kind == "delete_all":
            n = self.history.undo_all()
        else:
            return False
        if n <= 0:
            log.info("Command %s — nothing to delete", kind)
            return False
        ok = delete_chars(n)
        # Trim context too so Whisper doesn't keep deleted words
        if kind == "delete_all":
            self._context = ""
        elif self._context and n > 0:
            self._context = self._context[:-n] if n < len(self._context) else ""
        log.info("Command %s deleted %d chars ok=%s", kind, n, ok)
        if self.on_status:
            try:
                self.on_status(f"Deleted ({kind})")
            except Exception:
                pass
        return ok

    def _loop(self) -> None:
        silence_started: float | None = None
        speech_started: float | None = None
        had_real = False
        _, replacements = load_vocabulary()
        min_n = int(MIN_PHRASE_S * SAMPLE_RATE)
        max_n = int(MAX_PHRASE_S * SAMPLE_RATE)

        while not self._stop.is_set():
            time.sleep(POLL_S)
            try:
                snap = self.recorder.snapshot()
            except Exception:
                log.exception("snapshot failed")
                continue
            if snap.size == 0:
                continue

            pending = snap[self._cursor :]
            tail_n = min(snap.size, int(0.08 * SAMPLE_RATE))
            level = float(np.sqrt(np.mean(np.square(snap[-tail_n:]))))
            if self.on_level:
                try:
                    self.on_level(level)
                except Exception:
                    pass

            voiced = level >= VOICE_RMS
            now = time.monotonic()

            if voiced:
                silence_started = None
                if speech_started is None:
                    speech_started = now
                if pending.size >= max_n:
                    ok = self._emit(pending, replacements, self._should_capitalize())
                    self._cursor = snap.size
                    speech_started = now
                    if ok:
                        had_real = True
                continue

            if silence_started is None:
                silence_started = now
            silent_for = now - silence_started

            if silent_for >= COMMIT_SILENCE_S and pending.size >= min_n and _has_voice(pending):
                ok = self._emit(pending, replacements, self._should_capitalize())
                self._cursor = snap.size
                speech_started = None
                if ok:
                    had_real = True
                silence_started = now

            if (
                ENABLE_AUTO_STOP
                and had_real
                and self.on_auto_stop
                and silent_for >= AUTO_STOP_SILENCE_S
            ):
                log.info("Auto-stop on silence")
                try:
                    self.on_auto_stop()
                except Exception:
                    log.exception("auto-stop callback failed")
                return

    def _should_capitalize(self) -> bool:
        if not self.history.chunks:
            return True
        prev = self.history.chunks[-1]
        if not prev:
            return True
        return ends_with_sentence_end(prev)

    def _flush_remaining(self) -> None:
        try:
            snap = self.recorder.snapshot()
        except Exception:
            return
        rem = snap[self._cursor :]
        min_n = int(0.5 * SAMPLE_RATE)
        if rem.size < min_n or not _has_voice(rem):
            return
        _, replacements = load_vocabulary()
        self._emit(rem, replacements, capitalize=self._should_capitalize())
        self._cursor = snap.size

    def _emit(
        self,
        chunk: np.ndarray,
        replacements: dict[str, str],
        capitalize: bool,
    ) -> bool:
        if not self._busy.acquire(blocking=False):
            # Previous emit still running — wait briefly so we don't drop the last phrase
            if not self._busy.acquire(timeout=2.5):
                log.warning("emit busy — dropping chunk")
                return False
        try:
            raw = self.transcriber.transcribe(chunk, context=self._context)
            cmd = parse_voice_command(raw or "")
            if cmd is None:
                cleaned = prepare_transcript(
                    raw,
                    replacements=replacements,
                    sentence_start=capitalize,
                )
                cmd = parse_voice_command(cleaned) if cleaned else None
            if cmd is not None:
                return self._run_command(cmd.kind)

            text = prepare_transcript(
                raw,
                replacements=replacements,
                sentence_start=capitalize,
            )
            if not text:
                log.info("Skip: %r", (raw or "")[:60])
                return False

            # Glue comma/period onto the previous word (eat trailing space)
            if should_attach_to_previous(text) and self.history.chunks:
                prev = self.history.chunks[-1]
                if prev.endswith(" "):
                    if delete_chars(1):
                        self.history.chunks[-1] = prev[:-1]
                        if self._context.endswith(" "):
                            self._context = self._context[:-1]

            if text.endswith("\n"):
                pass  # keep newline; no trailing space
            elif not text.endswith(" "):
                text = text + " "
            ok = paste_text(text)
            if ok:
                self.history.add(text)
                self._context = (self._context + " " + text).strip()[-120:]
                if self.on_status:
                    try:
                        self.on_status(text.strip()[:48] or "↵")
                    except Exception:
                        pass
                log.info("Paste ok: %r", text[:100])
            else:
                log.warning("Paste failed: %r", text[:80])
            return ok
        except Exception:
            log.exception("emit failed")
            return False
        finally:
            self._busy.release()


def _has_voice(samples: np.ndarray) -> bool:
    if samples.size == 0:
        return False
    return float(np.sqrt(np.mean(np.square(samples)))) >= VOICE_RMS
