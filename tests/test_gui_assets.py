"""Tests for GUI static assets."""

from __future__ import annotations

from pathlib import Path


def test_settings_css_disables_selection_but_allows_inputs():
    css = (
        Path("src/kanademinder/gui/settings/static/style.css")
        .read_text(encoding="utf-8")
    )

    assert "user-select: none;" in css
    assert 'input[type="text"]' in css
    assert "user-select: text;" in css
