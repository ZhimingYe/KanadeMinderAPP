"""Tests for daemon/html_report.py."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from kanademinder.app.daemon.html_report import build_html_report, open_html_summary
from kanademinder.models import Task, TaskStatus


NOW = datetime(2026, 3, 6, 14, 0)


def _overdue_task(**kw) -> Task:
    return Task(deadline=datetime(2026, 3, 4, 9, 0), **kw)


def _due_today_task(**kw) -> Task:
    return Task(deadline=datetime(2026, 3, 6, 16, 0), **kw)


def _upcoming_task(**kw) -> Task:
    return Task(deadline=datetime(2026, 3, 10, 9, 0), **kw)


# --- build_html_report structure ---

def test_html_report_is_valid_html():
    tasks = [Task(name="Simple task")]
    html = build_html_report(tasks, "Do the task!", NOW)
    assert "<!DOCTYPE html>" in html
    assert "<html" in html
    assert "</html>" in html


def test_html_report_contains_suggestion():
    tasks = [Task(name="Task A")]
    html = build_html_report(tasks, "Focus on Task A right now.", NOW)
    assert "Focus on Task A right now." in html


def test_html_report_contains_timestamp():
    html = build_html_report([Task(name="T")], "Do it.", NOW)
    assert "2026-03-06" in html
    assert "14:00" in html
    assert "Friday" in html


def test_html_report_overdue_section():
    tasks = [_overdue_task(name="Late report", priority=5)]
    html = build_html_report(tasks, "Do it.", NOW)
    assert "OVERDUE" in html
    assert "Late report" in html
    assert "overdue" in html


def test_html_report_due_today_section():
    tasks = [_due_today_task(name="Call dentist", priority=4)]
    html = build_html_report(tasks, "Call now.", NOW)
    assert "DUE TODAY" in html
    assert "Call dentist" in html
    assert "left" in html


def test_html_report_upcoming_section():
    tasks = [_upcoming_task(name="Prepare slides", priority=3)]
    html = build_html_report(tasks, "Plan ahead.", NOW)
    assert "UPCOMING" in html
    assert "Prepare slides" in html


def test_html_report_no_deadline_section():
    tasks = [Task(name="Someday task", priority=2)]
    html = build_html_report(tasks, "Pick one.", NOW)
    assert "NO DEADLINE" in html
    assert "Someday task" in html


def test_html_report_empty_section_omitted():
    # Only overdue tasks — DUE TODAY / UPCOMING / NO DEADLINE sections should not appear
    tasks = [_overdue_task(name="Old task", priority=3)]
    html = build_html_report(tasks, "Handle it.", NOW)
    assert "DUE TODAY" not in html
    assert "UPCOMING" not in html
    assert "NO DEADLINE" not in html


def test_html_report_stats_line_all_categories():
    tasks = [
        _overdue_task(name="Overdue", priority=5),
        _due_today_task(name="Today", priority=4),
        _upcoming_task(name="Upcoming", priority=3),
        Task(name="No deadline", priority=2),
    ]
    html = build_html_report(tasks, "Handle them.", NOW)
    assert "1 overdue" in html
    assert "1 due today" in html
    assert "1 upcoming" in html
    assert "1 no deadline" in html


def test_html_report_priority_badges():
    tasks = [Task(name="High pri", priority=5), Task(name="Low pri", priority=1)]
    html = build_html_report(tasks, "Work.", NOW)
    assert "P5" in html
    assert "P1" in html


def test_html_report_notes_included():
    tasks = [Task(name="Task with notes", notes="Remember to attach file")]
    html = build_html_report(tasks, "Do it.", NOW)
    assert "Remember to attach file" in html


def test_html_report_recurrence_included():
    tasks = [Task(name="Standup", recurrence="daily")]
    html = build_html_report(tasks, "Check in.", NOW)
    assert "daily" in html


def test_html_report_estimated_minutes():
    tasks = [Task(name="Deep work", estimated_minutes=90)]
    html = build_html_report(tasks, "Focus.", NOW)
    assert "90min" in html


# --- open_html_summary ---

def test_open_html_summary_writes_file(tmp_path):
    path = tmp_path / "summary.html"
    tasks = [Task(name="My task")]
    with patch("kanademinder.app.daemon.html_report.webbrowser.open"):
        returned = open_html_summary(tasks, "Do it.", NOW, path=path)
    assert returned == path
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "My task" in content
    assert "Do it." in content


def test_open_html_summary_calls_open(tmp_path):
    path = tmp_path / "summary.html"
    tasks = [Task(name="Task")]
    with patch("kanademinder.app.daemon.html_report.webbrowser.open") as mock_open:
        open_html_summary(tasks, "Go.", NOW, path=path)
    mock_open.assert_called_once_with(path.as_uri())


def test_open_html_summary_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "dir" / "summary.html"
    tasks = [Task(name="Task")]
    with patch("kanademinder.app.daemon.html_report.webbrowser.open"):
        open_html_summary(tasks, "Go.", NOW, path=path)
    assert path.exists()


def test_open_html_summary_overwrites_on_refresh(tmp_path):
    path = tmp_path / "summary.html"
    tasks = [Task(name="First task")]
    with patch("kanademinder.app.daemon.html_report.webbrowser.open"):
        open_html_summary(tasks, "First.", NOW, path=path)

    tasks2 = [Task(name="Second task")]
    with patch("kanademinder.app.daemon.html_report.webbrowser.open"):
        open_html_summary(tasks2, "Second.", NOW, path=path)

    content = path.read_text(encoding="utf-8")
    assert "Second task" in content
    assert "First task" not in content


# --- run_tick integration ---

def test_run_tick_opens_html_when_enabled(tmp_db):
    from datetime import datetime
    from unittest.mock import MagicMock, patch
    from kanademinder.daemon.scheduler import run_tick
    from kanademinder.app.daemon.scheduler import make_kanademinder_tick
    from kanademinder.db import create_task

    llm = MagicMock()
    llm.chat.return_value = "Do the task!"
    now = datetime(2026, 3, 6, 14, 0)
    create_task(tmp_db, Task(name="HTML test task"))

    build = make_kanademinder_tick(llm, tmp_db, end_of_day="22:00", notification_mode="both")
    with patch("kanademinder.daemon.scheduler.send_notification"):
        with patch("kanademinder.app.daemon.html_report.open_html_summary") as mock_html:
            run_tick(build, end_of_day="22:00", now=now)
            mock_html.assert_called_once()
            call_tasks, call_suggestion, call_now = mock_html.call_args[0]
            assert any(t.name == "HTML test task" for t in call_tasks)
            assert call_suggestion == "Do the task!"


def test_run_tick_skips_html_by_default(tmp_db):
    from datetime import datetime
    from unittest.mock import MagicMock, patch
    from kanademinder.daemon.scheduler import run_tick
    from kanademinder.app.daemon.scheduler import make_kanademinder_tick
    from kanademinder.db import create_task

    llm = MagicMock()
    llm.chat.return_value = "Focus!"
    now = datetime(2026, 3, 6, 14, 0)
    create_task(tmp_db, Task(name="A task"))

    # end_of_day="02:00" with now=14:00 → quiet hours → tick suppressed → HTML not opened
    build = make_kanademinder_tick(llm, tmp_db, end_of_day="02:00")
    with patch("kanademinder.daemon.scheduler.send_notification"):
        with patch("kanademinder.app.daemon.html_report.open_html_summary") as mock_html:
            run_tick(build, end_of_day="02:00", now=now)
            mock_html.assert_not_called()
