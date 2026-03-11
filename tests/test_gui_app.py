"""Tests for GUI app HTML assembly."""

from __future__ import annotations

from kanademinder.gui.app import create_html_with_bridge


def test_create_html_with_bridge_disables_text_selection_for_gui():
    html = create_html_with_bridge()

    assert "window.isPyWebView = true" in html
    assert "-webkit-user-select: none;" in html
    assert "input, textarea, select, option" in html
