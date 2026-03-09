"""SQLite schema and CRUD operations."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from kanademinder.models import Task, TaskStatus, TaskType

SCHEMA_VERSION = 2

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id                INTEGER  PRIMARY KEY AUTOINCREMENT,
    name              TEXT     NOT NULL,
    type              TEXT     NOT NULL DEFAULT 'major',
    parent_id         INTEGER  REFERENCES tasks(id) ON DELETE SET NULL,
    deadline          TEXT,
    estimated_minutes INTEGER,
    priority          INTEGER  NOT NULL DEFAULT 3,
    status            TEXT     NOT NULL DEFAULT 'pending',
    notes             TEXT,
    recurrence        TEXT,
    recurrence_end    TEXT,
    created_at        TEXT     NOT NULL
);
"""


def open_db(path: Path, *, now: datetime | None = None) -> sqlite3.Connection:
    """Open (or create) the SQLite database, apply schema, return connection.

    Automatically calls :func:`sanitize_recurring_tasks` after schema
    initialisation so that any corrupted recurring-task state left by a
    previous session (duplicates, ghost future copies, stale overdue tasks) is
    repaired before the application starts.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    sanitize_recurring_tasks(conn, now=now)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Apply schema, run any pending migrations, ensure schema_version row exists."""
    conn.executescript(_SCHEMA_SQL)
    row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()
    else:
        version = row["version"]
        if version < 2:
            _migrate_v1_to_v2(conn)


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Migrate schema from v1 to v2: add recurrence columns, convert date-only deadlines."""
    # Add new columns (may already exist if schema was freshly created — ignore errors)
    for col_def in (
        "ALTER TABLE tasks ADD COLUMN recurrence TEXT",
        "ALTER TABLE tasks ADD COLUMN recurrence_end TEXT",
    ):
        try:
            conn.execute(col_def)
        except sqlite3.OperationalError:
            pass  # Column already exists

    # Convert date-only deadlines (YYYY-MM-DD) to datetime strings (YYYY-MM-DDTHH:MM:SS)
    rows = conn.execute(
        "SELECT id, deadline FROM tasks WHERE deadline IS NOT NULL"
    ).fetchall()
    for row in rows:
        dl = row["deadline"]
        if dl and "T" not in dl and " " not in dl:
            conn.execute(
                "UPDATE tasks SET deadline = ? WHERE id = ?",
                (dl + "T00:00:00", row["id"]),
            )

    conn.execute("UPDATE schema_version SET version = 2")
    conn.commit()


def create_task(conn: sqlite3.Connection, task: Task) -> Task:
    """Insert a task and return it with the assigned id."""
    d = task.to_insert_dict()
    cols = ", ".join(d.keys())
    placeholders = ", ".join("?" for _ in d)
    cur = conn.execute(
        f"INSERT INTO tasks ({cols}) VALUES ({placeholders})",
        list(d.values()),
    )
    conn.commit()
    task.id = cur.lastrowid
    return task


def get_task(conn: sqlite3.Connection, task_id: int) -> Task | None:
    """Fetch a single task by id, or None if not found."""
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return Task.from_row(row) if row else None


def update_task(conn: sqlite3.Connection, task_id: int, updates: dict[str, Any]) -> Task | None:
    """Apply partial updates to a task. Returns updated Task or None if not found."""
    if not updates:
        return get_task(conn, task_id)

    # Coerce enum values to their string representation
    coerced: dict[str, Any] = {}
    for k, v in updates.items():
        if isinstance(v, (TaskType, TaskStatus)):
            coerced[k] = v.value
        else:
            coerced[k] = v

    set_clause = ", ".join(f"{k} = ?" for k in coerced)
    values = list(coerced.values()) + [task_id]
    conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)
    conn.commit()
    return get_task(conn, task_id)


def delete_task(conn: sqlite3.Connection, task_id: int) -> bool:
    """Delete a task and all its direct children recursively. Returns True if a row was deleted."""
    children = conn.execute(
        "SELECT id FROM tasks WHERE parent_id = ?", (task_id,)
    ).fetchall()
    for child in children:
        delete_task(conn, child["id"])
    cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    return cur.rowcount > 0


def list_tasks(
    conn: sqlite3.Connection,
    *,
    status: TaskStatus | None = None,
    task_type: TaskType | None = None,
    parent_id: int | None = None,
) -> list[Task]:
    """Return tasks with optional filtering."""
    conditions: list[str] = []
    params: list[Any] = []

    if status is not None:
        conditions.append("status = ?")
        params.append(status.value)
    if task_type is not None:
        conditions.append("type = ?")
        params.append(task_type.value)
    if parent_id is not None:
        conditions.append("parent_id = ?")
        params.append(parent_id)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM tasks {where} ORDER BY priority DESC, deadline ASC, id ASC",
        params,
    ).fetchall()
    return [Task.from_row(r) for r in rows]


def mark_subtasks_done(conn: sqlite3.Connection, parent_id: int) -> None:
    """Recursively mark all children of parent_id as done."""
    children = conn.execute(
        "SELECT * FROM tasks WHERE parent_id = ?", (parent_id,)
    ).fetchall()
    for row in children:
        child = Task.from_row(row)
        if child.status != TaskStatus.DONE:
            update_task(conn, child.id, {"status": TaskStatus.DONE.value})
        if child.id is not None:
            mark_subtasks_done(conn, child.id)


def sanitize_recurring_tasks(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Detect and repair corrupted recurring-task state in the database.

    Runs three repair passes in order:

    1. **Exact duplicates** — multiple non-done tasks sharing the same name
       *and* deadline.  The row with the lowest id is kept; the rest are
       deleted (including their children).

    2. **Over-advanced families** — multiple non-done occurrences that belong
       to the same recurring family (same name + recurrence pattern).  Only
       the occurrence with the earliest deadline is kept; later ghost copies
       created by repeated LLM actions are deleted.

    3. **Stale overdue tasks** — a non-done recurring task whose deadline is
       already in the past.  Rather than marking it done (the user never
       completed it), the deadline is fast-forwarded in-place to the next
       occurrence that falls on or after *now*.

    Returns a dict with the number of repairs in each category::

        {"duplicates": N, "excess_future": N, "fast_forwarded": N}
    """
    from collections import defaultdict

    from kanademinder.recurrence import next_occurrence

    if now is None:
        now = datetime.now()

    stats: dict[str, int] = {"duplicates": 0, "excess_future": 0, "fast_forwarded": 0}

    def _active() -> list[Task]:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status != ?", (TaskStatus.DONE.value,)
        ).fetchall()
        return sorted([Task.from_row(r) for r in rows], key=lambda t: t.id or 0)

    # ── Phase 1: exact duplicates (same name + same deadline) ─────────────────
    seen: dict[tuple[str, str], int] = {}  # key → lowest id kept
    for task in _active():
        if task.deadline is None:
            continue
        key = (task.name.strip().lower(), task.deadline.isoformat())
        if key not in seen:
            seen[key] = task.id
        else:
            delete_task(conn, task.id)
            stats["duplicates"] += 1

    # ── Phase 2: multiple non-done occurrences in same recurring family ────────
    families: dict[tuple[str, str], list[Task]] = defaultdict(list)
    for task in _active():
        if task.recurrence:
            families[(task.name.strip().lower(), task.recurrence)].append(task)

    for members in families.values():
        if len(members) <= 1:
            continue
        # Sort: tasks with a deadline first (earliest first), then no-deadline tasks.
        with_dl = sorted(
            [t for t in members if t.deadline is not None],
            key=lambda t: t.deadline,  # type: ignore[arg-type]
        )
        without_dl = [t for t in members if t.deadline is None]
        ordered = with_dl + without_dl
        # Keep the first (earliest / most imminent); delete the excess.
        for extra in ordered[1:]:
            delete_task(conn, extra.id)
            stats["excess_future"] += 1

    # ── Phase 3: fast-forward stale overdue recurring tasks ───────────────────
    for task in _active():
        if not task.recurrence or not task.deadline:
            continue
        if task.deadline >= now:
            continue
        # Advance deadline until it reaches a future date.
        dt = task.deadline
        while dt is not None and dt < now:
            dt = next_occurrence(dt, task.recurrence)
        if dt is None:
            continue
        if task.recurrence_end and dt.date() > task.recurrence_end:
            continue
        update_task(conn, task.id, {"deadline": dt.isoformat()})
        stats["fast_forwarded"] += 1

    return stats


def advance_recurring_task(conn: sqlite3.Connection, task: Task) -> Task | None:
    """Mark task as done and create the next pending occurrence.

    Returns the newly created Task, or None if recurrence has ended or
    the pattern is unrecognized.
    """
    from kanademinder.recurrence import next_occurrence

    # Mark current task done
    update_task(conn, task.id, {"status": TaskStatus.DONE.value})

    if task.deadline is None or task.recurrence is None:
        return None

    next_dt = next_occurrence(task.deadline, task.recurrence)
    if next_dt is None:
        return None

    # Respect recurrence_end
    if task.recurrence_end and next_dt.date() > task.recurrence_end:
        return None

    # Avoid duplicates: return existing pending/in_progress occurrence if present
    row = conn.execute(
        "SELECT * FROM tasks WHERE name = ? AND deadline = ? AND status != ?",
        (task.name, next_dt.isoformat(), TaskStatus.DONE.value),
    ).fetchone()
    if row:
        return Task.from_row(row)

    new_task = Task(
        name=task.name,
        type=task.type,
        parent_id=task.parent_id,
        deadline=next_dt,
        estimated_minutes=task.estimated_minutes,
        priority=task.priority,
        status=TaskStatus.PENDING,
        notes=task.notes,
        recurrence=task.recurrence,
        recurrence_end=task.recurrence_end,
    )
    return create_task(conn, new_task)
