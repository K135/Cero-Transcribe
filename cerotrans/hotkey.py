"""Global hotkeys for Cero-Transcribe — configurable toggle + undo."""

from __future__ import annotations

import threading
from typing import Callable

from pynput import keyboard

# Built-in presets shown in the menu
PRESET_SHORTCUTS: dict[str, str] = {
    "Right Option": "alt_r",
    "Left Option": "alt_l",
    "Shift+F3": "shift+f3",
    "F5": "f5",
    "F6": "f6",
    "Ctrl+Space": "ctrl+space",
    "Cmd+Shift+Space": "cmd+shift+space",
    "Cmd+Shift+D": "cmd+shift+d",
}

DEFAULT_TOGGLE = "alt_r"
DEFAULT_UNDO = "cmd+shift+u"
UNDO_LABEL = "Cmd+Shift+U"


def shortcut_label(spec: str) -> str:
    """Human label for a shortcut spec."""
    s = (spec or "").strip().lower()
    for name, val in PRESET_SHORTCUTS.items():
        if val == s:
            return name
    parts = s.split("+")
    pretty = []
    for p in parts:
        pretty.append(
            {
                "cmd": "Cmd",
                "ctrl": "Ctrl",
                "alt": "Option",
                "alt_l": "Left Option",
                "alt_r": "Right Option",
                "shift": "Shift",
                "space": "Space",
                "f3": "F3",
                "f4": "F4",
                "f5": "F5",
                "f6": "F6",
                "f7": "F7",
                "f8": "F8",
            }.get(p, p.upper() if len(p) == 1 else p.title())
        )
    return "+".join(pretty) if pretty else "Not set"


def _norm_key(key) -> str | None:
    if key == keyboard.Key.alt_r:
        return "alt_r"
    if key == keyboard.Key.alt_l:
        return "alt_l"
    if key in (keyboard.Key.alt,):
        return "alt"
    if key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
        return "shift"
    if key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r):
        return "cmd"
    if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
        return "ctrl"
    if key == keyboard.Key.space:
        return "space"
    if key == keyboard.Key.esc:
        return "esc"
    for i in range(1, 13):
        if key == getattr(keyboard.Key, f"f{i}", None):
            return f"f{i}"
    if isinstance(key, keyboard.KeyCode):
        if key.char:
            return key.char.lower()
        # macOS often reports Option+letter with no char; use vk if needed
        if key.vk is not None and 0 <= key.vk <= 127:
            try:
                import string

                # Best-effort for letter keys via vk is platform-specific; skip
            except Exception:
                pass
    return None


def combo_from_pressed(pressed: set[str]) -> str | None:
    """Build a stable shortcut string from currently held normalized keys."""
    if not pressed:
        return None
    if pressed == {"esc"}:
        return "esc"
    mods = []
    for m in ("ctrl", "alt", "alt_l", "alt_r", "shift", "cmd"):
        if m in pressed:
            mods.append(m)
    mains = sorted(k for k in pressed if k not in {"ctrl", "alt", "alt_l", "alt_r", "shift", "cmd"})
    # Bare modifier as toggle (Right Option alone)
    if not mains and len(mods) == 1 and mods[0] in ("alt_r", "alt_l", "alt"):
        return mods[0]
    if not mains:
        return None
    return "+".join(mods + [mains[0]])


def parse_shortcut(spec: str) -> set[str]:
    return {p for p in (spec or "").lower().split("+") if p}


class HotkeyListener:
    def __init__(
        self,
        on_toggle: Callable[[], None],
        on_undo: Callable[[], None] | None = None,
        *,
        toggle_shortcut: str = DEFAULT_TOGGLE,
        undo_shortcut: str = DEFAULT_UNDO,
    ) -> None:
        self._on_toggle = on_toggle
        self._on_undo = on_undo
        self._toggle_spec = (toggle_shortcut or DEFAULT_TOGGLE).lower()
        self._undo_spec = (undo_shortcut or DEFAULT_UNDO).lower()
        self._pressed: set[str] = set()
        self._toggle_latched = False
        self._undo_latched = False
        self._listener: keyboard.Listener | None = None
        self._lock = threading.Lock()

    @property
    def toggle_shortcut(self) -> str:
        return self._toggle_spec

    @property
    def toggle_label(self) -> str:
        return shortcut_label(self._toggle_spec)

    def set_toggle_shortcut(self, spec: str) -> None:
        with self._lock:
            self._toggle_spec = (spec or DEFAULT_TOGGLE).lower()
            self._toggle_latched = False
            self._pressed.clear()

    def start(self) -> None:
        self._listener = keyboard.Listener(
            on_press=self._handle_press,
            on_release=self._handle_release,
        )
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def _matches(self, spec: str) -> bool:
        need = parse_shortcut(spec)
        if not need:
            return False
        # Exact match of required keys (all must be pressed; extras ok for mods? keep exact)
        # Allow extras only if they're not conflicting — require need ⊆ pressed
        return need.issubset(self._pressed)

    def _handle_press(self, key) -> None:
        nk = _norm_key(key)
        if nk is None:
            return
        self._pressed.add(nk)

        with self._lock:
            toggle_spec = self._toggle_spec
            undo_spec = self._undo_spec

        # Toggle
        if not self._toggle_latched and self._matches(toggle_spec):
            self._toggle_latched = True
            self._on_toggle()
            return

        # Undo
        if (
            self._on_undo
            and not self._undo_latched
            and self._matches(undo_spec)
        ):
            self._undo_latched = True
            self._on_undo()

    def _handle_release(self, key) -> None:
        nk = _norm_key(key)
        if nk is None:
            return
        self._pressed.discard(nk)
        need_t = parse_shortcut(self._toggle_spec)
        need_u = parse_shortcut(self._undo_spec)
        if nk in need_t or not need_t.issubset(self._pressed):
            self._toggle_latched = False
        if nk in need_u or not need_u.issubset(self._pressed):
            self._undo_latched = False


def capture_shortcut(timeout_s: float = 8.0) -> str | None:
    """Block briefly and return the next pressed shortcut, or None if Esc/timeout."""
    result: dict[str, str | None] = {"spec": None}
    done = threading.Event()
    pressed: set[str] = set()

    def on_press(key) -> None:
        nk = _norm_key(key)
        if nk is None:
            return
        if nk == "esc":
            result["spec"] = None
            done.set()
            return False  # stop listener
        pressed.add(nk)
        # Fire when we have a main key, or a lone Option key
        combo = combo_from_pressed(pressed)
        if combo and (
            any(k not in {"ctrl", "alt", "alt_l", "alt_r", "shift", "cmd"} for k in pressed)
            or combo in ("alt_r", "alt_l", "alt")
        ):
            # For combos with modifiers, wait until a non-modifier arrives
            if combo in ("alt_r", "alt_l", "alt") or "+" in combo or len(parse_shortcut(combo)) == 1:
                result["spec"] = combo
                done.set()
                return False

    def on_release(key) -> None:
        nk = _norm_key(key)
        if nk:
            pressed.discard(nk)

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.daemon = True
    listener.start()
    done.wait(timeout=timeout_s)
    try:
        listener.stop()
    except Exception:
        pass
    return result["spec"]
