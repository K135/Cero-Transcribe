"""macOS permission checks + System Settings redirects for Cero-Transcribe."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

log = logging.getLogger("cerotrans.permissions")

# Modern macOS (Ventura+) System Settings deep links + legacy Preference pane URLs
_PANES: dict[str, tuple[str, ...]] = {
    "microphone": (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
        "x-apple.systempreferences:com.apple.Settings.PrivacySecurity.extension?Privacy_Microphone",
    ),
    "accessibility": (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        "x-apple.systempreferences:com.apple.Settings.PrivacySecurity.extension?Privacy_Accessibility",
    ),
    "input": (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
        "x-apple.systempreferences:com.apple.Settings.PrivacySecurity.extension?Privacy_ListenEvent",
    ),
}


@dataclass
class PermissionStatus:
    accessibility: bool
    microphone: bool | None  # None = unknown
    input_monitoring: bool | None

    @property
    def ready(self) -> bool:
        # Mic often reports unknown until first capture — don't block on it
        return bool(self.accessibility)


def check_accessibility(prompt: bool = False) -> bool:
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions
        from Foundation import NSDictionary

        opts = NSDictionary.dictionaryWithDictionary_(
            {"AXTrustedCheckOptionPrompt": bool(prompt)}
        )
        return bool(AXIsProcessTrustedWithOptions(opts))
    except Exception as exc:
        log.warning("Accessibility check failed: %s", exc)
        return False


def check_input_monitoring() -> bool | None:
    """Return True/False when detectable; None if API unavailable."""
    try:
        # macOS 10.15+
        from Quartz import CGPreflightListenEventAccess, CGRequestListenEventAccess

        ok = bool(CGPreflightListenEventAccess())
        if not ok:
            # Soft-request (may no-op on some versions)
            try:
                CGRequestListenEventAccess()
            except Exception:
                pass
            ok = bool(CGPreflightListenEventAccess())
        return ok
    except Exception as exc:
        log.info("Input Monitoring check unavailable: %s", exc)
        return None


def check_microphone() -> bool | None:
    """Best-effort mic authorization. None if API unavailable."""
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
        from AVFoundation import (
            AVAuthorizationStatusAuthorized,
            AVAuthorizationStatusNotDetermined,
        )

        status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
        if status == AVAuthorizationStatusNotDetermined:
            # Trigger system prompt asynchronously
            sem = {"done": False, "ok": False}

            def _cb(granted: bool) -> None:
                sem["ok"] = bool(granted)
                sem["done"] = True

            AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                AVMediaTypeAudio, _cb
            )
            # Don't block long — permission UI is async
            import time

            for _ in range(40):
                if sem["done"]:
                    break
                time.sleep(0.05)
            return bool(sem["ok"]) if sem["done"] else None
        return status == AVAuthorizationStatusAuthorized
    except Exception as exc:
        log.info("Microphone check unavailable: %s", exc)
        return None


def get_status(prompt: bool = False) -> PermissionStatus:
    return PermissionStatus(
        accessibility=check_accessibility(prompt=prompt),
        microphone=check_microphone(),
        input_monitoring=check_input_monitoring(),
    )


def open_pane(kind: str) -> None:
    urls = _PANES.get(kind, ())
    for url in urls:
        subprocess.run(["open", url], check=False)


def open_privacy_settings() -> None:
    """Open all privacy panes Cero-Transcribe needs."""
    for kind in ("microphone", "accessibility", "input"):
        open_pane(kind)


def ensure_accessibility(prompt: bool = True) -> bool:
    trusted = check_accessibility(prompt=prompt)
    if not trusted and prompt:
        open_pane("accessibility")
    return trusted


def ensure_all(prompt: bool = True) -> PermissionStatus:
    """Prompt + open Settings for anything missing. Returns current status."""
    status = get_status(prompt=False)

    if prompt:
        # Accessibility system dialog
        if not status.accessibility:
            status.accessibility = check_accessibility(prompt=True)
            if not status.accessibility:
                open_pane("accessibility")

        # Mic system dialog (async)
        if status.microphone is not True:
            mic = check_microphone()
            status.microphone = mic
            if mic is not True:
                open_pane("microphone")

        # Input Monitoring
        if status.input_monitoring is not True:
            im = check_input_monitoring()
            status.input_monitoring = im
            if im is not True:
                open_pane("input")

    return status


def status_summary(status: PermissionStatus) -> str:
    def mark(v: bool | None) -> str:
        if v is True:
            return "✓"
        if v is False:
            return "✗"
        return "?"

    return (
        f"Mic {mark(status.microphone)}  "
        f"Accessibility {mark(status.accessibility)}  "
        f"Input Monitoring {mark(status.input_monitoring)}"
    )
