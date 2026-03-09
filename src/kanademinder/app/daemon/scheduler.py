"""KanadeMinder-specific notification builder — adapter for the generic daemon scheduler.

Import ``make_kanademinder_tick`` and pass the result to ``run_tick`` to wire
everything together.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from typing import Callable

from kanademinder.db import advance_recurring_task, list_tasks
from kanademinder.llm.client import LLMClient
from kanademinder.models import TaskStatus

from kanademinder.app.daemon.notifications import (
    _MAX_SUGGESTION,
    _build_overview_body,
    _build_reminder_body,
    _most_urgent_task,
)
from kanademinder.app.daemon.prompts import SCHEDULING_SYSTEM_PROMPT, build_scheduling_user_message


def build_kanademinder_notifications(
    llm: LLMClient,
    conn: sqlite3.Connection,
    *,
    end_of_day: str,
    notification_mode: str = "banner",
    now: datetime,
) -> list[tuple[str, str]] | None:
    """Build KanadeMinder task notifications for a scheduler tick.

    Returns a list of ``(title, body)`` tuples to be sent as system
    notifications, or ``None`` when there is nothing to notify about.

    Side-effect: opens the HTML summary report when ``notification_mode`` is
    ``"webpage"`` or ``"both"`` (macOS), or unconditionally on non-macOS
    platforms as a fallback.
    """
    # Auto-advance overdue recurring tasks before building the prompt
    for task in list_tasks(conn, status=TaskStatus.PENDING) + list_tasks(conn, status=TaskStatus.IN_PROGRESS):
        if task.recurrence and task.deadline and task.deadline < now:
            advance_recurring_task(conn, task)

    # Re-fetch after potential advances
    pending = list_tasks(conn, status=TaskStatus.PENDING)
    in_progress = list_tasks(conn, status=TaskStatus.IN_PROGRESS)
    tasks = pending + in_progress

    if not tasks:
        return None

    overdue_tasks = [t for t in tasks if t.deadline and t.deadline < now]
    due_today_tasks = [
        t for t in tasks
        if t.deadline and t.deadline.date() == now.date() and t.deadline >= now
    ]

    # LLM suggestion — needed for both notifications and the HTML report
    user_message = build_scheduling_user_message(tasks, end_of_day, now)
    messages = [
        {"role": "system", "content": SCHEDULING_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]
    suggestion = llm.chat(messages)
    if len(suggestion) > _MAX_SUGGESTION:
        suggestion = suggestion[:_MAX_SUGGESTION].rsplit(" ", 1)[0] + "…"

    if sys.platform == "darwin":
        if notification_mode in ("webpage", "both"):
            from kanademinder.app.daemon.html_report import open_html_summary
            open_html_summary(tasks, suggestion, now)
        if notification_mode in ("banner", "both"):
            overview = _build_overview_body(tasks, overdue_tasks, due_today_tasks, now)
            urgent = _most_urgent_task(tasks, overdue_tasks, due_today_tasks)
            return [
                ("KanadeMinder — Tasks", overview),
                ("KanadeMinder — Suggestion", suggestion),
                ("KanadeMinder — Reminder", _build_reminder_body(urgent, now)),
            ]
        else:
            # "webpage" on macOS: HTML opened above, no banners
            return None
    else:
        # Non-macOS: system notifications are unavailable; open HTML report instead
        from kanademinder.app.daemon.html_report import open_html_summary
        open_html_summary(tasks, suggestion, now)
        return None


def make_kanademinder_tick(
    llm: LLMClient,
    conn: sqlite3.Connection,
    *,
    end_of_day: str,
    notification_mode: str = "banner",
) -> Callable[[datetime], list[tuple[str, str]] | None]:
    """Return a ``build_notifications`` callback ready for ``run_tick``.

    Usage::

        from kanademinder.daemon.scheduler import run_tick
        from kanademinder.app.daemon.scheduler import make_kanademinder_tick

        run_tick(
            make_kanademinder_tick(llm, conn, end_of_day="22:00"),
            start_of_day="08:00",
            end_of_day="22:00",
        )
    """
    def _build(now: datetime) -> list[tuple[str, str]] | None:
        return build_kanademinder_notifications(
            llm, conn, end_of_day=end_of_day, notification_mode=notification_mode, now=now
        )
    return _build
