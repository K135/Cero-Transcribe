"""Whisper transcription via a warm local whisper-server (fast) with CLI fallback."""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

import numpy as np

from .config import load_vocabulary

log = logging.getLogger("cerotrans.transcriber")

MODEL_FILES = {
    "Tiny EN": "ggml-tiny.en.bin",
    "Base EN": "ggml-base.en.bin",
}

# Tiny is snappy for live dictation; Base stays in the menu for accuracy.
DEFAULT_MODEL = "Tiny EN"


def _default_models_dir() -> Path:
    env = os.environ.get("CEROTRANS_MODELS_DIR") or os.environ.get("GOTRANSCRIBE_MODELS_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "models"


def _find_bin(name: str, env_keys: tuple[str, ...]) -> str:
    for key in env_keys:
        env = os.environ.get(key)
        if env and Path(env).is_file():
            return env
    path = shutil.which(name)
    if path:
        return path
    here = Path(__file__).resolve()
    for candidate in (
        here.parents[2] / "whisper" / "bin" / name,
        Path("/usr/local/bin") / name,
        Path("/opt/homebrew/bin") / name,
    ):
        if candidate.is_file():
            return str(candidate)
    raise FileNotFoundError(
        f"{name} not found. Install with: brew install whisper-cpp"
    )


def _find_whisper_cli() -> str:
    return _find_bin(
        "whisper-cli",
        ("CEROTRANS_WHISPER_CLI", "GOTRANSCRIBE_WHISPER_CLI"),
    )


def _find_whisper_server() -> str | None:
    try:
        return _find_bin(
            "whisper-server",
            ("CEROTRANS_WHISPER_SERVER", "GOTRANSCRIBE_WHISPER_SERVER"),
        )
    except FileNotFoundError:
        return None


def _thread_count() -> str:
    n = os.cpu_count() or 4
    return str(max(4, min(8, n)))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int = 16000) -> None:
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def _multipart(fields: list[tuple[str, bytes | tuple[str, str, bytes]]]) -> tuple[bytes, str]:
    boundary = f"----gotranscribe{int(time.time() * 1000)}"
    body = bytearray()
    for name, value in fields:
        body.extend(f"--{boundary}\r\n".encode())
        if isinstance(value, tuple):
            filename, content_type, data = value
            body.extend(
                (
                    f'Content-Disposition: form-data; name="{name}"; '
                    f'filename="{filename}"\r\n'
                    f"Content-Type: {content_type}\r\n\r\n"
                ).encode()
            )
            body.extend(data)
            body.extend(b"\r\n")
        else:
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            body.extend(value)
            body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return bytes(body), f"multipart/form-data; boundary={boundary}"


class Transcriber:
    def __init__(self) -> None:
        self._cli = _find_whisper_cli()
        self._server_bin = _find_whisper_server()
        self._models_dir = _default_models_dir()
        self._model_name: str | None = None
        self._model_path: Path | None = None
        self._lock = threading.Lock()
        self._server_proc: subprocess.Popen[str] | None = None
        self._server_port: int | None = None
        self._server_log: Path | None = None

    @property
    def model_name(self) -> str | None:
        return self._model_name

    def model_path(self, name: str) -> Path:
        return self._models_dir / MODEL_FILES[name]

    def model_available(self, name: str) -> bool:
        return self.model_path(name).is_file()

    def load(self, name: str) -> None:
        if name not in MODEL_FILES:
            raise ValueError(f"Unknown model: {name}")
        path = self.model_path(name)
        if not path.is_file():
            raise FileNotFoundError(
                f"Model not found: {path}\nRun ./scripts/download_model.sh first."
            )
        with self._lock:
            self._stop_server_locked()
            self._model_name = name
            self._model_path = path
            self._start_server_locked()
        # Warm weights so the first real phrase is fast
        try:
            silence = np.zeros(int(0.4 * 16000), dtype=np.float32)
            self.transcribe(silence)
            log.info("Warmup complete for %s", name)
        except Exception:
            log.exception("Warmup failed (will still try live)")

    def close(self) -> None:
        with self._lock:
            self._stop_server_locked()

    def transcribe(self, samples: np.ndarray, context: str = "") -> str:
        with self._lock:
            model_path = self._model_path
            cli = self._cli
            port = self._server_port
            alive = self._server_alive_locked()
        if model_path is None:
            raise RuntimeError("Model not loaded")
        if samples.size == 0:
            return ""

        terms, _ = load_vocabulary()
        prompt_parts: list[str] = []
        if terms:
            prompt_parts.append(", ".join(terms[:30]))
        ctx = (context or "").strip()
        if ctx:
            prompt_parts.append(ctx[-160:])
        prompt = " ".join(prompt_parts)

        if alive and port is not None:
            try:
                return self._transcribe_server(port, samples, prompt)
            except Exception:
                log.exception("whisper-server inference failed; falling back to CLI")
                with self._lock:
                    self._stop_server_locked()
                    self._start_server_locked()

        return self._transcribe_cli(cli, model_path, samples, prompt)

    # -- server ----------------------------------------------------------

    def _server_alive_locked(self) -> bool:
        proc = self._server_proc
        return proc is not None and proc.poll() is None and self._server_port is not None

    def _start_server_locked(self) -> None:
        if self._server_bin is None or self._model_path is None:
            log.info("whisper-server unavailable — using CLI per phrase")
            return
        port = _free_port()
        support = Path.home() / "Library" / "Application Support" / "cerotrans"
        support.mkdir(parents=True, exist_ok=True)
        log_path = support / "whisper-server.log"
        self._server_log = log_path
        cmd = [
            self._server_bin,
            "-m",
            str(self._model_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "-l",
            "en",
            "-t",
            _thread_count(),
            "-nt",  # no timestamps — much faster for live phrases
        ]
        log_f = open(log_path, "ab", buffering=0)  # noqa: SIM115
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                text=True,
                env=os.environ.copy(),
            )
        except Exception:
            log_f.close()
            raise
        self._server_proc = proc
        self._server_port = port
        # Wait until HTTP answers
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                log.error("whisper-server exited early; see %s", log_path)
                self._server_proc = None
                self._server_port = None
                return
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/", timeout=0.4
                ) as resp:
                    resp.read(64)
                log.info("whisper-server ready on :%d (%s)", port, self._model_name)
                return
            except Exception:
                time.sleep(0.15)
        log.error("whisper-server failed to become ready; see %s", log_path)
        self._stop_server_locked()

    def _stop_server_locked(self) -> None:
        proc = self._server_proc
        self._server_proc = None
        self._server_port = None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _transcribe_server(self, port: int, samples: np.ndarray, prompt: str) -> str:
        with tempfile.TemporaryDirectory(prefix="gotranscribe-") as tmp:
            wav_path = Path(tmp) / "utterance.wav"
            _write_wav(wav_path, samples)
            wav_bytes = wav_path.read_bytes()
        fields: list[tuple[str, bytes | tuple[str, str, bytes]]] = [
            ("file", ("utterance.wav", "audio/wav", wav_bytes)),
            ("response_format", b"json"),
            ("temperature", b"0.0"),
            ("temperature_inc", b"0.2"),
        ]
        if prompt:
            fields.append(("prompt", prompt.encode("utf-8")))
        body, content_type = _multipart(fields)
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/inference",
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        text = self._parse_server_response(raw)
        from .textproc import strip_special_tokens

        return strip_special_tokens(text)

    @staticmethod
    def _parse_server_response(raw: str) -> str:
        raw = (raw or "").strip()
        if not raw:
            return ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        if isinstance(data, dict):
            if data.get("text"):
                return str(data["text"]).strip()
            segs = data.get("transcription") or data.get("segments") or []
            if isinstance(segs, list):
                parts = []
                for seg in segs:
                    if isinstance(seg, dict) and seg.get("text"):
                        parts.append(str(seg["text"]))
                    elif isinstance(seg, str):
                        parts.append(seg)
                return " ".join(parts).strip()
        return raw

    # -- CLI fallback ----------------------------------------------------

    def _transcribe_cli(
        self,
        cli: str,
        model_path: Path,
        samples: np.ndarray,
        prompt: str,
    ) -> str:
        with tempfile.TemporaryDirectory(prefix="gotranscribe-") as tmp:
            wav_path = Path(tmp) / "utterance.wav"
            _write_wav(wav_path, samples)
            cmd = [
                cli,
                "-m",
                str(model_path),
                "-f",
                str(wav_path),
                "-l",
                "en",
                "-t",
                _thread_count(),
                "-nt",
                "-np",
            ]
            # Do NOT pass -ng / -fa: -ng disables GPU; -fa is slow on some CPUs.
            if prompt:
                cmd.extend(["--prompt", prompt])
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                env=os.environ.copy(),
            )
            if result.returncode != 0:
                err = (result.stderr or result.stdout or "").strip()
                raise RuntimeError(f"whisper-cli failed ({result.returncode}): {err}")
            text = (result.stdout or "").strip()
            if not text and result.stderr:
                lines = [
                    ln.strip()
                    for ln in result.stderr.splitlines()
                    if ln.strip()
                    and not ln.startswith(
                        ("whisper_", "ggml_", "main:", "system_info", "load_")
                    )
                ]
                text = " ".join(lines).strip()
            from .textproc import strip_special_tokens

            return strip_special_tokens(text)
