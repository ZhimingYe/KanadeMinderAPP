"""Shared LLM prompt utilities."""

from __future__ import annotations

from datetime import datetime


def _fmt_deadline(dt: datetime) -> str:
    """Format a deadline datetime: include time only when it is not midnight."""
    if dt.hour or dt.minute:
        return dt.strftime("%Y-%m-%d %H:%M")
    return dt.strftime("%Y-%m-%d")
