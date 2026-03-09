"""Tests for llm/client.py — error handling, resilience, and multi-provider support."""

from __future__ import annotations

import json
import socket
import urllib.error
from unittest.mock import MagicMock, call, patch

import pytest

from kanademinder.llm.client import (
    LLMClient,
    LLMError,
    _build_anthropic_request,
    _build_openai_request,
    _detect_provider,
    _extract_anthropic_content,
    _extract_openai_content,
    _hint_for_http_error,
    _merge_consecutive_roles,
)


# --- _hint_for_http_error ---

def test_hint_401():
    hint = _hint_for_http_error(401, "")
    assert "API key" in hint


def test_hint_404_model():
    hint = _hint_for_http_error(404, "model not found")
    assert "model" in hint.lower()


def test_hint_404_endpoint():
    hint = _hint_for_http_error(404, "not found")
    assert "base_url" in hint


def test_hint_429():
    hint = _hint_for_http_error(429, "")
    assert "Rate limited" in hint


def test_hint_500():
    hint = _hint_for_http_error(500, "")
    assert "Server error" in hint


def test_hint_unknown():
    hint = _hint_for_http_error(418, "I'm a teapot")
    assert hint == ""


# --- Provider detection ---

def test_detect_openai():
    assert _detect_provider("https://api.openai.com/v1") == "openai"


def test_detect_anthropic():
    assert _detect_provider("https://api.anthropic.com") == "anthropic"


def test_detect_anthropic_case_insensitive():
    assert _detect_provider("https://API.ANTHROPIC.COM") == "anthropic"


def test_detect_custom_openai_compatible():
    assert _detect_provider("https://my-proxy.example.com/v1") == "openai"


def test_detect_localhost():
    assert _detect_provider("http://localhost:8000") == "openai"


def test_explicit_provider_override():
    client = LLMClient(
        base_url="https://my-custom-proxy.com",
        api_key="sk-test",
        model="claude-sonnet-4-20250514",
        provider="anthropic",
    )
    assert client.is_anthropic is True


# --- Pre-flight checks ---

def test_empty_api_key_raises():
    client = LLMClient(base_url="https://api.example.com", api_key="", model="gpt-4o")
    with pytest.raises(LLMError, match="API key not configured"):
        client.chat([{"role": "user", "content": "hi"}])


def test_placeholder_api_key_raises():
    client = LLMClient(base_url="https://api.example.com", api_key="sk-REPLACE_ME", model="gpt-4o")
    with pytest.raises(LLMError, match="API key not configured"):
        client.chat([{"role": "user", "content": "hi"}])


# --- OpenAI request building ---

def test_openai_request_url():
    url, body, headers = _build_openai_request(
        "https://api.openai.com/v1", "sk-test", "gpt-4o",
        [{"role": "user", "content": "hi"}], json_mode=False,
    )
    assert url == "https://api.openai.com/v1/chat/completions"
    assert headers["Authorization"] == "Bearer sk-test"
    payload = json.loads(body)
    assert payload["model"] == "gpt-4o"
    assert payload["messages"][0]["role"] == "user"


def test_openai_request_json_mode():
    _, body, _ = _build_openai_request(
        "https://api.openai.com/v1", "sk-test", "gpt-4o",
        [{"role": "user", "content": "hi"}], json_mode=True,
    )
    payload = json.loads(body)
    assert payload["response_format"] == {"type": "json_object"}


def test_openai_request_no_json_mode():
    _, body, _ = _build_openai_request(
        "https://api.openai.com/v1", "sk-test", "gpt-4o",
        [{"role": "user", "content": "hi"}], json_mode=False,
    )
    payload = json.loads(body)
    assert "response_format" not in payload


# --- Anthropic request building ---

def test_anthropic_request_url():
    url, body, headers = _build_anthropic_request(
        "https://api.anthropic.com", "sk-ant-test", "claude-sonnet-4-20250514",
        [{"role": "system", "content": "Be helpful"}, {"role": "user", "content": "hi"}],
        json_mode=False,
    )
    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == "sk-ant-test"
    assert "anthropic-version" in headers
    assert "Authorization" not in headers


def test_anthropic_system_extracted():
    _, body, _ = _build_anthropic_request(
        "https://api.anthropic.com", "sk-ant-test", "claude-sonnet-4-20250514",
        [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
        ],
        json_mode=False,
    )
    payload = json.loads(body)
    assert payload["system"] == "System prompt"
    # No system message in the messages array
    for msg in payload["messages"]:
        assert msg["role"] != "system"


def test_anthropic_multiple_system_merged():
    _, body, _ = _build_anthropic_request(
        "https://api.anthropic.com", "sk-ant-test", "claude-sonnet-4-20250514",
        [
            {"role": "system", "content": "Part 1"},
            {"role": "system", "content": "Part 2"},
            {"role": "user", "content": "Hello"},
        ],
        json_mode=False,
    )
    payload = json.loads(body)
    assert "Part 1" in payload["system"]
    assert "Part 2" in payload["system"]


def test_anthropic_max_tokens_set():
    _, body, _ = _build_anthropic_request(
        "https://api.anthropic.com", "sk-ant-test", "claude-sonnet-4-20250514",
        [{"role": "user", "content": "hi"}], json_mode=False,
    )
    payload = json.loads(body)
    assert payload["max_tokens"] == 4096


def test_anthropic_json_mode_prefill():
    _, body, _ = _build_anthropic_request(
        "https://api.anthropic.com", "sk-ant-test", "claude-sonnet-4-20250514",
        [{"role": "user", "content": "give me json"}], json_mode=True,
    )
    payload = json.loads(body)
    # Last message should be an assistant prefill with "{"
    last_msg = payload["messages"][-1]
    assert last_msg["role"] == "assistant"
    assert last_msg["content"] == "{"


def test_anthropic_starts_with_user():
    _, body, _ = _build_anthropic_request(
        "https://api.anthropic.com", "sk-ant-test", "claude-sonnet-4-20250514",
        [{"role": "assistant", "content": "Previous response"}, {"role": "user", "content": "hi"}],
        json_mode=False,
    )
    payload = json.loads(body)
    assert payload["messages"][0]["role"] == "user"


# --- Merge consecutive roles ---

def test_merge_same_role():
    msgs = [
        {"role": "user", "content": "A"},
        {"role": "user", "content": "B"},
        {"role": "assistant", "content": "C"},
    ]
    merged = _merge_consecutive_roles(msgs)
    assert len(merged) == 2
    assert "A" in merged[0]["content"]
    assert "B" in merged[0]["content"]
    assert merged[1]["content"] == "C"


def test_merge_alternating():
    msgs = [
        {"role": "user", "content": "A"},
        {"role": "assistant", "content": "B"},
        {"role": "user", "content": "C"},
    ]
    merged = _merge_consecutive_roles(msgs)
    assert len(merged) == 3


def test_merge_empty():
    assert _merge_consecutive_roles([]) == []


# --- Response extraction ---

def test_extract_openai_content():
    data = {"choices": [{"message": {"content": "Hello!"}, "finish_reason": "stop"}]}
    assert _extract_openai_content(data) == "Hello!"


def test_extract_openai_no_choices():
    with pytest.raises(LLMError, match="no choices"):
        _extract_openai_content({"choices": []})


def test_extract_openai_null_content():
    with pytest.raises(LLMError, match="empty message"):
        _extract_openai_content({"choices": [{"message": {"content": None}}]})


def test_extract_anthropic_text():
    data = {"content": [{"type": "text", "text": "Hello!"}]}
    assert _extract_anthropic_content(data, json_prefilled=False) == "Hello!"


def test_extract_anthropic_json_prefill():
    data = {"content": [{"type": "text", "text": '"action": "create", "task": null}'}]}
    result = _extract_anthropic_content(data, json_prefilled=True)
    assert result.startswith("{")
    assert '"action": "create"' in result


def test_extract_anthropic_multiple_blocks():
    data = {"content": [
        {"type": "text", "text": "Part 1"},
        {"type": "text", "text": "Part 2"},
    ]}
    result = _extract_anthropic_content(data, json_prefilled=False)
    assert "Part 1" in result
    assert "Part 2" in result


def test_extract_anthropic_no_content():
    with pytest.raises(LLMError, match="no content"):
        _extract_anthropic_content({"content": []}, json_prefilled=False)


# --- End-to-end: OpenAI response ---

def test_successful_openai_response():
    client = LLMClient(base_url="https://api.openai.com/v1", api_key="sk-test", model="gpt-4o")
    response_data = json.dumps({
        "choices": [{"message": {"content": "Hello!"}, "finish_reason": "stop"}]
    }).encode()

    mock_resp = MagicMock()
    mock_resp.read.return_value = response_data
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = client.chat([{"role": "user", "content": "hi"}])
    assert result == "Hello!"


# --- End-to-end: Anthropic response ---

def test_successful_anthropic_response():
    client = LLMClient(
        base_url="https://api.anthropic.com", api_key="sk-ant-test",
        model="claude-sonnet-4-20250514",
    )
    assert client.is_anthropic

    response_data = json.dumps({
        "content": [{"type": "text", "text": "Hello from Claude!"}],
        "stop_reason": "end_turn",
    }).encode()

    mock_resp = MagicMock()
    mock_resp.read.return_value = response_data
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        result = client.chat([
            {"role": "system", "content": "Be nice"},
            {"role": "user", "content": "hi"},
        ])

    assert result == "Hello from Claude!"

    # Verify the request was sent to the Anthropic endpoint
    actual_req = mock_urlopen.call_args[0][0]
    assert "/v1/messages" in actual_req.full_url
    assert actual_req.get_header("X-api-key") == "sk-ant-test"
    assert actual_req.get_header("Anthropic-version") is not None


def test_anthropic_json_mode_roundtrip():
    client = LLMClient(
        base_url="https://api.anthropic.com", api_key="sk-ant-test",
        model="claude-sonnet-4-20250514",
    )

    # Simulate Anthropic returning the rest of the JSON after our "{" prefill
    response_data = json.dumps({
        "content": [{"type": "text", "text": '"action": "create", "task": {"name": "Test"}, "message": "Done!"}'}],
        "stop_reason": "end_turn",
    }).encode()

    mock_resp = MagicMock()
    mock_resp.read.return_value = response_data
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = client.chat(
            [{"role": "system", "content": "respond in JSON"}, {"role": "user", "content": "test"}],
            json_mode=True,
        )

    # Result should be valid JSON
    parsed = json.loads(result)
    assert parsed["action"] == "create"
    assert parsed["task"]["name"] == "Test"


# --- HTTP errors ---

def test_401_raises_with_hint():
    client = LLMClient(base_url="https://api.example.com", api_key="sk-bad", model="gpt-4o")

    exc = urllib.error.HTTPError(
        "https://api.example.com/v1/chat/completions",
        401, "Unauthorized", {}, None,
    )
    with patch("urllib.request.urlopen", side_effect=exc):
        with pytest.raises(LLMError, match="API key"):
            client.chat([{"role": "user", "content": "hi"}])


def test_url_error_raises_with_base_url_hint():
    client = LLMClient(base_url="https://bad-host.invalid", api_key="sk-test", model="gpt-4o")

    exc = urllib.error.URLError("Name or service not known")
    with patch("urllib.request.urlopen", side_effect=exc):
        with pytest.raises(LLMError, match="Cannot connect"):
            client.chat([{"role": "user", "content": "hi"}])


# --- Timeout retry via URLError(socket.timeout) ---

def test_timeout_urlopen_is_retried():
    client = LLMClient(
        base_url="https://api.example.com", api_key="sk-test", model="gpt-4o",
        timeout=5,
    )
    timeout_exc = urllib.error.URLError(socket.timeout("timed out"))

    with patch("urllib.request.urlopen", side_effect=timeout_exc) as mock_urlopen:
        with patch("time.sleep"):
            with pytest.raises(LLMError, match="timed out"):
                client.chat([{"role": "user", "content": "hi"}], max_retries=3)

    assert mock_urlopen.call_count == 3


def test_retry_after_clamped_high():
    """Retry-After: 3600 should be clamped to at most 60 s."""
    client = LLMClient(base_url="https://api.example.com", api_key="sk-test", model="gpt-4o")

    headers = {"Retry-After": "3600"}
    exc = urllib.error.HTTPError(
        "https://api.example.com/v1/chat/completions",
        429, "Too Many Requests", headers, None,
    )
    # Succeed on the last attempt
    response_data = json.dumps({
        "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]
    }).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = response_data
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", side_effect=[exc, mock_resp]):
        with patch("time.sleep") as mock_sleep:
            client.chat([{"role": "user", "content": "hi"}], max_retries=3)

    # The sleep value should have been clamped to ≤ 60
    sleep_val = mock_sleep.call_args_list[0][0][0]
    assert sleep_val <= 60


def test_retry_after_clamped_zero():
    """Retry-After: 0 should be clamped to at least 1 s."""
    client = LLMClient(base_url="https://api.example.com", api_key="sk-test", model="gpt-4o")

    headers = {"Retry-After": "0"}
    exc = urllib.error.HTTPError(
        "https://api.example.com/v1/chat/completions",
        429, "Too Many Requests", headers, None,
    )
    response_data = json.dumps({
        "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]
    }).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = response_data
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", side_effect=[exc, mock_resp]):
        with patch("time.sleep") as mock_sleep:
            client.chat([{"role": "user", "content": "hi"}], max_retries=3)

    sleep_val = mock_sleep.call_args_list[0][0][0]
    assert sleep_val >= 1
