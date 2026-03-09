"""Fuzzy task matching for the KanadeMinder conversation handler."""

from __future__ import annotations

import sqlite3
from typing import Any

from kanademinder.db import list_tasks
from kanademinder.models import Task


class _AmbiguousMatch(Exception):
    def __init__(self, candidates: list[Task]) -> None:
        self.candidates = candidates


def _fuzzy_find_task(
    conn: sqlite3.Connection,
    task_data: dict[str, Any],
) -> int | None:
    """Try to resolve a task ID from partial info (name, status, etc.).

    Used when the LLM omits the id for update/delete actions.
    Returns the matched task ID or None.
    """
    name = task_data.get("name")
    if not name:
        return None

    name_lower = name.lower().strip()
    all_tasks = list_tasks(conn)

    # Exact name match (case-insensitive)
    for t in all_tasks:
        if t.name.lower() == name_lower:
            return t.id

    # Substring match — return the best (shortest name that contains the query)
    candidates = [t for t in all_tasks if name_lower in t.name.lower()]
    if len(candidates) == 1:
        return candidates[0].id
    if len(candidates) > 1:
        raise _AmbiguousMatch(candidates)

    # Try the reverse: task name is substring of query
    candidates = [t for t in all_tasks if t.name.lower() in name_lower]
    if len(candidates) == 1:
        return candidates[0].id
    if len(candidates) > 1:
        raise _AmbiguousMatch(candidates)

    return None
