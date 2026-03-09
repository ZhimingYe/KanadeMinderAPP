"""Tests for recurrence.py — next_occurrence edge cases."""

from __future__ import annotations

from datetime import datetime

import pytest

from kanademinder.recurrence import next_occurrence


# --- daily ---

def test_daily_advances_one_day():
    dt = datetime(2026, 3, 6, 9, 0)
    assert next_occurrence(dt, "daily") == datetime(2026, 3, 7, 9, 0)


def test_daily_preserves_time():
    dt = datetime(2026, 3, 10, 14, 30)
    result = next_occurrence(dt, "daily")
    assert result == datetime(2026, 3, 11, 14, 30)


def test_daily_crosses_month_boundary():
    dt = datetime(2026, 3, 31, 8, 0)
    assert next_occurrence(dt, "daily") == datetime(2026, 4, 1, 8, 0)


# --- weekdays ---

def test_weekdays_friday_to_monday():
    # Friday → Monday (skips Saturday and Sunday)
    dt = datetime(2026, 3, 6, 9, 0)  # Friday
    result = next_occurrence(dt, "weekdays")
    assert result == datetime(2026, 3, 9, 9, 0)  # Monday
    assert result.weekday() == 0  # Monday


def test_weekdays_monday_to_tuesday():
    dt = datetime(2026, 3, 9, 9, 0)  # Monday
    result = next_occurrence(dt, "weekdays")
    assert result == datetime(2026, 3, 10, 9, 0)  # Tuesday


def test_weekdays_thursday_to_friday():
    dt = datetime(2026, 3, 5, 9, 0)  # Thursday
    result = next_occurrence(dt, "weekdays")
    assert result == datetime(2026, 3, 6, 9, 0)  # Friday


def test_weekdays_saturday_to_monday():
    dt = datetime(2026, 3, 7, 9, 0)  # Saturday
    result = next_occurrence(dt, "weekdays")
    assert result.weekday() == 0  # Monday


# --- weekly ---

def test_weekly_advances_seven_days():
    dt = datetime(2026, 3, 6, 10, 0)
    assert next_occurrence(dt, "weekly") == datetime(2026, 3, 13, 10, 0)


def test_weekly_preserves_time():
    dt = datetime(2026, 3, 6, 14, 45)
    result = next_occurrence(dt, "weekly")
    assert result.hour == 14
    assert result.minute == 45


# --- monthly ---

def test_monthly_advances_one_month():
    dt = datetime(2026, 3, 15, 9, 0)
    assert next_occurrence(dt, "monthly") == datetime(2026, 4, 15, 9, 0)


def test_monthly_december_to_january():
    dt = datetime(2026, 12, 10, 8, 0)
    result = next_occurrence(dt, "monthly")
    assert result == datetime(2027, 1, 10, 8, 0)


def test_monthly_clamps_to_month_end():
    # March 31 → April 30 (April has only 30 days)
    dt = datetime(2026, 3, 31, 9, 0)
    result = next_occurrence(dt, "monthly")
    assert result == datetime(2026, 4, 30, 9, 0)


def test_monthly_jan_31_to_feb():
    # Jan 31 → Feb 28 (non-leap year)
    dt = datetime(2026, 1, 31, 9, 0)
    result = next_occurrence(dt, "monthly")
    assert result == datetime(2026, 2, 28, 9, 0)


# --- yearly ---

def test_yearly_advances_one_year():
    dt = datetime(2026, 3, 6, 9, 0)
    assert next_occurrence(dt, "yearly") == datetime(2027, 3, 6, 9, 0)


def test_yearly_preserves_month_day():
    dt = datetime(2026, 12, 25, 0, 0)
    result = next_occurrence(dt, "yearly")
    assert result == datetime(2027, 12, 25, 0, 0)


# --- unknown pattern ---

def test_unknown_pattern_returns_none():
    dt = datetime(2026, 3, 6, 9, 0)
    assert next_occurrence(dt, "biweekly") is None


def test_empty_pattern_returns_none():
    dt = datetime(2026, 3, 6, 9, 0)
    assert next_occurrence(dt, "") is None


# --- case insensitivity ---

def test_pattern_case_insensitive():
    dt = datetime(2026, 3, 6, 9, 0)
    assert next_occurrence(dt, "DAILY") == datetime(2026, 3, 7, 9, 0)
    assert next_occurrence(dt, "Weekly") == datetime(2026, 3, 13, 9, 0)
