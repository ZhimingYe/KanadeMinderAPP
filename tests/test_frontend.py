"""Tests for shared web/GUI frontend assembly."""

from __future__ import annotations

from kanademinder import __version__
from kanademinder.app.web.frontend import get_frontend_html


def test_frontend_includes_version_note_in_header():
    html = get_frontend_html()

    assert "brand-lockup" in html
    assert f"v{__version__}" in html
    assert "__VERSION__" not in html
