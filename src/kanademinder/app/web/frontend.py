"""Assembles the single-page frontend from separate static source files.

The three source files in ``static/`` are read once at import time and spliced
into a single HTML page.  ``get_frontend_html()`` returns the assembled page and
is the only public API — all other code stays unchanged.

Static source files
-------------------
``static/index.html``  — HTML skeleton; contains ``__STYLE__`` and ``__SCRIPT__``
                         placeholder markers
``static/style.css``   — all CSS (no ``<style>`` tags)
``static/app.js``      — all JavaScript (no ``<script>`` tags)
"""

from __future__ import annotations

from pathlib import Path

from kanademinder import __version__

_STATIC = Path(__file__).parent / "static"

_css      = (_STATIC / "style.css").read_text(encoding="utf-8")
_js       = (_STATIC / "app.js").read_text(encoding="utf-8")
_template = (_STATIC / "index.html").read_text(encoding="utf-8")

# Splice once at import time; no per-request file I/O
_PAGE = (
    _template
    .replace("__STYLE__", _css)
    .replace("__SCRIPT__", _js)
    .replace("__VERSION__", __version__)
)


def get_frontend_html() -> str:
    """Return the assembled single-page HTML frontend."""
    return _PAGE
