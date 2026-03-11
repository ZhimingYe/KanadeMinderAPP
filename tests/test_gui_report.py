"""Tests for GUI report window behavior."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import patch

from kanademinder.gui.api import KanadeMinderAPI
from kanademinder.gui.report import window as report_window


class _FakeEventHook:
    def __init__(self) -> None:
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class _FakeWindow:
    def __init__(self, html: str) -> None:
        self.html = html
        self.show_calls = 0
        self.hide_calls = 0
        self.load_html_calls: list[str] = []
        self.events = SimpleNamespace(closing=_FakeEventHook())

    def show(self) -> None:
        self.show_calls += 1

    def hide(self) -> None:
        self.hide_calls += 1

    def load_html(self, html: str) -> None:
        self.html = html
        self.load_html_calls.append(html)


def test_decorate_report_html_adds_print_controls():
    html = "<html><head><title>Report</title></head><body><h1>Report</h1></body></html>"

    decorated = report_window._decorate_report_html(html)

    assert "km-report-print-btn" in decorated
    assert "window.print()" in decorated
    assert "Cmd/Ctrl+P" in decorated


def test_open_report_window_reuses_single_window(monkeypatch):
    created: list[_FakeWindow] = []

    def fake_create_window(*, html: str, **kwargs):
        win = _FakeWindow(html)
        created.append(win)
        return win

    monkeypatch.setattr(report_window, "_report_window", None)
    monkeypatch.setattr(report_window.webview, "create_window", fake_create_window)

    first = report_window.open_report_window("<h1>First</h1>")
    second = report_window.open_report_window("<h1>Second</h1>")

    assert first is second
    assert len(created) == 1
    assert first.show_calls == 2
    assert "km-report-print-btn" in created[0].html
    assert len(first.load_html_calls) == 1
    assert "km-report-print-btn" in first.load_html_calls[0]


def test_report_window_close_event_hides_window(monkeypatch):
    created: list[_FakeWindow] = []

    def fake_create_window(*, html: str, **kwargs):
        win = _FakeWindow(html)
        created.append(win)
        return win

    monkeypatch.setattr(report_window, "_report_window", None)
    monkeypatch.setattr(report_window.webview, "create_window", fake_create_window)

    win = report_window.open_report_window("<h1>Report</h1>")
    handler = win.events.closing.handlers[0]

    assert handler() is False
    assert win.hide_calls == 1


def test_api_open_report_window_uses_reusable_window():
    api = object.__new__(KanadeMinderAPI)
    api._lock = threading.Lock()
    api._daemon_state = {"last_html_report": "<h1>Report</h1>"}

    with patch("kanademinder.gui.api.open_report_window") as mock_open:
        result = KanadeMinderAPI.open_report_window(api)

    assert result == {"success": True, "error": None}
    mock_open.assert_called_once_with("<h1>Report</h1>")
