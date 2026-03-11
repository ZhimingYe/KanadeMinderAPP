"""Tests for GUI native window lifecycle helpers."""

from __future__ import annotations

from types import SimpleNamespace

from kanademinder.gui.report import window as report_window
from kanademinder.gui.settings import window as settings_window


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


def test_settings_window_reuses_single_native_window(monkeypatch):
    created: list[_FakeWindow] = []

    def fake_create_window(*, html: str, **kwargs):
        win = _FakeWindow(html)
        created.append(win)
        return win

    monkeypatch.setattr(settings_window, "_settings_window", None)
    monkeypatch.setattr(settings_window, "_get_settings_html", lambda: "<h1>Settings</h1>")
    monkeypatch.setattr(settings_window.webview, "create_window", fake_create_window)

    first = settings_window.open_settings_window()
    second = settings_window.open_settings_window()

    assert first is second
    assert len(created) == 1
    assert first.show_calls == 2


def test_settings_window_native_close_hides_instead_of_destroy(monkeypatch):
    created: list[_FakeWindow] = []

    def fake_create_window(*, html: str, **kwargs):
        win = _FakeWindow(html)
        created.append(win)
        return win

    monkeypatch.setattr(settings_window, "_settings_window", None)
    monkeypatch.setattr(settings_window, "_get_settings_html", lambda: "<h1>Settings</h1>")
    monkeypatch.setattr(settings_window.webview, "create_window", fake_create_window)

    win = settings_window.open_settings_window()
    handler = win.events.closing.handlers[0]

    assert handler() is False
    assert win.hide_calls == 1


def test_report_window_reuses_single_native_window(monkeypatch):
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
    assert len(first.load_html_calls) == 1
    assert "km-report-print-btn" in first.load_html_calls[0]
    assert "<h1>Second</h1>" in first.load_html_calls[0]


def test_report_window_native_close_hides_instead_of_destroy(monkeypatch):
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
