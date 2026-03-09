"""Scheduling LLM prompt builder for the KanadeMinder daemon."""

from __future__ import annotations

from datetime import datetime

from kanademinder.llm.prompts import _fmt_deadline
from kanademinder.models import Task


SCHEDULING_SYSTEM_PROMPT = """\
You are a productivity assistant nudging the user via a macOS push notification.

Write ONE or TWO plain-text sentences (150 characters max total) recommending the single most important task to act on right now. Be specific: use the actual task name and a brief reason.

Priority scale: P5 = highest, P1 = lowest. When tasks share the same deadline, always prefer the higher-priority task.

Rules:
- Plain text only — no markdown, no bullet points, no section headers
- Do NOT list every task; pick the ONE most urgent action
- Stay under 150 characters"""


def build_scheduling_user_message(
    tasks: list[Task], end_of_day: str, now: datetime | None = None
) -> str:
    """Build the user message for the scheduling / daemon mode."""
    if now is None:
        now = datetime.now()

    today = now.date()
    overdue = [t for t in tasks if t.deadline and t.deadline < now]
    due_today = [t for t in tasks if t.deadline and t.deadline.date() == today and t.deadline >= now]
    upcoming = [t for t in tasks if t.deadline and t.deadline.date() > today]
    no_deadline = [t for t in tasks if not t.deadline]

    lines = ["Current time: " + now.strftime("%H:%M on %A, %B %-d %Y")]
    lines.append(f"End of day: {end_of_day}")
    lines.append(
        f"Summary: {len(overdue)} overdue, {len(due_today)} due today, "
        f"{len(upcoming)} upcoming, {len(no_deadline)} without deadline"
    )
    lines.append("")

    def _task_line(task: Task) -> str:
        parts = [f"  [{task.type.value.upper()}, P{task.priority}, {task.status.value}] {task.name}"]
        if task.deadline:
            if task.deadline < now:
                delta = now - task.deadline
                days = delta.days
                hours = int(delta.total_seconds() // 3600)
                age = f"{days}d overdue" if days >= 1 else f"{hours}h overdue"
                parts.append(f"OVERDUE {age} (was due {_fmt_deadline(task.deadline)})")
            elif task.deadline.date() == today:
                secs_left = int((task.deadline - now).total_seconds())
                mins_left = secs_left // 60
                if mins_left < 60:
                    remaining = f"{mins_left}min left"
                else:
                    remaining = f"{mins_left // 60}h {mins_left % 60}min left"
                parts.append(f"DUE TODAY at {task.deadline.strftime('%H:%M')} ({remaining})")
            else:
                parts.append(f"due {_fmt_deadline(task.deadline)}")
        else:
            parts.append("no deadline")
        if task.estimated_minutes:
            parts.append(f"~{task.estimated_minutes}min estimated")
        if task.recurrence:
            rec = f"recurs {task.recurrence}"
            if task.recurrence_end:
                rec += f" until {task.recurrence_end}"
            parts.append(rec)
        if task.notes:
            parts.append(f'notes: "{task.notes}"')
        return " | ".join(parts)

    if overdue:
        lines.append(f"OVERDUE ({len(overdue)} tasks):")
        for t in sorted(overdue, key=lambda t: t.deadline):  # type: ignore[arg-type]
            lines.append(_task_line(t))
        lines.append("")

    if due_today:
        lines.append(f"DUE TODAY ({len(due_today)} tasks):")
        for t in sorted(due_today, key=lambda t: (t.deadline, -t.priority)):
            lines.append(_task_line(t))
        lines.append("")

    if upcoming:
        lines.append(f"UPCOMING ({len(upcoming)} tasks):")
        for t in sorted(upcoming, key=lambda t: (t.deadline, -t.priority)):
            lines.append(_task_line(t))
        lines.append("")

    if no_deadline:
        lines.append(f"NO DEADLINE ({len(no_deadline)} tasks):")
        for t in sorted(no_deadline, key=lambda t: -t.priority):
            lines.append(_task_line(t))
        lines.append("")

    lines.append("Give me a concise 1-2 sentence recommendation for what to focus on right now.")
    return "\n".join(lines)
