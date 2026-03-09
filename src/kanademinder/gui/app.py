"""KanadeMinder native GUI application using pywebview.

This module provides the entry point for running KanadeMinder as a
desktop application with a native webview window.
"""

from __future__ import annotations

import atexit
import os
import signal
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Set macOS app name before importing webview (must be done early)
if sys.platform == "darwin":
    try:
        from Foundation import NSBundle

        bundle = NSBundle.mainBundle()
        info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        if info:
            info["CFBundleName"] = "KanadeMinder"
            info["CFBundleDisplayName"] = "KanadeMinder"
    except ImportError:
        pass  # Foundation not available, will show "python3" in menu

import webview

from kanademinder.config import CONFIG_PATH, DB_PATH
from kanademinder.db import open_db
from kanademinder.gui.api import KanadeMinderAPI
from kanademinder.gui.settings.window import open_settings_window
from kanademinder.app.web.frontend import get_frontend_html


def create_html_with_bridge() -> str:
    """Create the main HTML file with pywebview bridge injected."""
    html_content = get_frontend_html()

    # Inject pywebview bridge script before closing </head> tag
    bridge_script = """
    <script>
    // pywebview bridge - detects desktop mode and provides Python API access
    window.isPyWebView = true;  // We're in pywebview mode
    window.openSettingsWindow = function() {
        if (window.pywebview && window.pywebview.api && window.pywebview.api.open_settings_window) {
            window.pywebview.api.open_settings_window();
        } else {
            console.error('Settings API not available');
        }
    };

    // Helper to wait for pywebview API to be ready
    async function waitForPyWebViewAPI() {
        let retries = 0;
        const maxRetries = 100;  // 10 seconds total

        while (retries < maxRetries) {
            // Check if pywebview is fully initialized with the call method
            if (window.pywebview &&
                window.pywebview.api &&
                typeof window.pywebview.api.call === 'function') {
                return true;
            }
            await new Promise(r => setTimeout(r, 100));
            retries++;
        }
        return false;
    }

    // Override fetch to use pywebview API when running in desktop mode
    const originalFetch = window.fetch;
    window.fetch = async function(url, options = {}) {
        if (typeof url === 'string' && url.startsWith('/api/')) {
            const method = options.method || 'GET';
            const body = options.body || null;

            // Wait for pywebview API to be fully ready
            const apiReady = await waitForPyWebViewAPI();
            if (!apiReady) {
                console.error('pywebview API not available after waiting');
                throw new Error('pywebview API not available');
            }

            try {
                const result = await window.pywebview.api.call(method, url, body);
                // Return a Response-like object
                return {
                    ok: true,
                    status: 200,
                    json: async () => result,
                    text: async () => JSON.stringify(result),
                };
            } catch (e) {
                console.error('pywebview API call failed:', e);
                throw e;
            }
        }
        // Fall back to original fetch for non-API requests
        return originalFetch.apply(this, arguments);
    };

    // Also expose a ready promise for other code to use
    window.pywebviewReady = waitForPyWebViewAPI();
    </script>
    """

    # Insert the bridge script before </head>
    if "</head>" in html_content:
        html_content = html_content.replace("</head>", bridge_script + "</head>")
    else:
        # Fallback: prepend to body
        html_content = html_content.replace("<body>", bridge_script + "<body>")

    return html_content


def run_background_daemon(api: KanadeMinderAPI, interval_minutes: int) -> None:
    """Run the background daemon tick at regular intervals."""
    while True:
        time.sleep(interval_minutes * 60)
        try:
            api.run_daemon_tick()
        except Exception as e:
            print(f"Background daemon error: {e}", file=sys.stderr)


def check_first_run() -> bool:
    """Check if this is the first run (no config or database exists)."""
    return not CONFIG_PATH.exists() or not DB_PATH.exists()


def run_gui() -> None:
    """Run the KanadeMinder GUI application."""
    # Check for config
    if not CONFIG_PATH.exists():
        print(f"Configuration not found at {CONFIG_PATH}")
        print("Please run: kanademinder config init")
        print("Then edit the config to add your LLM API key.")
        sys.exit(1)

    # Ensure database exists
    conn = open_db(DB_PATH)
    conn.close()

    # Create API instance
    api = KanadeMinderAPI()

    # Start background daemon thread
    from kanademinder.config import load_config
    cfg = load_config()
    interval = cfg.schedule.interval_minutes

    daemon_thread = threading.Thread(
        target=run_background_daemon,
        args=(api, interval),
        daemon=True,
    )
    daemon_thread.start()

    # Get HTML content with bridge injected
    html_content = create_html_with_bridge()

    # Window configuration
    window_title = "KanadeMinder"
    window_width = 1200
    window_height = 800
    min_width = 800
    min_height = 600

    # Create the webview window with API exposed via js_api
    window = webview.create_window(
        title=window_title,
        html=html_content,
        js_api=api,  # Expose the entire API object to JavaScript
        width=window_width,
        height=window_height,
        min_size=(min_width, min_height),
        text_select=True,
    )

    # Set up close handler to exit gracefully
    def on_closed():
        # Close settings window first (if open), then terminate the process.
        # os._exit(0) is used instead of sys.exit(0) because the `closed` event
        # fires from a non-main thread on macOS — sys.exit() in a non-main thread
        # only raises SystemExit in that thread, leaving webview.start() blocked.
        from kanademinder.gui.settings.window import close_settings_window
        close_settings_window()
        os._exit(0)

    window.events.closed += on_closed

    # Run the webview
    try:
        webview.start(
            debug=False,  # Set to True for developer tools
            http_server=False,  # We don't need HTTP server in desktop mode
            menu=[],  # Use default menu
        )
    except KeyboardInterrupt:
        pass  # Handle Ctrl+C gracefully


def main() -> None:
    """Entry point for the GUI application."""
    try:
        run_gui()
    except KeyboardInterrupt:
        print("\nShutting down...")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
