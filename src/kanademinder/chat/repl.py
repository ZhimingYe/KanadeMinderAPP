"""Generic REPL loop — no project-specific dependencies.

Inject application behaviour through the ``turn_handler``,
``response_renderer``, and ``error_handler`` callables::

    from kanademinder.chat.repl import run_repl
    from kanademinder.chat.handler import (
        make_turn_handler, make_response_renderer, make_error_handler,
    )

    run_repl(
        make_turn_handler(llm, conn, default_task_type),
        response_renderer=make_response_renderer(conn),
        error_handler=make_error_handler(),
        welcome="[bold cyan]MyApp[/bold cyan] — Ctrl-C to exit.\\n",
    )
"""

from __future__ import annotations

import readline  # noqa: F401 — enables up/down arrow history in input()
from typing import Callable

from rich.console import Console

console = Console()

MAX_HISTORY_MESSAGES = 20

_PROMPT = "\001\033[1;32m\002You\001\033[0m\002 > "


def run_repl(
    turn_handler: Callable[[str, list[dict[str, str]]], str],
    *,
    response_renderer: Callable[[str], None] | None = None,
    error_handler: Callable[[Exception], bool] | None = None,
    prompt: str = _PROMPT,
    welcome: str = "Type your input. Ctrl-C to exit.",
    max_history: int = MAX_HISTORY_MESSAGES,
) -> None:
    """Start the interactive REPL loop. Exits on Ctrl-C or Ctrl-D.

    Args:
        turn_handler: Called with ``(user_input, history)`` each turn;
            returns the assistant response string and may mutate *history*
            in-place to append the exchange.
        response_renderer: Called with the response string to display it.
            Defaults to a plain ``console.print``.
        error_handler: Called when ``turn_handler`` raises.  Should print a
            user-facing message and return ``True`` if the error is handled
            (REPL continues), or ``False`` / raise to let the exception
            propagate.
        prompt: The readline prompt string.
        welcome: Printed once at startup (supports rich markup).
        max_history: Maximum messages kept in the LLM context window.
    """
    history: list[dict[str, str]] = []
    _history_warned = False

    console.print(welcome)

    while True:
        try:
            user_input = input(prompt)
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not user_input.strip():
            continue

        # Cap history before sending to the LLM
        if len(history) > max_history:
            if not _history_warned:
                console.print(
                    "[dim](Older messages are no longer sent to the AI to keep "
                    "requests fast. Recent context is preserved.)[/dim]"
                )
                _history_warned = True
            history = history[-max_history:]

        try:
            with console.status("[bold cyan]Thinking...", spinner="dots"):
                response = turn_handler(user_input, history)
        except Exception as exc:
            if error_handler and error_handler(exc):
                if history and history[-1]["role"] == "user":
                    history.pop()
                continue
            raise

        if response_renderer:
            response_renderer(response)
        else:
            console.print(f"{response}\n")
