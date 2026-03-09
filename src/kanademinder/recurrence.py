"""Recurrence arithmetic: compute the next occurrence datetime for a pattern."""

from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta


def next_occurrence(current: datetime, pattern: str) -> datetime | None:
    """Return the next datetime for the given recurrence pattern.

    Returns None if the pattern is unrecognized.
    Supported patterns: "daily", "weekdays", "weekly", "monthly", "yearly".
    """
    p = pattern.lower().strip()
    if p == "daily":
        return current + timedelta(days=1)
    if p == "weekdays":
        nxt = current + timedelta(days=1)
        while nxt.weekday() >= 5:  # skip Sat(5), Sun(6)
            nxt += timedelta(days=1)
        return nxt
    if p == "weekly":
        return current + timedelta(weeks=1)
    if p == "monthly":
        # Same day next month, clamped to month end
        m = current.month % 12 + 1
        y = current.year + (1 if current.month == 12 else 0)
        d = min(current.day, monthrange(y, m)[1])
        return current.replace(year=y, month=m, day=d)
    if p == "yearly":
        return current.replace(year=current.year + 1)
    return None
