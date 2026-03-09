"""Notification body builders for the KanadeMinder daemon tick."""

from __future__ import annotations

from datetime import datetime

from kanademinder.models import Task

_MAX_BODY = 200        # macOS clips notification body beyond ~3-4 lines
_MAX_SUGGESTION = 160


def _build_overview_body(
    tasks: list[Task],
    overdue_tasks: list[Task],
    due_today_tasks: list[Task],
    now: datetime,
) -> str:
    """Compact all-tasks list for the first notification.

    Shows tasks in urgency order (overdue → due today → other by priority).
    Appends "… and N more" when the body would exceed _MAX_BODY characters.
    """
    stats_parts = []
    if overdue_tasks:
        stats_parts.append(f"{len(overdue_tasks)} overdue")
    if due_today_tasks:
        stats_parts.append(f"{len(due_today_tasks)} due today")
    rest = len(tasks) - len(overdue_tasks) - len(due_today_tasks)
    if rest:
        stats_parts.append(f"{rest} other")
    stats_line = " · ".join(stats_parts) if stats_parts else f"{len(tasks)} active"

    def _task_line(t: Task) -> str:
        if t.deadline and t.deadline < now:
            delta = now - t.deadline
            age = f"{delta.days}d" if delta.days >= 1 else f"{int(delta.total_seconds() // 3600)}h"
            return f"- {t.name} [{age} overdue]"
        if t.deadline and t.deadline.date() == now.date():
            return f"- {t.name} [due {t.deadline.strftime('%H:%M')}]"
        if t.deadline:
            return f"- {t.name} [due {t.deadline.strftime('%m/%d')}]"
        return f"- {t.name}"

    other_tasks = [t for t in tasks if t not in overdue_tasks and t not in due_today_tasks]
    ordered = (
        sorted(overdue_tasks, key=lambda t: t.deadline)  # type: ignore[arg-type]
        + sorted(due_today_tasks, key=lambda t: (t.deadline, -t.priority))
        + sorted(other_tasks, key=lambda t: -t.priority)
    )

    body = stats_line
    shown = 0
    for t in ordered:
        line = "\n" + _task_line(t)
        if len(body) + len(line) > _MAX_BODY:
            body += f"\n… and {len(ordered) - shown} more"
            break
        body += line
        shown += 1

    return body


def _most_urgent_task(
    tasks: list[Task], overdue_tasks: list[Task], due_today_tasks: list[Task]
) -> Task:
    """Return the single most urgent task for the reminder notification."""
    if overdue_tasks:
        return max(overdue_tasks, key=lambda t: (t.priority, -t.deadline.timestamp()))  # type: ignore[union-attr]
    if due_today_tasks:
        return min(due_today_tasks, key=lambda t: (t.deadline, -t.priority))
    return max(tasks, key=lambda t: t.priority)


def _build_reminder_body(task: Task, now: datetime) -> str:
    """Single-line description of the most urgent task."""
    parts = [task.name, f"P{task.priority}"]
    if task.deadline and task.deadline < now:
        delta = now - task.deadline
        age = f"{delta.days}d overdue" if delta.days >= 1 else f"{int(delta.total_seconds() // 3600)}h overdue"
        parts.append(age)
    elif task.deadline and task.deadline.date() == now.date():
        secs_left = int((task.deadline - now).total_seconds())
        mins_left = secs_left // 60
        remaining = f"{mins_left}min left" if mins_left < 60 else f"{mins_left // 60}h {mins_left % 60}min left"
        parts.append(f"due {task.deadline.strftime('%H:%M')} · {remaining}")
    elif task.deadline:
        parts.append(f"due {task.deadline.strftime('%Y-%m-%d')}")
    return " · ".join(parts)
