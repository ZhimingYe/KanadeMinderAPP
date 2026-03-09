"""Tests for daemon/scheduler.py (generic engine) and daemon/task_scheduler.py (KanadeMinder adapter)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from kanademinder.daemon.scheduler import (
    _in_quiet_hours,
    _is_past_end_of_day,
    run_tick,
)
from kanademinder.app.daemon.notifications import (
    _build_overview_body,
    _build_reminder_body,
    _most_urgent_task,
)
from kanademinder.app.daemon.scheduler import make_kanademinder_tick
from kanademinder.db import create_task, get_task, list_tasks, update_task
from kanademinder.models import Task, TaskStatus


def _make_llm(response: str = "Focus on your most urgent task!") -> MagicMock:
    llm = MagicMock()
    llm.chat.return_value = response
    return llm


# --- _in_quiet_hours (start=08:00, end=22:00 defaults) ---

def test_quiet_hours_active_midday():
    # 14:00 — active window, do NOT suppress
    now = datetime(2026, 3, 6, 14, 0)
    assert _in_quiet_hours("22:00", "08:00", now) is False


def test_quiet_hours_at_exact_start():
    # exactly 08:00 — active, do NOT suppress
    now = datetime(2026, 3, 6, 8, 0)
    assert _in_quiet_hours("22:00", "08:00", now) is False


def test_quiet_hours_before_start():
    # 07:30 — before morning start, suppress
    now = datetime(2026, 3, 6, 7, 30)
    assert _in_quiet_hours("22:00", "08:00", now) is True


def test_quiet_hours_at_exact_eod():
    # exactly 22:00 — suppress
    now = datetime(2026, 3, 6, 22, 0)
    assert _in_quiet_hours("22:00", "08:00", now) is True


def test_quiet_hours_late_night():
    # 23:30, past EOD — suppress
    now = datetime(2026, 3, 6, 23, 30)
    assert _in_quiet_hours("22:00", "08:00", now) is True


def test_quiet_hours_overnight_after_midnight():
    # 01:00, overnight after midnight — suppress
    now = datetime(2026, 3, 7, 1, 0)
    assert _in_quiet_hours("22:00", "08:00", now) is True


def test_quiet_hours_invalid_format():
    now = datetime(2026, 3, 6, 12, 0)
    assert _in_quiet_hours("not-a-time", "08:00", now) is False


# _is_past_end_of_day (legacy alias — same behaviour, start_of_day defaults to 08:00)

def test_past_end_of_day_evening_cutoff_past():
    now = datetime(2026, 3, 6, 23, 0)
    assert _is_past_end_of_day("22:00", now) is True


def test_past_end_of_day_evening_cutoff_before():
    now = datetime(2026, 3, 6, 21, 0)
    assert _is_past_end_of_day("22:00", now) is False


def test_past_end_of_day_invalid_format():
    now = datetime(2026, 3, 6, 12, 0)
    assert _is_past_end_of_day("not-a-time", now) is False


# --- Generic run_tick suppression (uses a mock build_notifications) ---

def test_run_tick_suppressed_when_past_eod(tmp_db):
    llm = _make_llm()
    # 01:30 is overnight (after midnight, before start_of_day 08:00) — suppress
    now = datetime(2026, 3, 6, 1, 30)
    create_task(tmp_db, Task(name="Do something"))
    build = make_kanademinder_tick(llm, tmp_db, end_of_day="22:00")
    with patch("kanademinder.daemon.scheduler.send_notification") as mock_notify:
        run_tick(build, end_of_day="22:00", now=now)
        mock_notify.assert_not_called()
    llm.chat.assert_not_called()


def test_run_tick_suppressed_when_no_tasks(tmp_db):
    llm = _make_llm()
    now = datetime(2026, 3, 6, 14, 0)
    build = make_kanademinder_tick(llm, tmp_db, end_of_day="22:00")
    with patch("kanademinder.daemon.scheduler.send_notification") as mock_notify:
        run_tick(build, end_of_day="22:00", now=now)
        mock_notify.assert_not_called()
    llm.chat.assert_not_called()


def test_run_tick_sends_three_notifications(tmp_db):
    """run_tick fires exactly 3 notifications: Tasks, Suggestion, Reminder."""
    llm = _make_llm("Focus on writing the report!")
    now = datetime(2026, 3, 6, 14, 0)
    create_task(tmp_db, Task(name="Write the report", priority=4))
    build = make_kanademinder_tick(llm, tmp_db, end_of_day="22:00")
    with patch("kanademinder.daemon.scheduler.send_notification") as mock_notify:
        run_tick(build, end_of_day="22:00", now=now)
        assert mock_notify.call_count == 3
        titles = [c[0][0] for c in mock_notify.call_args_list]
        assert titles == ["KanadeMinder — Tasks", "KanadeMinder — Suggestion", "KanadeMinder — Reminder"]


def test_run_tick_tasks_notification_content(tmp_db):
    llm = _make_llm("Focus on writing the report!")
    now = datetime(2026, 3, 6, 14, 0)
    create_task(tmp_db, Task(name="Write the report", priority=4))
    build = make_kanademinder_tick(llm, tmp_db, end_of_day="22:00")
    with patch("kanademinder.daemon.scheduler.send_notification") as mock_notify:
        run_tick(build, end_of_day="22:00", now=now)
        overview_body = mock_notify.call_args_list[0][0][1]
        assert "1 other" in overview_body  # no deadline → "other" bucket
        assert "Write the report" in overview_body


def test_run_tick_suggestion_notification_content(tmp_db):
    llm = _make_llm("Focus on writing the report!")
    now = datetime(2026, 3, 6, 14, 0)
    create_task(tmp_db, Task(name="Write the report", priority=4))
    build = make_kanademinder_tick(llm, tmp_db, end_of_day="22:00")
    with patch("kanademinder.daemon.scheduler.send_notification") as mock_notify:
        run_tick(build, end_of_day="22:00", now=now)
        suggestion_body = mock_notify.call_args_list[1][0][1]
        assert "Focus on writing the report!" in suggestion_body


def test_run_tick_reminder_notification_content(tmp_db):
    llm = _make_llm("Get it done!")
    now = datetime(2026, 3, 6, 14, 0)
    create_task(tmp_db, Task(name="Write the report", priority=4))
    build = make_kanademinder_tick(llm, tmp_db, end_of_day="22:00")
    with patch("kanademinder.daemon.scheduler.send_notification") as mock_notify:
        run_tick(build, end_of_day="22:00", now=now)
        reminder_body = mock_notify.call_args_list[2][0][1]
        assert "Write the report" in reminder_body
        assert "P4" in reminder_body


def test_run_tick_fires_with_in_progress_tasks(tmp_db):
    llm = _make_llm("Keep going!")
    now = datetime(2026, 3, 6, 10, 0)
    t = create_task(tmp_db, Task(name="In progress task"))
    update_task(tmp_db, t.id, {"status": TaskStatus.IN_PROGRESS})
    build = make_kanademinder_tick(llm, tmp_db, end_of_day="22:00")
    with patch("kanademinder.daemon.scheduler.send_notification") as mock_notify:
        run_tick(build, end_of_day="22:00", now=now)
        assert mock_notify.call_count == 3


def test_run_tick_does_not_fire_for_done_tasks_only(tmp_db):
    llm = _make_llm()
    now = datetime(2026, 3, 6, 10, 0)
    t = create_task(tmp_db, Task(name="Finished task"))
    update_task(tmp_db, t.id, {"status": TaskStatus.DONE})
    build = make_kanademinder_tick(llm, tmp_db, end_of_day="22:00")
    with patch("kanademinder.daemon.scheduler.send_notification") as mock_notify:
        run_tick(build, end_of_day="22:00", now=now)
        mock_notify.assert_not_called()


def test_run_tick_llm_receives_task_info(tmp_db):
    llm = _make_llm("Do the report!")
    now = datetime(2026, 3, 6, 14, 30)
    create_task(tmp_db, Task(name="Quarterly report", priority=5))
    build = make_kanademinder_tick(llm, tmp_db, end_of_day="22:00")
    with patch("kanademinder.daemon.scheduler.send_notification"):
        run_tick(build, end_of_day="22:00", now=now)

    assert llm.chat.called
    messages = llm.chat.call_args[0][0]
    user_msg = next(m for m in messages if m["role"] == "user")
    assert "Quarterly report" in user_msg["content"]


# --- Auto-advance overdue recurring tasks in tick ---

def test_run_tick_auto_advances_overdue_recurring_task(tmp_db):
    """An overdue recurring task gets advanced to next occurrence before the prompt."""
    # Task due yesterday, recurring daily
    overdue_dt = datetime(2026, 3, 5, 9, 0)  # yesterday
    task = create_task(tmp_db, Task(name="Daily standup", deadline=overdue_dt, recurrence="daily"))

    llm = _make_llm("Focus on standup!")
    now = datetime(2026, 3, 6, 10, 0)
    build = make_kanademinder_tick(llm, tmp_db, end_of_day="22:00")

    with patch("kanademinder.daemon.scheduler.send_notification"):
        run_tick(build, end_of_day="22:00", now=now)

    # Original task should be marked done
    original = get_task(tmp_db, task.id)
    assert original.status == TaskStatus.DONE

    # Next occurrence should exist as pending
    pending = list_tasks(tmp_db, status=TaskStatus.PENDING)
    assert len(pending) == 1
    assert pending[0].name == "Daily standup"
    assert pending[0].deadline == datetime(2026, 3, 6, 9, 0)


def test_run_tick_non_recurring_overdue_not_advanced(tmp_db):
    """A non-recurring overdue task stays pending (is included in notification)."""
    overdue_dt = datetime(2026, 3, 5, 9, 0)
    task = create_task(tmp_db, Task(name="One-off overdue", deadline=overdue_dt))

    llm = _make_llm("Get it done!")
    now = datetime(2026, 3, 6, 10, 0)
    build = make_kanademinder_tick(llm, tmp_db, end_of_day="22:00")

    with patch("kanademinder.daemon.scheduler.send_notification") as mock_notify:
        run_tick(build, end_of_day="22:00", now=now)

    # Task should still be pending
    original = get_task(tmp_db, task.id)
    assert original.status == TaskStatus.PENDING
    assert mock_notify.call_count == 3


# --- _build_overview_body ---

def test_overview_body_stats_line_overdue_and_due_today():
    now = datetime(2026, 3, 6, 14, 0)
    overdue = [Task(name="Old task", deadline=datetime(2026, 3, 5, 9, 0))]
    due_today = [Task(name="Today task", deadline=datetime(2026, 3, 6, 16, 0))]
    tasks = overdue + due_today
    body = _build_overview_body(tasks, overdue, due_today, now)
    assert "1 overdue" in body
    assert "1 due today" in body
    assert "Old task" in body
    assert "Today task" in body


def test_overview_body_stats_line_other_only():
    now = datetime(2026, 3, 6, 14, 0)
    tasks = [Task(name="No deadline task")]
    body = _build_overview_body(tasks, [], [], now)
    assert "1 other" in body
    assert "No deadline task" in body


def test_overview_body_truncates_with_many_tasks():
    now = datetime(2026, 3, 6, 14, 0)
    tasks = [Task(name=f"Task number {i:02d}") for i in range(20)]
    body = _build_overview_body(tasks, [], [], now)
    assert "… and" in body
    assert len(body) <= 220  # stays near the limit


def test_overview_body_overdue_age_days():
    now = datetime(2026, 3, 6, 14, 0)
    overdue = [Task(name="Late task", deadline=datetime(2026, 3, 4, 9, 0))]
    body = _build_overview_body(overdue, overdue, [], now)
    assert "2d overdue" in body


def test_overview_body_due_today_shows_time():
    now = datetime(2026, 3, 6, 14, 0)
    due_today = [Task(name="Meeting", deadline=datetime(2026, 3, 6, 16, 30))]
    body = _build_overview_body(due_today, [], due_today, now)
    assert "due 16:30" in body


# --- _build_reminder_body ---

def test_reminder_body_overdue_task():
    now = datetime(2026, 3, 6, 14, 0)
    task = Task(name="Write report", priority=5, deadline=datetime(2026, 3, 4, 9, 0))
    body = _build_reminder_body(task, now)
    assert "Write report" in body
    assert "P5" in body
    assert "overdue" in body


def test_reminder_body_due_today():
    now = datetime(2026, 3, 6, 14, 0)
    task = Task(name="Call dentist", priority=4, deadline=datetime(2026, 3, 6, 16, 0))
    body = _build_reminder_body(task, now)
    assert "Call dentist" in body
    assert "16:00" in body
    assert "left" in body


def test_reminder_body_no_deadline():
    now = datetime(2026, 3, 6, 14, 0)
    task = Task(name="Review slides", priority=3)
    body = _build_reminder_body(task, now)
    assert "Review slides" in body
    assert "P3" in body


# --- _most_urgent_task ---

def test_most_urgent_prefers_overdue():
    overdue = [Task(name="Overdue", priority=3, deadline=datetime(2026, 3, 5, 9, 0))]
    due_today = [Task(name="Due today", priority=5, deadline=datetime(2026, 3, 6, 15, 0))]
    tasks = overdue + due_today
    result = _most_urgent_task(tasks, overdue, due_today)
    assert result.name == "Overdue"


def test_most_urgent_due_today_soonest_deadline():
    due_today = [
        Task(name="Later", priority=5, deadline=datetime(2026, 3, 6, 17, 0)),
        Task(name="Sooner", priority=3, deadline=datetime(2026, 3, 6, 15, 0)),
    ]
    result = _most_urgent_task(due_today, [], due_today)
    assert result.name == "Sooner"


def test_most_urgent_no_deadline_highest_priority():
    tasks = [Task(name="Low", priority=2), Task(name="High", priority=5)]
    result = _most_urgent_task(tasks, [], [])
    assert result.name == "High"


# --- notification_mode tests ---

def test_banner_mode_sends_notifications_no_html(tmp_db):
    """notification_mode='banner' on macOS: banners sent, HTML not opened."""
    llm = _make_llm("Focus!")
    now = datetime(2026, 3, 6, 14, 0)
    create_task(tmp_db, Task(name="Test task"))
    build = make_kanademinder_tick(llm, tmp_db, end_of_day="22:00", notification_mode="banner")
    with patch("kanademinder.daemon.scheduler.send_notification") as mock_notify, \
         patch("sys.platform", "darwin"), \
         patch("kanademinder.app.daemon.scheduler.sys") as mock_sys:
        mock_sys.platform = "darwin"
        with patch("kanademinder.app.daemon.html_report.open_html_summary") as mock_html:
            run_tick(build, end_of_day="22:00", now=now)
            assert mock_notify.call_count == 3
            mock_html.assert_not_called()


def test_webpage_mode_opens_html_no_notifications(tmp_db):
    """notification_mode='webpage' on macOS: HTML opened, no banners."""
    llm = _make_llm("Focus!")
    now = datetime(2026, 3, 6, 14, 0)
    create_task(tmp_db, Task(name="Test task"))
    with patch("kanademinder.daemon.scheduler.send_notification") as mock_notify, \
         patch("kanademinder.app.daemon.scheduler.sys") as mock_sys, \
         patch("kanademinder.app.daemon.html_report.open") as _:
        mock_sys.platform = "darwin"
        from unittest.mock import patch as _patch
        with _patch("kanademinder.app.daemon.html_report.open_html_summary") as mock_html:
            # Re-create build so it picks up the patched sys.platform
            from kanademinder.app.daemon.scheduler import build_kanademinder_notifications
            result = build_kanademinder_notifications(
                llm, tmp_db, end_of_day="22:00", notification_mode="webpage", now=now
            )
            mock_html.assert_called_once()
            assert result is None
        mock_notify.assert_not_called()


def test_both_mode_sends_notifications_and_opens_html(tmp_db):
    """notification_mode='both' on macOS: banners sent AND HTML opened."""
    llm = _make_llm("Focus!")
    now = datetime(2026, 3, 6, 14, 0)
    create_task(tmp_db, Task(name="Test task"))
    with patch("kanademinder.daemon.scheduler.send_notification") as mock_notify, \
         patch("kanademinder.app.daemon.scheduler.sys") as mock_sys:
        mock_sys.platform = "darwin"
        with patch("kanademinder.app.daemon.html_report.open_html_summary") as mock_html:
            from kanademinder.app.daemon.scheduler import build_kanademinder_notifications
            result = build_kanademinder_notifications(
                llm, tmp_db, end_of_day="22:00", notification_mode="both", now=now
            )
            mock_html.assert_called_once()
            assert result is not None
            assert len(result) == 3
        mock_notify.assert_not_called()  # run_tick not called, but result has 3 items


def test_non_macos_always_opens_html(tmp_db):
    """On non-macOS, HTML is always opened regardless of notification_mode."""
    llm = _make_llm("Focus!")
    now = datetime(2026, 3, 6, 14, 0)
    create_task(tmp_db, Task(name="Test task"))
    with patch("kanademinder.app.daemon.scheduler.sys") as mock_sys:
        mock_sys.platform = "linux"
        with patch("kanademinder.app.daemon.html_report.open_html_summary") as mock_html:
            from kanademinder.app.daemon.scheduler import build_kanademinder_notifications
            result = build_kanademinder_notifications(
                llm, tmp_db, end_of_day="22:00", notification_mode="banner", now=now
            )
            mock_html.assert_called_once()
            assert result is None
