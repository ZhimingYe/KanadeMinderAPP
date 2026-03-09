"""launchd plist generation and launchctl management."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PLIST_LABEL = "com.kanademinder.daemon"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"


def _find_executable() -> tuple[str, ...]:
    """Return the ProgramArguments entries to invoke 'kanademinder daemon'.

    Preference order:
    1. kanademinder script in the same bin/ dir as the running Python interpreter
       (covers 'uv sync' / editable installs where the venv is not on PATH)
    2. kanademinder found anywhere on PATH
    3. Fallback: run the package via 'python -m kanademinder'
    """
    venv_script = Path(sys.executable).parent / "kanademinder"
    if venv_script.exists():
        return (str(venv_script),)

    on_path = shutil.which("kanademinder")
    if on_path:
        return (on_path,)

    return (sys.executable, "-m", "kanademinder")


def _build_plist(interval_minutes: int) -> str:
    """Generate the launchd plist XML string."""
    program_args = _find_executable()
    interval_seconds = interval_minutes * 60

    program_arg_strings = "\n".join(f"        <string>{a}</string>" for a in program_args)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{program_arg_strings}
        <string>daemon</string>
    </array>
    <key>StartInterval</key>
    <integer>{interval_seconds}</integer>
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{Path.home()}/.kanademinder/daemon.log</string>
    <key>StandardErrorPath</key>
    <string>{Path.home()}/.kanademinder/daemon-error.log</string>
</dict>
</plist>
"""


class LaunchdError(Exception):
    """Raised when a launchctl command fails."""


def is_installed() -> bool:
    """Return True if the launchd plist is present on disk."""
    return PLIST_PATH.exists()


def install_daemon(interval_minutes: int = 30) -> None:
    """Write the plist and load it with launchctl."""
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    plist_content = _build_plist(interval_minutes)
    PLIST_PATH.write_text(plist_content, encoding="utf-8")

    result = subprocess.run(
        ["launchctl", "load", str(PLIST_PATH)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise LaunchdError(f"launchctl load failed: {result.stderr.strip()}")


def uninstall_daemon() -> None:
    """Unload and remove the plist."""
    if PLIST_PATH.exists():
        result = subprocess.run(
            ["launchctl", "unload", str(PLIST_PATH)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise LaunchdError(f"launchctl unload failed: {result.stderr.strip()}")
        PLIST_PATH.unlink()
    else:
        raise LaunchdError(f"Plist not found at {PLIST_PATH}")
