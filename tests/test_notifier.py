"""Tests for daemon/notifier.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from kanademinder.daemon.notifier import NotificationError, _escape_for_applescript, send_notification


def test_escape_double_quotes():
    assert _escape_for_applescript('say "hello"') == 'say \\"hello\\"'


def test_escape_backslashes():
    assert _escape_for_applescript("path\\to\\file") == "path\\\\to\\\\file"


def test_escape_both():
    assert _escape_for_applescript('back\\slash "quote"') == 'back\\\\slash \\"quote\\"'


def test_escape_plain_text():
    assert _escape_for_applescript("Focus on the report") == "Focus on the report"


def test_send_notification_calls_osascript():
    mock_result = MagicMock()
    mock_result.returncode = 0
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        send_notification("KanadeMinder", "Work on your report!")
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "osascript"
        assert "KanadeMinder" in args[-1]
        assert "Work on your report!" in args[-1]


def test_send_notification_escapes_special_chars():
    mock_result = MagicMock()
    mock_result.returncode = 0
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        send_notification('Title "with" quotes', 'Body "with" quotes')
        script = mock_run.call_args[0][0][-1]
        assert '\\"with\\"' in script


def test_send_notification_with_subtitle():
    mock_result = MagicMock()
    mock_result.returncode = 0
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        send_notification("KanadeMinder", "Details here", subtitle="2 overdue · 1 due today")
        script = mock_run.call_args[0][0][-1]
        assert "subtitle" in script
        assert "2 overdue" in script
        assert "Details here" in script


def test_send_notification_without_subtitle_omits_subtitle_keyword():
    mock_result = MagicMock()
    mock_result.returncode = 0
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        send_notification("KanadeMinder", "Just a body")
        script = mock_run.call_args[0][0][-1]
        assert "subtitle" not in script


def test_send_notification_raises_on_failure():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "osascript: can't open display"
    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(NotificationError, match="osascript failed"):
            send_notification("Title", "Body")
