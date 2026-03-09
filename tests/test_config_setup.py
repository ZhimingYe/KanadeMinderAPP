"""Tests for app/config/setup.py — interactive setup wizard."""

from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from kanademinder.app.config.setup import (
    _ask,
    _build_config_toml,
    _validate_hhmm,
    _validate_notification_mode,
    _validate_positive_int,
    _validate_task_type,
    run_setup,
)


# --- Validator unit tests (pure, no IO) ---

def test_validate_hhmm_valid():
    assert _validate_hhmm("08:00") is True
    assert _validate_hhmm("22:30") is True
    assert _validate_hhmm("00:00") is True
    assert _validate_hhmm("23:59") is True


def test_validate_hhmm_invalid():
    assert _validate_hhmm("24:00") is False
    assert _validate_hhmm("12:60") is False
    assert _validate_hhmm("not-a-time") is False
    assert _validate_hhmm("12") is False
    assert _validate_hhmm("") is False


def test_validate_positive_int_valid():
    assert _validate_positive_int("1") is True
    assert _validate_positive_int("30") is True
    assert _validate_positive_int("999") is True


def test_validate_positive_int_invalid():
    assert _validate_positive_int("0") is False
    assert _validate_positive_int("-1") is False
    assert _validate_positive_int("abc") is False
    assert _validate_positive_int("1.5") is False


def test_validate_notification_mode_valid():
    assert _validate_notification_mode("banner") is True
    assert _validate_notification_mode("webpage") is True
    assert _validate_notification_mode("both") is True


def test_validate_notification_mode_invalid():
    assert _validate_notification_mode("toast") is False
    assert _validate_notification_mode("") is False
    assert _validate_notification_mode("Banner") is False


def test_validate_task_type_valid():
    assert _validate_task_type("major") is True
    assert _validate_task_type("minor") is True


def test_validate_task_type_invalid():
    assert _validate_task_type("Major") is False
    assert _validate_task_type("") is False
    assert _validate_task_type("other") is False


# --- _ask tests ---

def test_ask_empty_input_returns_default():
    with patch("builtins.input", return_value=""):
        result = _ask("Prompt", "default_val")
    assert result == "default_val"


def test_ask_valid_input_returned():
    with patch("builtins.input", return_value="my_value"):
        result = _ask("Prompt", "default")
    assert result == "my_value"


def test_ask_loops_on_invalid_then_accepts_valid(capsys):
    inputs = iter(["bad", "good"])
    with patch("builtins.input", side_effect=inputs):
        result = _ask("Prompt", "default", validator=lambda v: v == "good", error_msg="Try 'good'.")
    assert result == "good"
    captured = capsys.readouterr()
    assert "Try 'good'." in captured.out


def test_ask_no_validator_accepts_any_input():
    with patch("builtins.input", return_value="anything"):
        result = _ask("Prompt", "default")
    assert result == "anything"


# --- _build_config_toml ---

def test_build_config_toml_round_trips():
    llm = {"base_url": "https://api.openai.com/v1", "api_key": "sk-test", "model": "gpt-4o"}
    schedule = {"interval_minutes": 30, "start_of_day": "08:00", "end_of_day": "22:00"}
    behavior = {"default_task_type": "major", "notification_mode": "banner"}
    content = _build_config_toml(llm, schedule, behavior)
    parsed = tomllib.loads(content)
    assert parsed["llm"]["base_url"] == "https://api.openai.com/v1"
    assert parsed["llm"]["api_key"] == "sk-test"
    assert parsed["llm"]["model"] == "gpt-4o"
    assert parsed["schedule"]["interval_minutes"] == 30
    assert parsed["schedule"]["start_of_day"] == "08:00"
    assert parsed["schedule"]["end_of_day"] == "22:00"
    assert parsed["behavior"]["default_task_type"] == "major"
    assert parsed["behavior"]["notification_mode"] == "banner"


def test_build_config_toml_escapes_special_chars():
    llm = {"base_url": "https://host/v1", "api_key": 'sk-"quoted"', "model": "m"}
    schedule = {"interval_minutes": 15, "start_of_day": "09:00", "end_of_day": "21:00"}
    behavior = {"default_task_type": "minor", "notification_mode": "both"}
    content = _build_config_toml(llm, schedule, behavior)
    parsed = tomllib.loads(content)
    assert parsed["llm"]["api_key"] == 'sk-"quoted"'


# --- run_setup integration ---

def _make_inputs(*values: str):
    """Build a side_effect list for input() mocking."""
    return list(values)


def test_run_setup_creates_new_config(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    inputs = _make_inputs(
        # LLM
        "https://api.openai.com/v1",  # base_url
        "sk-mykey",                   # api_key
        "gpt-4o",                     # model
        # Schedule
        "30",                         # interval_minutes
        "08:00",                      # start_of_day
        "22:00",                      # end_of_day
        # Behavior
        "major",                      # default_task_type
        "banner",                     # notification_mode
        # Confirm
        "y",
    )
    with patch("builtins.input", side_effect=inputs):
        result = run_setup(config_file)
    assert result is True
    assert config_file.exists()
    parsed = tomllib.loads(config_file.read_text())
    assert parsed["llm"]["api_key"] == "sk-mykey"
    assert parsed["behavior"]["notification_mode"] == "banner"


def test_run_setup_uses_existing_values_as_defaults(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '[llm]\nbase_url = "https://custom.host/v1"\napi_key = "sk-existing"\nmodel = "gpt-3.5"\n'
        "[schedule]\ninterval_minutes = 15\nstart_of_day = \"09:00\"\nend_of_day = \"21:00\"\n"
        '[behavior]\ndefault_task_type = "minor"\nnotification_mode = "both"\n',
        encoding="utf-8",
    )
    # Accept all defaults (empty input) and confirm
    inputs = _make_inputs("", "", "", "", "", "", "", "", "y")
    with patch("builtins.input", side_effect=inputs):
        result = run_setup(config_file)
    assert result is True
    parsed = tomllib.loads(config_file.read_text())
    assert parsed["llm"]["api_key"] == "sk-existing"
    assert parsed["schedule"]["interval_minutes"] == 15
    assert parsed["behavior"]["notification_mode"] == "both"


def test_run_setup_returns_false_on_n(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    inputs = _make_inputs(
        "https://api.openai.com/v1", "sk-key", "gpt-4o",
        "30", "08:00", "22:00",
        "major", "banner",
        "n",  # abort
    )
    with patch("builtins.input", side_effect=inputs):
        result = run_setup(config_file)
    assert result is False
    assert not config_file.exists()


def test_run_setup_keyboard_interrupt_propagates(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    with patch("builtins.input", side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            run_setup(config_file)


def test_run_setup_written_toml_is_valid(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    inputs = _make_inputs(
        "https://api.anthropic.com", "sk-ant-key", "claude-sonnet-4-20250514",
        "60", "07:00", "23:00",
        "minor", "webpage",
        "",  # confirm (default Y)
    )
    with patch("builtins.input", side_effect=inputs):
        run_setup(config_file)
    content = config_file.read_text()
    parsed = tomllib.loads(content)
    assert parsed["llm"]["model"] == "claude-sonnet-4-20250514"
    assert parsed["schedule"]["interval_minutes"] == 60
    assert parsed["behavior"]["notification_mode"] == "webpage"
