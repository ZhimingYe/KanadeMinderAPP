"""Multi-provider HTTP client (OpenAI + Anthropic) using stdlib urllib with retry logic."""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any

# Anthropic API version to use
_ANTHROPIC_VERSION = "2023-06-01"

# Known Anthropic base URLs for auto-detection
_ANTHROPIC_HOSTS = ("api.anthropic.com",)


class LLMError(Exception):
    """Raised when the LLM call fails after all retries."""


def _hint_for_http_error(code: int, body: str) -> str:
    """Return a user-friendly hint based on the HTTP error code."""
    if code == 401:
        return "Invalid API key. Check [llm] api_key in ~/.kanademinder/config.toml"
    if code == 403:
        return "Access forbidden. Your API key may lack permissions for this model."
    if code == 404:
        if "model" in body.lower():
            return "Model not found. Check [llm] model in ~/.kanademinder/config.toml"
        return "Endpoint not found. Check [llm] base_url in ~/.kanademinder/config.toml"
    if code == 429:
        return "Rate limited. The request will be retried automatically."
    if code == 400:
        return "Bad request. The prompt may be too long or malformed."
    if code >= 500:
        return "Server error on the LLM provider side. Retrying..."
    return ""


def _detect_provider(base_url: str) -> str:
    """Auto-detect provider from base_url.

    Returns "anthropic" or "openai" (default for any OpenAI-compatible endpoint).
    """
    lower = base_url.lower()
    for host in _ANTHROPIC_HOSTS:
        if host in lower:
            return "anthropic"
    return "openai"


def _build_openai_request(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    json_mode: bool,
) -> tuple[str, bytes, dict[str, str]]:
    """Build URL, body, and headers for an OpenAI-compatible request."""
    url = f"{base_url}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    return url, body, headers


def _build_anthropic_request(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    json_mode: bool,
) -> tuple[str, bytes, dict[str, str]]:
    """Build URL, body, and headers for an Anthropic Messages API request.

    Handles the key differences:
    - System messages are extracted to a top-level "system" field
    - Auth is via x-api-key header (not Bearer token)
    - max_tokens is required
    - JSON mode is enforced via a prefill trick
    """
    url = f"{base_url}/v1/messages"

    # Separate system messages from the rest
    system_parts: list[str] = []
    api_messages: list[dict[str, str]] = []
    for msg in messages:
        if msg["role"] == "system":
            system_parts.append(msg["content"])
        else:
            api_messages.append({"role": msg["role"], "content": msg["content"]})

    # Anthropic requires alternating user/assistant; merge consecutive same-role msgs
    api_messages = _merge_consecutive_roles(api_messages)

    # Anthropic requires messages to start with a user message
    if api_messages and api_messages[0]["role"] != "user":
        api_messages.insert(0, {"role": "user", "content": "(conversation continues)"})

    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": 4096,
        "messages": api_messages,
    }

    if system_parts:
        payload["system"] = "\n\n".join(system_parts)

    # JSON mode: add a prefill to steer output toward JSON
    if json_mode:
        # Append an assistant prefill so Claude starts with "{"
        payload["messages"].append({"role": "assistant", "content": "{"})

    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": _ANTHROPIC_VERSION,
    }
    return url, body, headers


def _merge_consecutive_roles(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Merge consecutive messages with the same role (required by Anthropic API)."""
    if not messages:
        return []
    merged: list[dict[str, str]] = [dict(messages[0])]
    for msg in messages[1:]:
        if msg["role"] == merged[-1]["role"]:
            merged[-1]["content"] += "\n\n" + msg["content"]
        else:
            merged.append(dict(msg))
    return merged


def _extract_openai_content(data: dict[str, Any]) -> str:
    """Extract assistant content from an OpenAI response."""
    choices = data.get("choices")
    if not choices:
        raise LLMError("LLM returned no choices in the response.")
    content = choices[0].get("message", {}).get("content")
    if content is None:
        raise LLMError("LLM returned an empty message content.")
    return content


def _extract_anthropic_content(data: dict[str, Any], json_prefilled: bool) -> str:
    """Extract assistant content from an Anthropic response."""
    content_blocks = data.get("content")
    if not content_blocks:
        raise LLMError("Anthropic returned no content blocks.")

    # Collect all text blocks
    texts: list[str] = []
    for block in content_blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            texts.append(block["text"])
        elif isinstance(block, str):
            texts.append(block)

    if not texts:
        raise LLMError("Anthropic returned no text content.")

    result = "\n".join(texts)

    # If we used a JSON prefill, prepend the "{" we started with
    if json_prefilled:
        result = "{" + result

    return result


class LLMClient:
    """HTTP client for OpenAI-compatible and Anthropic chat completion APIs.

    Auto-detects the provider from base_url:
    - api.anthropic.com → Anthropic Messages API
    - anything else → OpenAI-compatible /chat/completions

    Can be overridden with the `provider` parameter.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        provider: str | None = None,
        debug: bool = False,
        timeout: int = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.provider = provider or _detect_provider(self.base_url)
        self.debug = debug
        self.timeout = timeout

    @property
    def is_anthropic(self) -> bool:
        return self.provider == "anthropic"

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        max_retries: int = 3,
    ) -> str:
        """Send a chat completion request and return the assistant's message content.

        Retries up to max_retries times with exponential backoff on 429 and 5xx errors.
        Respects Retry-After headers when provided.
        Automatically adapts request/response format based on provider.
        """
        # Pre-flight check: empty API key
        if not self.api_key or self.api_key == "sk-REPLACE_ME":
            raise LLMError(
                "API key not configured. Run 'kanademinder config init' "
                "then edit [llm] api_key in ~/.kanademinder/config.toml"
            )

        # Build provider-specific request
        if self.is_anthropic:
            url, body, headers = _build_anthropic_request(
                self.base_url, self.api_key, self.model, messages, json_mode
            )
        else:
            url, body, headers = _build_openai_request(
                self.base_url, self.api_key, self.model, messages, json_mode
            )

        if self.debug:
            print(f"[DEBUG] POST {url} (provider={self.provider})")
            print(f"[DEBUG] model={self.model}, messages={len(messages)}, json_mode={json_mode}")
            print(f"[DEBUG] payload size: {len(body)} bytes")

        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                req = urllib.request.Request(url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8")
                    if self.debug:
                        print(f"[DEBUG] response ({len(raw)} bytes): {raw[:2000]}")
                    data = json.loads(raw)

                    # Extract content based on provider
                    if self.is_anthropic:
                        content = _extract_anthropic_content(data, json_prefilled=json_mode)
                    else:
                        content = _extract_openai_content(data)

                        # Log finish reason if not 'stop' (OpenAI only)
                        finish_reason = data.get("choices", [{}])[0].get("finish_reason", "stop")
                        if self.debug and finish_reason != "stop":
                            print(f"[DEBUG] finish_reason: {finish_reason}")

                    return content

            except urllib.error.HTTPError as exc:
                last_exc = exc
                error_body = ""
                try:
                    error_body = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
                hint = _hint_for_http_error(exc.code, error_body)

                if exc.code in (429, 500, 502, 503, 504, 529):
                    # 529 = Anthropic overloaded
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    if retry_after:
                        try:
                            wait = int(retry_after)
                            wait = max(1, min(wait, 60))   # floor 1 s, ceiling 60 s
                        except ValueError:
                            wait = 2**attempt
                    else:
                        wait = 2**attempt
                    if self.debug:
                        print(
                            f"[DEBUG] HTTP {exc.code}: {hint}. "
                            f"Retrying in {wait}s (attempt {attempt + 1}/{max_retries})"
                        )
                    time.sleep(wait)
                else:
                    error_msg = f"HTTP {exc.code}"
                    if hint:
                        error_msg += f": {hint}"
                    # Extract API error message
                    try:
                        err_data = json.loads(error_body)
                        # OpenAI: error.message, Anthropic: error.message
                        api_msg = err_data.get("error", {}).get("message", "")
                        if api_msg:
                            error_msg += f" ({api_msg})"
                    except (json.JSONDecodeError, AttributeError):
                        pass
                    raise LLMError(error_msg) from exc

            except urllib.error.URLError as exc:
                reason = exc.reason if hasattr(exc, "reason") else exc
                if isinstance(reason, (socket.timeout, TimeoutError)):
                    last_exc = exc
                    if self.debug:
                        print(f"[DEBUG] Request timed out (attempt {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                    raise LLMError(
                        f"Request timed out after {self.timeout}s. "
                        "The LLM provider may be slow or unreachable."
                    ) from exc
                raise LLMError(
                    f"Cannot connect to {self.base_url}: {reason}. "
                    "Check [llm] base_url in ~/.kanademinder/config.toml"
                ) from exc

            except json.JSONDecodeError as exc:
                raise LLMError(f"LLM returned invalid JSON: {exc}") from exc

        raise LLMError(f"LLM call failed after {max_retries} attempts.") from last_exc
