"""GUI Settings module for KanadeMinder configuration wizard.

This module provides a standalone settings window for configuring
KanadeMinder without using the CLI.
"""

from __future__ import annotations

from kanademinder.gui.settings.api import SettingsAPI
from kanademinder.gui.settings.window import open_settings_window

__all__ = ["SettingsAPI", "open_settings_window"]
