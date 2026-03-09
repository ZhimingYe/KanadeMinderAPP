"""Tests for models.py."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from kanademinder.models import Task, TaskStatus, TaskType


def test_task_defaults():
    t = Task(name="Write report")
    assert t.type == TaskType.MAJOR
    assert t.status == TaskStatus.PENDING
    assert t.priority == 3
    assert t.id is None
    assert t.parent_id is None
    assert t.deadline is None
    assert t.recurrence is None
    assert t.recurrence_end is None


def test_task_priority_validation():
    with pytest.raises(ValueError):
        Task(name="Bad priority", priority=0)
    with pytest.raises(ValueError):
        Task(name="Bad priority", priority=6)


def test_task_priority_boundary():
    t1 = Task(name="Min", priority=1)
    t5 = Task(name="Max", priority=5)
    assert t1.priority == 1
    assert t5.priority == 5


def test_task_string_type_coercion():
    t = Task(name="Test", type="minor")  # type: ignore[arg-type]
    assert t.type == TaskType.MINOR


def test_task_string_status_coercion():
    t = Task(name="Test", status="in_progress")  # type: ignore[arg-type]
    assert t.status == TaskStatus.IN_PROGRESS


def test_task_string_deadline_date_only_becomes_midnight():
    t = Task(name="Test", deadline="2026-03-10")  # type: ignore[arg-type]
    assert t.deadline == datetime(2026, 3, 10, 0, 0, 0)


def test_task_string_deadline_with_time():
    t = Task(name="Test", deadline="2026-03-10T14:30")  # type: ignore[arg-type]
    assert t.deadline == datetime(2026, 3, 10, 14, 30)


def test_task_string_deadline_with_seconds():
    t = Task(name="Test", deadline="2026-03-10T14:30:00")  # type: ignore[arg-type]
    assert t.deadline == datetime(2026, 3, 10, 14, 30, 0)


def test_task_string_deadline_space_separator():
    t = Task(name="Test", deadline="2026-03-10 09:00")  # type: ignore[arg-type]
    assert t.deadline == datetime(2026, 3, 10, 9, 0)


def test_task_date_object_deadline_becomes_midnight_datetime():
    t = Task(name="Test", deadline=date(2026, 6, 1))  # type: ignore[arg-type]
    assert t.deadline == datetime(2026, 6, 1, 0, 0, 0)


def test_task_datetime_deadline_unchanged():
    dt = datetime(2026, 3, 10, 14, 30)
    t = Task(name="Test", deadline=dt)
    assert t.deadline == dt


def test_task_invalid_deadline_string_becomes_none():
    t = Task(name="Test", deadline="not-a-date")  # type: ignore[arg-type]
    assert t.deadline is None


def test_task_recurrence_field():
    t = Task(name="Standup", recurrence="daily")
    assert t.recurrence == "daily"


def test_task_recurrence_end_string_coercion():
    t = Task(name="Test", recurrence="weekly", recurrence_end="2026-12-31")  # type: ignore[arg-type]
    assert t.recurrence_end == date(2026, 12, 31)


def test_task_recurrence_end_date_object():
    d = date(2026, 12, 31)
    t = Task(name="Test", recurrence="weekly", recurrence_end=d)
    assert t.recurrence_end == d


def test_to_insert_dict_contains_expected_keys():
    t = Task(name="Buy groceries", type=TaskType.MINOR, priority=2)
    d = t.to_insert_dict()
    assert "id" not in d
    assert d["name"] == "Buy groceries"
    assert d["type"] == "minor"
    assert d["priority"] == 2
    assert d["status"] == "pending"
    assert "recurrence" in d
    assert "recurrence_end" in d


def test_to_insert_dict_deadline_iso_midnight():
    t = Task(name="Deadline task", deadline=datetime(2026, 6, 1, 0, 0, 0))
    d = t.to_insert_dict()
    assert d["deadline"] == "2026-06-01T00:00:00"


def test_to_insert_dict_deadline_iso_with_time():
    t = Task(name="Deadline task", deadline=datetime(2026, 6, 1, 14, 30))
    d = t.to_insert_dict()
    assert d["deadline"] == "2026-06-01T14:30:00"


def test_to_insert_dict_recurrence():
    t = Task(name="Standup", recurrence="weekdays", recurrence_end=date(2026, 12, 31))
    d = t.to_insert_dict()
    assert d["recurrence"] == "weekdays"
    assert d["recurrence_end"] == "2026-12-31"


def test_task_enum_values():
    assert TaskType.MAJOR.value == "major"
    assert TaskType.MINOR.value == "minor"
    assert TaskStatus.PENDING.value == "pending"
    assert TaskStatus.IN_PROGRESS.value == "in_progress"
    assert TaskStatus.DONE.value == "done"
