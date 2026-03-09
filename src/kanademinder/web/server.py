"""Generic HTTP server engine — no KanadeMinder-specific imports.

Usage::

    from kanademinder.web.server import run_server

    def my_router(method, path, body):
        return (200, "text/plain", b"Hello")

    run_server(my_router, host="127.0.0.1", port=8080)
"""

from __future__ import annotations

import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

MAX_BODY = 1 * 1024 * 1024  # 1 MB


def make_handler(router: Callable[[str, str, bytes], tuple[int, str, bytes]]) -> type:
    """Return a ``BaseHTTPRequestHandler`` subclass that routes through *router*."""

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:  # noqa: N802
            # Silence default access logs
            pass

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(body)

        def _dispatch(self, method: str) -> None:
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > MAX_BODY:
                err = json.dumps({"error": "Payload too large"}).encode()
                self._send(413, "application/json", err)
                return
            body = self.rfile.read(content_len) if content_len > 0 else b""
            try:
                status, content_type, response = router(method, self.path, body)
            except Exception:  # noqa: BLE001
                traceback.print_exc(file=sys.stderr)
                err = json.dumps({"error": "Internal server error"}).encode()
                self._send(500, "application/json", err)
                return
            self._send(status, content_type, response)

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

    return _Handler


def run_server(
    router: Callable[[str, str, bytes], tuple[int, str, bytes]],
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
) -> None:
    """Start a threaded HTTP server, routing all requests through *router*.

    *router* signature: ``(method: str, path: str, body: bytes) -> (status: int, content_type: str, body: bytes)``

    Catches per-request exceptions and returns a 500 JSON error instead of
    crashing the server.
    """
    handler_class = make_handler(router)
    server = ThreadingHTTPServer((host, port), handler_class)
    print(f"Listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
