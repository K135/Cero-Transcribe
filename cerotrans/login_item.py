"""Launch-at-login helper via LaunchAgent."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

LABEL = "app.cerotrans.dictation"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def app_bundle_path() -> Path | None:
    # Prefer the running .app Contents parent
    exe = Path(os.environ.get("CEROTRANS_APP_BUNDLE", "")).expanduser()
    if exe.is_dir() and (exe / "Contents").is_dir():
        return exe
    # Walk up from this file when running inside Resources/project
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name.endswith(".app") and (parent / "Contents").is_dir():
            return parent
        # Resources/project/cerotrans → .app
        if parent.name == "Resources" and parent.parent.name == "Contents":
            return parent.parent.parent
    # Installed location
    installed = Path("/Applications/Cerotrans.app")
    if installed.is_dir():
        return installed
    dist = Path.home() / "Projects" / "cerotrans" / "dist" / "Cerotrans.app"
    if dist.is_dir():
        return dist
    return None


def is_enabled() -> bool:
    return PLIST.exists()


def enable() -> bool:
    bundle = app_bundle_path()
    if bundle is None:
        return False
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    # Use `open -a` so LaunchAgent starts the GUI app properly
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/open</string>
    <string>-a</string>
    <string>{bundle}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
"""
    PLIST.write_text(plist, encoding="utf-8")
    subprocess.run(["launchctl", "unload", str(PLIST)], check=False, capture_output=True)
    subprocess.run(["launchctl", "load", str(PLIST)], check=False, capture_output=True)
    return True


def disable() -> None:
    if PLIST.exists():
        subprocess.run(["launchctl", "unload", str(PLIST)], check=False, capture_output=True)
        PLIST.unlink(missing_ok=True)
