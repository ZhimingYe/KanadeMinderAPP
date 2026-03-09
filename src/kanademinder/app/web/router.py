"""KanadeMinder web router factory.

Usage::

    from kanademinder.app.web.router import make_web_router
    from kanademinder.web.server import run_server
    from kanademinder.db import open_db

    router = make_web_router(llm, lambda: open_db(db_path))
    run_server(router, host="0.0.0.0", port=8080)
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Callable

from kanademinder.llm.client import LLMClient

from kanademinder.app.web.api import (
    chat_turn,
    daemon_status,
    daemon_tick,
    get_suggestion,
    list_tasks_handler,
    serve_frontend,
    serve_report,
)


def make_web_router(
    llm: LLMClient,
    db_factory: Callable[[], sqlite3.Connection],
) -> Callable[[str, str, bytes], tuple[int, str, bytes]]:
    """Return a router callable: ``(method, path, body) → (status, content_type, body_bytes)``.

    *db_factory* is called at most once per thread to obtain a SQLite connection,
    which is then reused for all subsequent requests on that thread.
    """
    state: dict = {}
    _local = threading.local()

    def _get_conn() -> sqlite3.Connection:
        if not hasattr(_local, "conn"):
            _local.conn = db_factory()
        return _local.conn

    _routes: dict[tuple[str, str], Callable] = {
        ("GET",  "/"                  ): serve_frontend,
        ("GET",  "/api/tasks"         ): list_tasks_handler,
        ("GET",  "/api/suggestion"    ): get_suggestion,
        ("POST", "/api/chat"          ): chat_turn,
        ("GET",  "/api/daemon/status" ): daemon_status,
        ("POST", "/api/daemon/tick"   ): daemon_tick,
        ("GET",  "/api/report"        ): serve_report,
    }

    def router(method: str, path: str, body: bytes) -> tuple[int, str, bytes]:
        clean_path = path.split("?")[0]
        handler = _routes.get((method, clean_path))
        if handler is None:
            err = json.dumps({"error": f"Not found: {method} {clean_path}"}).encode()
            return 404, "application/json", err
        return handler(_get_conn(), llm, state, body)

    return router
