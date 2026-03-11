"""Tests for chat/handler.py — task dispatch, fuzzy matching, auto-retry."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call

import pytest

from datetime import datetime

from kanademinder.app.chat.matching import _AmbiguousMatch, _fuzzy_find_task
from kanademinder.app.chat.handler import handle_turn
from kanademinder.db import create_task, get_task, list_tasks
from kanademinder.llm.parser import ParseError
from kanademinder.models import Task, TaskStatus


def _mock_llm(response: dict | str) -> MagicMock:
    """Create a mock LLMClient that returns a JSON string."""
    llm = MagicMock()
    if isinstance(response, dict):
        llm.chat.return_value = json.dumps(response)
    else:
        llm.chat.return_value = response
    return llm


# --- Create action ---

def test_handle_create(tmp_db):
    llm = _mock_llm({
        "action": "create",
        "task": {"name": "Write report", "priority": 4, "deadline": "2026-03-10T00:00:00"},
        "message": "Created your report task!",
    })
    history: list = []
    result = handle_turn("add a task to write a report", history, llm, tmp_db)
    assert "Created" in result or "report" in result.lower()

    tasks = list_tasks(tmp_db)
    assert len(tasks) == 1
    assert tasks[0].name == "Write report"
    assert tasks[0].priority == 4


def test_handle_create_no_name_asks(tmp_db):
    llm = _mock_llm({
        "action": "create",
        "task": {"priority": 3},
        "message": "",
    })
    history: list = []
    result = handle_turn("add a task", history, llm, tmp_db)
    # Should ask for a name, not crash
    assert "name" in result.lower()
    assert list_tasks(tmp_db) == []


# --- Update action ---

def test_handle_update_by_id(tmp_db):
    create_task(tmp_db, Task(name="Write report", priority=3))
    llm = _mock_llm({
        "action": "update",
        "task": {"id": 1, "status": "done"},
        "message": "Marked as done!",
    })
    history: list = []
    result = handle_turn("mark task 1 as done", history, llm, tmp_db)
    task = get_task(tmp_db, 1)
    assert task.status == TaskStatus.DONE


def test_handle_update_by_name_fuzzy(tmp_db):
    create_task(tmp_db, Task(name="Write quarterly report"))
    llm = _mock_llm({
        "action": "update",
        "task": {"name": "quarterly report", "status": "in_progress"},
        "message": "Started working on it!",
    })
    history: list = []
    result = handle_turn("start working on the quarterly report", history, llm, tmp_db)
    task = get_task(tmp_db, 1)
    assert task.status == TaskStatus.IN_PROGRESS


def test_handle_update_nonexistent_task(tmp_db):
    llm = _mock_llm({
        "action": "update",
        "task": {"id": 999, "status": "done"},
        "message": "",
    })
    history: list = []
    result = handle_turn("mark task 999 done", history, llm, tmp_db)
    assert "not found" in result.lower()


def test_handle_update_nonexistent_task_nonempty_message(tmp_db):
    """LLM success message must not mask a missing task — always return error."""
    llm = _mock_llm({
        "action": "update",
        "task": {"id": 999, "status": "done"},
        "message": "Marked task #999 as done!",
    })
    history: list = []
    result = handle_turn("mark task 999 done", history, llm, tmp_db)
    assert "not found" in result.lower()


def test_handle_update_no_id_no_name(tmp_db):
    create_task(tmp_db, Task(name="Something"))
    llm = _mock_llm({
        "action": "update",
        "task": {"status": "done"},
        "message": "",
    })
    history: list = []
    result = handle_turn("mark it as done", history, llm, tmp_db)
    assert "couldn't determine" in result.lower() or "specify" in result.lower()


def test_handle_update_no_id_no_name_nonempty_message(tmp_db):
    """LLM success message must not mask fuzzy-match failure — always return error."""
    create_task(tmp_db, Task(name="Something"))
    llm = _mock_llm({
        "action": "update",
        "task": {"status": "done"},
        "message": "Marked it as done!",
    })
    history: list = []
    result = handle_turn("mark it as done", history, llm, tmp_db)
    assert "couldn't determine" in result.lower() or "specify" in result.lower()


def test_handle_update_rename_by_id(tmp_db):
    """Renaming a task by id updates the name in the DB."""
    create_task(tmp_db, Task(name="Old Name"))
    llm = _mock_llm({
        "action": "update",
        "task": {"id": 1, "name": "New Name"},
        "message": "Renamed to 'New Name'.",
    })
    history: list = []
    handle_turn("rename task 1 to New Name", history, llm, tmp_db)
    task = get_task(tmp_db, 1)
    assert task.name == "New Name"


def test_handle_update_no_valid_fields_nonempty_message(tmp_db):
    """LLM success message must not mask a no-op update — always return no-changes message."""
    create_task(tmp_db, Task(name="Something"))
    llm = _mock_llm({
        "action": "update",
        "task": {"id": 1},  # no updatable fields
        "message": "Updated task #1!",
    })
    history: list = []
    result = handle_turn("update task 1", history, llm, tmp_db)
    assert "no changes" in result.lower()


# --- Delete action ---

def test_handle_delete_by_id(tmp_db):
    create_task(tmp_db, Task(name="Obsolete task"))
    llm = _mock_llm({
        "action": "delete",
        "task": {"id": 1},
        "message": "Deleted!",
    })
    history: list = []
    result = handle_turn("delete task 1", history, llm, tmp_db)
    assert get_task(tmp_db, 1) is None


def test_handle_delete_by_name(tmp_db):
    create_task(tmp_db, Task(name="Buy groceries"))
    llm = _mock_llm({
        "action": "delete",
        "task": {"name": "Buy groceries"},
        "message": "Removed!",
    })
    history: list = []
    result = handle_turn("remove the groceries task", history, llm, tmp_db)
    assert get_task(tmp_db, 1) is None


def test_handle_delete_nonexistent(tmp_db):
    llm = _mock_llm({
        "action": "delete",
        "task": {"id": 999},
        "message": "",
    })
    history: list = []
    result = handle_turn("delete task 999", history, llm, tmp_db)
    assert "not found" in result.lower()


# --- Query action ---

def test_handle_query_empty(tmp_db):
    llm = _mock_llm({
        "action": "query",
        "task": None,
        "message": "Here are your tasks:",
    })
    history: list = []
    result = handle_turn("show my tasks", history, llm, tmp_db)
    assert "no tasks" in result.lower()


def test_handle_query_with_tasks(tmp_db):
    create_task(tmp_db, Task(name="Task A"))
    create_task(tmp_db, Task(name="Task B"))
    llm = _mock_llm({
        "action": "query",
        "task": None,
        "message": "Here you go:",
    })
    history: list = []
    result = handle_turn("what are my tasks", history, llm, tmp_db)
    assert "Task A" in result
    assert "Task B" in result


# --- Safety net: none → query override ---

def test_none_overridden_to_query_for_list_request(tmp_db):
    """LLM returns 'none' for an explicit listing request → handler overrides to query."""
    from kanademinder.app.chat.handler import QUERY_RESPONSE_SENTINEL
    create_task(tmp_db, Task(name="Task A"))
    llm = _mock_llm({
        "action": "none",
        "task": None,
        "message": "You have 1 task: Task A — pending",
    })
    result = handle_turn("list my tasks", [], llm, tmp_db)
    assert result.startswith(QUERY_RESPONSE_SENTINEL)
    assert "Task A" in result


def test_none_not_overridden_for_suggestion_request(tmp_db):
    """action='none' is kept for suggestion/casual requests, not overridden."""
    from kanademinder.app.chat.handler import QUERY_RESPONSE_SENTINEL
    llm = _mock_llm({
        "action": "none",
        "task": None,
        "message": "You're welcome! Let me know if you need anything.",
    })
    result = handle_turn("thanks", [], llm, tmp_db)
    assert not result.startswith(QUERY_RESPONSE_SENTINEL)
    assert "welcome" in result.lower()


# --- Clarify and None actions ---

def test_handle_clarify(tmp_db):
    llm = _mock_llm({
        "action": "clarify",
        "task": None,
        "message": "When is the deadline for that task?",
    })
    history: list = []
    result = handle_turn("add a task", history, llm, tmp_db)
    assert "deadline" in result.lower()


def test_handle_none(tmp_db):
    llm = _mock_llm({
        "action": "none",
        "task": None,
        "message": "You're welcome! Let me know if you need anything.",
    })
    history: list = []
    result = handle_turn("thanks", history, llm, tmp_db)
    assert "welcome" in result.lower()


# --- History management ---

def test_history_appended(tmp_db):
    llm = _mock_llm({
        "action": "none",
        "task": None,
        "message": "Hello!",
    })
    history: list = []
    handle_turn("hi", history, llm, tmp_db)
    assert len(history) == 2
    assert history[0] == {"role": "user", "content": "hi"}
    assert history[1] == {"role": "assistant", "content": "Hello!"}


# --- Auto-retry on ParseError ---

def test_auto_retry_on_parse_error(tmp_db):
    llm = MagicMock()
    # First call returns invalid, second returns valid
    llm.chat.side_effect = [
        "I'm sorry, here is your task",  # not valid JSON
        json.dumps({"action": "none", "task": None, "message": "Hello!"}),
    ]
    history: list = []
    result = handle_turn("hi", history, llm, tmp_db)
    assert result == "Hello!"
    assert llm.chat.call_count == 2


def test_auto_retry_both_fail_raises(tmp_db):
    llm = MagicMock()
    llm.chat.return_value = "This is not JSON at all"
    history: list = []
    with pytest.raises(ParseError):
        handle_turn("hi", history, llm, tmp_db)


# --- Fuzzy find ---

def test_fuzzy_find_exact_match(tmp_db):
    create_task(tmp_db, Task(name="Write report"))
    task_id = _fuzzy_find_task(tmp_db, {"name": "Write report"})
    assert task_id == 1


def test_fuzzy_find_case_insensitive(tmp_db):
    create_task(tmp_db, Task(name="Write Report"))
    task_id = _fuzzy_find_task(tmp_db, {"name": "write report"})
    assert task_id == 1


def test_fuzzy_find_substring(tmp_db):
    create_task(tmp_db, Task(name="Write quarterly report"))
    task_id = _fuzzy_find_task(tmp_db, {"name": "quarterly report"})
    assert task_id == 1


def test_fuzzy_find_no_match(tmp_db):
    create_task(tmp_db, Task(name="Write report"))
    task_id = _fuzzy_find_task(tmp_db, {"name": "buy groceries"})
    assert task_id is None


def test_fuzzy_find_no_name(tmp_db):
    create_task(tmp_db, Task(name="Write report"))
    task_id = _fuzzy_find_task(tmp_db, {"status": "done"})
    assert task_id is None


# --- Auto-advance on done for recurring tasks ---

def test_handle_update_recurring_done_creates_next(tmp_db):
    dt = datetime(2026, 3, 6, 9, 0)
    create_task(tmp_db, Task(name="Daily standup", deadline=dt, recurrence="daily"))
    llm = _mock_llm({
        "action": "update",
        "task": {"id": 1, "status": "done"},
        "message": "Marked standup as done!",
    })
    history: list = []
    result = handle_turn("mark standup done", history, llm, tmp_db)

    # Original task should be done
    original = get_task(tmp_db, 1)
    assert original.status == TaskStatus.DONE

    # Next occurrence should be created
    tasks = list_tasks(tmp_db, status=TaskStatus.PENDING)
    assert len(tasks) == 1
    assert tasks[0].name == "Daily standup"
    assert tasks[0].deadline == datetime(2026, 3, 7, 9, 0)
    assert tasks[0].recurrence == "daily"

    # Result message should mention next occurrence
    assert "next occurrence" in result.lower() or "2026-03-07" in result


def test_handle_update_non_recurring_done_no_next(tmp_db):
    create_task(tmp_db, Task(name="One-off task"))
    llm = _mock_llm({
        "action": "update",
        "task": {"id": 1, "status": "done"},
        "message": "Done!",
    })
    history: list = []
    handle_turn("mark task 1 done", history, llm, tmp_db)

    # Only one task, now done
    all_tasks = list_tasks(tmp_db)
    assert len(all_tasks) == 1
    assert all_tasks[0].status == TaskStatus.DONE


def test_handle_update_already_done_recurring_no_duplicate(tmp_db):
    """Marking an already-done recurring task done again must not create a second occurrence."""
    from kanademinder.db import advance_recurring_task

    dt = datetime(2026, 3, 6, 1, 0)
    task = create_task(tmp_db, Task(name="Shower", deadline=dt, recurrence="daily"))

    # Simulate daemon auto-advancing the task: marks original done, creates pending for 2026-03-07
    advance_recurring_task(tmp_db, task)

    pending_after_daemon = list_tasks(tmp_db, status=TaskStatus.PENDING)
    assert len(pending_after_daemon) == 1
    assert pending_after_daemon[0].deadline == datetime(2026, 3, 7, 1, 0)

    # LLM now tells the handler to mark the original (already-done) task done again
    llm = _mock_llm({
        "action": "update",
        "task": {"id": task.id, "status": "done"},
        "message": "Marked shower as done.",
    })
    handle_turn("今天洗澡已完成", [], llm, tmp_db)

    # Still only one pending occurrence — no duplicate created
    pending_after_chat = list_tasks(tmp_db, status=TaskStatus.PENDING)
    assert len(pending_after_chat) == 1
    assert pending_after_chat[0].deadline == datetime(2026, 3, 7, 1, 0)


# --- Task context injection ---

def test_system_prompt_contains_task_context(tmp_db):
    create_task(tmp_db, Task(name="Existing task", priority=5))
    llm = _mock_llm({
        "action": "none",
        "task": None,
        "message": "Hello!",
    })
    history: list = []
    handle_turn("hi", history, llm, tmp_db)

    # Check that the system prompt sent to LLM contains the existing task
    call_args = llm.chat.call_args[0][0]  # messages list
    system_msg = call_args[0]["content"]
    assert "Existing task" in system_msg
    assert "P5" in system_msg


# --- Ambiguous match ---

def test_fuzzy_find_multiple_candidates_raises_ambiguous(tmp_db):
    create_task(tmp_db, Task(name="Write report Q1"))
    create_task(tmp_db, Task(name="Write report Q2"))
    with pytest.raises(_AmbiguousMatch) as exc_info:
        _fuzzy_find_task(tmp_db, {"name": "write report"})
    assert len(exc_info.value.candidates) == 2


def test_handle_update_ambiguous_returns_candidate_ids(tmp_db):
    create_task(tmp_db, Task(name="Write report Q1"))
    create_task(tmp_db, Task(name="Write report Q2"))
    llm = _mock_llm({
        "action": "update",
        "task": {"name": "write report", "status": "done"},
        "message": "",
    })
    history: list = []
    result = handle_turn("mark write report done", history, llm, tmp_db)
    assert "#1" in result
    assert "#2" in result


# --- Batch create ---

def test_handle_batch_create(tmp_db):
    llm = _mock_llm({
        "action": "create",
        "task": None,
        "tasks": [
            {"name": "Buy milk", "priority": 3},
            {"name": "Call dentist", "priority": 4},
            {"name": "Review slides", "priority": 2},
        ],
        "message": "Created 3 tasks.",
    })
    history: list = []
    result = handle_turn("add 3 tasks: buy milk, call dentist, review slides", history, llm, tmp_db)
    tasks = list_tasks(tmp_db)
    assert len(tasks) == 3
    names = {t.name for t in tasks}
    assert names == {"Buy milk", "Call dentist", "Review slides"}
    assert "3" in result or "Created" in result


def test_handle_batch_create_skips_nameless(tmp_db):
    llm = _mock_llm({
        "action": "create",
        "task": None,
        "tasks": [
            {"name": "Valid task"},
            {"priority": 3},  # no name
        ],
        "message": "Created tasks.",
    })
    history: list = []
    handle_turn("add tasks", history, llm, tmp_db)
    tasks = list_tasks(tmp_db)
    assert len(tasks) == 1
    assert tasks[0].name == "Valid task"


# --- Batch delete ---

def test_handle_batch_delete(tmp_db):
    create_task(tmp_db, Task(name="Task A"))
    create_task(tmp_db, Task(name="Task B"))
    create_task(tmp_db, Task(name="Task C"))
    llm = _mock_llm({
        "action": "delete",
        "task": None,
        "tasks": [{"id": 1}, {"id": 2}],
        "message": "Deleted 2 tasks.",
    })
    history: list = []
    result = handle_turn("delete tasks 1 and 2", history, llm, tmp_db)
    assert get_task(tmp_db, 1) is None
    assert get_task(tmp_db, 2) is None
    assert get_task(tmp_db, 3) is not None
    assert "2" in result or "Deleted" in result


def test_handle_batch_delete_partial_not_found(tmp_db):
    create_task(tmp_db, Task(name="Existing task"))
    llm = _mock_llm({
        "action": "delete",
        "task": None,
        "tasks": [{"id": 1}, {"id": 999}],
        "message": "",
    })
    history: list = []
    result = handle_turn("delete tasks 1 and 999", history, llm, tmp_db)
    assert get_task(tmp_db, 1) is None
    assert "not found" in result.lower() or "skip" in result.lower()


# --- Batch update ---

def test_handle_batch_update_deadline(tmp_db):
    create_task(tmp_db, Task(name="整理gene2gene差异通路的结果"))
    create_task(tmp_db, Task(name="理解gene2gene的算法"))
    llm = _mock_llm({
        "action": "update",
        "task": None,
        "tasks": [
            {"id": 1, "deadline": "2026-03-13T23:59:00"},
            {"id": 2, "deadline": "2026-03-13T23:59:00"},
        ],
        "message": "已将两个gene2gene相关任务延期到3月13日。",
    })
    history: list = []
    result = handle_turn("两个gene2gene任务都要延期到3.13", history, llm, tmp_db)
    task1 = get_task(tmp_db, 1)
    task2 = get_task(tmp_db, 2)
    assert task1.deadline == datetime(2026, 3, 13, 23, 59)
    assert task2.deadline == datetime(2026, 3, 13, 23, 59)
    assert "3月13" in result or "2026-03-13" in result or "Delayed" in result


def test_handle_batch_update_by_name_fuzzy(tmp_db):
    create_task(tmp_db, Task(name="整理gene2gene差异通路的结果"))
    create_task(tmp_db, Task(name="理解gene2gene的算法"))
    llm = _mock_llm({
        "action": "update",
        "task": None,
        "tasks": [
            {"name": "整理gene2gene差异通路的结果", "deadline": "2026-03-13T23:59:00"},
            {"name": "理解gene2gene的算法", "deadline": "2026-03-13T23:59:00"},
        ],
        "message": "",
    })
    history: list = []
    result = handle_turn("把两个gene2gene任务都延期到3月13日", history, llm, tmp_db)
    task1 = get_task(tmp_db, 1)
    task2 = get_task(tmp_db, 2)
    assert task1.deadline == datetime(2026, 3, 13, 23, 59)
    assert task2.deadline == datetime(2026, 3, 13, 23, 59)
    assert "updated" in result.lower() or "#1" in result


# --- Delete parent cascades to children ---

def test_handle_delete_parent_removes_children(tmp_db):
    parent = create_task(tmp_db, Task(name="Parent task"))
    child = create_task(tmp_db, Task(name="Child task", parent_id=parent.id))
    llm = _mock_llm({
        "action": "delete",
        "task": {"id": parent.id},
        "message": "Deleted parent.",
    })
    history: list = []
    handle_turn("delete the parent task", history, llm, tmp_db)
    assert get_task(tmp_db, parent.id) is None
    assert get_task(tmp_db, child.id) is None


# --- parent_name auto-resolution ---

def test_batch_create_with_parent_name_creates_parent(tmp_db):
    """Batch create with parent_name creates parent and links all subtasks."""
    llm = _mock_llm({
        "action": "create",
        "task": None,
        "tasks": [
            {"name": "Get rainy", "parent_name": "AAA", "deadline": "2026-03-06 21:00"},
            {"name": "Get happy", "parent_name": "AAA", "deadline": "2026-03-06 22:00"},
            {"name": "Wash myself", "parent_name": "AAA", "deadline": "2026-03-06 23:00"},
        ],
        "message": "Created project 'AAA' and added 3 subtasks.",
    })
    history: list = []
    result = handle_turn("add three tasks as subtasks of project AAA", history, llm, tmp_db)

    tasks = list_tasks(tmp_db)
    # 4 tasks total: 1 parent + 3 children
    assert len(tasks) == 4
    parent = next(t for t in tasks if t.name == "AAA")
    children = [t for t in tasks if t.name != "AAA"]
    assert len(children) == 3
    assert all(c.parent_id == parent.id for c in children)
    child_names = {c.name for c in children}
    assert child_names == {"Get rainy", "Get happy", "Wash myself"}


def test_batch_create_with_parent_name_reuses_existing_parent(tmp_db):
    """If parent already exists, parent_name links to it without creating a duplicate."""
    from kanademinder.db import create_task as db_create
    from kanademinder.models import Task
    existing_parent = db_create(tmp_db, Task(name="AAA"))

    llm = _mock_llm({
        "action": "create",
        "task": None,
        "tasks": [
            {"name": "Child A", "parent_name": "AAA"},
            {"name": "Child B", "parent_name": "AAA"},
        ],
        "message": "Added subtasks under AAA.",
    })
    history: list = []
    handle_turn("add subtasks to AAA", history, llm, tmp_db)

    tasks = list_tasks(tmp_db)
    # Still only 1 parent (no duplicate), plus 2 children
    parents = [t for t in tasks if t.name == "AAA"]
    assert len(parents) == 1
    children = [t for t in tasks if t.parent_id == existing_parent.id]
    assert len(children) == 2


def test_single_create_with_parent_name(tmp_db):
    """Single create with parent_name creates parent and links the child."""
    llm = _mock_llm({
        "action": "create",
        "task": {"name": "Write spec", "parent_name": "Project X"},
        "message": "Created subtask under Project X.",
    })
    history: list = []
    handle_turn("add write spec as subtask of Project X", history, llm, tmp_db)

    tasks = list_tasks(tmp_db)
    assert len(tasks) == 2
    parent = next(t for t in tasks if t.name == "Project X")
    child = next(t for t in tasks if t.name == "Write spec")
    assert child.parent_id == parent.id


def test_batch_create_reuses_orphan_tasks_instead_of_duplicating(tmp_db):
    """When orphan tasks already exist with the same names, batch create with
    parent_name updates them rather than inserting duplicates."""
    # Pre-existing orphan tasks (from a prior broken session)
    orphan1 = create_task(tmp_db, Task(name="Get rainy"))
    orphan2 = create_task(tmp_db, Task(name="Get happy"))
    orphan3 = create_task(tmp_db, Task(name="Wash myself"))

    llm = _mock_llm({
        "action": "create",
        "task": None,
        "tasks": [
            {"name": "Get rainy", "parent_name": "AAA", "deadline": "2026-03-06 21:00"},
            {"name": "Get happy", "parent_name": "AAA", "deadline": "2026-03-06 22:00"},
            {"name": "Wash myself", "parent_name": "AAA", "deadline": "2026-03-06 23:00"},
        ],
        "message": "Linked 3 tasks under project AAA.",
    })
    history: list = []
    handle_turn("add tasks as subtasks of project AAA", history, llm, tmp_db)

    tasks = list_tasks(tmp_db)
    # Exactly 4 tasks: AAA parent + 3 original orphans (updated, not duplicated)
    assert len(tasks) == 4
    aaa = next(t for t in tasks if t.name == "AAA")
    children = [t for t in tasks if t.parent_id == aaa.id]
    assert len(children) == 3
    # The original task IDs must have been reused, not new ones created
    child_ids = {c.id for c in children}
    assert child_ids == {orphan1.id, orphan2.id, orphan3.id}


# --- Subtask type defaulting ---

def test_subtask_defaults_to_minor_type(tmp_db):
    """Tasks with a parent_id default to 'minor' even when type is omitted."""
    parent = create_task(tmp_db, Task(name="Project AAA"))
    llm = _mock_llm({
        "action": "create",
        "task": None,
        "tasks": [
            {"name": "Get rainy", "parent_name": "Project AAA", "deadline": "2026-03-06 21:00"},
            {"name": "Get happy", "parent_name": "Project AAA", "deadline": "2026-03-06 22:00"},
        ],
        "message": "Created subtasks.",
    })
    history: list = []
    handle_turn("add subtasks", history, llm, tmp_db)

    from kanademinder.models import TaskType
    tasks = list_tasks(tmp_db)
    children = [t for t in tasks if t.parent_id == parent.id]
    assert len(children) == 2
    assert all(c.type == TaskType.MINOR for c in children)


def test_top_level_task_keeps_major_default(tmp_db):
    """Top-level tasks (no parent) still default to the configured type."""
    llm = _mock_llm({
        "action": "create",
        "task": {"name": "Big project"},
        "message": "Created.",
    })
    history: list = []
    handle_turn("add big project", history, llm, tmp_db)

    from kanademinder.models import TaskType
    tasks = list_tasks(tmp_db)
    assert tasks[0].type == TaskType.MAJOR


# --- Recurring task without deadline warning ---

def test_handle_create_recurring_no_deadline_warns(tmp_db):
    llm = _mock_llm({
        "action": "create",
        "task": {"name": "Water plants", "recurrence": "weekly"},
        "message": "Created recurring task.",
    })
    history: list = []
    result = handle_turn("water plants every week", history, llm, tmp_db)
    assert "deadline" in result.lower()
    # Task should still be created
    tasks = list_tasks(tmp_db)
    assert len(tasks) == 1
    assert tasks[0].recurrence == "weekly"


# --- Cascade done to children ---

def test_handle_update_done_cascades_to_children(tmp_db):
    parent = create_task(tmp_db, Task(name="Parent task", priority=3))
    child1 = create_task(tmp_db, Task(name="Child 1", priority=2, parent_id=parent.id))
    child2 = create_task(tmp_db, Task(name="Child 2", priority=2, parent_id=parent.id))

    llm = _mock_llm({
        "action": "update",
        "task": {"id": parent.id, "status": "done"},
        "message": "Marked parent done.",
    })
    handle_turn("mark parent task done", [], llm, tmp_db)

    assert get_task(tmp_db, parent.id).status == TaskStatus.DONE
    assert get_task(tmp_db, child1.id).status == TaskStatus.DONE
    assert get_task(tmp_db, child2.id).status == TaskStatus.DONE


def test_handle_update_done_does_not_affect_sibling(tmp_db):
    parent_a = create_task(tmp_db, Task(name="Parent A", priority=3))
    child_a = create_task(tmp_db, Task(name="Child of A", priority=2, parent_id=parent_a.id))
    parent_b = create_task(tmp_db, Task(name="Parent B", priority=3))
    child_b = create_task(tmp_db, Task(name="Child of B", priority=2, parent_id=parent_b.id))

    llm = _mock_llm({
        "action": "update",
        "task": {"id": parent_a.id, "status": "done"},
        "message": "Marked Parent A done.",
    })
    handle_turn("mark Parent A done", [], llm, tmp_db)

    assert get_task(tmp_db, parent_a.id).status == TaskStatus.DONE
    assert get_task(tmp_db, child_a.id).status == TaskStatus.DONE
    # Parent B and its child are unaffected
    assert get_task(tmp_db, parent_b.id).status == TaskStatus.PENDING
    assert get_task(tmp_db, child_b.id).status == TaskStatus.PENDING
