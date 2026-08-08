"""Microphone capture via sounddevice (16 kHz mono float32)."""

from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
CHANNELS = 1
BLOCKSIZE = 2048
MIN_DURATION_S = 0.4


class Recorder:
    """Toggle capture from the default input device with live snapshots."""

    def __init__(self) -> None:
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._recording = False

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    def start(self) -> None:
        with self._lock:
            if self._recording:
                return
            self._frames = []
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                blocksize=BLOCKSIZE,
                callback=self._callback,
            )
            self._stream.start()
            self._recording = True

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        with self._lock:
            if self._recording:
                self._frames.append(indata[:, 0].copy())

    def snapshot(self) -> np.ndarray:
        """Return all samples captured so far without stopping."""
        with self._lock:
            frames = list(self._frames)
        if not frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(frames).astype(np.float32)

    def stop(self) -> np.ndarray:
        """Stop capture and return the full recorded mono float32 samples."""
        with self._lock:
            self._recording = False
            stream = self._stream
            self._stream = None
            frames = self._frames
            self._frames = []
        if stream is not None:
            stream.stop()
            stream.close()
        if not frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(frames).astype(np.float32)

    @staticmethod
    def duration_seconds(samples: np.ndarray) -> float:
        return len(samples) / float(SAMPLE_RATE)

    @staticmethod
    def has_voice(samples: np.ndarray, threshold: float = 0.012) -> bool:
        """Cheap energy gate so we don't burn CPU / type junk on silence."""
        if samples.size == 0:
            return False
        return float(np.sqrt(np.mean(np.square(samples)))) >= threshold
