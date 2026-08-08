"""Global hotkeys: Right Option toggles dictation; Cmd+Shift+U undoes.

Also accepts Shift+F3 as a secondary toggle for keyboards without a distinct
right Option key.
"""

from __future__ import annotations

from typing import Callable

from pynput import keyboard

HOTKEY_LABEL = "Right Option (tap)"
UNDO_LABEL = "Cmd+Shift+U"


class HotkeyListener:
    def __init__(
        self,
        on_toggle: Callable[[], None],
        on_undo: Callable[[], None] | None = None,
    ) -> None:
        self._on_toggle = on_toggle
        self._on_undo = on_undo
        self._pressed: set = set()
        self._toggle_latched = False
        self._undo_latched = False
        self._listener: keyboard.Listener | None = None

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

    def _handle_press(self, key) -> None:
        # --- Right Option alone = toggle ---
        if key == keyboard.Key.alt_r:
            if not self._toggle_latched:
                self._toggle_latched = True
                self._on_toggle()
            return

        # --- Secondary: Shift+F3 ---
        if key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
            self._pressed.add("shift")
        elif key == keyboard.Key.f3:
            self._pressed.add("f3")
        elif key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r):
            self._pressed.add("cmd")
        elif key == keyboard.KeyCode.from_char("u") or (
            hasattr(key, "char") and key.char in ("u", "U")
        ):
            self._pressed.add("u")

        if (
            not self._toggle_latched
            and {"shift", "f3"}.issubset(self._pressed)
        ):
            self._toggle_latched = True
            self._on_toggle()

        # Cmd+Shift+U = undo
        if (
            self._on_undo
            and not self._undo_latched
            and {"cmd", "shift", "u"}.issubset(self._pressed)
        ):
            self._undo_latched = True
            self._on_undo()

    def _handle_release(self, key) -> None:
        if key == keyboard.Key.alt_r:
            self._toggle_latched = False
            return
        if key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
            self._pressed.discard("shift")
            self._toggle_latched = False
            self._undo_latched = False
        elif key == keyboard.Key.f3:
            self._pressed.discard("f3")
            self._toggle_latched = False
        elif key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r):
            self._pressed.discard("cmd")
            self._undo_latched = False
        elif key == keyboard.KeyCode.from_char("u") or (
            hasattr(key, "char") and key.char in ("u", "U")
        ):
            self._pressed.discard("u")
            self._undo_latched = False
