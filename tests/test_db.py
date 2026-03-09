"""Tests for db.py CRUD operations."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from kanademinder.db import (
    advance_recurring_task,
    create_task,
    delete_task,
    get_task,
    init_db,
    list_tasks,
    mark_subtasks_done,
    open_db,
    sanitize_recurring_tasks,
    update_task,
)
from kanademinder.models import Task, TaskStatus, TaskType


def _make_task(**kwargs) -> Task:
    defaults = dict(name="Test task", priority=3)
    defaults.update(kwargs)
    return Task(**defaults)


def test_create_task_assigns_id(tmp_db):
    task = create_task(tmp_db, _make_task())
    assert task.id is not None
    assert task.id > 0


def test_get_task_roundtrip(tmp_db):
    original = create_task(tmp_db, _make_task(name="Roundtrip task", priority=4))
    fetched = get_task(tmp_db, original.id)
    assert fetched is not None
    assert fetched.name == "Roundtrip task"
    assert fetched.priority == 4


def test_get_task_not_found(tmp_db):
    assert get_task(tmp_db, 99999) is None


def test_create_task_with_datetime_deadline(tmp_db):
    dt = datetime(2026, 6, 1, 14, 30)
    task = create_task(tmp_db, _make_task(name="Deadline task", deadline=dt))
    fetched = get_task(tmp_db, task.id)
    assert fetched.deadline == dt


def test_create_task_with_date_deadline_becomes_midnight(tmp_db):
    task = create_task(tmp_db, _make_task(name="Deadline task", deadline=date(2026, 6, 1)))
    fetched = get_task(tmp_db, task.id)
    assert fetched.deadline == datetime(2026, 6, 1, 0, 0, 0)


def test_create_task_with_recurrence(tmp_db):
    task = create_task(tmp_db, _make_task(
        name="Daily standup",
        recurrence="daily",
        recurrence_end=date(2026, 12, 31),
    ))
    fetched = get_task(tmp_db, task.id)
    assert fetched.recurrence == "daily"
    assert fetched.recurrence_end == date(2026, 12, 31)


def test_update_task_name(tmp_db):
    task = create_task(tmp_db, _make_task(name="Old name"))
    updated = update_task(tmp_db, task.id, {"name": "New name"})
    assert updated.name == "New name"


def test_update_task_status(tmp_db):
    task = create_task(tmp_db, _make_task())
    updated = update_task(tmp_db, task.id, {"status": TaskStatus.DONE})
    assert updated.status == TaskStatus.DONE


def test_update_task_not_found(tmp_db):
    result = update_task(tmp_db, 99999, {"name": "Ghost"})
    assert result is None


def test_delete_task(tmp_db):
    task = create_task(tmp_db, _make_task())
    assert delete_task(tmp_db, task.id) is True
    assert get_task(tmp_db, task.id) is None


def test_delete_task_not_found(tmp_db):
    assert delete_task(tmp_db, 99999) is False


def test_delete_task_cascades_to_children(tmp_db):
    parent = create_task(tmp_db, _make_task(name="Parent"))
    child1 = create_task(tmp_db, _make_task(name="Child 1", parent_id=parent.id))
    child2 = create_task(tmp_db, _make_task(name="Child 2", parent_id=parent.id))
    grandchild = create_task(tmp_db, _make_task(name="Grandchild", parent_id=child1.id))

    delete_task(tmp_db, parent.id)

    assert get_task(tmp_db, parent.id) is None
    assert get_task(tmp_db, child1.id) is None
    assert get_task(tmp_db, child2.id) is None
    assert get_task(tmp_db, grandchild.id) is None


def test_delete_task_leaves_sibling_intact(tmp_db):
    parent = create_task(tmp_db, _make_task(name="Parent"))
    child1 = create_task(tmp_db, _make_task(name="Child 1", parent_id=parent.id))
    child2 = create_task(tmp_db, _make_task(name="Child 2", parent_id=parent.id))

    delete_task(tmp_db, child1.id)

    assert get_task(tmp_db, child1.id) is None
    assert get_task(tmp_db, child2.id) is not None
    assert get_task(tmp_db, parent.id) is not None


def test_list_tasks_empty(tmp_db):
    assert list_tasks(tmp_db) == []


def test_list_tasks_returns_all(tmp_db):
    for i in range(3):
        create_task(tmp_db, _make_task(name=f"Task {i}"))
    tasks = list_tasks(tmp_db)
    assert len(tasks) == 3


def test_list_tasks_filter_status(tmp_db):
    t1 = create_task(tmp_db, _make_task(name="Pending"))
    t2 = create_task(tmp_db, _make_task(name="Done"))
    update_task(tmp_db, t2.id, {"status": TaskStatus.DONE})

    pending = list_tasks(tmp_db, status=TaskStatus.PENDING)
    assert len(pending) == 1
    assert pending[0].name == "Pending"

    done = list_tasks(tmp_db, status=TaskStatus.DONE)
    assert len(done) == 1
    assert done[0].name == "Done"


def test_list_tasks_filter_type(tmp_db):
    create_task(tmp_db, _make_task(name="Major task", type=TaskType.MAJOR))
    create_task(tmp_db, _make_task(name="Minor task", type=TaskType.MINOR))

    majors = list_tasks(tmp_db, task_type=TaskType.MAJOR)
    assert all(t.type == TaskType.MAJOR for t in majors)

    minors = list_tasks(tmp_db, task_type=TaskType.MINOR)
    assert all(t.type == TaskType.MINOR for t in minors)


def test_list_tasks_sorted_by_priority_desc(tmp_db):
    create_task(tmp_db, _make_task(name="Low", priority=1))
    create_task(tmp_db, _make_task(name="High", priority=5))
    create_task(tmp_db, _make_task(name="Mid", priority=3))

    tasks = list_tasks(tmp_db)
    priorities = [t.priority for t in tasks]
    assert priorities == sorted(priorities, reverse=True)


def test_multiple_tasks_unique_ids(tmp_db):
    t1 = create_task(tmp_db, _make_task(name="T1"))
    t2 = create_task(tmp_db, _make_task(name="T2"))
    assert t1.id != t2.id


# --- advance_recurring_task ---

def test_advance_recurring_task_creates_next(tmp_db):
    dt = datetime(2026, 3, 6, 9, 0)
    task = create_task(tmp_db, _make_task(name="Standup", deadline=dt, recurrence="daily"))
    next_task = advance_recurring_task(tmp_db, task)

    assert next_task is not None
    assert next_task.id != task.id
    assert next_task.name == "Standup"
    assert next_task.deadline == datetime(2026, 3, 7, 9, 0)
    assert next_task.status == TaskStatus.PENDING
    assert next_task.recurrence == "daily"


def test_advance_recurring_task_marks_original_done(tmp_db):
    dt = datetime(2026, 3, 6, 9, 0)
    task = create_task(tmp_db, _make_task(name="Standup", deadline=dt, recurrence="daily"))
    advance_recurring_task(tmp_db, task)

    original = get_task(tmp_db, task.id)
    assert original.status == TaskStatus.DONE


def test_advance_recurring_task_respects_recurrence_end(tmp_db):
    dt = datetime(2026, 3, 6, 9, 0)
    task = create_task(tmp_db, _make_task(
        name="Standup",
        deadline=dt,
        recurrence="daily",
        recurrence_end=date(2026, 3, 6),  # ends today
    ))
    next_task = advance_recurring_task(tmp_db, task)
    # Next would be 2026-03-07, which is after end date → no next task
    assert next_task is None


def test_advance_recurring_task_recurrence_within_end(tmp_db):
    dt = datetime(2026, 3, 6, 9, 0)
    task = create_task(tmp_db, _make_task(
        name="Standup",
        deadline=dt,
        recurrence="daily",
        recurrence_end=date(2026, 3, 31),
    ))
    next_task = advance_recurring_task(tmp_db, task)
    assert next_task is not None
    assert next_task.deadline == datetime(2026, 3, 7, 9, 0)


def test_advance_recurring_task_no_deadline_returns_none(tmp_db):
    task = create_task(tmp_db, _make_task(name="Standup", recurrence="daily"))
    next_task = advance_recurring_task(tmp_db, task)
    assert next_task is None


def test_advance_recurring_task_unknown_pattern_returns_none(tmp_db):
    dt = datetime(2026, 3, 6, 9, 0)
    task = create_task(tmp_db, _make_task(name="Task", deadline=dt, recurrence="biweekly"))
    next_task = advance_recurring_task(tmp_db, task)
    assert next_task is None


def test_advance_recurring_task_no_duplicate_when_next_exists(tmp_db):
    """If a pending occurrence for the next date already exists, return it — don't create another."""
    dt = datetime(2026, 3, 6, 9, 0)
    task = create_task(tmp_db, _make_task(name="Shower", deadline=dt, recurrence="daily"))

    # First advance: creates the next occurrence for 2026-03-07
    next1 = advance_recurring_task(tmp_db, task)
    assert next1 is not None
    assert next1.deadline == datetime(2026, 3, 7, 9, 0)

    # Simulate daemon calling advance again on the same (now-done) original task
    next2 = advance_recurring_task(tmp_db, task)
    assert next2 is not None
    assert next2.id == next1.id  # same row returned, not a new one

    # Only one pending task should exist
    pending = list_tasks(tmp_db, status=TaskStatus.PENDING)
    assert len(pending) == 1
    assert pending[0].name == "Shower"
    assert pending[0].deadline == datetime(2026, 3, 7, 9, 0)


# --- sanitize_recurring_tasks ---

def test_sanitize_removes_exact_duplicates(tmp_db):
    """Two non-done tasks with the same name + deadline: keep lowest id, delete the other."""
    dt = datetime(2026, 3, 10, 9, 0)
    t1 = create_task(tmp_db, _make_task(name="Shower", deadline=dt, recurrence="daily"))
    t2 = create_task(tmp_db, _make_task(name="Shower", deadline=dt, recurrence="daily"))

    stats = sanitize_recurring_tasks(tmp_db, now=datetime(2026, 3, 10, 12, 0))

    assert stats["duplicates"] == 1
    active = list_tasks(tmp_db)
    assert len(active) == 1
    assert active[0].id == t1.id  # lowest id kept


def test_sanitize_keeps_only_earliest_in_family(tmp_db):
    """Multiple non-done occurrences of the same recurring family: keep earliest, delete the rest."""
    dt1 = datetime(2026, 3, 10, 9, 0)
    dt2 = datetime(2026, 3, 11, 9, 0)
    dt3 = datetime(2026, 3, 12, 9, 0)
    create_task(tmp_db, _make_task(name="Shower", deadline=dt1, recurrence="daily"))
    create_task(tmp_db, _make_task(name="Shower", deadline=dt2, recurrence="daily"))
    create_task(tmp_db, _make_task(name="Shower", deadline=dt3, recurrence="daily"))

    # All three deadlines are in the future relative to the 'now' we pass in
    stats = sanitize_recurring_tasks(tmp_db, now=datetime(2026, 3, 9, 12, 0))

    assert stats["excess_future"] == 2
    active = list_tasks(tmp_db)
    assert len(active) == 1
    assert active[0].deadline == dt1  # earliest kept


def test_sanitize_fast_forwards_stale_overdue_task(tmp_db):
    """A non-done recurring task with a past deadline gets its deadline moved forward to now."""
    # Task due 5 days ago (daily recurrence)
    stale_dt = datetime(2026, 3, 4, 9, 0)
    task = create_task(tmp_db, _make_task(name="Shower", deadline=stale_dt, recurrence="daily"))
    now = datetime(2026, 3, 9, 12, 0)  # 5 days later

    stats = sanitize_recurring_tasks(tmp_db, now=now)

    assert stats["fast_forwarded"] == 1
    updated = get_task(tmp_db, task.id)
    # Deadline should be on or after now (2026-03-09), never before
    assert updated.deadline >= now
    # For daily recurrence the next day at or after 2026-03-09 12:00 is 2026-03-09 09:00? No —
    # next_occurrence advances by 1 day each step, so from 2026-03-04 09:00:
    # → 05, 06, 07, 08, 09 09:00 — which is still before noon on the 9th.
    # One more step: 2026-03-10 09:00.
    assert updated.deadline == datetime(2026, 3, 10, 9, 0)
    # Status must NOT be changed — user never completed the task
    assert updated.status == TaskStatus.PENDING


def test_sanitize_respects_recurrence_end(tmp_db):
    """A stale overdue task whose next future occurrence is past recurrence_end is left alone."""
    from datetime import date as _date
    stale_dt = datetime(2026, 3, 4, 9, 0)
    task = create_task(tmp_db, _make_task(
        name="Shower",
        deadline=stale_dt,
        recurrence="daily",
        recurrence_end=_date(2026, 3, 5),  # already expired
    ))
    now = datetime(2026, 3, 9, 12, 0)

    stats = sanitize_recurring_tasks(tmp_db, now=now)

    # All next occurrences fall after recurrence_end → deadline should NOT be changed
    assert stats["fast_forwarded"] == 0
    unchanged = get_task(tmp_db, task.id)
    assert unchanged.deadline == stale_dt


def test_sanitize_does_not_touch_non_recurring_overdue(tmp_db):
    """A non-recurring overdue task is never modified by sanitize."""
    stale_dt = datetime(2026, 3, 4, 9, 0)
    task = create_task(tmp_db, _make_task(name="One-off", deadline=stale_dt))
    now = datetime(2026, 3, 9, 12, 0)

    stats = sanitize_recurring_tasks(tmp_db, now=now)

    assert stats == {"duplicates": 0, "excess_future": 0, "fast_forwarded": 0}
    unchanged = get_task(tmp_db, task.id)
    assert unchanged.deadline == stale_dt


def test_open_db_sanitizes_on_startup(tmp_path):
    """open_db automatically runs sanitize so duplicates are cleaned before the app starts."""
    import sqlite3 as _sqlite3
    from kanademinder.db import init_db

    db_path = tmp_path / "tasks.db"
    # Manually insert two duplicate pending occurrences (bypassing the normal API)
    conn = _sqlite3.connect(str(db_path))
    conn.row_factory = _sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    iso_dl = "2026-03-10T09:00:00"
    for _ in range(2):
        conn.execute(
            "INSERT INTO tasks (name, type, priority, status, deadline, recurrence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("Shower", "major", 3, "pending", iso_dl, "daily", "2026-03-09T00:00:00"),
        )
    conn.commit()
    conn.close()

    # open_db should sanitize on startup
    clean_conn = open_db(db_path, now=datetime(2026, 3, 9, 12, 0))
    active = list_tasks(clean_conn)
    clean_conn.close()

    assert len(active) == 1


# --- Schema migration v1 → v2 ---

def test_schema_migration_v1_to_v2(tmp_path):
    """A v1 schema DB gets migrated: recurrence columns added, date-only deadlines converted."""
    db_path = tmp_path / "v1.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Create v1 schema manually (no recurrence columns)
    conn.executescript("""
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        CREATE TABLE tasks (
            id                INTEGER  PRIMARY KEY AUTOINCREMENT,
            name              TEXT     NOT NULL,
            type              TEXT     NOT NULL DEFAULT 'major',
            parent_id         INTEGER,
            deadline          TEXT,
            estimated_minutes INTEGER,
            priority          INTEGER  NOT NULL DEFAULT 3,
            status            TEXT     NOT NULL DEFAULT 'pending',
            notes             TEXT,
            created_at        TEXT     NOT NULL
        );
        INSERT INTO schema_version (version) VALUES (1);
        INSERT INTO tasks (name, deadline, priority, status, created_at)
            VALUES ('Old task', '2026-03-06', 3, 'pending', '2026-03-01T08:00:00');
    """)
    conn.commit()

    # Run init_db — should trigger migration
    init_db(conn)

    # Check version upgraded
    version = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()["version"]
    assert version == 2

    # Check recurrence columns exist
    row = conn.execute("SELECT recurrence, recurrence_end FROM tasks WHERE name = 'Old task'").fetchone()
    assert row is not None

    # Check date-only deadline was converted to datetime string
    task_row = conn.execute("SELECT deadline FROM tasks WHERE name = 'Old task'").fetchone()
    assert "T" in task_row["deadline"]
    assert task_row["deadline"] == "2026-03-06T00:00:00"

    conn.close()


def test_schema_migration_idempotent(tmp_path):
    """Running init_db twice on a v2 DB does not error."""
    db_path = tmp_path / "v2.db"
    conn = open_db(db_path)
    # Run again — should not raise
    init_db(conn)
    version = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()["version"]
    assert version == 2
    conn.close()


# ── mark_subtasks_done ─────────────────────────────────────────────────────────

def test_mark_subtasks_done_marks_all_children(tmp_db):
    parent = create_task(tmp_db, _make_task(name="Parent"))
    child1 = create_task(tmp_db, _make_task(name="Child 1", parent_id=parent.id))
    child2 = create_task(tmp_db, _make_task(name="Child 2", parent_id=parent.id))

    mark_subtasks_done(tmp_db, parent.id)

    assert get_task(tmp_db, child1.id).status == TaskStatus.DONE
    assert get_task(tmp_db, child2.id).status == TaskStatus.DONE
    # Parent itself is unchanged
    assert get_task(tmp_db, parent.id).status == TaskStatus.PENDING


def test_mark_subtasks_done_recursive(tmp_db):
    grandparent = create_task(tmp_db, _make_task(name="Grandparent"))
    parent = create_task(tmp_db, _make_task(name="Parent", parent_id=grandparent.id))
    grandchild = create_task(tmp_db, _make_task(name="Grandchild", parent_id=parent.id))

    mark_subtasks_done(tmp_db, grandparent.id)

    assert get_task(tmp_db, parent.id).status == TaskStatus.DONE
    assert get_task(tmp_db, grandchild.id).status == TaskStatus.DONE
    assert get_task(tmp_db, grandparent.id).status == TaskStatus.PENDING


def test_mark_subtasks_done_skips_already_done(tmp_db):
    parent = create_task(tmp_db, _make_task(name="Parent"))
    child_done = create_task(tmp_db, _make_task(name="Already done", parent_id=parent.id, status=TaskStatus.DONE))
    child_pending = create_task(tmp_db, _make_task(name="Still pending", parent_id=parent.id))

    mark_subtasks_done(tmp_db, parent.id)

    assert get_task(tmp_db, child_done.id).status == TaskStatus.DONE
    assert get_task(tmp_db, child_pending.id).status == TaskStatus.DONE
