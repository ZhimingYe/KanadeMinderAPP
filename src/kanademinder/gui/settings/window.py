"""Settings window management for KanadeMinder GUI.

This module handles opening the settings window as a separate
pywebview window or within the main window.
"""

from __future__ import annotations

import webview

from kanademinder.gui.settings.api import SettingsAPI


# Global reference to settings window to prevent garbage collection
_settings_window: webview.Window | None = None


def _get_settings_html() -> str:
    """Load and return the settings HTML content with embedded CSS and JS."""
    from pathlib import Path

    static_dir = Path(__file__).parent / "static"

    css = (static_dir / "style.css").read_text(encoding="utf-8")
    js = (static_dir / "app.js").read_text(encoding="utf-8")
    html = (static_dir / "settings.html").read_text(encoding="utf-8")

    return html.replace("__STYLE__", css).replace("__SCRIPT__", js)


def open_settings_window() -> webview.Window:
    """Open the settings window.

    Creates a new pywebview window with the settings GUI.
    Returns the window object for reference.

    If a settings window is already open, returns the existing window.
    """
    global _settings_window

    # Check if window already exists and is not destroyed
    if _settings_window is not None:
        try:
            # Try to access window property to check if it's still valid
            _ = _settings_window.title
            # Window exists, bring it to front
            _settings_window.show()
            return _settings_window
        except Exception:
            # Window was closed/destroyed
            _settings_window = None

    # Create API instance for this window
    api = SettingsAPI()

    # Get HTML content
    html_content = _get_settings_html()

    # Create the settings window
    _settings_window = webview.create_window(
        title="KanadeMinder Settings",
        html=html_content,
        js_api=api,
        width=600,
        height=700,
        min_size=(500, 500),
        resizable=True,
        text_select=True,
    )

    # Set up close handler to reset the global reference
    def on_closed():
        global _settings_window
        _settings_window = None

    _settings_window.events.closed += on_closed

    return _settings_window


def close_settings_window() -> None:
    """Close the settings window if it's open."""
    global _settings_window

    if _settings_window is not None:
        try:
            _settings_window.destroy()
        except Exception:
            pass
        _settings_window = None
