"""Generic daemon tick: EOD suppression + system notification dispatch.

This module has no project-specific dependencies.  Pass a
``build_notifications`` callable to ``run_tick`` to inject the
application-level content (see ``daemon.task_scheduler`` for the
KanadeMinder implementation).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from kanademinder.daemon.notifier import send_notification


def _parse_hhmm(s: str) -> tuple[int, int] | None:
    """Parse "HH:MM" into (hour, minute), or return None on invalid input."""
    try:
        h, m = map(int, s.split(":"))
        return h, m
    except (ValueError, AttributeError):
        return None


def _in_quiet_hours(
    end_of_day: str,
    start_of_day: str = "08:00",
    now: datetime | None = None,
) -> bool:
    """Return True when the current time falls in the quiet window.

    Two modes depending on whether the active window crosses midnight:

    Normal window (end_of_day > start_of_day, e.g. start=08:00, end=22:00):
      Active:  08:00 ≤ now < 22:00
      Quiet:   now < 08:00  OR  now ≥ 22:00

    Overnight window (end_of_day < start_of_day, e.g. start=08:00, end=02:00):
      Active:  now ≥ 08:00  OR  now < 02:00   (spans midnight)
      Quiet:   02:00 ≤ now < 08:00

    Examples with start=08:00, end=22:00:
      - 07:30 → quiet  (before morning)
      - 08:00 → active
      - 21:59 → active
      - 22:00 → quiet  (past end of day)
      - 01:00 → quiet  (overnight)

    Examples with start=08:00, end=02:00:
      - 16:23 → active  (afternoon, before midnight)
      - 01:00 → active  (early morning, before 02:00)
      - 02:00 → quiet   (quiet window begins)
      - 07:59 → quiet   (still in quiet window)
      - 08:00 → active  (new day starts)
    """
    if now is None:
        now = datetime.now()

    eod = _parse_hhmm(end_of_day)
    sod = _parse_hhmm(start_of_day)
    if eod is None or sod is None:
        return False

    now_mins = now.hour * 60 + now.minute
    eod_mins = eod[0] * 60 + eod[1]
    sod_mins = sod[0] * 60 + sod[1]

    if eod_mins < sod_mins:
        # Overnight window: quiet zone is eod ≤ now < sod
        return eod_mins <= now_mins < sod_mins
    else:
        # Normal window: quiet zone is now < sod OR now ≥ eod
        return now_mins < sod_mins or now_mins >= eod_mins


# Keep old name as an alias so existing tests referencing it still work
def _is_past_end_of_day(end_of_day: str, now: datetime | None = None) -> bool:
    return _in_quiet_hours(end_of_day, now=now)


def run_tick(
    build_notifications: Callable[[datetime], list[tuple[str, str]] | None],
    *,
    start_of_day: str = "08:00",
    end_of_day: str = "22:00",
    force: bool = False,
    now: datetime | None = None,
) -> None:
    """One scheduler tick.

    Suppression conditions (exits silently), bypassed when ``force=True``:
    - Current time is in the overnight quiet window (>= end_of_day or < start_of_day)
    - ``build_notifications`` returns ``None`` or an empty list

    ``build_notifications(now)`` is responsible for fetching data, calling any
    external services, and returning a list of ``(title, body)`` tuples — one
    per system notification to fire.  Returning ``None`` signals "nothing to
    notify about" and the tick exits silently.
    """
    if now is None:
        now = datetime.now()

    if not force and _in_quiet_hours(end_of_day, start_of_day, now):
        print(
            f"Suppressed: current time {now.strftime('%H:%M')} is outside active window "
            f"({start_of_day}–{end_of_day}). Use --force to run anyway."
        )
        return

    notifications = build_notifications(now)
    if not notifications:
        return

    for title, body in notifications:
        send_notification(title, body)
