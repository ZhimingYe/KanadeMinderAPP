"""KanadeMinder API exposed to JavaScript via pywebview.

This module provides the bridge between the Python backend and the JavaScript
frontend when running as a desktop application.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from typing import Any, Callable

from kanademinder.app.chat.handler import handle_turn, QUERY_RESPONSE_SENTINEL, QUERY_PREAMBLE_SEP
from kanademinder.app.daemon.html_report import build_html_report
from kanademinder.app.daemon.scheduler import build_kanademinder_notifications
from kanademinder.config import DB_PATH, load_config
from kanademinder.gui.report.window import open_report_window
from kanademinder.gui.settings.window import open_settings_window
from kanademinder.db import list_tasks, open_db
from kanademinder.llm.client import LLMClient
from kanademinder.models import Task, TaskStatus


class KanadeMinderAPI:
    """API class exposed to JavaScript via pywebview's JS-Python bridge.

    Usage from JavaScript:
        const tasks = await window.pywebview.api.list_tasks();
        const response = await window.pywebview.api.send_chat_message("Add a task");
    """

    def __init__(self) -> None:
        self._cfg = load_config()
        self._llm = LLMClient(
            base_url=self._cfg.llm.base_url,
            api_key=self._cfg.llm.api_key,
            model=self._cfg.llm.model,
            provider=self._cfg.llm.provider or None,
        )
        self._local = threading.local()
        self._daemon_state: dict[str, Any] = {
            "last_tick": None,
            "last_notifications": [],
        }
        self._lock = threading.Lock()

    def _get_db(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, "conn"):
            self._local.conn = open_db(DB_PATH)
        return self._local.conn

    def list_tasks(self) -> list[dict]:
        """Return all tasks as a list of dictionaries."""
        conn = self._get_db()
        cursor = conn.execute(
            """
            SELECT id, name, deadline, recurrence, recurrence_end,
                   priority, status, type, parent_id, estimated_minutes
            FROM tasks
            ORDER BY priority DESC, deadline ASC NULLS LAST, created_at DESC
            """
        )
        rows = cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert a database row to a task dictionary."""
        return {
            "id": row["id"],
            "name": row["name"],
            "deadline": row["deadline"],
            "recurrence": row["recurrence"],
            "recurrence_end": row["recurrence_end"],
            "priority": row["priority"],
            "status": row["status"],
            "type": row["type"],
            "parent_id": row["parent_id"],
            "estimated_minutes": row["estimated_minutes"],
        }

    def send_chat_message(self, message: str) -> dict:
        """Send a message to the chat handler and return the response.

        Returns:
            dict with keys:
                - response: str - text response from the assistant
                - is_query: bool - whether this was a query response (task list)
                - tasks: list - current task list (if query or task changed)
                - error: str - error message if something went wrong
        """
        conn = self._get_db()

        # Use an empty history for simplicity in GUI mode
        # (history management can be added later)
        history: list[dict] = []

        try:
            response_text = handle_turn(
                message,
                history,
                self._llm,
                conn,
                default_task_type=self._cfg.behavior.default_task_type,
            )

            # Refresh task list after any operation
            tasks = self.list_tasks()

            is_query = response_text.startswith(QUERY_RESPONSE_SENTINEL)
            if is_query:
                body = response_text[len(QUERY_RESPONSE_SENTINEL):]
                parts = body.split(QUERY_PREAMBLE_SEP, 1)
                response_text = parts[0].strip() if len(parts) > 1 else ""

            return {
                "response": response_text,
                "is_query": is_query,
                "tasks": tasks,
                "error": None,
            }

        except Exception as e:
            return {
                "response": None,
                "is_query": False,
                "tasks": None,
                "error": str(e),
            }

    def get_suggestion(self) -> dict:
        """Get an LLM suggestion based on current tasks.

        Returns:
            dict with keys:
                - suggestion: str - the LLM's suggestion
                - error: str - error message if failed
        """
        from kanademinder.app.daemon.prompts import SCHEDULING_SYSTEM_PROMPT, build_scheduling_user_message
        from kanademinder.app.daemon.notifications import _MAX_SUGGESTION
        from kanademinder.db import list_tasks
        from kanademinder.models import TaskStatus

        conn = self._get_db()
        now = datetime.now()

        try:
            tasks = (
                list_tasks(conn, status=TaskStatus.PENDING)
                + list_tasks(conn, status=TaskStatus.IN_PROGRESS)
            )
            if not tasks:
                return {"suggestion": None, "error": None}

            user_message = build_scheduling_user_message(tasks, self._cfg.schedule.end_of_day, now)
            messages = [
                {"role": "system", "content": SCHEDULING_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ]
            suggestion = self._llm.chat(messages)

            if len(suggestion) > _MAX_SUGGESTION:
                suggestion = suggestion[:_MAX_SUGGESTION].rsplit(" ", 1)[0] + "…"

            return {"suggestion": suggestion, "error": None}
        except Exception as e:
            return {"suggestion": None, "error": str(e)}

    def run_daemon_tick(self) -> dict:
        """Run one daemon tick and return notifications.

        Returns:
            dict with keys:
                - notifications: list of {title, body} notification dicts (like web)
                - tick_time: str - ISO timestamp of when tick ran
                - html_report: str - HTML content of the report (for GUI display)
                - error: str - error message if failed
        """
        conn = self._get_db()

        try:
            now = datetime.now()
            # Get pending and in_progress tasks
            from kanademinder.db import list_tasks as db_list_tasks
            from kanademinder.app.daemon.prompts import SCHEDULING_SYSTEM_PROMPT, build_scheduling_user_message
            from kanademinder.app.daemon.notifications import (
                _MAX_SUGGESTION,
                _build_overview_body,
                _build_reminder_body,
                _most_urgent_task,
            )

            pending = db_list_tasks(conn, status=TaskStatus.PENDING)
            in_progress = db_list_tasks(conn, status=TaskStatus.IN_PROGRESS)
            tasks = pending + in_progress

            if not tasks:
                return {
                    "notifications": [],
                    "tick_time": now.isoformat(),
                    "html_report": None,
                    "error": None,
                }

            # Calculate overdue and due today for notifications
            overdue_tasks = [t for t in tasks if t.deadline and t.deadline < now]
            due_today_tasks = [
                t for t in tasks
                if t.deadline and t.deadline.date() == now.date() and t.deadline >= now
            ]

            # Generate LLM suggestion
            user_message = build_scheduling_user_message(tasks, self._cfg.schedule.end_of_day, now)
            messages = [
                {"role": "system", "content": SCHEDULING_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ]
            suggestion = self._llm.chat(messages)
            if len(suggestion) > _MAX_SUGGESTION:
                suggestion = suggestion[:_MAX_SUGGESTION].rsplit(" ", 1)[0] + "…"

            # Build the three notification cards (same as web)
            overview = _build_overview_body(tasks, overdue_tasks, due_today_tasks, now)
            urgent = _most_urgent_task(tasks, overdue_tasks, due_today_tasks)
            reminder = _build_reminder_body(urgent, now)

            notifications = [
                {"title": "KanadeMinder — Tasks", "body": overview},
                {"title": "KanadeMinder — Suggestion", "body": suggestion},
                {"title": "KanadeMinder — Reminder", "body": reminder},
            ]

            # Build HTML report (without opening browser)
            html_content = build_html_report(tasks, suggestion, now)

            tick_time = now.isoformat()

            # Store the HTML and suggestion for the GUI to display
            with self._lock:
                self._daemon_state["last_tick"] = tick_time
                self._daemon_state["last_html_report"] = html_content
                self._daemon_state["last_suggestion"] = suggestion
                self._daemon_state["last_notifications"] = notifications

            return {
                "notifications": notifications,
                "tick_time": tick_time,
                "html_report": html_content,
                "suggestion": suggestion,
                "error": None,
            }

        except Exception as e:
            return {
                "notifications": None,
                "tick_time": None,
                "html_report": None,
                "suggestion": None,
                "error": str(e),
            }

    def get_daemon_status(self) -> dict:
        """Get current daemon status.

        Returns:
            dict with keys:
                - last_tick: str - ISO timestamp of last tick
                - last_notifications: list of notification dicts
                - last_html_report: str - last generated HTML report
                - last_suggestion: str - last generated suggestion
        """
        with self._lock:
            return {
                "last_tick": self._daemon_state.get("last_tick"),
                "last_notifications": self._daemon_state.get("last_notifications", []),
                "last_html_report": self._daemon_state.get("last_html_report"),
                "last_suggestion": self._daemon_state.get("last_suggestion"),
            }

    def open_report_window(self) -> dict:
        """Open the HTML report in a new pywebview window.

        Returns:
            dict with keys:
                - success: bool - whether window was opened
                - error: str - error message if failed
        """
        with self._lock:
            html_content = self._daemon_state.get("last_html_report")

        if not html_content:
            return {"success": False, "error": "No report available. Run a tick first."}

        try:
            open_report_window(html_content)
            return {"success": True, "error": None}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def open_settings_window(self) -> dict:
        """Open the settings window.

        Returns:
            dict with keys:
                - success: bool - whether window was opened
                - error: str - error message if failed
        """
        try:
            open_settings_window()
            return {"success": True, "error": None}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def call(self, method: str, path: str, body: str | None) -> dict | list:
        """Generic API call handler for the web frontend compatibility.

        This allows the existing web frontend to work with pywebview
        by routing requests through this method.

        Args:
            method: HTTP method (GET, POST)
            path: API path (/api/tasks, /api/chat, etc.)
            body: Request body as JSON string (for POST)

        Returns:
            Response dictionary or list (for /api/tasks)
        """
        try:
            # Route to appropriate method based on path
            if path == "/api/tasks" and method == "GET":
                return self.list_tasks()

            if path == "/api/suggestion" and method == "GET":
                return self.get_suggestion()

            if path == "/api/chat" and method == "POST":
                if body:
                    data = json.loads(body)
                    return self.send_chat_message(data.get("message", ""))
                return {"error": "No message provided"}

            if path == "/api/daemon/status" and method == "GET":
                return self.get_daemon_status()

            if path == "/api/daemon/tick" and method == "POST":
                return self.run_daemon_tick()

            if path == "/api/settings" and method == "GET":
                from kanademinder.gui.settings.api import SettingsAPI
                api = SettingsAPI()
                return api.get_config()

            if path == "/api/settings" and method == "POST":
                if body:
                    data = json.loads(body)
                    from kanademinder.gui.settings.api import SettingsAPI
                    api = SettingsAPI()
                    return api.save_config(data)
                return {"error": "No config data provided"}

            return {"error": f"Unknown endpoint: {method} {path}"}
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON: {e}"}
        except Exception as e:
            return {"error": str(e)}
