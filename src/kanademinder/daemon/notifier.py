"""macOS notification via osascript."""

from __future__ import annotations

import subprocess


class NotificationError(Exception):
    """Raised when the osascript notification fails."""


def _escape_for_applescript(text: str) -> str:
    """Escape backslashes and double-quotes for embedding in an AppleScript string."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def send_notification(title: str, body: str, subtitle: str | None = None) -> None:
    """Fire a macOS notification using osascript.

    subtitle is shown beneath the title in the notification banner (optional).
    Raises NotificationError if osascript returns a non-zero exit code.
    """
    safe_title = _escape_for_applescript(title)
    safe_body = _escape_for_applescript(body)
    if subtitle:
        safe_subtitle = _escape_for_applescript(subtitle)
        script = (
            f'display notification "{safe_body}" with title "{safe_title}"'
            f' subtitle "{safe_subtitle}"'
        )
    else:
        script = f'display notification "{safe_body}" with title "{safe_title}"'
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise NotificationError(
            f"osascript failed (exit {result.returncode}): {result.stderr.strip()}"
        )
