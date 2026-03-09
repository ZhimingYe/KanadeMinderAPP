"""Settings API for loading and saving KanadeMinder configuration.

This module provides a clean API for the settings GUI to interact
with the configuration file.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import webview

from kanademinder.config import (
    CONFIG_PATH,
    BehaviorConfig,
    Config,
    LLMConfig,
    ScheduleConfig,
    load_config,
)


class SettingsAPI:
    """API for settings operations exposed to JavaScript via pywebview.

    This class provides methods to get, validate, and save configuration
    from the settings GUI.
    """

    # Validation constants
    VALID_NOTIFICATION_MODES = {"banner", "webpage", "both"}
    VALID_TASK_TYPES = {"major", "minor"}
    VALID_PROVIDERS = {"", "openai", "anthropic"}
    TIME_PATTERN = re.compile(r"^([01]?[0-9]|2[0-3]):([0-5][0-9])$")
    STRICT_TIME_PATTERN = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")  # Requires HH:MM with leading zero

    def __init__(self, config_path: Path | None = None) -> None:
        """Initialize SettingsAPI with optional custom config path.

        Args:
            config_path: Optional path to config file. Uses default if not provided.
        """
        self._config_path = config_path or CONFIG_PATH

    def get_config(self) -> dict[str, Any]:
        """Load and return the current configuration as a dictionary.

        Returns:
            dict with llm, schedule, and behavior sections.
        """
        cfg = load_config(self._config_path)
        return {
            "llm": {
                "base_url": cfg.llm.base_url,
                "api_key": cfg.llm.api_key,
                "model": cfg.llm.model,
                "provider": cfg.llm.provider,
            },
            "schedule": {
                "interval_minutes": cfg.schedule.interval_minutes,
                "start_of_day": cfg.schedule.start_of_day,
                "end_of_day": cfg.schedule.end_of_day,
            },
            "behavior": {
                "default_task_type": cfg.behavior.default_task_type,
                "notification_mode": cfg.behavior.notification_mode,
            },
        }

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        """Validate a configuration dictionary.

        Args:
            config: Configuration dict with llm, schedule, behavior sections.

        Returns:
            List of validation error messages (empty if valid).
        """
        errors: list[str] = []

        # Validate LLM section
        llm = config.get("llm", {})
        if not llm.get("base_url", "").strip():
            errors.append("LLM base URL is required")
        if not llm.get("model", "").strip():
            errors.append("LLM model is required")

        provider = llm.get("provider", "")
        if provider and provider not in self.VALID_PROVIDERS:
            errors.append(f"Invalid provider: {provider}")

        # Validate schedule section
        schedule = config.get("schedule", {})

        interval = schedule.get("interval_minutes", 30)
        if not isinstance(interval, int) or interval < 1:
            errors.append("Interval minutes must be a positive integer")
        elif interval < 5:
            errors.append("Interval minutes should be at least 5")

        start_of_day = schedule.get("start_of_day", "")
        if not self.STRICT_TIME_PATTERN.match(start_of_day):
            errors.append("Start of day must be in HH:MM format (e.g., 08:00)")

        end_of_day = schedule.get("end_of_day", "")
        if not self.STRICT_TIME_PATTERN.match(end_of_day):
            errors.append("End of day must be in HH:MM format (e.g., 22:00)")

        # Validate behavior section
        behavior = config.get("behavior", {})

        default_type = behavior.get("default_task_type", "")
        if default_type not in self.VALID_TASK_TYPES:
            errors.append(f"Default task type must be one of: {', '.join(self.VALID_TASK_TYPES)}")

        notif_mode = behavior.get("notification_mode", "")
        if notif_mode not in self.VALID_NOTIFICATION_MODES:
            errors.append(f"Notification mode must be one of: {', '.join(self.VALID_NOTIFICATION_MODES)}")

        return errors

    def save_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Save configuration to file.

        Args:
            config: Configuration dict with llm, schedule, behavior sections.

        Returns:
            dict with success status and optional error message.
        """
        # Validate first
        errors = self.validate_config(config)
        if errors:
            return {"success": False, "error": "; ".join(errors)}

        try:
            # Build Config object from dict
            llm_data = config.get("llm", {})
            schedule_data = config.get("schedule", {})
            behavior_data = config.get("behavior", {})

            cfg = Config(
                llm=LLMConfig(
                    base_url=llm_data.get("base_url", "").strip(),
                    api_key=llm_data.get("api_key", "").strip(),
                    model=llm_data.get("model", "").strip(),
                    provider=llm_data.get("provider", "").strip(),
                ),
                schedule=ScheduleConfig(
                    interval_minutes=int(schedule_data.get("interval_minutes", 30)),
                    start_of_day=schedule_data.get("start_of_day", "08:00").strip(),
                    end_of_day=schedule_data.get("end_of_day", "22:00").strip(),
                ),
                behavior=BehaviorConfig(
                    default_task_type=behavior_data.get("default_task_type", "major"),
                    notification_mode=behavior_data.get("notification_mode", "banner"),
                ),
            )

            # Write to TOML file
            self._write_config_to_file(cfg, self._config_path)

            return {"success": True, "error": None}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def close_window(self) -> dict:
        """Close the settings window.

        Returns:
            dict with success status.
        """
        try:
            from kanademinder.gui.settings.window import close_settings_window
            close_settings_window()
            return {"success": True, "error": None}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _write_config_to_file(self, cfg: Config, path: Path = CONFIG_PATH) -> None:
        """Write configuration to TOML file.

        Args:
            cfg: Config object to write.
            path: Path to config file.
        """
        # Ensure directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        # Build TOML content
        lines: list[str] = []

        # LLM section
        lines.append("[llm]")
        if cfg.llm.provider:
            lines.append(f'provider = "{cfg.llm.provider}"')
        lines.append(f'base_url = "{cfg.llm.base_url}"')
        lines.append(f'api_key = "{cfg.llm.api_key}"')
        lines.append(f'model = "{cfg.llm.model}"')
        lines.append("")

        # Schedule section
        lines.append("[schedule]")
        lines.append(f"interval_minutes = {cfg.schedule.interval_minutes}")
        lines.append(f'start_of_day = "{cfg.schedule.start_of_day}"')
        lines.append(f'end_of_day = "{cfg.schedule.end_of_day}"')
        lines.append("")

        # Behavior section
        lines.append("[behavior]")
        lines.append(f'default_task_type = "{cfg.behavior.default_task_type}"')
        lines.append(f'notification_mode = "{cfg.behavior.notification_mode}"')
        lines.append("")

        # Write file
        path.write_text("\n".join(lines), encoding="utf-8")
