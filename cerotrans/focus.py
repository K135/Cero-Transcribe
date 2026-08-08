"""Track and restore the frontmost macOS app so Chrome keeps the input focus."""

from __future__ import annotations

import subprocess
import threading
import time

_IGNORE = {
    "cerotrans",
    "Cerotrans",
    "Python",
    "python",
    "python3",
    "LoginUI",
    "SystemUIServer",
    "Control Center",
    "Notification Center",
    "Window Server",
    "Spotlight",
}


class FocusTracker:
    """Remembers the last user-facing frontmost app (e.g. Google Chrome)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._app: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def current(self) -> str | None:
        with self._lock:
            return self._app

    def remember_now(self) -> str | None:
        name = _frontmost_app()
        if name and name not in _IGNORE:
            with self._lock:
                self._app = name
            return name
        return self.current()

    def restore(self) -> bool:
        name = self.current()
        if not name:
            return False
        return _activate_app(name)

    def _loop(self) -> None:
        while not self._stop.is_set():
            name = _frontmost_app()
            if name and name not in _IGNORE:
                with self._lock:
                    self._app = name
            self._stop.wait(0.4)


def _frontmost_app() -> str | None:
    try:
        r = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to get name of first application process whose frontmost is true',
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        name = (r.stdout or "").strip()
        return name or None
    except Exception:
        return None


def _activate_app(name: str) -> bool:
    try:
        r = subprocess.run(
            ["osascript", "-e", f'tell application "{name}" to activate'],
            capture_output=True,
            text=True,
            check=False,
        )
        time.sleep(0.12)
        return r.returncode == 0
    except Exception:
        return False
