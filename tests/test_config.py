"""Tests for config.py."""

from __future__ import annotations

from pathlib import Path

from kanademinder.config import Config, load_config, write_default_config


def test_load_config_defaults_when_no_file(tmp_path: Path):
    cfg = load_config(tmp_path / "nonexistent.toml")
    assert isinstance(cfg, Config)
    assert cfg.llm.model == "gpt-4o"
    assert cfg.schedule.interval_minutes == 30
    assert cfg.behavior.default_task_type == "major"


def test_load_config_from_file(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '[llm]\nbase_url = "https://example.com/v1"\napi_key = "sk-test"\nmodel = "gpt-3.5-turbo"\n'
        "[schedule]\ninterval_minutes = 15\nend_of_day = \"23:00\"\n"
        '[behavior]\ndefault_task_type = "minor"\n',
        encoding="utf-8",
    )
    cfg = load_config(config_file)
    assert cfg.llm.base_url == "https://example.com/v1"
    assert cfg.llm.api_key == "sk-test"
    assert cfg.llm.model == "gpt-3.5-turbo"
    assert cfg.schedule.interval_minutes == 15
    assert cfg.schedule.end_of_day == "23:00"
    assert cfg.behavior.default_task_type == "minor"


def test_load_config_partial_override(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[llm]\nmodel = "claude-3"\n', encoding="utf-8")
    cfg = load_config(config_file)
    assert cfg.llm.model == "claude-3"
    # Defaults preserved for unspecified keys
    assert cfg.llm.base_url == "https://api.openai.com/v1"
    assert cfg.schedule.interval_minutes == 30


def test_write_default_config_creates_file(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    result = write_default_config(config_file)
    assert result is True
    assert config_file.exists()
    content = config_file.read_text()
    assert "api_key" in content
    assert "interval_minutes" in content


def test_write_default_config_does_not_overwrite(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("custom = true\n")
    result = write_default_config(config_file)
    assert result is False
    assert "custom = true" in config_file.read_text()


def test_write_default_config_creates_parent_dirs(tmp_path: Path):
    config_file = tmp_path / "nested" / "dirs" / "config.toml"
    write_default_config(config_file)
    assert config_file.exists()


def test_default_config_is_valid_toml(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    write_default_config(config_file)
    cfg = load_config(config_file)
    assert isinstance(cfg, Config)


def test_notification_mode_defaults_to_banner(tmp_path: Path):
    cfg = load_config(tmp_path / "nonexistent.toml")
    assert cfg.behavior.notification_mode == "banner"


def test_notification_mode_can_be_set(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[behavior]\nnotification_mode = "webpage"\n', encoding="utf-8")
    cfg = load_config(config_file)
    assert cfg.behavior.notification_mode == "webpage"


def test_html_summary_true_migrates_to_both(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[behavior]\nhtml_summary = true\n', encoding="utf-8")
    cfg = load_config(config_file)
    assert cfg.behavior.notification_mode == "both"


def test_html_summary_false_migrates_to_banner(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[behavior]\nhtml_summary = false\n', encoding="utf-8")
    cfg = load_config(config_file)
    assert cfg.behavior.notification_mode == "banner"


def test_notification_mode_takes_precedence_over_html_summary(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '[behavior]\nhtml_summary = true\nnotification_mode = "banner"\n', encoding="utf-8"
    )
    cfg = load_config(config_file)
    assert cfg.behavior.notification_mode == "banner"


def test_notification_mode_invalid_falls_back_to_banner(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[behavior]\nnotification_mode = "toast"\n', encoding="utf-8")
    cfg = load_config(config_file)
    assert cfg.behavior.notification_mode == "banner"
