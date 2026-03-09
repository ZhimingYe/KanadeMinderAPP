"""Generate and open a full HTML task summary report in the default browser."""

from __future__ import annotations

import webbrowser
from datetime import datetime
from pathlib import Path

from kanademinder.models import Task

_SUMMARY_PATH = Path.home() / ".kanademinder" / "summary.html"


def _priority_badge(priority: int) -> str:
    css = {5: "p5", 4: "p4", 3: "p3", 2: "p2", 1: "p1"}.get(priority, "p3")
    return f'<span class="badge {css}">P{priority}</span>'


def _deadline_cell(task: Task, now: datetime) -> str:
    if not task.deadline:
        return '<span class="muted">—</span>'
    dt = task.deadline
    if dt < now:
        delta = now - dt
        age = f"{delta.days}d" if delta.days >= 1 else f"{int(delta.total_seconds() // 3600)}h"
        return f'<span class="overdue">{dt.strftime("%Y-%m-%d %H:%M")} ({age} overdue)</span>'
    if dt.date() == now.date():
        secs_left = int((dt - now).total_seconds())
        mins_left = secs_left // 60
        remaining = f"{mins_left}min" if mins_left < 60 else f"{mins_left // 60}h {mins_left % 60}min"
        return f'<span class="due-today">{dt.strftime("%H:%M")} ({remaining} left)</span>'
    fmt = "%Y-%m-%d" if not (dt.hour or dt.minute) else "%Y-%m-%d %H:%M"
    return dt.strftime(fmt)


def _task_rows(section_tasks: list[Task], all_tasks: list[Task], now: datetime) -> str:
    by_parent: dict[int | None, list[Task]] = {}
    for t in all_tasks:
        by_parent.setdefault(t.parent_id, []).append(t)

    rows: list[str] = []
    visited: set[int] = set()

    def _visit(t: Task, depth: int) -> None:
        if t.id is not None:
            if t.id in visited:
                return
            visited.add(t.id)
        name = t.name
        if depth > 0:
            indent_px = depth * 18
            name = f'<span style="padding-left:{indent_px}px;color:#bbb">└─</span> {name}'
        if t.notes:
            name += f'<br><span class="muted">{t.notes}</span>'
        if t.recurrence:
            rec = t.recurrence + (f" until {t.recurrence_end}" if t.recurrence_end else "")
            name += f'<br><span class="muted">↻ {rec}</span>'
        est = f"~{t.estimated_minutes}min" if t.estimated_minutes else '<span class="muted">—</span>'
        row_style = ' style="background:#fafafa"' if depth > 0 else ""
        rows.append(
            f"<tr{row_style}>"
            f"<td>{_priority_badge(t.priority)}</td>"
            f"<td>{name}</td>"
            f"<td>{_deadline_cell(t, now)}</td>"
            f"<td><span class='muted'>{t.status.value}</span></td>"
            f"<td><span class='muted'>{est}</span></td>"
            f"</tr>"
        )
        if t.id is not None:
            for child in by_parent.get(t.id, []):
                _visit(child, depth + 1)

    for t in section_tasks:
        _visit(t, 0)
    return "\n".join(rows)


def _section(title: str, tasks: list[Task], all_tasks: list[Task], now: datetime, color: str) -> str:
    if not tasks:
        return ""
    rows = _task_rows(tasks, all_tasks, now)
    return f"""
<h2 style="color:{color}">{title} ({len(tasks)})</h2>
<table>
  <thead><tr><th>Pri</th><th>Task</th><th>Deadline</th><th>Status</th><th>Est.</th></tr></thead>
  <tbody>
{rows}
  </tbody>
</table>"""


def build_html_report(tasks: list[Task], suggestion: str, now: datetime) -> str:
    """Return a complete HTML page summarising all tasks and the LLM suggestion."""
    all_ids = {t.id for t in tasks if t.id is not None}
    tasks_by_id = {t.id: t for t in tasks if t.id is not None}

    def is_root(t: Task) -> bool:
        if t.parent_id is None or t.parent_id not in all_ids:
            return True
        # Follow parent chain to detect cycles; treat cycle members as roots
        seen: set[int] = set()
        if t.id is not None:
            seen.add(t.id)
        pid = t.parent_id
        while pid is not None and pid in all_ids:
            if pid in seen:
                return True
            seen.add(pid)
            parent = tasks_by_id.get(pid)
            if parent is None:
                break
            pid = parent.parent_id
        return False

    overdue = [t for t in tasks if t.deadline and t.deadline < now and is_root(t)]
    due_today = [
        t for t in tasks
        if t.deadline and t.deadline.date() == now.date() and t.deadline >= now and is_root(t)
    ]
    upcoming = [t for t in tasks if t.deadline and t.deadline.date() > now.date() and is_root(t)]
    no_deadline = [t for t in tasks if not t.deadline and is_root(t)]

    stats_parts = []
    if overdue:
        stats_parts.append(f"{len(overdue)} overdue")
    if due_today:
        stats_parts.append(f"{len(due_today)} due today")
    if upcoming:
        stats_parts.append(f"{len(upcoming)} upcoming")
    if no_deadline:
        stats_parts.append(f"{len(no_deadline)} no deadline")
    stats = " · ".join(stats_parts) if stats_parts else f"{len(tasks)} active"

    sections = (
        _section("OVERDUE", sorted(overdue, key=lambda t: t.deadline), tasks, now, "#c0392b")  # type: ignore[arg-type]
        + _section("DUE TODAY", sorted(due_today, key=lambda t: (t.deadline, -t.priority)), tasks, now, "#e67e22")
        + _section("UPCOMING", sorted(upcoming, key=lambda t: (t.deadline, -t.priority)), tasks, now, "#2980b9")
        + _section("NO DEADLINE", sorted(no_deadline, key=lambda t: -t.priority), tasks, now, "#27ae60")
    )

    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    weekday = now.strftime("%A")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>KanadeMinder \u2014 {date_str}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, sans-serif;
      max-width: 780px; margin: 2rem auto; padding: 0 1.2rem;
      color: #1a1a1a; line-height: 1.5; background: #fff;
    }}
    h1 {{ font-size: 1.5rem; color: #111; margin-bottom: 0.2rem; }}
    .meta {{ color: #888; font-size: 0.85rem; margin-bottom: 0.3rem; }}
    .stats {{ color: #555; font-size: 0.9rem; margin-bottom: 1.5rem; }}
    .suggestion {{
      background: #f0f7ff; border-left: 4px solid #0066cc;
      padding: 0.75rem 1rem; border-radius: 0 6px 6px 0; margin-bottom: 2rem;
      font-size: 1rem;
    }}
    .suggestion strong {{
      display: block; font-size: 0.72rem; text-transform: uppercase;
      letter-spacing: 0.07em; color: #0066cc; margin-bottom: 0.3rem;
    }}
    h2 {{
      font-size: 0.82rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.07em; margin: 1.8rem 0 0.5rem;
      border-bottom: 2px solid currentColor; padding-bottom: 0.3rem;
    }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    th {{
      text-align: left; padding: 0.3rem 0.5rem; color: #aaa;
      font-weight: 500; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em;
    }}
    td {{ padding: 0.42rem 0.5rem; border-bottom: 1px solid #f0f0f0; vertical-align: top; }}
    tr:last-child td {{ border-bottom: none; }}
    .overdue {{ color: #c0392b; font-weight: 600; }}
    .due-today {{ color: #e67e22; font-weight: 600; }}
    .muted {{ font-size: 0.78rem; color: #aaa; }}
    .badge {{
      display: inline-block; padding: 0.1rem 0.4rem; border-radius: 4px;
      font-size: 0.73rem; font-weight: 700; white-space: nowrap;
    }}
    .p5 {{ background: #fde8e8; color: #9b1c1c; }}
    .p4 {{ background: #fef3e0; color: #b45309; }}
    .p3 {{ background: #f3f4f6; color: #374151; }}
    .p2 {{ background: #ecfdf5; color: #065f46; }}
    .p1 {{ background: #f0fdf4; color: #166534; }}
  </style>
</head>
<body>
  <h1>KanadeMinder</h1>
  <div class="meta">Generated {time_str} on {weekday}, {date_str}</div>
  <div class="stats">{stats}</div>
  <div class="suggestion"><strong>Suggestion</strong>{suggestion}</div>
  {sections}
</body>
</html>"""


def open_html_summary(
    tasks: list[Task],
    suggestion: str,
    now: datetime,
    path: Path = _SUMMARY_PATH,
) -> Path:
    """Write the HTML report to *path* and open it in the default browser.

    Returns the path that was written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_html_report(tasks, suggestion, now), encoding="utf-8")
    webbrowser.open(path.as_uri())
    return path
