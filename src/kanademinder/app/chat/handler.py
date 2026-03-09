"""handle_turn(): orchestrates one KanadeMinder conversation turn.

Wires the LLM, parser, and DB action handlers together.
"""

from __future__ import annotations

import sqlite3

from kanademinder.db import list_tasks
from kanademinder.llm.client import LLMClient
from kanademinder.llm.parser import ParseError, parse_task_action

from kanademinder.app.chat.actions import (
    _format_task_list,
    _handle_batch_create,
    _handle_batch_delete,
    _handle_create,
    _handle_delete,
    _handle_update,
)
from kanademinder.app.chat.prompts import build_conversation_system_prompt

QUERY_RESPONSE_SENTINEL = "\x00QUERY\x00"
QUERY_PREAMBLE_SEP = "\x00TASKS\x00"

_LIST_VERBS = frozenset({"list", "show", "display", "view", "see", "get"})
_TASK_NOUNS = frozenset({"task", "tasks", "todo", "todos"})


def _is_list_intent(user_input: str) -> bool:
    """Return True if the user is clearly asking to see their task list."""
    words = set(user_input.lower().split())
    return bool(words & _LIST_VERBS) and bool(words & _TASK_NOUNS)


def handle_turn(
    user_input: str,
    history: list[dict[str, str]],
    llm: LLMClient,
    conn: sqlite3.Connection,
    default_task_type: str = "major",
) -> str:
    """Process one conversation turn.

    Appends user message to history, calls LLM with current task context,
    parses response, dispatches to DB, returns the assistant's confirmation
    string (also appended to history).

    On ParseError, automatically retries once with a correction hint.
    Raises LLMError on network/API failure.
    """
    history.append({"role": "user", "content": user_input})

    # Inject current task state so LLM can reference existing tasks
    current_tasks = list_tasks(conn)
    system_prompt = build_conversation_system_prompt(
        default_task_type=default_task_type,
        tasks=current_tasks,
    )
    messages = [{"role": "system", "content": system_prompt}] + history

    raw = llm.chat(messages, json_mode=True)

    # Parse with one auto-retry on failure
    try:
        action_obj = parse_task_action(raw)
    except ParseError:
        # Retry: send a correction hint
        retry_messages = messages + [
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    "Your previous response was not valid JSON. "
                    "Please respond with ONLY a JSON object with keys: "
                    '"action", "task", "message". No other text.'
                ),
            },
        ]
        raw = llm.chat(retry_messages, json_mode=True)
        action_obj = parse_task_action(raw)  # let ParseError propagate on second failure

    action = action_obj["action"]
    task_data = action_obj.get("task")
    tasks_data = action_obj.get("tasks")
    message = action_obj.get("message", "")

    # Safety net: LLM sometimes returns "none" for explicit listing requests,
    # causing the web frontend to show a plain-text response instead of the
    # structured task table.  Override to "query" so the sentinel is always
    # emitted and is_query=true reaches the JS renderer.
    if action == "none" and _is_list_intent(user_input):
        action = "query"
        message = ""

    if action == "create":
        if tasks_data:
            message = _handle_batch_create(conn, tasks_data, default_task_type, message)
        elif task_data:
            message = _handle_create(conn, task_data, default_task_type, message)

    elif action == "update" and task_data:
        message = _handle_update(conn, task_data, message)

    elif action == "delete":
        if tasks_data:
            message = _handle_batch_delete(conn, tasks_data, message)
        elif task_data:
            message = _handle_delete(conn, task_data, message)

    elif action == "query":
        tasks = list_tasks(conn)
        task_list_str = _format_task_list(tasks)
        llm_prefix = f"{message}\n" if message else ""
        # Store only the friendly message in history — the task list is already injected
        # fresh via the system prompt on every turn; storing the sentinel + full list
        # would send garbage (\x00QUERY\x00) back to the LLM and confuse it.
        history_message = message or "Here are your tasks."
        message = f"{QUERY_RESPONSE_SENTINEL}{llm_prefix}{QUERY_PREAMBLE_SEP}{task_list_str}"
        history.append({"role": "assistant", "content": history_message})
        return message

    # "clarify" and "none" — use the LLM message as-is

    history.append({"role": "assistant", "content": message})
    return message
