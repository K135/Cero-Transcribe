"""Cero-Transcribe menu-bar dictation — live, offline, click-to-toggle."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import rumps
from AppKit import NSApp
from Foundation import NSObject
import objc

from .config import LOG_FILE, SUPPORT, VOCAB_FILE, ensure_support_dir
from .focus import FocusTracker
from .glow import EdgeGlow
from .hotkey import HOTKEY_LABEL, UNDO_LABEL, HotkeyListener
from .live_engine import LiveEngine
from . import login_item
from .permissions import ensure_all, open_privacy_settings, status_summary
from .recorder import Recorder
from . import sounds
from .transcriber import DEFAULT_MODEL, MODEL_FILES, Transcriber
from .wakeword import WakeWordWatcher

ICON_IDLE = "🎙️"
ICON_RECORDING = "🔴"
ICON_TRANSCRIBING = "⏳"

APP_NAME = "Cero-Transcribe"
START_LABEL = "▶ Start Recording"
STOP_LABEL = "⏹ Stop Recording"


def _setup_logging() -> None:
    ensure_support_dir()
    root = logging.getLogger("cerotrans")
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    fh = logging.FileHandler(LOG_FILE)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root.addHandler(fh)


log = logging.getLogger("cerotrans")


def _notify(subtitle: str, message: str) -> None:
    try:
        rumps.notification(title=APP_NAME, subtitle=subtitle, message=message, sound=False)
    except Exception:
        pass


class _StatusClickProxy(NSObject):
    """Left-click status item → toggle; right-click keeps the menu."""

    def initWithApp_(self, app):
        self = objc.super(_StatusClickProxy, self).init()
        if self is None:
            return None
        self._app = app
        return self

    def statusItemClicked_(self, sender):  # noqa: N802
        try:
            event = NSApp.currentEvent()
            from AppKit import NSEventTypeRightMouseUp, NSEventModifierFlagControl

            if event is not None:
                etype = event.type()
                mods = event.modifierFlags()
                if etype == NSEventTypeRightMouseUp or (mods & NSEventModifierFlagControl):
                    item = getattr(self._app, "_status_item", None)
                    menu = getattr(self._app, "_saved_menu", None)
                    if item is not None and menu is not None:
                        item.popUpStatusItemMenu_(menu)
                    return
        except Exception:
            pass
        self._app._on_toggle()


class CerotransApp(rumps.App):
    def __init__(self) -> None:
        super().__init__(APP_NAME, title=ICON_IDLE, quit_button=None)
        _setup_logging()

        self.recorder = Recorder()
        self.transcriber = Transcriber()
        self.focus = FocusTracker()
        self.glow = EdgeGlow()
        self._state_lock = threading.Lock()
        self._state = "idle"
        self._engine: LiveEngine | None = None
        self._level = 0.0
        self._pending_auto_stop = False
        self._pending_idle = False
        self._pending_wake_start = False
        self._pending_glow_armed = False
        self._hud_text = ""
        self._last_history = None
        self._wake: WakeWordWatcher | None = None

        # Menu
        self.action_item = rumps.MenuItem(START_LABEL, callback=self._on_action_clicked)
        self.status_item = rumps.MenuItem("Status: Idle")
        self.status_item.set_callback(None)
        self.level_item = rumps.MenuItem("Mic: ▱▱▱▱▱▱▱▱")
        self.level_item.set_callback(None)
        self.hotkey_item = rumps.MenuItem(f"Toggle: {HOTKEY_LABEL}")
        self.hotkey_item.set_callback(None)
        self.wake_item = rumps.MenuItem('Hey Cero  (say "Hey Cero")', callback=self._on_wake_toggle)
        self.wake_item.state = 1
        self.undo_item = rumps.MenuItem(f"Undo last  ({UNDO_LABEL})", callback=self._on_undo_clicked)
        self.clear_item = rumps.MenuItem("Clear Context (new email)", callback=self._on_clear_context)
        self.login_item = rumps.MenuItem("Launch at Login", callback=self._on_login_toggle)
        self.login_item.state = 1 if login_item.is_enabled() else 0
        self.vocab_item = rumps.MenuItem("Edit Vocabulary…", callback=self._on_edit_vocab)

        self.menu = [
            self.action_item,
            self.undo_item,
            None,
            self.status_item,
            self.level_item,
            self.hotkey_item,
            self.wake_item,
            None,
        ]
        self._model_items: dict[str, rumps.MenuItem] = {}
        for name in MODEL_FILES:
            item = rumps.MenuItem(name, callback=self._on_model_selected)
            item.state = 1 if name == DEFAULT_MODEL else 0
            self._model_items[name] = item
            self.menu.add(item)
        self.menu.add(None)
        self.menu.add(self.clear_item)
        self.menu.add(self.vocab_item)
        self.menu.add(self.login_item)
        self.menu.add(rumps.MenuItem("Grant Permissions…", callback=self._on_grant_permissions))
        self.menu.add(None)
        self.menu.add(rumps.MenuItem("Quit", callback=self._on_quit))

        self.hotkey = HotkeyListener(on_toggle=self._on_toggle, on_undo=self._on_undo)
        self._model_ready = threading.Event()
        self._meter_timer = rumps.Timer(self._on_meter_tick, 0.2)
        threading.Thread(target=self._load_initial_model, daemon=True).start()
        threading.Thread(target=self._first_run_and_permissions, daemon=True).start()

    # -- lifecycle -------------------------------------------------------

    def _first_run_and_permissions(self) -> None:
        """Install → permissions → use. Show a one-time welcome, then prompt TCC."""
        import time

        ensure_support_dir()
        marker = SUPPORT / "welcomed.v1"
        first = not marker.exists()
        # Let the menu bar icon appear before dialogs
        time.sleep(1.2)
        if first:
            try:
                rumps.alert(
                    title="Welcome to Cero-Transcribe",
                    message=(
                        "Fully offline voice typing for your Mac.\n\n"
                        "Next, macOS will ask for permissions:\n"
                        "  1. Microphone — hear you\n"
                        "  2. Accessibility — type into other apps\n"
                        "  3. Input Monitoring — hotkeys\n\n"
                        "Then click 🎙️ in the menu bar (or press Right Option) and speak.\n\n"
                        "You can re-open Settings anytime via:\n"
                        "🎙️ → Grant Permissions…"
                    ),
                    ok="Continue",
                )
                marker.write_text("1", encoding="utf-8")
            except Exception:
                log.exception("Welcome dialog failed")
        status = ensure_all(prompt=True)
        log.info("Permissions: %s", status_summary(status))
        if not status.ready:
            _notify(
                "Permissions needed",
                "Enable Accessibility (+ Mic & Input Monitoring). Menu → Grant Permissions…",
            )
        elif first:
            _notify(
                "Ready",
                "Click 🎙️ (or Right Option), then speak into any text field.",
            )

    def _load_initial_model(self) -> None:
        try:
            # Prefer Base EN; fall back to Tiny if missing.
            name = DEFAULT_MODEL
            if not self.transcriber.model_available(name):
                name = "Tiny EN"
            self.transcriber.load(name)
            for item_name, item in self._model_items.items():
                item.state = 1 if item_name == name else 0
            self._model_ready.set()
            log.info("Model ready: %s", name)
            # Start low-CPU Hey Cero watcher once model is ready
            self._wake = WakeWordWatcher(self.transcriber, on_wake=self._on_wake_detected)
            self._wake.start()
            # Glow only while dictating — never while idle/armed
        except Exception as exc:
            log.exception("Model load failed")
            _notify("Model missing", str(exc))

    def _on_wake_detected(self) -> None:
        log.info("Hey Cero detected")
        self._pending_wake_start = True

    def _on_wake_toggle(self, sender: rumps.MenuItem) -> None:
        enabled = not bool(sender.state)
        sender.state = 1 if enabled else 0
        if self._wake is not None:
            self._wake.set_enabled(enabled)
        if self._current_state() == "idle":
            self.glow.hide()
        _notify("Hey Cero", "On — say Hey Cero" if enabled else "Off")

    def _wire_status_click(self) -> None:
        """Left-click toggles; right-click / ctrl-click opens the menu."""
        try:
            status = getattr(getattr(self, "_nsapp", None), "nsstatusitem", None)
            if status is None:
                log.warning("Could not find NSStatusItem for click wiring")
                return
            self._status_item = status
            button = status.button()
            if button is None:
                return
            # Detach menu from left-click; we pop it up manually on right-click.
            self._saved_menu = status.menu()
            status.setMenu_(None)
            proxy = _StatusClickProxy.alloc().initWithApp_(self)
            self._click_proxy = proxy  # retain
            button.setTarget_(proxy)
            button.setAction_("statusItemClicked:")
            log.info("Status item click wired for toggle")
        except Exception:
            log.exception("Failed wiring status click")

    def run(self) -> None:
        self.focus.start()
        self.hotkey.start()
        self._meter_timer.start()
        rumps.Timer(self._deferred_wire, 0.5).start()
        try:
            super().run()
        finally:
            self.hotkey.stop()
            self.focus.stop()
            self._meter_timer.stop()
            if self._wake is not None:
                self._wake.stop()
            try:
                self.glow.hide()
            except Exception:
                pass

    def _deferred_wire(self, _timer: rumps.Timer) -> None:
        self._wire_status_click()
        try:
            _timer.stop()
        except Exception:
            pass

    # -- state -----------------------------------------------------------

    def _set_state(self, state: str) -> None:
        with self._state_lock:
            self._state = state
        if state == "idle":
            self.title = ICON_IDLE
            self.status_item.title = 'Status: Idle — say "Hey Cero" or click 🎙️'
            self.action_item.title = START_LABEL
            self.glow.hide()
        elif state == "recording":
            self.title = ICON_RECORDING
            self.status_item.title = "Status: Live — immersive glow on"
            self.action_item.title = STOP_LABEL
            self.glow.show_active()
        elif state == "transcribing":
            self.title = ICON_TRANSCRIBING
            self.status_item.title = "Status: Finishing…"
            self.action_item.title = START_LABEL
            # Keep glow visible while finishing the last phrase
            self.glow.show_active()

    def _current_state(self) -> str:
        with self._state_lock:
            return self._state

    def _on_meter_tick(self, _timer: rumps.Timer) -> None:
        try:
            self._pending_glow_armed = False

            if self._pending_wake_start:
                self._pending_wake_start = False
                if self._current_state() == "idle":
                    self._start()
                    return

            if self._pending_auto_stop:
                self._pending_auto_stop = False
                if self._current_state() == "recording":
                    self._stop()
                    return

            if self._pending_idle:
                self._pending_idle = False
                self._set_state("idle")
                if self._wake is not None:
                    self._wake.resume()

            # Animate glow on main thread
            if self._current_state() == "recording":
                self.glow.set_level(min(1.0, self._level / 0.08))
            self.glow.tick()

            if self._current_state() != "recording":
                self.level_item.title = "Mic: ▱▱▱▱▱▱▱▱"
                return
            level = self._level
            n = int(max(0.0, min(1.0, level / 0.08)) * 8)
            self.level_item.title = "Mic: " + ("▰" * n) + ("▱" * (8 - n))
            if self._hud_text:
                self.status_item.title = f"Live: {self._hud_text[:40]}"
        except Exception:
            log.exception("meter tick failed")

    # -- actions ---------------------------------------------------------

    def _on_action_clicked(self, _sender: rumps.MenuItem) -> None:
        self.focus.remember_now()
        self._on_toggle()

    def _on_toggle(self) -> None:
        state = self._current_state()
        log.info("Toggle state=%s", state)
        if state == "idle":
            self._start()
        elif state == "recording":
            self._stop()

    def _start(self) -> None:
        if not self._model_ready.is_set():
            _notify("Still loading", "Model not ready yet.")
            return
        if self._current_state() == "recording":
            return
        # Accessibility is required to paste into other apps
        from .permissions import check_accessibility, open_pane

        if not check_accessibility(prompt=True):
            open_pane("accessibility")
            _notify(
                "Accessibility required",
                "Enable Cero-Transcribe in System Settings → Privacy → Accessibility, then try again.",
            )
            return
        self.focus.remember_now()
        if self._wake is not None:
            self._wake.pause()
        try:
            self.recorder.start()
        except Exception as exc:
            log.exception("Mic failed")
            _notify("Microphone error", str(exc))
            if self._wake is not None:
                self._wake.resume()
            return

        self._pending_idle = False
        self._engine = LiveEngine(
            self.recorder,
            self.transcriber,
            on_level=self._on_level,
            on_status=self._on_engine_status,
            on_auto_stop=self._on_auto_stop,
        )
        self._set_state("recording")
        self.focus.restore()
        self._engine.start()
        sounds.play("start")
        log.info("Live session started → %s", self.focus.current())

    def _stop(self) -> None:
        if self._current_state() != "recording":
            return
        self._set_state("transcribing")
        engine = self._engine
        self._engine = None

        def finish() -> None:
            try:
                if engine is not None:
                    engine.stop(flush=True)
                    self._last_history = engine.history
                self.recorder.stop()
            except Exception:
                log.exception("stop/finish failed")
            finally:
                try:
                    sounds.play("stop")
                except Exception:
                    pass
                self._pending_idle = True
                log.info("Live session stopped")

        threading.Thread(target=finish, daemon=True).start()

    def _on_auto_stop(self) -> None:
        self._pending_auto_stop = True

    def _on_level(self, level: float) -> None:
        self._level = level

    def _on_engine_status(self, text: str) -> None:
        self._hud_text = text

    def _on_undo(self) -> None:
        from .output import delete_chars

        ok = False
        engine = self._engine
        self.focus.restore()
        if engine is not None:
            ok = engine.undo()
        elif self._last_history is not None:
            n = self._last_history.undo_last()
            if n > 0:
                ok = delete_chars(n)
        if ok:
            sounds.play("undo")
        else:
            _notify("Undo", "Nothing to undo.")

    def _on_undo_clicked(self, _sender: rumps.MenuItem) -> None:
        self._on_undo()

    def _on_clear_context(self, _sender: rumps.MenuItem) -> None:
        """Start a fresh document/email: reset history + context for clean caps."""
        engine = self._engine
        if engine is not None:
            engine.history.reset()
            engine._context = ""
        self._last_history = None
        _notify("Cero-Transcribe", "Context cleared — fresh start.")

    def _on_login_toggle(self, sender: rumps.MenuItem) -> None:
        if sender.state:
            login_item.disable()
            sender.state = 0
            _notify("Launch at Login", "Disabled.")
        else:
            if login_item.enable():
                sender.state = 1
                _notify("Launch at Login", "Cero-Transcribe will open when you log in.")
            else:
                _notify("Launch at Login", "Could not find Cero-Transcribe.app bundle.")

    def _on_edit_vocab(self, _sender: rumps.MenuItem) -> None:
        ensure_support_dir()
        os.system(f'open -e "{VOCAB_FILE}"')  # noqa: S605

    def _on_grant_permissions(self, _sender: rumps.MenuItem) -> None:
        status = ensure_all(prompt=True)
        open_privacy_settings()
        _notify("Permissions", status_summary(status))

    def _on_model_selected(self, sender: rumps.MenuItem) -> None:
        name = sender.title
        if name == self.transcriber.model_name:
            return
        if not self.transcriber.model_available(name):
            _notify("Model missing", f"{name} not downloaded.")
            return

        def switch() -> None:
            try:
                self.transcriber.load(name)
            except Exception as exc:
                _notify("Model load failed", str(exc))
                return
            for item_name, item in self._model_items.items():
                item.state = 1 if item_name == name else 0
            self._model_ready.set()
            _notify("Model", f"Switched to {name}")

        self._model_ready.clear()
        threading.Thread(target=switch, daemon=True).start()

    def _on_quit(self, _sender: rumps.MenuItem) -> None:
        if self._current_state() == "recording":
            try:
                if self._engine:
                    self._engine.stop(flush=False)
                self.recorder.stop()
            except Exception:
                pass
        if self._wake is not None:
            self._wake.stop()
        try:
            self.transcriber.close()
        except Exception:
            pass
        try:
            self.glow.hide()
        except Exception:
            pass
        self.hotkey.stop()
        self.focus.stop()
        rumps.quit_application()


def main() -> None:
    # Launcher sets CEROTRANS_* ; also publish bundle path for login item.
    for parent in Path(__file__).resolve().parents:
        if parent.name.endswith(".app"):
            os.environ.setdefault("CEROTRANS_APP_BUNDLE", str(parent))
            break
    CerotransApp().run()


if __name__ == "__main__":
    main()
