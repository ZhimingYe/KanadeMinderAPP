"""Settings window management for KanadeMinder GUI.

This module handles opening the settings window as a separate
pywebview window or within the main window.
"""

from __future__ import annotations

import webview

from kanademinder.gui.settings.api import SettingsAPI


# Global reference to the settings window.
# Created once and reused via show/hide — never destroyed while the app is running,
# because recreating native windows on macOS leaves ghost entries in Mission Control.
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
    """Show the settings window, creating it the first time if needed."""
    global _settings_window

    if _settings_window is None:
        api = SettingsAPI()
        html_content = _get_settings_html()

        _settings_window = webview.create_window(
            title="KanadeMinder Settings",
            html=html_content,
            js_api=api,
            width=600,
            height=700,
            min_size=(500, 500),
            resizable=True,
            text_select=True,
            hidden=True,
        )

        # Intercept the native close button (red X): hide instead of destroy.
        # Returning False from a closing handler cancels the native close in pywebview.
        def on_closing() -> bool:
            _settings_window.hide()
            return False

        _settings_window.events.closing += on_closing

    _settings_window.show()
    return _settings_window


def close_settings_window() -> None:
    """Hide the settings window if it is visible."""
    global _settings_window

    if _settings_window is not None:
        try:
            _settings_window.hide()
        except Exception:
            pass
