"""Tests for the web API router (no real HTTP server started)."""

from __future__ import annotations

import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock, patch

from kanademinder.app.web.router import make_web_router
from kanademinder.db import create_task
from kanademinder.models import Task
from kanademinder.web.server import make_handler, MAX_BODY


# ── Real-server helper ─────────────────────────────────────────────────────────

class _LiveServer:
    """Minimal HTTP server bound to a random port for header-level tests."""

    def __init__(self, router):
        handler = make_handler(router)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def get(self, path: str) -> http.client.HTTPResponse:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        return conn.getresponse()

    def post(self, path: str, body: bytes) -> http.client.HTTPResponse:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", path, body=body, headers={"Content-Length": str(len(body))})
        return conn.getresponse()

    def stop(self):
        self._server.shutdown()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _mock_llm() -> MagicMock:
    llm = MagicMock()
    return llm


def _get(router, path: str) -> tuple[int, str, bytes]:
    return router("GET", path, b"")


def _post(router, path: str, payload: dict) -> tuple[int, str, bytes]:
    return router("POST", path, json.dumps(payload).encode())


# ── GET / ─────────────────────────────────────────────────────────────────────

def test_get_frontend_returns_html(tmp_db):
    router = make_web_router(_mock_llm(), lambda: tmp_db)
    status, content_type, body = _get(router, "/")
    assert status == 200
    assert "text/html" in content_type
    assert b"KanadeMinder" in body
    assert b"<html" in body


# ── GET /api/tasks ─────────────────────────────────────────────────────────────

def test_list_tasks_empty(tmp_db):
    router = make_web_router(_mock_llm(), lambda: tmp_db)
    status, content_type, body = _get(router, "/api/tasks")
    assert status == 200
    assert "application/json" in content_type
    data = json.loads(body)
    assert data == []


def test_list_tasks_with_tasks(tmp_db):
    create_task(tmp_db, Task(name="Buy groceries", priority=3))
    create_task(tmp_db, Task(name="Write report", priority=5))
    router = make_web_router(_mock_llm(), lambda: tmp_db)
    status, _, body = _get(router, "/api/tasks")
    assert status == 200
    tasks = json.loads(body)
    assert len(tasks) == 2
    names = {t["name"] for t in tasks}
    assert names == {"Buy groceries", "Write report"}
    # Verify expected fields are present
    for t in tasks:
        assert "id" in t
        assert "name" in t
        assert "priority" in t
        assert "status" in t


# ── POST /api/chat ─────────────────────────────────────────────────────────────

def test_chat_turn_calls_handle_turn(tmp_db):
    router = make_web_router(_mock_llm(), lambda: tmp_db)
    with patch("kanademinder.app.web.api.handle_turn") as mock_handle:
        mock_handle.return_value = "Task created!"
        status, content_type, body = _post(router, "/api/chat", {"message": "add a task"})
    assert status == 200
    assert "application/json" in content_type
    data = json.loads(body)
    assert data["response"] == "Task created!"
    assert "tasks" in data
    assert isinstance(data["tasks"], list)
    mock_handle.assert_called_once()
    # Verify the message was forwarded
    call_args = mock_handle.call_args
    assert call_args[0][0] == "add a task"


def test_chat_turn_tracks_history(tmp_db):
    """History accumulates across multiple turns on the same router instance."""
    router = make_web_router(_mock_llm(), lambda: tmp_db)
    with patch("kanademinder.app.web.api.handle_turn") as mock_handle:
        mock_handle.return_value = "Done."
        _post(router, "/api/chat", {"message": "first"})
        _post(router, "/api/chat", {"message": "second"})
    # handle_turn is called with the same history list both times
    assert mock_handle.call_count == 2
    first_history  = mock_handle.call_args_list[0][0][1]
    second_history = mock_handle.call_args_list[1][0][1]
    assert first_history is second_history  # same list object


def test_chat_turn_missing_message_returns_400(tmp_db):
    router = make_web_router(_mock_llm(), lambda: tmp_db)
    status, _, body = _post(router, "/api/chat", {})
    assert status == 400
    assert b"message" in body


def test_chat_turn_query_response_sets_is_query_flag(tmp_db):
    from kanademinder.app.chat.handler import QUERY_PREAMBLE_SEP, QUERY_RESPONSE_SENTINEL
    router = make_web_router(_mock_llm(), lambda: tmp_db)
    with patch("kanademinder.app.web.api.handle_turn") as mock_handle:
        mock_handle.return_value = (
            QUERY_RESPONSE_SENTINEL + "You have 4 tasks.\n" + QUERY_PREAMBLE_SEP + "Your tasks:\n..."
        )
        status, _, body = _post(router, "/api/chat", {"message": "list tasks"})
    data = json.loads(body)
    assert data["is_query"] is True
    # Preamble extracted — task list text stripped
    assert data["response"] == "You have 4 tasks."
    assert QUERY_RESPONSE_SENTINEL not in data["response"]


def test_chat_turn_non_query_response_is_query_false(tmp_db):
    from kanademinder.app.chat.handler import QUERY_RESPONSE_SENTINEL
    router = make_web_router(_mock_llm(), lambda: tmp_db)
    with patch("kanademinder.app.web.api.handle_turn") as mock_handle:
        mock_handle.return_value = "Task created!"
        status, _, body = _post(router, "/api/chat", {"message": "add a task"})
    data = json.loads(body)
    assert data["is_query"] is False
    assert data["response"] == "Task created!"


# ── GET /api/suggestion ───────────────────────────────────────────────────────

def test_suggestion_no_tasks_returns_null(tmp_db):
    router = make_web_router(_mock_llm(), lambda: tmp_db)
    status, content_type, body = _get(router, "/api/suggestion")
    assert status == 200
    assert "application/json" in content_type
    data = json.loads(body)
    assert data["suggestion"] is None
    assert "generated_at" in data


def test_suggestion_with_tasks_calls_llm(tmp_db):
    create_task(tmp_db, Task(name="Fix deploy pipeline", priority=5))
    llm = _mock_llm()
    llm.chat.return_value = "Fix deploy pipeline first — it's blocking the whole team."
    router = make_web_router(llm, lambda: tmp_db)
    status, _, body = _get(router, "/api/suggestion")
    assert status == 200
    data = json.loads(body)
    assert data["suggestion"] == "Fix deploy pipeline first — it's blocking the whole team."
    assert "generated_at" in data
    llm.chat.assert_called_once()


def test_suggestion_truncated_if_too_long(tmp_db):
    create_task(tmp_db, Task(name="Some task", priority=3))
    llm = _mock_llm()
    llm.chat.return_value = "word " * 50  # well over 160 chars
    router = make_web_router(llm, lambda: tmp_db)
    status, _, body = _get(router, "/api/suggestion")
    data = json.loads(body)
    assert len(data["suggestion"]) <= 164  # 160 + possible "…"


# ── GET /api/daemon/status ─────────────────────────────────────────────────────

def test_daemon_status_initial(tmp_db):
    router = make_web_router(_mock_llm(), lambda: tmp_db)
    status, content_type, body = _get(router, "/api/daemon/status")
    assert status == 200
    assert "application/json" in content_type
    data = json.loads(body)
    assert data["last_tick"] is None
    assert data["last_notifications"] is None


# ── POST /api/daemon/tick ──────────────────────────────────────────────────────

def test_daemon_tick_triggers_notifications(tmp_db):
    mock_notifs = [
        ("KanadeMinder — Tasks", "2 overdue · 1 due today"),
        ("KanadeMinder — Suggestion", "Focus on overdue items first."),
    ]
    router = make_web_router(_mock_llm(), lambda: tmp_db)
    with patch("kanademinder.app.web.api.build_kanademinder_notifications") as mock_build:
        mock_build.return_value = mock_notifs
        status, content_type, body = _post(router, "/api/daemon/tick", {})
    assert status == 200
    data = json.loads(body)
    assert "tick_time" in data
    assert "notifications" in data
    assert len(data["notifications"]) == 2
    assert data["notifications"][0]["title"] == "KanadeMinder — Tasks"
    assert data["notifications"][1]["body"] == "Focus on overdue items first."


def test_daemon_tick_no_tasks_returns_empty_list(tmp_db):
    router = make_web_router(_mock_llm(), lambda: tmp_db)
    with patch("kanademinder.app.web.api.build_kanademinder_notifications") as mock_build:
        mock_build.return_value = None  # no pending tasks
        status, _, body = _post(router, "/api/daemon/tick", {})
    assert status == 200
    data = json.loads(body)
    assert data["notifications"] == []


def test_daemon_tick_updates_status(tmp_db):
    """After a tick, /api/daemon/status reflects the result."""
    router = make_web_router(_mock_llm(), lambda: tmp_db)
    with patch("kanademinder.app.web.api.build_kanademinder_notifications") as mock_build:
        mock_build.return_value = [("Title", "Body")]
        _post(router, "/api/daemon/tick", {})

    status, _, body = _get(router, "/api/daemon/status")
    data = json.loads(body)
    assert data["last_tick"] is not None
    assert len(data["last_notifications"]) == 1
    assert data["last_notifications"][0]["title"] == "Title"


# ── 404 ────────────────────────────────────────────────────────────────────────

def test_unknown_route_404(tmp_db):
    router = make_web_router(_mock_llm(), lambda: tmp_db)
    status, content_type, body = _get(router, "/nonexistent")
    assert status == 404
    assert "application/json" in content_type
    data = json.loads(body)
    assert "error" in data


def test_unknown_post_route_404(tmp_db):
    router = make_web_router(_mock_llm(), lambda: tmp_db)
    status, _, body = _post(router, "/api/unknown", {})
    assert status == 404


# ── Query string stripping ─────────────────────────────────────────────────────

def test_query_string_stripped_from_path(tmp_db):
    router = make_web_router(_mock_llm(), lambda: tmp_db)
    status, _, body = _get(router, "/api/tasks?foo=bar")
    assert status == 200
    data = json.loads(body)
    assert isinstance(data, list)


# ── Security tests ─────────────────────────────────────────────────────────────

def test_oversized_body_returns_413(tmp_db):
    """POST with body exceeding MAX_BODY → 413 Payload Too Large.

    Uses a raw socket to send only the headers (with a large Content-Length) so
    the server rejects the request immediately without the client needing to
    transmit a full megabyte.
    """
    import socket
    router = make_web_router(_mock_llm(), lambda: tmp_db)
    srv = _LiveServer(router)
    try:
        s = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
        # Send headers only; Content-Length signals a body larger than MAX_BODY
        request = (
            f"POST /api/chat HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{srv.port}\r\n"
            f"Content-Length: {MAX_BODY + 1}\r\n"
            f"\r\n"
        ).encode()
        s.sendall(request)
        raw = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            raw += chunk
        s.close()
        status_line = raw.split(b"\r\n")[0].decode()
        assert "413" in status_line, f"Expected 413 in status line, got: {status_line!r}"
    finally:
        srv.stop()


def test_security_headers_present(tmp_db):
    """GET / response includes X-Frame-Options and X-Content-Type-Options headers."""
    router = make_web_router(_mock_llm(), lambda: tmp_db)
    srv = _LiveServer(router)
    try:
        resp = srv.get("/")
        assert resp.status == 200
        assert resp.getheader("X-Frame-Options") == "DENY"
        assert resp.getheader("X-Content-Type-Options") == "nosniff"
    finally:
        srv.stop()


def test_no_cors_wildcard(tmp_path):
    """No Access-Control-Allow-Origin header is sent on any response."""
    from kanademinder.db import open_db
    db_path = tmp_path / "tasks.db"
    # Use a factory so each server thread gets its own SQLite connection
    router = make_web_router(_mock_llm(), lambda: open_db(db_path))
    srv = _LiveServer(router)
    try:
        resp = srv.get("/api/tasks")
        assert resp.status == 200
        assert resp.getheader("Access-Control-Allow-Origin") is None
    finally:
        srv.stop()


def test_chat_history_capped(tmp_db):
    """After many turns, state['history'] length stays at or below MAX_WEB_HISTORY."""
    from kanademinder.app.web.api import MAX_WEB_HISTORY
    router = make_web_router(_mock_llm(), lambda: tmp_db)
    with patch("kanademinder.app.web.api.handle_turn") as mock_handle:
        mock_handle.return_value = "ok"
        for _ in range(MAX_WEB_HISTORY + 1):
            _post(router, "/api/chat", {"message": "ping"})
    # Access internal state via a closure — extract via another call
    # The router exposes state indirectly; verify through handle_turn's history arg
    last_history = mock_handle.call_args[0][1]
    assert len(last_history) <= MAX_WEB_HISTORY


def test_exception_returns_generic_500(tmp_db):
    """A handler that raises returns {"error": "Internal server error"}, not the traceback."""
    router = make_web_router(_mock_llm(), lambda: tmp_db)
    with patch("kanademinder.app.web.api.handle_turn", side_effect=RuntimeError("secret detail")):
        status, _, body = _post(router, "/api/chat", {"message": "hi"})
    assert status == 500
    data = json.loads(body)
    assert data["error"] == "Internal server error"
    assert "secret detail" not in data["error"]
