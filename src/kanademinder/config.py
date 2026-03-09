"""Configuration loading via tomllib."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_DIR = Path.home() / ".kanademinder"
CONFIG_PATH = CONFIG_DIR / "config.toml"
DB_PATH = CONFIG_DIR / "tasks.db"

_DEFAULT_CONFIG_TOML = """\
[llm]
# Provider is auto-detected from base_url, or set explicitly: "openai" | "anthropic"
# provider = "openai"

## --- OpenAI (default) ---
base_url = "https://api.openai.com/v1"
api_key  = "sk-REPLACE_ME"
model    = "gpt-4o"

## --- Anthropic (uncomment to use) ---
# base_url = "https://api.anthropic.com"
# api_key  = "sk-ant-REPLACE_ME"
# model    = "claude-sonnet-4-20250514"

[schedule]
interval_minutes = 30
start_of_day     = "08:00"
end_of_day       = "22:00"

[behavior]
default_task_type = "major"
# Notification mode: "banner" (macOS banners only), "webpage" (HTML report in
# browser), or "both" (banners + HTML report). Non-macOS always uses "webpage".
# notification_mode = "banner"
"""


@dataclass
class LLMConfig:
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o"
    provider: str = ""  # "" = auto-detect from base_url


@dataclass
class ScheduleConfig:
    interval_minutes: int = 30
    start_of_day: str = "08:00"
    end_of_day: str = "22:00"


@dataclass
class BehaviorConfig:
    default_task_type: str = "major"
    notification_mode: str = "banner"


@dataclass
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    behavior: BehaviorConfig = field(default_factory=BehaviorConfig)


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Load config from TOML file, falling back to defaults for missing keys."""
    if not path.exists():
        return Config()

    with open(path, "rb") as f:
        data = tomllib.load(f)

    llm_data = data.get("llm", {})
    schedule_data = data.get("schedule", {})
    behavior_data = data.get("behavior", {})

    return Config(
        llm=LLMConfig(
            base_url=llm_data.get("base_url", "https://api.openai.com/v1"),
            api_key=llm_data.get("api_key", ""),
            model=llm_data.get("model", "gpt-4o"),
            provider=llm_data.get("provider", ""),
        ),
        schedule=ScheduleConfig(
            interval_minutes=schedule_data.get("interval_minutes", 30),
            start_of_day=schedule_data.get("start_of_day", "08:00"),
            end_of_day=schedule_data.get("end_of_day", "22:00"),
        ),
        behavior=BehaviorConfig(
            default_task_type=behavior_data.get("default_task_type", "major"),
            notification_mode=_resolve_notification_mode(behavior_data),
        ),
    )


def _resolve_notification_mode(behavior_data: dict) -> str:
    if "notification_mode" in behavior_data:
        raw = behavior_data["notification_mode"]
        return raw if raw in ("banner", "webpage", "both") else "banner"
    elif behavior_data.get("html_summary", False):
        return "both"
    else:
        return "banner"


def write_default_config(path: Path = CONFIG_PATH) -> bool:
    """Write default config.toml if it doesn't already exist.

    Returns True if the file was written, False if it already existed.
    """
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_DEFAULT_CONFIG_TOML, encoding="utf-8")
    return True
