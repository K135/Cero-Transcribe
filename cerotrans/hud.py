"""Floating always-on-top HUD while dictating."""

from __future__ import annotations

import threading

try:
    from AppKit import (
        NSBackingStoreBuffered,
        NSColor,
        NSFont,
        NSMakeRect,
        NSPanel,
        NSScreen,
        NSTextField,
        NSBorderlessWindowMask,
        NSNonactivatingPanelMask,
        NSFloatingWindowLevel,
    )
    from Foundation import NSObject
    _OK = True
except Exception:  # pragma: no cover
    _OK = False


class HUD:
    """Small non-activating panel: status + mic bars."""

    def __init__(self) -> None:
        self._panel = None
        self._label = None
        self._lock = threading.Lock()
        self._visible = False

    def show(self, text: str = "Listening…") -> None:
        if not _OK:
            return
        with self._lock:
            self._ensure()
            if self._label is not None:
                self._label.setStringValue_(text)
            if self._panel is not None:
                self._panel.orderFrontRegardless()
            self._visible = True

    def update(self, text: str, level: float = 0.0) -> None:
        if not _OK or not self._visible:
            return
        bars = _level_bars(level)
        with self._lock:
            if self._label is not None:
                self._label.setStringValue_(f"{bars}  {text}")

    def hide(self) -> None:
        if not _OK:
            return
        with self._lock:
            if self._panel is not None:
                self._panel.orderOut_(None)
            self._visible = False

    def _ensure(self) -> None:
        if self._panel is not None:
            return
        screen = NSScreen.mainScreen()
        frame = screen.frame() if screen else NSMakeRect(0, 0, 1280, 800)
        width, height = 340, 44
        x = (frame.size.width - width) / 2
        y = frame.size.height - height - 56  # under menu bar
        style = NSBorderlessWindowMask | NSNonactivatingPanelMask
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, width, height),
            style,
            NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(NSFloatingWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.08, 0.88))
        panel.setHasShadow_(True)
        panel.setIgnoresMouseEvents_(True)
        panel.setCollectionBehavior_(1 << 0 | 1 << 3)  # canJoinAllSpaces | stationary-ish

        label = NSTextField.alloc().initWithFrame_(NSMakeRect(12, 8, width - 24, 28))
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setTextColor_(NSColor.whiteColor())
        label.setFont_(NSFont.systemFontOfSize_(14))
        label.setStringValue_("Listening…")
        panel.contentView().addSubview_(label)

        self._panel = panel
        self._label = label


def _level_bars(level: float) -> str:
    # Map RMS ~0..0.1+ into 8 bars
    n = int(max(0.0, min(1.0, level / 0.08)) * 8)
    filled = "▰" * n
    empty = "▱" * (8 - n)
    return filled + empty
