"""Interactive setup wizard for KanadeMinder configuration."""

from __future__ import annotations

import sys
from pathlib import Path

from kanademinder.config import (
    CONFIG_PATH,
    BehaviorConfig,
    LLMConfig,
    ScheduleConfig,
    load_config,
)


# --- Validators ---

def _validate_hhmm(value: str) -> bool:
    """Return True if value matches HH:MM format with valid hours/minutes."""
    parts = value.split(":")
    if len(parts) != 2:
        return False
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return 0 <= h <= 23 and 0 <= m <= 59


def _validate_positive_int(value: str) -> bool:
    """Return True if value is a string representation of a positive integer."""
    try:
        return int(value) > 0
    except ValueError:
        return False


def _validate_notification_mode(value: str) -> bool:
    return value in ("banner", "webpage", "both")


def _validate_task_type(value: str) -> bool:
    return value in ("major", "minor")


# --- Input helper ---

def _ask(
    prompt: str,
    default: str,
    validator=None,
    error_msg: str = "Invalid value.",
) -> str:
    """Prompt the user for input, looping until valid; empty input returns default."""
    display_default = f" [{default}]" if default else ""
    while True:
        raw = input(f"{prompt}{display_default}: ").strip()
        if raw == "":
            return default
        if validator is None or validator(raw):
            return raw
        print(f"  {error_msg}")


# --- Section prompts ---

def _prompt_llm_section(current: LLMConfig) -> dict:
    print("\n[llm]")
    base_url = _ask("  base_url", current.base_url)
    api_key = _ask("  api_key", current.api_key)
    model = _ask("  model", current.model)
    return {"base_url": base_url, "api_key": api_key, "model": model}


def _prompt_schedule_section(current: ScheduleConfig) -> dict:
    print("\n[schedule]")
    interval_minutes = _ask(
        "  interval_minutes",
        str(current.interval_minutes),
        validator=_validate_positive_int,
        error_msg="Must be a positive integer.",
    )
    start_of_day = _ask(
        "  start_of_day (HH:MM)",
        current.start_of_day,
        validator=_validate_hhmm,
        error_msg="Must be HH:MM format (e.g. 08:00).",
    )
    end_of_day = _ask(
        "  end_of_day (HH:MM)",
        current.end_of_day,
        validator=_validate_hhmm,
        error_msg="Must be HH:MM format (e.g. 22:00).",
    )
    return {
        "interval_minutes": int(interval_minutes),
        "start_of_day": start_of_day,
        "end_of_day": end_of_day,
    }


def _prompt_behavior_section(current: BehaviorConfig) -> dict:
    print("\n[behavior]")
    default_task_type = _ask(
        "  default_task_type (major/minor)",
        current.default_task_type,
        validator=_validate_task_type,
        error_msg="Must be 'major' or 'minor'.",
    )
    if sys.platform != "darwin":
        print("  Note: macOS banners are unavailable on this platform; 'banner' mode will use 'webpage'.")
    notification_mode = _ask(
        "  notification_mode (banner/webpage/both)",
        current.notification_mode,
        validator=_validate_notification_mode,
        error_msg="Must be 'banner', 'webpage', or 'both'.",
    )
    return {
        "default_task_type": default_task_type,
        "notification_mode": notification_mode,
    }


# --- TOML builder ---

def _toml_str(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _build_config_toml(llm: dict, schedule: dict, behavior: dict) -> str:
    return (
        "[llm]\n"
        f'base_url = "{_toml_str(llm["base_url"])}"\n'
        f'api_key  = "{_toml_str(llm["api_key"])}"\n'
        f'model    = "{_toml_str(llm["model"])}"\n'
        "\n"
        "[schedule]\n"
        f'interval_minutes = {schedule["interval_minutes"]}\n'
        f'start_of_day     = "{_toml_str(schedule["start_of_day"])}"\n'
        f'end_of_day       = "{_toml_str(schedule["end_of_day"])}"\n'
        "\n"
        "[behavior]\n"
        f'default_task_type = "{_toml_str(behavior["default_task_type"])}"\n'
        f'notification_mode = "{_toml_str(behavior["notification_mode"])}"\n'
    )


# --- Top-level ---

def run_setup(path: Path = CONFIG_PATH) -> bool:
    """Run the interactive setup wizard.

    Returns True if the config was written, False if the user aborted.
    KeyboardInterrupt propagates to the caller.
    """
    if path.exists():
        cfg = load_config(path)
        print(f"Existing config found at {path}. Existing values shown as defaults.")
    else:
        cfg = type("_Defaults", (), {
            "llm": LLMConfig(),
            "schedule": ScheduleConfig(),
            "behavior": BehaviorConfig(),
        })()

    print("KanadeMinder Setup Wizard")
    print("=" * 40)
    print("Press Enter to keep the default value shown in brackets.")

    llm = _prompt_llm_section(cfg.llm)
    schedule = _prompt_schedule_section(cfg.schedule)
    behavior = _prompt_behavior_section(cfg.behavior)

    print("\nSummary:")
    print(f"  base_url          = {llm['base_url']}")
    print(f"  model             = {llm['model']}")
    print(f"  interval_minutes  = {schedule['interval_minutes']}")
    print(f"  start_of_day      = {schedule['start_of_day']}")
    print(f"  end_of_day        = {schedule['end_of_day']}")
    print(f"  default_task_type = {behavior['default_task_type']}")
    print(f"  notification_mode = {behavior['notification_mode']}")

    confirm = input("\nWrite config? [Y/n]: ").strip().lower()
    if confirm not in ("", "y", "yes"):
        print("Aborted. No changes written.")
        return False

    content = _build_config_toml(llm, schedule, behavior)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"Config written to {path}")
    return True
