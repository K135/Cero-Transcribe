"""Low-CPU 'Hey Cero' / 'Hey Sero' wake-word watcher.

Idle: mic energy only. Whisper runs only after voice is detected.
Strict matching — must sound like “Hey Cero”, never “bye Cero”.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Callable

import numpy as np
import sounddevice as sd

from .recorder import SAMPLE_RATE
from .textproc import strip_special_tokens
from .transcriber import Transcriber

log = logging.getLogger("cerotrans.wake")

# Names Whisper commonly hears for “Cero”. Keep tight — no “cheerio” etc.
_NAME = r"cero|sero|zero|ciro|cerro|searo|saro"

# Require an explicit attention word + the name. Never match bare “Cero”
# or “bye Cero” / “to Cero”.
_WAKE_RE = re.compile(
    rf"\b(?:hey|hi|hello|okay|ok)\s+(?:there\s+)?(?:{_NAME})\b",
    re.IGNORECASE,
)

# Reject common false starts that Whisper confuses with the wake phrase.
_REJECT_RE = re.compile(
    r"\b(?:bye|goodbye|good\s*bye|by|buy|to|too|two|for|from|about)\b",
    re.IGNORECASE,
)

VOICE_RMS = 0.012  # slightly higher — ignore quiet room noise
VOICE_HOLD_S = 0.22
CAPTURE_S = 1.6
COOLDOWN_S = 5.0  # after a hit (or strong false alarm)
IDLE_POLL_S = 0.05
# Soft prompt only — do NOT bias Whisper into inventing “hey cero”
WAKE_PROMPT = "Wake phrase."


def is_wake_phrase(text: str) -> bool:
    t = strip_special_tokens(text or "").lower()
    t = re.sub(r"[^a-z\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return False
    # “bye to Cero”, “goodbye Cero”, etc. must never start dictation
    if _REJECT_RE.search(t):
        return False
    if _WAKE_RE.search(t):
        return True
    # Short utterance: exactly attention + name (2–3 words)
    words = t.split()
    if 2 <= len(words) <= 3:
        attn = {"hey", "hi", "hello", "ok", "okay"}
        names = {"cero", "sero", "zero", "ciro", "cerro", "searo", "saro"}
        if words[0] in attn and any(w in names for w in words[1:]):
            return True
    return False


class WakeWordWatcher:
    def __init__(
        self,
        transcriber: Transcriber,
        on_wake: Callable[[], None],
    ) -> None:
        self.transcriber = transcriber
        self.on_wake = on_wake
        self._enabled = False
        self._paused = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._ring: list[np.ndarray] = []
        self._ring_samples = 0
        self._stream: sd.InputStream | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, value: bool) -> None:
        self._enabled = bool(value)
        log.info("Wake word enabled=%s", self._enabled)

    def start(self) -> None:
        self._stop.clear()
        self._paused = False
        self._thread = threading.Thread(target=self._loop, name="cerotrans-wake", daemon=True)
        self._thread.start()
        log.info("Wake watcher started (opt-in Hey Cero / Hey Sero)")

    def stop(self) -> None:
        self._stop.set()
        self._close_stream()
        t = self._thread
        self._thread = None
        if t is not None and t is not threading.current_thread():
            t.join(timeout=2)

    def pause(self) -> None:
        self._paused = True
        self._close_stream()
        log.info("Wake watcher paused")

    def resume(self) -> None:
        self._paused = False
        log.info("Wake watcher resumed")

    def _loop(self) -> None:
        voiced_since: float | None = None
        cooldown_until = 0.0
        last_level_log = 0.0

        while not self._stop.is_set():
            if not self._enabled or self._paused:
                self._close_stream()
                time.sleep(0.25)
                continue

            now = time.monotonic()
            if now < cooldown_until:
                time.sleep(0.1)
                continue

            try:
                self._ensure_stream()
            except Exception:
                log.exception("wake mic open failed")
                time.sleep(1.0)
                continue

            level = self._recent_rms()
            if now - last_level_log > 5.0 and level > 0.004:
                log.info("Wake mic live (rms=%.4f)", level)
                last_level_log = now

            if level >= VOICE_RMS:
                if voiced_since is None:
                    voiced_since = now
                elif now - voiced_since >= VOICE_HOLD_S:
                    log.info("Voice detected (rms=%.4f) — checking for Hey Cero", level)
                    samples = self._snapshot_capture()
                    self._close_stream()
                    voiced_since = None
                    if samples.size >= int(0.5 * SAMPLE_RATE):
                        if self._check_wake(samples):
                            cooldown_until = time.monotonic() + COOLDOWN_S
                            try:
                                self.on_wake()
                            except Exception:
                                log.exception("on_wake failed")
                            self._paused = True
                            continue
                    cooldown_until = time.monotonic() + 1.0
            else:
                voiced_since = None

            time.sleep(IDLE_POLL_S)

        self._close_stream()

    def _ensure_stream(self) -> None:
        with self._lock:
            if self._stream is not None:
                return
            self._ring = []
            self._ring_samples = 0
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=2048,
                callback=self._callback,
            )
            self._stream.start()
            log.info("Wake mic stream opened")

    def _close_stream(self) -> None:
        with self._lock:
            stream = self._stream
            self._stream = None
            self._ring = []
            self._ring_samples = 0
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        mono = indata[:, 0].copy()
        with self._lock:
            self._ring.append(mono)
            self._ring_samples += len(mono)
            max_n = int(3.0 * SAMPLE_RATE)
            while self._ring_samples > max_n and self._ring:
                dropped = self._ring.pop(0)
                self._ring_samples -= len(dropped)

    def _recent_rms(self) -> float:
        with self._lock:
            if not self._ring:
                return 0.0
            need = int(0.12 * SAMPLE_RATE)
            chunks: list[np.ndarray] = []
            got = 0
            for arr in reversed(self._ring):
                chunks.append(arr)
                got += len(arr)
                if got >= need:
                    break
        if not chunks:
            return 0.0
        data = np.concatenate(list(reversed(chunks)))[-need:]
        return float(np.sqrt(np.mean(np.square(data))))

    def _snapshot_capture(self) -> np.ndarray:
        # Keep listening briefly so "Hey Cero" finishes into the buffer
        deadline = time.monotonic() + 0.7
        while time.monotonic() < deadline and not self._stop.is_set():
            time.sleep(0.05)
        with self._lock:
            if not self._ring:
                return np.zeros(0, dtype=np.float32)
            data = np.concatenate(self._ring).astype(np.float32)
        need = int(CAPTURE_S * SAMPLE_RATE)
        return data[-need:] if len(data) > need else data

    def _check_wake(self, samples: np.ndarray) -> bool:
        try:
            raw = self.transcriber.transcribe(samples, context=WAKE_PROMPT)
            text = strip_special_tokens(raw or "").lower().strip()
            hit = is_wake_phrase(text)
            log.info("Wake check hit=%s text=%r", hit, text[:100])
            return hit
        except Exception:
            log.exception("wake transcribe failed")
            return False
