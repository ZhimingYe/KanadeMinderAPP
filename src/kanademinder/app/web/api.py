"""KanadeMinder web API route handlers.

Each handler receives ``(conn, llm, state, body_bytes)`` and returns
``(status, content_type, body_bytes)``.

``state`` is a mutable dict held in the router closure:
  - ``history``       : list[dict]   — chat history
  - ``last_tick``     : str | None   — ISO datetime of last daemon tick
  - ``last_notifications``: list[dict] | None — notifications from last tick
"""

from __future__ import annotations

import json
import sqlite3
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

MAX_WEB_HISTORY = 40

from kanademinder.db import list_tasks
from kanademinder.llm.client import LLMClient
from kanademinder.models import TaskStatus
from kanademinder.app.chat.handler import handle_turn, QUERY_RESPONSE_SENTINEL, QUERY_PREAMBLE_SEP
from kanademinder.app.daemon.scheduler import build_kanademinder_notifications
from kanademinder.app.daemon.notifications import _MAX_SUGGESTION
from kanademinder.app.daemon.prompts import SCHEDULING_SYSTEM_PROMPT, build_scheduling_user_message

from kanademinder.app.web.frontend import get_frontend_html


def _json(data: Any, status: int = 200) -> tuple[int, str, bytes]:
    return status, "application/json", json.dumps(data).encode()


def _task_to_dict(task: Any) -> dict:
    return {
        "id": task.id,
        "name": task.name,
        "type": task.type.value,
        "priority": task.priority,
        "status": task.status.value,
        "deadline": task.deadline.isoformat() if task.deadline else None,
        "estimated_minutes": task.estimated_minutes,
        "notes": task.notes,
        "recurrence": task.recurrence,
        "recurrence_end": task.recurrence_end.isoformat() if task.recurrence_end else None,
        "parent_id": task.parent_id,
    }


_REPORT_PATH = Path.home() / ".kanademinder" / "summary.html"


def serve_report(
    conn: sqlite3.Connection,
    llm: LLMClient,
    state: dict,
    body: bytes,
) -> tuple[int, str, bytes]:
    if not _REPORT_PATH.exists():
        return 404, "text/plain; charset=utf-8", b"Report not found. Run a daemon tick first."
    return 200, "text/html; charset=utf-8", _REPORT_PATH.read_bytes()


def serve_frontend(
    conn: sqlite3.Connection,
    llm: LLMClient,
    state: dict,
    body: bytes,
) -> tuple[int, str, bytes]:
    return 200, "text/html; charset=utf-8", get_frontend_html().encode()


def list_tasks_handler(
    conn: sqlite3.Connection,
    llm: LLMClient,
    state: dict,
    body: bytes,
) -> tuple[int, str, bytes]:
    tasks = list_tasks(conn)
    return _json([_task_to_dict(t) for t in tasks])


def chat_turn(
    conn: sqlite3.Connection,
    llm: LLMClient,
    state: dict,
    body: bytes,
) -> tuple[int, str, bytes]:
    try:
        payload = json.loads(body.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json({"error": "Invalid JSON body"}, 400)

    message = payload.get("message", "").strip()
    if not message:
        return _json({"error": "message field is required"}, 400)

    history: list[dict] = state.setdefault("history", [])
    if len(history) > MAX_WEB_HISTORY:
        del history[:len(history) - MAX_WEB_HISTORY]

    try:
        response = handle_turn(message, history, llm, conn)
    except Exception:  # noqa: BLE001
        traceback.print_exc(file=sys.stderr)
        return _json({"error": "Internal server error"}, 500)

    is_query = response.startswith(QUERY_RESPONSE_SENTINEL)
    if is_query:
        body = response[len(QUERY_RESPONSE_SENTINEL):]
        parts = body.split(QUERY_PREAMBLE_SEP, 1)
        response = parts[0].strip() if len(parts) > 1 else ""

    tasks = list_tasks(conn)
    return _json({
        "response": response,
        "is_query": is_query,
        "tasks": [_task_to_dict(t) for t in tasks],
    })


def get_suggestion(
    conn: sqlite3.Connection,
    llm: LLMClient,
    state: dict,
    body: bytes,
) -> tuple[int, str, bytes]:
    now = datetime.now()
    tasks = (
        list_tasks(conn, status=TaskStatus.PENDING)
        + list_tasks(conn, status=TaskStatus.IN_PROGRESS)
    )
    if not tasks:
        return _json({"suggestion": None, "generated_at": now.isoformat()})
    user_message = build_scheduling_user_message(tasks, "23:59", now)
    messages = [
        {"role": "system", "content": SCHEDULING_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]
    try:
        suggestion = llm.chat(messages)
    except Exception:  # noqa: BLE001
        traceback.print_exc(file=sys.stderr)
        return _json({"error": "Internal server error"}, 500)
    if len(suggestion) > _MAX_SUGGESTION:
        suggestion = suggestion[:_MAX_SUGGESTION].rsplit(" ", 1)[0] + "…"
    return _json({"suggestion": suggestion, "generated_at": now.isoformat()})


def daemon_status(
    conn: sqlite3.Connection,
    llm: LLMClient,
    state: dict,
    body: bytes,
) -> tuple[int, str, bytes]:
    return _json({
        "last_tick": state.get("last_tick"),
        "last_notifications": state.get("last_notifications"),
    })


def daemon_tick(
    conn: sqlite3.Connection,
    llm: LLMClient,
    state: dict,
    body: bytes,
) -> tuple[int, str, bytes]:
    now = datetime.now()
    try:
        notifications = build_kanademinder_notifications(
            llm,
            conn,
            end_of_day="23:59",
            notification_mode="banner",
            now=now,
        )
    except Exception:  # noqa: BLE001
        traceback.print_exc(file=sys.stderr)
        return _json({"error": "Internal server error"}, 500)

    tick_time = now.isoformat()
    state["last_tick"] = tick_time

    if notifications is None:
        notif_list: list[dict] = []
    else:
        notif_list = [{"title": t, "body": b} for t, b in notifications]

    state["last_notifications"] = notif_list

    return _json({
        "tick_time": tick_time,
        "notifications": notif_list,
        "report_path": str(_REPORT_PATH),
    })
