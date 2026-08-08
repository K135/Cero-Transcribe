"""Immersive right-edge wavy glow (replaces the Listening popup)."""

from __future__ import annotations

import math
import threading

try:
    from AppKit import (
        NSBackingStoreBuffered,
        NSBezierPath,
        NSColor,
        NSGraphicsContext,
        NSMakeRect,
        NSPanel,
        NSScreen,
        NSView,
        NSBorderlessWindowMask,
        NSNonactivatingPanelMask,
        NSFloatingWindowLevel,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorStationary,
        NSWindowCollectionBehaviorIgnoresCycle,
    )
    from Quartz import CGRectMake
    from Foundation import NSObject
    import objc

    _OK = True
except Exception:  # pragma: no cover
    _OK = False
    NSView = object  # type: ignore
    NSObject = object  # type: ignore


if _OK:

    class _GlowView(NSView):
        """Draws a teal wavy glow along the right edge."""

        def initWithFrame_(self, frame):
            self = objc.super(_GlowView, self).initWithFrame_(frame)
            if self is None:
                return None
            self.phase = 0.0
            self.level = 0.0
            self.active = False
            self.armed = False  # waiting for "Hey Cero"
            return self

        def isOpaque(self):
            return False

        def drawRect_(self, rect):
            bounds = self.bounds()
            w = float(bounds.size.width)
            h = float(bounds.size.height)
            if w <= 0 or h <= 0:
                return

            # Clear
            NSColor.clearColor().set()
            NSBezierPath.fillRect_(bounds)

            active = bool(getattr(self, "active", False))
            armed = bool(getattr(self, "armed", False))
            if not active and not armed:
                return

            phase = float(getattr(self, "phase", 0.0))
            level = max(0.0, min(1.0, float(getattr(self, "level", 0.0))))

            if active:
                base_alpha = 0.35 + 0.45 * level
                amp = 5.0 + 10.0 * level
                layers = (
                    ((0.10, 0.85, 0.75), 1.00, 14.0),  # mint
                    ((0.05, 0.55, 0.55), 0.70, 22.0),  # teal
                    ((0.02, 0.30, 0.40), 0.40, 32.0),  # deep
                )
            else:
                # Soft idle "ready for Hey Cero" breath
                breath = 0.5 + 0.5 * math.sin(phase * 0.6)
                base_alpha = 0.10 + 0.12 * breath
                amp = 3.0 + 2.0 * breath
                layers = (
                    ((0.08, 0.55, 0.55), 0.85, 12.0),
                    ((0.04, 0.35, 0.40), 0.50, 20.0),
                )

            for (r, g, b), alpha_mul, spread in layers:
                path = NSBezierPath.bezierPath()
                # Start at bottom-right outside, wave leftward
                path.moveToPoint_((w, 0))
                steps = 48
                for i in range(steps + 1):
                    y = h * (i / steps)
                    # layered sine for organic wave
                    wave = (
                        math.sin(phase * 2.2 + y * 0.018)
                        + 0.45 * math.sin(phase * 3.1 + y * 0.041)
                        + 0.25 * math.sin(phase * 1.3 + y * 0.009)
                    )
                    x = w - (spread * 0.35 + amp * (0.55 + 0.45 * wave))
                    path.lineToPoint_((x, y))
                path.lineToPoint_((w + 2, h))
                path.closePath()
                NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    r, g, b, base_alpha * alpha_mul
                ).set()
                path.fill()


class EdgeGlow:
    """Right-of-screen immersive glow controller (main-thread UI only)."""

    WIDTH = 36

    def __init__(self) -> None:
        self._panel = None
        self._view = None
        self._lock = threading.Lock()
        self._active = False
        self._armed = False
        self._level = 0.0
        self._phase = 0.0

    def show_armed(self) -> None:
        """Subtle idle glow — waiting for Hey Cero."""
        self._armed = True
        self._active = False
        self._ensure_and_apply()

    def show_active(self) -> None:
        """Strong wavy glow — dictation live."""
        self._armed = False
        self._active = True
        self._ensure_and_apply()

    def hide(self) -> None:
        self._active = False
        self._armed = False
        if not _OK:
            return
        with self._lock:
            if self._panel is not None:
                self._panel.orderOut_(None)

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, float(level)))

    def tick(self) -> None:
        """Advance animation; call from rumps.Timer (main thread)."""
        if not _OK:
            return
        if not (self._active or self._armed):
            return
        self._phase += 0.14 if self._active else 0.06
        with self._lock:
            view = self._view
            panel = self._panel
        if view is None or panel is None:
            return
        view.phase = self._phase
        view.level = self._level
        view.active = self._active
        view.armed = self._armed
        view.setNeedsDisplay_(True)
        if not panel.isVisible():
            panel.orderFrontRegardless()

    def _ensure_and_apply(self) -> None:
        if not _OK:
            return
        with self._lock:
            self._ensure()
            view = self._view
            panel = self._panel
            if view is not None:
                view.active = self._active
                view.armed = self._armed
                view.level = self._level
                view.setNeedsDisplay_(True)
            if panel is not None:
                panel.orderFrontRegardless()

    def _ensure(self) -> None:
        if self._panel is not None:
            return
        screen = NSScreen.mainScreen()
        frame = screen.frame() if screen else NSMakeRect(0, 0, 1440, 900)
        # Right edge strip (AppKit origin bottom-left)
        x = frame.origin.x + frame.size.width - self.WIDTH
        y = frame.origin.y
        h = frame.size.height
        style = NSBorderlessWindowMask | NSNonactivatingPanelMask
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, self.WIDTH, h),
            style,
            NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(NSFloatingWindowLevel + 1)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(False)
        panel.setIgnoresMouseEvents_(True)
        behavior = (
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorIgnoresCycle
        )
        panel.setCollectionBehavior_(behavior)

        view = _GlowView.alloc().initWithFrame_(NSMakeRect(0, 0, self.WIDTH, h))
        panel.setContentView_(view)
        self._panel = panel
        self._view = view
