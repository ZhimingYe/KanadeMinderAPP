"""Tests for the GUI settings module."""

from __future__ import annotations

import pytest

from kanademinder.gui.settings.api import SettingsAPI


class TestSettingsAPI:
    """Test the SettingsAPI class."""

    def test_get_config_returns_structure(self, tmp_path, monkeypatch):
        """get_config returns expected structure."""
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            """\
[llm]
base_url = "https://api.test.com/v1"
api_key = "test-key"
model = "test-model"
provider = "openai"

[schedule]
interval_minutes = 60
start_of_day = "09:00"
end_of_day = "21:00"

[behavior]
default_task_type = "minor"
notification_mode = "webpage"
""",
            encoding="utf-8",
        )

        api = SettingsAPI(config_path=config_path)
        result = api.get_config()

        assert "llm" in result
        assert "schedule" in result
        assert "behavior" in result

        assert result["llm"]["base_url"] == "https://api.test.com/v1"
        assert result["llm"]["api_key"] == "test-key"
        assert result["llm"]["model"] == "test-model"
        assert result["llm"]["provider"] == "openai"

        assert result["schedule"]["interval_minutes"] == 60
        assert result["schedule"]["start_of_day"] == "09:00"
        assert result["schedule"]["end_of_day"] == "21:00"

        assert result["behavior"]["default_task_type"] == "minor"
        assert result["behavior"]["notification_mode"] == "webpage"

    def test_validate_config_valid(self):
        """validate_config returns empty list for valid config."""
        api = SettingsAPI()
        config = {
            "llm": {
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
                "model": "gpt-4o",
                "provider": "",
            },
            "schedule": {
                "interval_minutes": 30,
                "start_of_day": "08:00",
                "end_of_day": "22:00",
            },
            "behavior": {
                "default_task_type": "major",
                "notification_mode": "banner",
            },
        }

        errors = api.validate_config(config)
        assert errors == []

    def test_validate_config_missing_llm_fields(self):
        """validate_config catches missing LLM fields."""
        api = SettingsAPI()
        config = {
            "llm": {
                "base_url": "",
                "api_key": "",
                "model": "",
                "provider": "",
            },
            "schedule": {
                "interval_minutes": 30,
                "start_of_day": "08:00",
                "end_of_day": "22:00",
            },
            "behavior": {
                "default_task_type": "major",
                "notification_mode": "banner",
            },
        }

        errors = api.validate_config(config)
        assert any("base url" in e.lower() for e in errors)
        assert any("model" in e.lower() for e in errors)

    def test_validate_config_invalid_time_format(self):
        """validate_config catches invalid time formats."""
        api = SettingsAPI()
        config = {
            "llm": {
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
                "model": "gpt-4o",
                "provider": "",
            },
            "schedule": {
                "interval_minutes": 30,
                "start_of_day": "8:00",  # Missing leading zero
                "end_of_day": "25:00",  # Invalid hour
            },
            "behavior": {
                "default_task_type": "major",
                "notification_mode": "banner",
            },
        }

        errors = api.validate_config(config)
        assert any("start of day" in e.lower() for e in errors) or any("hh:mm" in e.lower() for e in errors)
        assert any("end of day" in e.lower() for e in errors) or any("hh:mm" in e.lower() for e in errors)

    def test_validate_config_invalid_interval(self):
        """validate_config catches invalid interval."""
        api = SettingsAPI()
        config = {
            "llm": {
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
                "model": "gpt-4o",
                "provider": "",
            },
            "schedule": {
                "interval_minutes": 2,  # Too low
                "start_of_day": "08:00",
                "end_of_day": "22:00",
            },
            "behavior": {
                "default_task_type": "major",
                "notification_mode": "banner",
            },
        }

        errors = api.validate_config(config)
        assert any("interval" in e.lower() for e in errors)

    def test_validate_config_invalid_notification_mode(self):
        """validate_config catches invalid notification mode."""
        api = SettingsAPI()
        config = {
            "llm": {
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
                "model": "gpt-4o",
                "provider": "",
            },
            "schedule": {
                "interval_minutes": 30,
                "start_of_day": "08:00",
                "end_of_day": "22:00",
            },
            "behavior": {
                "default_task_type": "major",
                "notification_mode": "invalid_mode",
            },
        }

        errors = api.validate_config(config)
        assert any("notification" in e.lower() for e in errors)

    def test_validate_config_invalid_task_type(self):
        """validate_config catches invalid task type."""
        api = SettingsAPI()
        config = {
            "llm": {
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
                "model": "gpt-4o",
                "provider": "",
            },
            "schedule": {
                "interval_minutes": 30,
                "start_of_day": "08:00",
                "end_of_day": "22:00",
            },
            "behavior": {
                "default_task_type": "invalid_type",
                "notification_mode": "banner",
            },
        }

        errors = api.validate_config(config)
        assert any("task type" in e.lower() for e in errors)

    def test_save_config_creates_file(self, tmp_path, monkeypatch):
        """save_config writes valid config to file."""
        config_path = tmp_path / "config.toml"

        api = SettingsAPI(config_path=config_path)
        config = {
            "llm": {
                "base_url": "https://api.test.com/v1",
                "api_key": "test-key",
                "model": "test-model",
                "provider": "anthropic",
            },
            "schedule": {
                "interval_minutes": 45,
                "start_of_day": "07:30",
                "end_of_day": "23:00",
            },
            "behavior": {
                "default_task_type": "minor",
                "notification_mode": "both",
            },
        }

        result = api.save_config(config)

        assert result["success"] is True
        assert result["error"] is None
        assert config_path.exists()

        content = config_path.read_text(encoding="utf-8")
        assert 'base_url = "https://api.test.com/v1"' in content
        assert 'model = "test-model"' in content
        assert "interval_minutes = 45" in content
        assert 'default_task_type = "minor"' in content

    def test_save_config_validation_failure(self):
        """save_config returns error for invalid config."""
        api = SettingsAPI()
        config = {
            "llm": {
                "base_url": "",  # Invalid - empty
                "api_key": "test",
                "model": "",  # Invalid - empty
                "provider": "",
            },
            "schedule": {
                "interval_minutes": 30,
                "start_of_day": "08:00",
                "end_of_day": "22:00",
            },
            "behavior": {
                "default_task_type": "major",
                "notification_mode": "banner",
            },
        }

        result = api.save_config(config)

        assert result["success"] is False
        assert result["error"] is not None
