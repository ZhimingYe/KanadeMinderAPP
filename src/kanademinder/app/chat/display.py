"""Rich display helpers and REPL factory functions for the KanadeMinder chat adapter."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Callable

from rich.console import Console
from rich.table import Table

from kanademinder.db import list_tasks
from kanademinder.llm.client import LLMError
from kanademinder.llm.parser import ParseError
from kanademinder.llm.prompts import _fmt_deadline
from kanademinder.models import Task

from kanademinder.app.chat.actions import _ordered_with_depth
from kanademinder.app.chat.handler import QUERY_PREAMBLE_SEP, QUERY_RESPONSE_SENTINEL, handle_turn

_console = Console()


def _print_task_table(tasks: list[Task]) -> None:
    """Render tasks as a rich table to stdout."""
    if not tasks:
        _console.print("[dim]No tasks found.[/dim]")
        return

    now = datetime.now()
    today = now.date()

    table = Table(
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        title_style="bold",
    )
    table.add_column("#", justify="right", style="dim", width=4)
    table.add_column("Name", min_width=20)
    table.add_column("Type", width=6)
    table.add_column("P", justify="center", width=3)
    table.add_column("Deadline", width=18)
    table.add_column("Est.", justify="right", width=6)
    table.add_column("Status", width=12)

    for i, (t, depth) in enumerate(_ordered_with_depth(tasks), start=1):
        if t.deadline:
            deadline_str = _fmt_deadline(t.deadline)
            if t.deadline < now:
                deadline_display = f"[red]{deadline_str}[/red]"
            elif t.deadline.date() == today:
                deadline_display = f"[yellow]{deadline_str}[/yellow]"
            else:
                deadline_display = deadline_str
        else:
            deadline_display = "-"

        prefix = "[dim]└─[/dim] " if depth > 0 else ""
        name_display = prefix + t.name + (" ↻" if t.recurrence else "")
        est = f"{t.estimated_minutes}m" if t.estimated_minutes else "-"
        status_style = {
            "pending": "yellow",
            "in_progress": "green",
            "done": "dim",
        }.get(t.status.value, "")
        table.add_row(
            str(i),
            name_display,
            t.type.value,
            str(t.priority),
            deadline_display,
            est,
            f"[{status_style}]{t.status.value}[/{status_style}]",
        )

    _console.print(table)


def make_response_renderer(conn: sqlite3.Connection) -> Callable[[str], None]:
    """Return a KanadeMinder response renderer for ``run_repl``.

    Handles query responses (shows a rich task table) and plain messages.
    """
    def _renderer(response: str) -> None:
        if response.startswith(QUERY_RESPONSE_SENTINEL):
            body = response[len(QUERY_RESPONSE_SENTINEL):]
            parts = body.split(QUERY_PREAMBLE_SEP, 1)
            llm_msg = parts[0].strip() if len(parts) > 1 else ""
            if llm_msg:
                _console.print(f"[bold blue]KanadeMinder:[/bold blue] {llm_msg}\n")
            else:
                _console.print("[bold blue]KanadeMinder:[/bold blue]")
            _print_task_table(list_tasks(conn))
            _console.print()
        else:
            _console.print(f"[bold blue]KanadeMinder:[/bold blue] {response}\n")
    return _renderer


def make_turn_handler(
    llm: object,
    conn: sqlite3.Connection,
    default_task_type: str = "major",
) -> Callable[[str, list[dict[str, str]]], str]:
    """Return a turn-handler callable for ``run_repl``."""
    def _handler(user_input: str, history: list[dict[str, str]]) -> str:
        return handle_turn(user_input, history, llm, conn, default_task_type)  # type: ignore[arg-type]
    return _handler


def make_error_handler() -> Callable[[Exception], bool]:
    """Return an error handler for ``run_repl`` covering LLMError and ParseError."""
    def _handler(exc: Exception) -> bool:
        if isinstance(exc, LLMError):
            _console.print(f"[red]LLM error:[/red] {exc}")
            return True
        if isinstance(exc, ParseError):
            _console.print(
                "[yellow]The AI returned an unexpected response.[/yellow] "
                "Try being more specific about which task and what to do with it."
            )
            _console.print(f"[dim](detail: {exc})[/dim]")
            return True
        return False
    return _handler
