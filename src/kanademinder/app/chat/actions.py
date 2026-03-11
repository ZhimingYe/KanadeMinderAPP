"""Task CRUD action handlers for the KanadeMinder conversation handler."""

from __future__ import annotations

import sqlite3
from typing import Any

from kanademinder.db import (
    advance_recurring_task,
    create_task,
    delete_task,
    get_task,
    list_tasks,
    mark_subtasks_done,
    update_task,
)
from kanademinder.llm.prompts import _fmt_deadline
from kanademinder.models import Task, TaskStatus, TaskType

from kanademinder.app.chat.matching import _AmbiguousMatch, _fuzzy_find_task


def _task_from_dict(data: dict[str, Any], default_task_type: str) -> Task:
    """Build a Task from an LLM-produced task dict, applying defaults."""
    priority = data.get("priority", 3)
    try:
        priority = max(1, min(5, int(priority)))
    except (ValueError, TypeError):
        priority = 3

    # Subtasks default to minor; top-level tasks use the configured default
    effective_default = "minor" if data.get("parent_id") else default_task_type
    raw_type = data.get("type", effective_default)
    try:
        task_type = TaskType(raw_type)
    except ValueError:
        task_type = TaskType(effective_default)

    raw_status = data.get("status", TaskStatus.PENDING)
    try:
        task_status = TaskStatus(raw_status)
    except ValueError:
        task_status = TaskStatus.PENDING

    return Task(
        name=data.get("name", "Unnamed task"),
        type=task_type,
        parent_id=data.get("parent_id"),
        deadline=data.get("deadline"),
        estimated_minutes=data.get("estimated_minutes"),
        priority=priority,
        status=task_status,
        notes=data.get("notes"),
        recurrence=data.get("recurrence"),
        recurrence_end=data.get("recurrence_end"),
    )


def _task_updates_from_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Extract only updatable fields from a task dict (excludes id, created_at)."""
    allowed = {
        "name", "type", "parent_id", "deadline", "estimated_minutes",
        "priority", "status", "notes", "recurrence", "recurrence_end",
    }
    updates: dict[str, Any] = {}
    for k, v in data.items():
        if k in allowed and v is not None:
            if k == "type":
                try:
                    updates[k] = TaskType(v)
                except ValueError:
                    pass
            elif k == "status":
                try:
                    updates[k] = TaskStatus(v)
                except ValueError:
                    pass
            elif k == "priority":
                try:
                    updates[k] = max(1, min(5, int(v)))
                except (ValueError, TypeError):
                    pass
            else:
                updates[k] = v
    return updates


def _ordered_with_depth(tasks: list[Task]) -> list[tuple[Task, int]]:
    """Return tasks in hierarchical order (parent then children), with depth level."""
    ids = {t.id for t in tasks if t.id is not None}
    by_parent: dict[int | None, list[Task]] = {}
    for t in tasks:
        pid = t.parent_id if t.parent_id in ids else None
        by_parent.setdefault(pid, []).append(t)
    result: list[tuple[Task, int]] = []

    def _visit(pid: int | None, depth: int) -> None:
        for t in by_parent.get(pid, []):
            result.append((t, depth))
            if t.id is not None:
                _visit(t.id, depth + 1)

    _visit(None, 0)
    return result


def _format_task_list(tasks: list[Task]) -> str:
    if not tasks:
        return "You have no tasks."
    lines = ["Your tasks:"]
    for t, depth in _ordered_with_depth(tasks):
        if t.deadline:
            deadline = f", due {_fmt_deadline(t.deadline)}"
        else:
            deadline = ""
        if t.recurrence:
            end = f" until {t.recurrence_end.isoformat()}" if t.recurrence_end else ""
            recurrence = f" ↻{t.recurrence}{end}"
        else:
            recurrence = ""
        status_mark = {"pending": " ", "in_progress": "~", "done": "x"}.get(t.status.value, " ")
        if depth > 0:
            prefix = "    └─ "
        else:
            prefix = "  "
        lines.append(
            f"{prefix}[{status_mark}] #{t.id} {t.name}{recurrence} "
            f"[{t.type.value}, P{t.priority}]{deadline} — {t.status.value}"
        )
    return "\n".join(lines)


def _find_orphan_by_name(all_tasks: list[Task], name: str) -> Task | None:
    """Return an existing parentless task whose name matches exactly, or None."""
    name_lower = name.lower()
    for t in all_tasks:
        if t.name.lower() == name_lower and t.parent_id is None:
            return t
    return None


def _resolve_parent(conn: sqlite3.Connection, parent_name: str, default_task_type: str) -> int:
    """Look up a task by name or create it; return its ID."""
    name_lower = parent_name.lower().strip()
    for t in list_tasks(conn):
        if t.name.lower() == name_lower:
            return t.id
    parent = create_task(conn, Task(name=parent_name, type=TaskType(default_task_type)))
    return parent.id


def _upsert_task(
    conn: sqlite3.Connection,
    task_data: dict[str, Any],
    default_task_type: str,
    all_tasks: list[Task],
) -> tuple[Task, bool]:
    """Create a task, or update an existing same-named orphan. Returns (task, created)."""
    name = task_data["name"]
    existing = _find_orphan_by_name(all_tasks, name)
    if existing is not None:
        updates = _task_updates_from_dict(task_data)
        updated = update_task(conn, existing.id, updates)
        return updated, False
    task = _task_from_dict(task_data, default_task_type)
    return create_task(conn, task), True


def _handle_create(
    conn: sqlite3.Connection,
    task_data: dict[str, Any],
    default_task_type: str,
    message: str,
) -> str:
    """Handle a create action, reusing an existing same-named orphan when assigning a parent."""
    name = task_data.get("name", "").strip()
    if not name:
        return message or "I need a task name to create a task. What should I call it?"

    if task_data.get("parent_name") and not task_data.get("parent_id"):
        task_data = dict(task_data)
        task_data["parent_id"] = _resolve_parent(conn, task_data["parent_name"], default_task_type)

    warn_recurrence = bool(task_data.get("recurrence") and not task_data.get("deadline"))
    all_tasks = list_tasks(conn)
    result_task, created = _upsert_task(conn, task_data, default_task_type, all_tasks)
    verb = "Created" if created else "Updated"
    result = message or f"{verb} task #{result_task.id}: {result_task.name}"
    if warn_recurrence:
        result += " (Recurring tasks need a deadline to advance automatically — please add one.)"
    if task_data.get("_deadline_parse_warning"):
        bad = task_data["_deadline_parse_warning"]
        result += f' (I couldn\'t parse "{bad}" as a date — no deadline was set.)'
    return result


def _handle_batch_create(
    conn: sqlite3.Connection,
    tasks_data: list[dict[str, Any]],
    default_task_type: str,
    message: str,
) -> str:
    """Handle creating multiple tasks, reusing same-named orphans instead of duplicating."""
    labels: list[str] = []
    warnings: list[str] = []
    parent_name_cache: dict[str, int] = {}

    for task_data in tasks_data:
        name = task_data.get("name", "").strip()
        if not name:
            continue

        # Resolve parent_name → parent_id, creating the parent once if needed
        if task_data.get("parent_name") and not task_data.get("parent_id"):
            pname = task_data["parent_name"]
            if pname not in parent_name_cache:
                parent_name_cache[pname] = _resolve_parent(conn, pname, default_task_type)
            task_data = dict(task_data)
            task_data["parent_id"] = parent_name_cache[pname]

        if task_data.get("recurrence") and not task_data.get("deadline"):
            warnings.append(f'"{name}" needs a deadline for auto-advance.')

        all_tasks = list_tasks(conn)
        result_task, _ = _upsert_task(conn, task_data, default_task_type, all_tasks)
        labels.append(f"#{result_task.id}: {result_task.name}")

        if task_data.get("_deadline_parse_warning"):
            bad = task_data["_deadline_parse_warning"]
            warnings.append(f'Couldn\'t parse deadline "{bad}" for "{name}".')

    if not labels:
        return message or "No tasks were created — each task needs a name."

    base = message or f"Created {len(labels)} tasks: {', '.join(labels)}."
    if warnings:
        base += " " + " ".join(warnings)
    return base


def _handle_update(
    conn: sqlite3.Connection,
    task_data: dict[str, Any],
    message: str,
) -> str:
    """Handle an update action with fuzzy ID resolution and recurring auto-advance."""
    task_id = task_data.get("id")

    # If no id, try fuzzy matching by name
    if task_id is None:
        try:
            task_id = _fuzzy_find_task(conn, task_data)
        except _AmbiguousMatch as e:
            names = ", ".join(f'#{t.id} "{t.name}"' for t in e.candidates[:4])
            return (
                f"I found multiple matching tasks: {names}. "
                "Which one did you mean? Use the task ID or a more specific name."
            )
        if task_id is None:
            return "I couldn't determine which task to update. Could you specify the task name or ID?"

    task_id = int(task_id)

    # Verify the task exists before updating
    existing = get_task(conn, task_id)
    if existing is None:
        return f"Task #{task_id} not found. Use 'show my tasks' to see available tasks."

    updates = _task_updates_from_dict(task_data)
    if not updates:
        return f"No changes to apply to task #{task_id}: {existing.name}."

    was_done_before = existing.status == TaskStatus.DONE
    updated = update_task(conn, task_id, updates)

    # Cascade completion to children when marked done
    if updates.get("status") == TaskStatus.DONE and updated:
        mark_subtasks_done(conn, task_id)

    # Auto-advance recurring tasks when marked done — only on the FIRST completion
    if updates.get("status") == TaskStatus.DONE and not was_done_before and updated and updated.recurrence:
        next_task = advance_recurring_task(conn, updated)
        if next_task:
            base = message or f"Updated task #{updated.id}: {updated.name}"
            deadline_str = _fmt_deadline(next_task.deadline) if next_task.deadline else ""
            return (
                base + f" Since it recurs {updated.recurrence}, a new pending copy "
                f"has been created{f' due {deadline_str}' if deadline_str else ''}."
            )

    result = message or f"Updated task #{updated.id}: {updated.name}"
    if task_data and task_data.get("_deadline_parse_warning"):
        bad = task_data["_deadline_parse_warning"]
        result += f' (I couldn\'t parse "{bad}" as a date — no deadline was set.)'
    return result


def _handle_batch_update(
    conn: sqlite3.Connection,
    tasks_data: list[dict[str, Any]],
    message: str,
) -> str:
    """Handle updating multiple tasks at once."""
    updated_labels: list[str] = []
    skipped: list[str] = []
    warnings: list[str] = []

    for task_data in tasks_data:
        task_id = task_data.get("id")

        if task_id is None:
            try:
                task_id = _fuzzy_find_task(conn, task_data)
            except _AmbiguousMatch as e:
                names = ", ".join(f'#{t.id} "{t.name}"' for t in e.candidates[:4])
                skipped.append(f"ambiguous match ({names})")
                continue
            if task_id is None:
                name = task_data.get("name", "?")
                skipped.append(f'"{name}" not found')
                continue

        task_id = int(task_id)
        existing = get_task(conn, task_id)
        if existing is None:
            skipped.append(f"#{task_id} not found")
            continue

        updates = _task_updates_from_dict(task_data)
        if not updates:
            skipped.append(f"#{task_id} no changes")
            continue

        was_done_before = existing.status == TaskStatus.DONE
        updated = update_task(conn, task_id, updates)
        if updated is None:
            skipped.append(f"#{task_id} not found")
            continue

        if updates.get("status") == TaskStatus.DONE:
            mark_subtasks_done(conn, task_id)

        if updates.get("status") == TaskStatus.DONE and not was_done_before and updated.recurrence:
            next_task = advance_recurring_task(conn, updated)
            if next_task and next_task.deadline:
                warnings.append(
                    f'Created next recurring copy for "#{updated.id}: {updated.name}" due {_fmt_deadline(next_task.deadline)}.'
                )
            elif next_task:
                warnings.append(f'Created next recurring copy for "#{updated.id}: {updated.name}".')

        updated_labels.append(f"#{updated.id}: {updated.name}")

        if task_data.get("_deadline_parse_warning"):
            bad = task_data["_deadline_parse_warning"]
            warnings.append(f'Couldn\'t parse deadline "{bad}" for "{updated.name}".')

    if not updated_labels:
        detail = f" ({'; '.join(skipped)})" if skipped else ""
        return message or f"No tasks were updated{detail}."

    base = message or f"Updated {len(updated_labels)} tasks: {', '.join(updated_labels)}."
    if skipped:
        base += f" Skipped: {'; '.join(skipped)}."
    if warnings:
        base += " " + " ".join(warnings)
    return base


def _handle_delete(
    conn: sqlite3.Connection,
    task_data: dict[str, Any],
    message: str,
) -> str:
    """Handle a delete action with fuzzy ID resolution."""
    task_id = task_data.get("id")

    if task_id is None:
        try:
            task_id = _fuzzy_find_task(conn, task_data)
        except _AmbiguousMatch as e:
            names = ", ".join(f'#{t.id} "{t.name}"' for t in e.candidates[:4])
            return (
                f"I found multiple matching tasks: {names}. "
                "Which one did you mean? Use the task ID or a more specific name."
            )
        if task_id is None:
            return "I couldn't determine which task to delete. Could you specify the task name or ID?"

    task_id = int(task_id)

    existing = get_task(conn, task_id)
    if existing is None:
        return f"Task #{task_id} not found. Use 'show my tasks' to see available tasks."

    deleted = delete_task(conn, task_id)
    return message or (f"Deleted task #{task_id}: {existing.name}." if deleted else f"Task #{task_id} not found.")


def _handle_batch_delete(
    conn: sqlite3.Connection,
    tasks_data: list[dict[str, Any]],
    message: str,
) -> str:
    """Handle deleting multiple tasks at once."""
    deleted_labels: list[str] = []
    skipped: list[str] = []

    for task_data in tasks_data:
        task_id = task_data.get("id")
        if task_id is None:
            try:
                task_id = _fuzzy_find_task(conn, task_data)
            except _AmbiguousMatch as e:
                names = ", ".join(f'#{t.id} "{t.name}"' for t in e.candidates[:4])
                skipped.append(f"ambiguous match ({names})")
                continue
            if task_id is None:
                name = task_data.get("name", "?")
                skipped.append(f'"{name}" not found')
                continue

        task_id = int(task_id)
        existing = get_task(conn, task_id)
        if existing is None:
            skipped.append(f"#{task_id} not found")
            continue
        delete_task(conn, task_id)
        deleted_labels.append(f"#{task_id}: {existing.name}")

    if not deleted_labels:
        detail = f" ({'; '.join(skipped)})" if skipped else ""
        return message or f"No tasks were deleted{detail}."

    base = message or f"Deleted {len(deleted_labels)} tasks: {', '.join(deleted_labels)}."
    if skipped:
        base += f" Skipped: {'; '.join(skipped)}."
    return base
