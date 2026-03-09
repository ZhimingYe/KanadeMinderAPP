"""Tests for llm/parser.py — including normalization and robustness."""

from __future__ import annotations

import json

import pytest

from kanademinder.llm.parser import ParseError, _balanced_extract, parse_task_action


def _json(obj: dict) -> str:
    return json.dumps(obj)


# --- Happy path: all action types ---

def test_parse_create_action():
    raw = _json({
        "action": "create",
        "task": {"name": "Write report", "priority": 4},
        "message": "Got it! I'll create that task.",
    })
    result = parse_task_action(raw)
    assert result["action"] == "create"
    assert result["task"]["name"] == "Write report"
    assert "Got it" in result["message"]


def test_parse_update_action():
    raw = _json({
        "action": "update",
        "task": {"id": 7, "status": "done"},
        "message": "Marked as done.",
    })
    result = parse_task_action(raw)
    assert result["action"] == "update"
    assert result["task"]["id"] == 7


def test_parse_delete_action():
    raw = _json({
        "action": "delete",
        "task": {"id": 3},
        "message": "Deleted task 3.",
    })
    result = parse_task_action(raw)
    assert result["action"] == "delete"


def test_parse_query_action():
    raw = _json({
        "action": "query",
        "task": None,
        "message": "Here are your tasks:",
    })
    result = parse_task_action(raw)
    assert result["action"] == "query"
    assert result["task"] is None


def test_parse_clarify_action():
    raw = _json({
        "action": "clarify",
        "task": None,
        "message": "What deadline should I set?",
    })
    result = parse_task_action(raw)
    assert result["action"] == "clarify"


def test_parse_none_action():
    raw = _json({
        "action": "none",
        "task": None,
        "message": "Sure, let me know if you need anything.",
    })
    result = parse_task_action(raw)
    assert result["action"] == "none"


# --- JSON embedded in extra text ---

def test_parse_json_embedded_in_text():
    raw = 'Sure! Here is the response: {"action": "create", "task": {"name": "Buy milk"}, "message": "Added."}'
    result = parse_task_action(raw)
    assert result["action"] == "create"
    assert result["task"]["name"] == "Buy milk"


def test_parse_json_with_leading_trailing_whitespace():
    raw = '  \n  {"action": "none", "task": null, "message": "OK"}  \n  '
    result = parse_task_action(raw)
    assert result["action"] == "none"


def test_parse_json_in_markdown_code_fence():
    raw = '```json\n{"action": "create", "task": {"name": "Test"}, "message": "Created."}\n```'
    result = parse_task_action(raw)
    assert result["action"] == "create"
    assert result["task"]["name"] == "Test"


def test_parse_json_in_code_fence_no_lang():
    raw = '```\n{"action": "none", "task": null, "message": "Hi"}\n```'
    result = parse_task_action(raw)
    assert result["action"] == "none"


# --- Error cases ---

def test_parse_error_invalid_action():
    raw = _json({"action": "fly", "task": None, "message": "Oops"})
    with pytest.raises(ParseError, match="Invalid or missing action"):
        parse_task_action(raw)


def test_parse_error_missing_action():
    raw = _json({"task": None, "message": "No action field"})
    with pytest.raises(ParseError, match="Invalid or missing action"):
        parse_task_action(raw)


def test_parse_error_no_json():
    with pytest.raises(ParseError, match="No JSON object found"):
        parse_task_action("This is plain text, no JSON here.")


def test_parse_error_malformed_json():
    with pytest.raises(ParseError):
        parse_task_action("{action: create, broken}")


def test_parse_error_task_not_dict():
    raw = _json({"action": "create", "task": "should be dict", "message": "hmm"})
    with pytest.raises(ParseError, match="'task' must be an object or null"):
        parse_task_action(raw)


def test_parse_missing_message_defaults_to_empty():
    raw = _json({"action": "none", "task": None})
    result = parse_task_action(raw)
    assert result["message"] == ""


def test_parse_empty_string():
    with pytest.raises(ParseError):
        parse_task_action("")


# --- Normalization: status aliases ---

def test_normalize_status_completed():
    raw = _json({"action": "update", "task": {"id": 1, "status": "completed"}, "message": "Done"})
    result = parse_task_action(raw)
    assert result["task"]["status"] == "done"


def test_normalize_status_in_progress_space():
    raw = _json({"action": "update", "task": {"id": 1, "status": "in progress"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["status"] == "in_progress"


def test_normalize_status_finished():
    raw = _json({"action": "update", "task": {"id": 1, "status": "Finished"}, "message": "Done"})
    result = parse_task_action(raw)
    assert result["task"]["status"] == "done"


def test_normalize_status_todo():
    raw = _json({"action": "update", "task": {"id": 1, "status": "todo"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["status"] == "pending"


def test_normalize_status_invalid_dropped():
    raw = _json({"action": "update", "task": {"id": 1, "status": "banana"}, "message": "OK"})
    result = parse_task_action(raw)
    assert "status" not in result["task"]


# --- Normalization: priority ---

def test_normalize_priority_clamped_high():
    raw = _json({"action": "create", "task": {"name": "Test", "priority": 10}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["priority"] == 5


def test_normalize_priority_clamped_low():
    raw = _json({"action": "create", "task": {"name": "Test", "priority": -1}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["priority"] == 1


def test_normalize_priority_string():
    raw = _json({"action": "create", "task": {"name": "Test", "priority": "4"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["priority"] == 4


def test_normalize_priority_invalid_dropped():
    raw = _json({"action": "create", "task": {"name": "Test", "priority": "high"}, "message": "OK"})
    result = parse_task_action(raw)
    assert "priority" not in result["task"]


# --- Normalization: type ---

def test_normalize_type_case_insensitive():
    raw = _json({"action": "create", "task": {"name": "Test", "type": "MAJOR"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["type"] == "major"


def test_normalize_type_invalid_dropped():
    raw = _json({"action": "create", "task": {"name": "Test", "type": "huge"}, "message": "OK"})
    result = parse_task_action(raw)
    assert "type" not in result["task"]


# --- Normalization: name ---

def test_normalize_name_strips_whitespace():
    raw = _json({"action": "create", "task": {"name": "  Buy milk  "}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["name"] == "Buy milk"


def test_normalize_name_empty_dropped():
    raw = _json({"action": "create", "task": {"name": "   "}, "message": "OK"})
    result = parse_task_action(raw)
    assert "name" not in result["task"]


# --- Normalization: id ---

def test_normalize_id_string_to_int():
    raw = _json({"action": "update", "task": {"id": "5", "status": "done"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["id"] == 5


def test_normalize_id_invalid_dropped():
    raw = _json({"action": "update", "task": {"id": "abc", "status": "done"}, "message": "OK"})
    result = parse_task_action(raw)
    assert "id" not in result["task"]


# --- Normalization: deadline ---

def test_normalize_deadline_null_string():
    raw = _json({"action": "create", "task": {"name": "Test", "deadline": "null"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["deadline"] is None


def test_normalize_deadline_none_string():
    raw = _json({"action": "create", "task": {"name": "Test", "deadline": "None"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["deadline"] is None


def test_normalize_deadline_us_format():
    raw = _json({"action": "create", "task": {"name": "Test", "deadline": "03/15/2026"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["deadline"] == "2026-03-15T00:00:00"


def test_normalize_deadline_datetime_with_time():
    raw = _json({"action": "create", "task": {"name": "Test", "deadline": "2026-03-10T14:30"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["deadline"] == "2026-03-10T14:30:00"


def test_normalize_deadline_datetime_space_separator():
    raw = _json({"action": "create", "task": {"name": "Test", "deadline": "2026-03-10 09:00"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["deadline"] == "2026-03-10T09:00:00"


def test_normalize_deadline_date_only_becomes_midnight_iso():
    raw = _json({"action": "create", "task": {"name": "Test", "deadline": "2026-06-01"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["deadline"] == "2026-06-01T00:00:00"


# --- Normalization: recurrence ---

def test_normalize_recurrence_valid():
    raw = _json({"action": "create", "task": {"name": "Test", "recurrence": "daily"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["recurrence"] == "daily"


def test_normalize_recurrence_alias_every_day():
    raw = _json({"action": "create", "task": {"name": "Test", "recurrence": "every day"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["recurrence"] == "daily"


def test_normalize_recurrence_alias_every_week():
    raw = _json({"action": "create", "task": {"name": "Test", "recurrence": "every week"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["recurrence"] == "weekly"


def test_normalize_recurrence_alias_annually():
    raw = _json({"action": "create", "task": {"name": "Test", "recurrence": "annually"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["recurrence"] == "yearly"


def test_normalize_recurrence_invalid_becomes_none():
    raw = _json({"action": "create", "task": {"name": "Test", "recurrence": "biweekly"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["recurrence"] is None


def test_normalize_recurrence_weekdays_alias():
    raw = _json({"action": "create", "task": {"name": "Test", "recurrence": "every weekday"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["recurrence"] == "weekdays"


# --- Normalization: estimated_minutes ---

def test_normalize_estimated_minutes_valid():
    raw = _json({"action": "create", "task": {"name": "Test", "estimated_minutes": "45"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["estimated_minutes"] == 45


def test_normalize_estimated_minutes_invalid():
    raw = _json({"action": "create", "task": {"name": "Test", "estimated_minutes": "lots"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["estimated_minutes"] is None


# --- Action case insensitivity ---

def test_action_case_insensitive():
    raw = _json({"action": "Create", "task": {"name": "Test"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["action"] == "create"


def test_action_uppercase():
    raw = _json({"action": "QUERY", "task": None, "message": "OK"})
    result = parse_task_action(raw)
    assert result["action"] == "query"


# --- Message coercion ---

def test_message_non_string_coerced():
    raw = _json({"action": "none", "task": None, "message": 42})
    result = parse_task_action(raw)
    assert result["message"] == "42"


def test_message_null_becomes_empty():
    raw = _json({"action": "none", "task": None, "message": None})
    result = parse_task_action(raw)
    assert result["message"] == ""


# --- Balanced-brace extraction ---

def test_balanced_extract_trailing_brace_in_text():
    """Extra } after the JSON object should not corrupt extraction."""
    text = 'Some text {"action": "none", "task": null, "message": "Hi"} extra } brace'
    result = _balanced_extract(text)
    assert result == '{"action": "none", "task": null, "message": "Hi"}'
    # Should be valid JSON
    parsed = json.loads(result)
    assert parsed["action"] == "none"


def test_balanced_extract_no_object_returns_none():
    assert _balanced_extract("no braces here") is None


def test_balanced_extract_json_in_explanatory_text():
    """LLM wraps reply with extra explanation containing braces."""
    text = 'Sure! Here you go: {"action": "create", "task": {"name": "Test"}, "message": "Done."} Hope that helps!'
    result = parse_task_action(text)
    assert result["action"] == "create"
    assert result["task"]["name"] == "Test"


# --- New status aliases ---

def test_normalize_status_on_hold():
    raw = _json({"action": "update", "task": {"id": 1, "status": "on hold"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["status"] == "pending"


def test_normalize_status_paused():
    raw = _json({"action": "update", "task": {"id": 1, "status": "paused"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["status"] == "pending"


# --- New recurrence aliases ---

def test_normalize_recurrence_mon_fri():
    raw = _json({"action": "create", "task": {"name": "Standup", "recurrence": "mon-fri"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["recurrence"] == "weekdays"


def test_normalize_recurrence_monday_through_friday():
    raw = _json({"action": "create", "task": {"name": "Standup", "recurrence": "monday through friday"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["recurrence"] == "weekdays"


# --- Deadline parse warning ---

def test_normalize_deadline_unparseable_adds_warning():
    raw = _json({"action": "create", "task": {"name": "Test", "deadline": "next quarter"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result["task"]["deadline"] is None
    assert result["task"].get("_deadline_parse_warning") == "next quarter"


# --- Batch tasks array ---

def test_parse_tasks_array_create():
    raw = _json({
        "action": "create",
        "task": None,
        "tasks": [
            {"name": "Buy milk", "priority": 3},
            {"name": "Call dentist", "priority": 4},
        ],
        "message": "Created 2 tasks.",
    })
    result = parse_task_action(raw)
    assert result["action"] == "create"
    assert result["task"] is None
    assert result["tasks"] is not None
    assert len(result["tasks"]) == 2
    assert result["tasks"][0]["name"] == "Buy milk"
    assert result["tasks"][1]["name"] == "Call dentist"


def test_parse_tasks_array_delete():
    raw = _json({
        "action": "delete",
        "task": None,
        "tasks": [{"id": 1}, {"id": 3}],
        "message": "Deleted 2 tasks.",
    })
    result = parse_task_action(raw)
    assert result["action"] == "delete"
    assert result["tasks"] is not None
    assert result["tasks"][0]["id"] == 1
    assert result["tasks"][1]["id"] == 3


def test_parse_tasks_array_normalizes_each_item():
    raw = _json({
        "action": "create",
        "task": None,
        "tasks": [
            {"name": "  Trim name  ", "priority": "10"},
            {"name": "Another", "status": "completed"},
        ],
        "message": "OK",
    })
    result = parse_task_action(raw)
    assert result["tasks"][0]["name"] == "Trim name"
    assert result["tasks"][0]["priority"] == 5  # clamped
    assert result["tasks"][1]["status"] == "done"  # alias resolved


def test_parse_tasks_array_not_list_raises():
    raw = _json({
        "action": "create",
        "task": None,
        "tasks": "should be a list",
        "message": "OK",
    })
    with pytest.raises(ParseError, match="'tasks' must be an array or null"):
        parse_task_action(raw)


def test_parse_tasks_absent_gives_none():
    raw = _json({"action": "create", "task": {"name": "Single"}, "message": "OK"})
    result = parse_task_action(raw)
    assert result.get("tasks") is None
