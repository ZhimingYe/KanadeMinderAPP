# KanadeMinder — Claude Code Instructions

## Project Overview
Python CLI/GUI/Web app for conversational task management with LLM-powered scheduling nudges. Primarily macOS; non-macOS falls back to HTML report (no notifications/launchd).

- **Stack**: Python 3.11+, uv, SQLite, rich, readline, pywebview, stdlib urllib (no httpx/requests)
- **Entry point**: `kanademinder` → `src/kanademinder/cli.py:main`
- **Runtime data**: `~/.kanademinder/` (config.toml, tasks.db, summary.html, daemon logs)

## Commands

```bash
# Run tests
uv run --with pytest pytest -v

# Run with coverage
uv run --with pytest --with pytest-cov pytest --cov=kanademinder

# Lint
uv run ruff check src/ tests/

# Install package in dev mode
uv sync

# Run CLI
uv run kanademinder chat
uv run kanademinder web               # HTTP server with web frontend
uv run kanademinder gui               # Native pywebview desktop app
uv run kanademinder config init       # Write default config.toml
uv run kanademinder config setup      # Interactive setup wizard
uv run kanademinder install           # macOS: toggle launchd daemon; Windows/Linux: setup guide
```

## Architecture

The codebase is split into **generic reusable engines** and **KanadeMinder-specific adapters** injected into them.

```
src/kanademinder/
├── cli.py           — argparse; subcommands: chat, daemon, web, gui, install, config
├── models.py        — Task dataclass + TaskType/TaskStatus enums; from_row, to_insert_dict
├── db.py            — SQLite CRUD; schema v2; open_db, init_db, advance_recurring_task,
│                       sanitize_recurring_tasks (auto-runs on open_db)
├── config.py        — tomllib; Config + LLMConfig + ScheduleConfig + BehaviorConfig dataclasses
├── recurrence.py    — next_occurrence(dt, pattern) → datetime|None
├── llm/
│   ├── client.py    — LLMClient (urllib); auto-detects OpenAI vs Anthropic; 3× exp backoff
│   ├── prompts.py   — _fmt_deadline(dt) shared utility only
│   └── parser.py    — parse_task_action → TaskAction TypedDict; normalizes LLM output; ParseError
├── chat/
│   └── repl.py      — GENERIC: run_repl(turn_handler, *, response_renderer, error_handler,
│                        prompt, welcome, max_history); readline history; 20-msg cap
├── daemon/
│   ├── scheduler.py — GENERIC: run_tick(build_notifications, *, start_of_day, end_of_day,
│   │                    force, now); EOD suppression; dispatches (title, body) notifications
│   └── notifier.py  — GENERIC: send_notification via osascript; AppleScript quote escaping
├── web/
│   └── server.py    — GENERIC: make_handler(router), run_server(router, host, port);
│                        ThreadingHTTPServer; 1 MB payload limit; security headers
├── gui/
│   ├── app.py       — run_gui(): pywebview window + JS bridge; background daemon thread;
│   │                    create_html_with_bridge() overrides fetch() for desktop mode
│   ├── api.py       — KanadeMinderAPI: JS-Python bridge; call(method, path, body);
│   │                    thread-local DB; _daemon_state lock
│   └── settings/
│       ├── window.py — open_settings_window(); separate pywebview window; global ref
│       └── api.py    — SettingsAPI: get_config, validate_config, save_config, close_window;
│                         TOML written without external libs
└── app/                      ← KanadeMinder-specific adapters (injected into generic engines)
    ├── chat/
    │   ├── prompts.py        — build_conversation_system_prompt(); _add_minutes; _format_task_context
    │   ├── matching.py       — _AmbiguousMatch; _fuzzy_find_task
    │   ├── actions.py        — _task_from_dict; _task_updates_from_dict; _format_task_list;
    │   │                        _find_orphan_by_name; _resolve_parent; _upsert_task;
    │   │                        _handle_create/update/delete (+ batch variants)
    │   ├── handler.py        — handle_turn(); QUERY_RESPONSE_SENTINEL; _is_list_intent()
    │   └── display.py        — _print_task_table; make_turn_handler; make_response_renderer;
    │                            make_error_handler
    ├── config/
    │   └── setup.py          — run_setup(path): interactive wizard; _ask(); per-section prompts
    ├── daemon/
    │   ├── prompts.py        — SCHEDULING_SYSTEM_PROMPT; build_scheduling_user_message()
    │   ├── notifications.py  — _build_overview_body; _most_urgent_task; _build_reminder_body;
    │   │                        _MAX_BODY; _MAX_SUGGESTION
    │   ├── scheduler.py      — build_kanademinder_notifications(); make_kanademinder_tick()
    │   ├── html_report.py    — build_html_report(); open_html_summary(); fallback on non-macOS
    │   └── launchd.py        — plist at ~/Library/LaunchAgents/com.kanademinder.daemon.plist
    └── web/
        ├── api.py            — Route handlers: GET /, GET /api/tasks, POST /api/chat,
        │                        GET /api/suggestion, GET /api/daemon/status, POST /api/daemon/tick
        ├── router.py         — make_web_router(llm, db_factory): thread-local DB; routes dict
        └── frontend.py       — get_frontend_html(): splices static/style.css + static/app.js
```

### Generic engine interfaces

**`chat/repl.py`** — `run_repl(turn_handler, ...)`: accepts any `Callable[[str, list[dict]], str]`; injects `response_renderer` and `error_handler` for display/error concerns.

**`daemon/scheduler.py`** — `run_tick(build_notifications, ...)`: accepts any `Callable[[datetime], list[tuple[str, str]] | None]`; fires each `(title, body)` pair via `send_notification`.

**`web/server.py`** — `run_server(router, host, port)`: accepts any `Callable[(method, path, body) → (status, content_type, bytes)]`; no KanadeMinder imports.

**`cli.py`** wires them together:
```python
run_repl(make_turn_handler(llm, conn), response_renderer=make_response_renderer(conn), ...)
run_tick(make_kanademinder_tick(llm, conn, end_of_day=...), ...)
run_server(make_web_router(llm, db_factory), host, port)
run_gui()   # uses KanadeMinderAPI which embeds make_web_router logic
```

## Key Data Structures

**Task** (`models.py`):
- `deadline: datetime | None` — always stored as ISO datetime string in DB
- `recurrence: str | None` — one of: `daily`, `weekdays`, `weekly`, `monthly`, `yearly`
- `recurrence_end: date | None`
- `parent_id: int | None` — deleting a parent cascades to all children (handled in Python, not FK)
- `priority: int` — 1–5 (5 = highest)
- `status: TaskStatus` — `pending`, `in_progress`, `done`
- `type: TaskType` — `major` or `minor`

**TaskAction** (`llm/parser.py`):
```python
{"action": "create|update|delete|query|clarify|none",
 "task": {...} | None,      # single-task ops
 "tasks": [{...}, ...] | None,  # batch create/delete
 "message": "..."}
```

**Query response sentinels** (`app/chat/handler.py`):
```python
QUERY_RESPONSE_SENTINEL = "\x00QUERY\x00"   # marks query responses
QUERY_PREAMBLE_SEP      = "\x00TASKS\x00"   # separates LLM message from task list
```

## LLM Integration

- **Provider detection**: `api.anthropic.com` in base_url → Anthropic; otherwise OpenAI-compatible
- **JSON mode**: OpenAI uses `response_format`; Anthropic prefills `"{"` to force JSON
- **Anthropic extras**: system message at top-level field; consecutive same-role messages merged; placeholder user message inserted if needed; `max_tokens: 4096` required; auth via `x-api-key` header + `anthropic-version: 2023-06-01`
- **Retry**: 3× exponential backoff on 429/5xx/529; respects `Retry-After` header
- **Parse retry**: `handle_turn()` auto-retries once on `ParseError` with a correction prompt
- **Prompt refresh**: System prompt rebuilt every turn with current date/time and task list

## Parser Normalization (`llm/parser.py`)

- Strips markdown code fences; balanced JSON extraction for partial/wrapped responses
- **Status aliases** (20+ variants): `"in progress"` → `"in_progress"`, `"completed"/"finished"` → `"done"`, `"paused"` → `"pending"`, etc.
- **Recurrence aliases** (12+ variants): `"every day"` → `"daily"`, `"mon-fri"/"weekdays"` → `"weekdays"`, `"annually"` → `"yearly"`, etc. — defined in `_RECURRENCE_ALIASES`
- **Deadline formats**: ISO, slash-delimited, word-based (`"March 5, 2025"`)
- **Priority clamping**: integer coercion, clamped 1–5
- **`parent_name` field**: task may specify `parent_name` (string) instead of `parent_id`; handler auto-creates the parent if it doesn't exist

## Handler Logic (`app/chat/`)

- **Fuzzy task matching** (`matching.py` → `_fuzzy_find_task`): when LLM omits ID on update/delete, matches by name — exact (case-insensitive) → substring → reverse substring; raises `_AmbiguousMatch` on multiple hits
- **Parent auto-create** (`actions.py` → `_resolve_parent`): looks up parent by name; creates if absent; reuses existing same-named orphan task (`_upsert_task`)
- **Recurring task auto-advance**: when a task is updated to `done`, `advance_recurring_task()` is called automatically
- **`handle_turn()`** in `handler.py`: thin orchestrator — calls LLM, parses, dispatches to action handlers, manages history
- **`_is_list_intent()`**: word-set heuristic detecting "show tasks" style requests before hitting LLM

## Database

- **Schema version**: 2 (auto-migrates v1→v2 on startup)
- **Foreign key**: `parent_id REFERENCES tasks(id) ON DELETE SET NULL` — cascade deletion handled in `delete_task()` in Python
- **`advance_recurring_task(conn, task)`**: marks task done, creates next pending occurrence respecting `recurrence_end`
- **`sanitize_recurring_tasks(conn, now)`**: auto-runs on `open_db()`; three-pass repair — (1) delete exact duplicate (name+deadline) pairs keeping lowest id, (2) keep earliest occurrence in recurring family, (3) fast-forward stale overdue recurring tasks
- **`list_tasks()` sort order**: `priority DESC, deadline ASC, id ASC`

## Web Interface (`web/server.py` + `app/web/`)

- **Start**: `uv run kanademinder web [--host HOST] [--port PORT]`
- **History cap**: 40 messages (vs REPL's 20)
- **Routes**:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Single-page app HTML |
| GET | `/api/tasks` | All tasks as JSON list |
| POST | `/api/chat` | `{message}` → `{response, is_query, tasks}` |
| GET | `/api/suggestion` | One-sentence LLM scheduling recommendation |
| GET | `/api/daemon/status` | `{last_tick, notifications}` |
| POST | `/api/daemon/tick` | Run one daemon tick; returns notifications |

- **Frontend**: `app/web/frontend.py` reads `static/index.html`, `style.css`, `app.js` at import time; splices into SPA

## Native GUI (`gui/`)

- **Start**: `uv run kanademinder gui`
- **Requires**: pywebview installed
- **Bridge**: `create_html_with_bridge()` overrides `window.fetch()` in JS so `/api/*` calls route through `window.pywebview.api.call()` — no HTTP overhead
- **Background daemon**: `run_background_daemon()` thread runs tick at config interval; stores last state in `_daemon_state` (lock-protected)
- **Settings window**: separate pywebview window; `open_settings_window()` reuses existing window if still open; global ref prevents GC
- **Settings API** (`gui/settings/api.py`): validates all config fields; writes TOML manually without external libs

## Config (`config.py`)

```toml
[llm]
base_url = "https://api.openai.com/v1"
api_key  = "sk-..."
model    = "gpt-4o"
provider = ""          # auto-detect if empty: "anthropic" or "openai"

[schedule]
interval_minutes = 30
start_of_day     = "08:00"
end_of_day       = "22:00"

[behavior]
default_task_type   = "major"    # or "minor"
notification_mode   = "banner"   # "banner" | "webpage" | "both"
```

- `notification_mode` replaces the old `html_summary` boolean — `_resolve_notification_mode()` auto-migrates legacy configs
- Interactive setup: `config setup` → `app/config/setup.py:run_setup()`

## HTML Report (`app/daemon/html_report.py`)

- `build_html_report(tasks, llm_suggestion)` → complete HTML string
- `open_html_summary(tasks, llm_suggestion)` → writes to `~/.kanademinder/summary.html` and opens in default browser
- Color-coded sections: OVERDUE (red), DUE TODAY (orange), UPCOMING (blue), NO DEADLINE (green)
- Per-task: priority badge (P1–P5), name, deadline + time-remaining, status, est. minutes, recurrence
- Triggered when `notification_mode` is `"webpage"` or `"both"`
- **Non-macOS**: always uses HTML report regardless of `notification_mode`

## Daemon Notifications (`app/daemon/`)

Three macOS banner notifications built per tick (in `notifications.py`, fired by `scheduler.py`):
1. **Overview**: compact stats (`"2 overdue · 1 due today"`), task names truncated with `"… and N more"`
2. **Suggestion**: one-sentence LLM recommendation, capped at 160 chars
3. **Reminder**: single most-urgent task with urgency details

## EOD Suppression Logic (`daemon/scheduler.py`)

- `end_of_day < "12:00"` (e.g. `"02:00"`): suppress when `midnight ≤ now ≤ EOD` (quiet window)
- `end_of_day ≥ "12:00"` (e.g. `"22:00"`): suppress when `now ≥ EOD`
- Also suppressed when `build_notifications` returns `None` (no pending/in_progress tasks)

## REPL (`chat/repl.py`)

- **Input history**: `import readline` enables up/down arrow navigation through typed inputs
- **Task table**: rendered by `app/chat/display.py` — overdue deadlines RED, due-today YELLOW; recurring tasks show `↻` in name; status color-coded (pending YELLOW, in_progress GREEN, done DIM)
- **History cap**: 20 messages (10 turns × 2); warns user once when limit exceeded, older messages dropped from LLM context

## Testing Conventions

- **Run**: `uv run --with pytest pytest -v` — 369 tests, all pass
- **No external test deps** beyond pytest; all mocks via `unittest.mock`
- **LLM always mocked** — never hits real API in tests
- **`tmp_db` fixture** in `conftest.py`: `open_db(tmp_path / "tasks.db")`
- **Notification mock target**: `kanademinder.daemon.scheduler.send_notification`
- **Test files**: `test_models`, `test_db`, `test_config`, `test_config_setup`, `test_parser`, `test_handler`, `test_client`, `test_scheduler`, `test_notifier`, `test_recurrence`, `test_html_report`, `test_web_api`, `test_gui_settings`, `test_hierarchy_rendering`

## Coding Conventions

- All source files use `from __future__ import annotations`
- No external HTTP libraries — use `urllib.request` only
- Enum values accessed as `.value` when writing to DB; coerced back via `TaskType(str)` on read
- `_fmt_deadline(dt)` in `llm/prompts.py` is the shared deadline formatter — import from there, don't duplicate
- Batch operations: use `tasks: [...]` array; single ops: use `task: {...}`; never mix in one action
- `delete_task()` in `db.py` recursively deletes children before deleting parent
- AppleScript escaping in `notifier.py`: escape backslashes first, then double-quotes
- Keep `chat/repl.py`, `daemon/scheduler.py`, and `web/server.py` free of KanadeMinder-specific imports — all app logic belongs in `app/`
- GUI settings TOML write: manual string building, no external TOML lib

## Important Files for Common Tasks

| Task | Files to read |
|------|--------------|
| Add new LLM action type | `llm/parser.py`, `app/chat/actions.py`, `app/chat/handler.py`, `app/chat/prompts.py` |
| Change DB schema | `db.py` (add migration), `models.py` |
| Add new recurrence pattern | `recurrence.py`, `llm/parser.py` (`_RECURRENCE_ALIASES`) |
| Change notification behavior | `app/daemon/notifications.py`, `app/daemon/scheduler.py`, `daemon/notifier.py` |
| Change HTML report | `app/daemon/html_report.py` |
| Change REPL display | `app/chat/display.py`, `chat/repl.py` |
| Add web API endpoint | `app/web/api.py`, `app/web/router.py` |
| Change web frontend | `src/kanademinder/static/` (index.html, style.css, app.js) |
| Add GUI method | `gui/api.py` (KanadeMinderAPI) or `gui/settings/api.py` (SettingsAPI) |
| Add new CLI subcommand | `cli.py` |
| Change config options | `config.py`, `app/config/setup.py`, `gui/settings/api.py` |
| Add new generic engine | `chat/`, `daemon/`, or `web/` (no KanadeMinder imports); adapter in `app/` |
