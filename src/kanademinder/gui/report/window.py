"""Report window management for KanadeMinder GUI."""

from __future__ import annotations

import webview


# Reuse a single native report window on macOS to avoid lingering task-list entries
# when windows are repeatedly destroyed and recreated.
_report_window: webview.Window | None = None


def _decorate_report_html(html_content: str) -> str:
    """Inject a lightweight print toolbar into the report HTML."""
    toolbar = """
<style>
  .km-report-toolbar {
    position: sticky;
    top: 0;
    z-index: 9999;
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
    align-items: center;
    padding: 0.45rem 1.2rem;
    background: #ffffff;
    border-bottom: 1px solid #e0e0e0;
  }
  body {
    -webkit-user-select: none;
    user-select: none;
  }
  .km-report-print-btn {
    background: none;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
    padding: 0.2rem 0.6rem;
    color: #555;
    font: inherit;
    font-size: 0.78rem;
    line-height: 1.5;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s, color 0.15s;
  }
  .km-report-print-btn:hover {
    background: #f0f0f0;
    border-color: #bbb;
    color: #111;
  }
  .km-report-toolbar-hint {
    color: #888;
    font-size: 0.78rem;
  }
  @media print {
    .km-report-toolbar {
      display: none !important;
    }
  }
</style>
<script>
  function kmPrintReport() {
    window.print();
  }
  window.addEventListener('keydown', function(event) {
    const isPrintShortcut = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'p';
    if (!isPrintShortcut) return;
    event.preventDefault();
    kmPrintReport();
  });
</script>
"""
    toolbar_html = """
<div class="km-report-toolbar">
  <span class="km-report-toolbar-hint">Cmd/Ctrl+P</span>
  <button class="km-report-print-btn" onclick="kmPrintReport()">Print</button>
</div>
"""

    decorated = html_content
    if "</head>" in decorated:
        decorated = decorated.replace("</head>", toolbar + "</head>")
    else:
        decorated = toolbar + decorated

    if "<body>" in decorated:
        decorated = decorated.replace("<body>", "<body>" + toolbar_html, 1)
    else:
        decorated = toolbar_html + decorated

    return decorated


def open_report_window(html_content: str) -> webview.Window:
    """Show the report window, creating it once and refreshing its HTML."""
    global _report_window
    decorated_html = _decorate_report_html(html_content)

    if _report_window is None:
        _report_window = webview.create_window(
            title="KanadeMinder Report",
            html=decorated_html,
            width=900,
            height=700,
            hidden=True,
        )

        def on_closing() -> bool:
            _report_window.hide()
            return False

        _report_window.events.closing += on_closing
    else:
        _report_window.load_html(decorated_html)

    _report_window.show()
    return _report_window


def close_report_window() -> None:
    """Hide the report window if it exists."""
    global _report_window

    if _report_window is not None:
        try:
            _report_window.hide()
        except Exception:
            pass
