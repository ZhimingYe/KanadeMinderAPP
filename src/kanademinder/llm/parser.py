"""JSON extraction and TaskAction parsing with robust normalization."""

from __future__ import annotations

import json
import re
from datetime import datetime


def _balanced_extract(text: str) -> str | None:
    """Return the first balanced JSON object substring, or None."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(text[start:], start=start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None
from typing import Any, Literal, TypedDict


class ParseError(Exception):
    """Raised when the LLM response cannot be parsed into a valid TaskAction."""


class TaskAction(TypedDict, total=False):
    action: Literal["create", "update", "delete", "query", "clarify", "none"]
    task: dict[str, Any] | None
    tasks: list[dict[str, Any]] | None
    message: str


_VALID_ACTIONS = frozenset({"create", "update", "delete", "query", "clarify", "none"})

_VALID_TYPES = {"major", "minor"}
_VALID_STATUSES = {"pending", "in_progress", "done"}

# Status aliases LLMs commonly produce
_STATUS_ALIASES: dict[str, str] = {
    "in progress": "in_progress",
    "inprogress": "in_progress",
    "in-progress": "in_progress",
    "completed": "done",
    "complete": "done",
    "finished": "done",
    "todo": "pending",
    "not started": "pending",
    "not_started": "pending",
    "on hold": "pending",
    "paused": "pending",
    "open": "pending",
    "blocked": "pending",
}

# Recurrence aliases LLMs commonly produce
_RECURRENCE_ALIASES: dict[str, str] = {
    "every day": "daily",
    "everyday": "daily",
    "each day": "daily",
    "every weekday": "weekdays",
    "weekdays": "weekdays",
    "every week": "weekly",
    "each week": "weekly",
    "every month": "monthly",
    "each month": "monthly",
    "every year": "yearly",
    "each year": "yearly",
    "annually": "yearly",
    "mon-fri": "weekdays",
    "monday to friday": "weekdays",
    "monday through friday": "weekdays",
    "each weekday": "weekdays",
}
_VALID_RECURRENCES = {"daily", "weekdays", "weekly", "monthly", "yearly"}

# Deadline formats tried in order; date-only formats produce midnight datetimes
_DEADLINE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%B %d, %Y",
    "%b %d, %Y",
)


def _extract_json(text: str) -> dict[str, Any]:
    """Extract the first JSON object from text. Raises ParseError if none found."""
    text = text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
        text = text.strip()

    # Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to extract balanced JSON object
    extracted = _balanced_extract(text)
    if extracted is None:
        raise ParseError(f"No JSON object found in response: {text[:200]!r}")
    try:
        return json.loads(extracted)
    except json.JSONDecodeError as exc:
        raise ParseError(f"Invalid JSON in response: {exc}") from exc


def _normalize_task(task: dict[str, Any]) -> dict[str, Any]:
    """Normalize LLM-produced task fields to canonical values."""
    normalized = dict(task)

    # Normalize name: strip whitespace
    if "name" in normalized and isinstance(normalized["name"], str):
        normalized["name"] = normalized["name"].strip()
        if not normalized["name"]:
            del normalized["name"]

    # Normalize type: case-insensitive
    if "type" in normalized and isinstance(normalized["type"], str):
        t = normalized["type"].strip().lower()
        if t in _VALID_TYPES:
            normalized["type"] = t
        else:
            del normalized["type"]  # drop invalid, will use default

    # Normalize status: case-insensitive + aliases
    if "status" in normalized and isinstance(normalized["status"], str):
        s = normalized["status"].strip().lower()
        s = _STATUS_ALIASES.get(s, s)
        if s in _VALID_STATUSES:
            normalized["status"] = s
        else:
            del normalized["status"]

    # Normalize priority: clamp to 1–5, handle string input
    if "priority" in normalized:
        try:
            p = int(normalized["priority"])
            normalized["priority"] = max(1, min(5, p))
        except (ValueError, TypeError):
            del normalized["priority"]

    # Normalize id: ensure integer
    if "id" in normalized:
        try:
            normalized["id"] = int(normalized["id"])
        except (ValueError, TypeError):
            del normalized["id"]

    # Normalize parent_id: ensure integer or None
    if "parent_id" in normalized:
        if normalized["parent_id"] is None:
            pass
        else:
            try:
                normalized["parent_id"] = int(normalized["parent_id"])
            except (ValueError, TypeError):
                normalized["parent_id"] = None

    # Normalize estimated_minutes: ensure integer
    if "estimated_minutes" in normalized:
        if normalized["estimated_minutes"] is None:
            pass
        else:
            try:
                normalized["estimated_minutes"] = max(1, int(normalized["estimated_minutes"]))
            except (ValueError, TypeError):
                normalized["estimated_minutes"] = None

    # Normalize deadline: accept date-only and datetime formats → ISO string
    if "deadline" in normalized and normalized["deadline"] is not None:
        d = normalized["deadline"]
        if isinstance(d, str):
            d = d.strip()
            if not d or d.lower() in ("null", "none", "n/a", ""):
                normalized["deadline"] = None
            else:
                parsed_dt: datetime | None = None
                for fmt in _DEADLINE_FORMATS:
                    try:
                        parsed_dt = datetime.strptime(d, fmt)
                        break
                    except ValueError:
                        continue
                if parsed_dt is not None:
                    normalized["deadline"] = parsed_dt.isoformat()
                else:
                    normalized["deadline"] = None
                    normalized["_deadline_parse_warning"] = d

    # Normalize recurrence: aliases + validation
    if "recurrence" in normalized and isinstance(normalized["recurrence"], str):
        r = normalized["recurrence"].strip().lower()
        r = _RECURRENCE_ALIASES.get(r, r)
        normalized["recurrence"] = r if r in _VALID_RECURRENCES else None
    elif "recurrence" in normalized and normalized["recurrence"] is not None:
        normalized["recurrence"] = None

    # Normalize recurrence_end: accept YYYY-MM-DD strings only
    if "recurrence_end" in normalized and normalized["recurrence_end"] is not None:
        re_val = normalized["recurrence_end"]
        if isinstance(re_val, str):
            re_val = re_val.strip()
            if not re_val or re_val.lower() in ("null", "none"):
                normalized["recurrence_end"] = None
            else:
                try:
                    from datetime import date
                    date.fromisoformat(re_val)
                    normalized["recurrence_end"] = re_val  # keep as ISO string
                except ValueError:
                    normalized["recurrence_end"] = None
        else:
            normalized["recurrence_end"] = None

    return normalized


def parse_task_action(raw: str) -> TaskAction:
    """Parse raw LLM output into a validated TaskAction.

    Normalizes task field values for robustness against LLM format variations.
    Raises ParseError for structurally invalid responses.
    """
    data = _extract_json(raw)

    action = data.get("action")
    if isinstance(action, str):
        action = action.strip().lower()
    if action not in _VALID_ACTIONS:
        raise ParseError(
            f"Invalid or missing action: {action!r}. Must be one of {sorted(_VALID_ACTIONS)}"
        )

    message = data.get("message", "")
    if not isinstance(message, str):
        message = str(message) if message is not None else ""

    task_data = data.get("task")
    if task_data is not None and not isinstance(task_data, dict):
        raise ParseError(f"'task' must be an object or null, got {type(task_data).__name__}")

    if task_data is not None:
        task_data = _normalize_task(task_data)

    tasks_data = data.get("tasks")
    if tasks_data is not None:
        if not isinstance(tasks_data, list):
            raise ParseError(f"'tasks' must be an array or null, got {type(tasks_data).__name__}")
        tasks_data = [_normalize_task(t) for t in tasks_data if isinstance(t, dict)]

    return TaskAction(action=action, task=task_data, tasks=tasks_data, message=message)
