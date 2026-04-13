"""
git_agent.llm.anthropic — Anthropic Claude LLM provider.

Native Anthropic Messages API implementation with:
    - System prompt handling (Anthropic-style, passed separately)
    - Streaming support
    - Tool/function calling
    - Token counting and usage tracking
    - Retry with exponential backoff
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.request
import urllib.error
from typing import Any, AsyncIterator, Dict, List, Optional

from .base import (
    BaseLLMProvider,
    LLMAuthError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    ModelInfo,
    TokenUsage,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

_ANTHROPIC_MODELS: Dict[str, Dict[str, Any]] = {
    "claude-sonnet-4-20250514": {
        "context_window": 200000,
        "max_output_tokens": 16384,
        "supports_tools": True,
        "supports_streaming": True,
        "supports_vision": True,
        "cost_per_1k_prompt_tokens": 0.003,
        "cost_per_1k_completion_tokens": 0.015,
    },
    "claude-3-5-sonnet-20241022": {
        "context_window": 200000,
        "max_output_tokens": 8192,
        "supports_tools": True,
        "supports_streaming": True,
        "supports_vision": True,
        "cost_per_1k_prompt_tokens": 0.003,
        "cost_per_1k_completion_tokens": 0.015,
    },
    "claude-3-5-haiku-20241022": {
        "context_window": 200000,
        "max_output_tokens": 8192,
        "supports_tools": True,
        "supports_streaming": True,
        "supports_vision": True,
        "cost_per_1k_prompt_tokens": 0.001,
        "cost_per_1k_completion_tokens": 0.005,
    },
    "claude-3-opus-20240229": {
        "context_window": 200000,
        "max_output_tokens": 4096,
        "supports_tools": True,
        "supports_streaming": True,
        "supports_vision": True,
        "cost_per_1k_prompt_tokens": 0.015,
        "cost_per_1k_completion_tokens": 0.075,
    },
    "claude-3-haiku-20240307": {
        "context_window": 200000,
        "max_output_tokens": 4096,
        "supports_tools": True,
        "supports_streaming": True,
        "supports_vision": True,
        "cost_per_1k_prompt_tokens": 0.00025,
        "cost_per_1k_completion_tokens": 0.00125,
    },
}

_DEFAULT_ANTHROPIC_INFO: Dict[str, Any] = {
    "context_window": 200000,
    "max_output_tokens": 4096,
    "supports_tools": True,
    "supports_streaming": True,
    "supports_vision": False,
    "cost_per_1k_prompt_tokens": 0.0,
    "cost_per_1k_completion_tokens": 0.0,
}


# ---------------------------------------------------------------------------
# Anthropic Provider
# ---------------------------------------------------------------------------

class AnthropicProvider(BaseLLMProvider):
    """Native Anthropic Claude API provider.

    Parameters
    ----------
    model:
        Model name (e.g. "claude-sonnet-4-20250514").
    api_key:
        Anthropic API key.
    api_base:
        Custom API base URL. Defaults to Anthropic's official endpoint.
    temperature:
        Default sampling temperature.
    max_tokens:
        Default max response tokens.
    max_retries:
        Maximum retry attempts.
    timeout:
        Request timeout in seconds.
    **kwargs:
        Additional parameters (e.g. ``anthropic_version``).
    """

    DEFAULT_BASE_URL = "https://api.anthropic.com"
    DEFAULT_VERSION = "2023-06-01"

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        max_retries: int = 3,
        timeout: float = 60.0,
        anthropic_version: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            timeout=timeout,
            **kwargs,
        )
        self.api_key = api_key or ""
        self.api_base = (api_base or self.DEFAULT_BASE_URL).rstrip("/")
        self.anthropic_version = anthropic_version or self.DEFAULT_VERSION
        self.max_retries = max_retries
        self.timeout = timeout
        self._last_usage: Optional[TokenUsage] = None

    # -- Model info ---------------------------------------------------------

    def _get_model_info(self) -> ModelInfo:
        info = _ANTHROPIC_MODELS.get(self.model, _DEFAULT_ANTHROPIC_INFO)
        return ModelInfo(
            name=self.model,
            provider="anthropic",
            **info,
        )

    def get_last_usage(self) -> Optional[TokenUsage]:
        return self._last_usage

    # -- Message conversion -------------------------------------------------

    @staticmethod
    def _convert_messages(
        messages: List[Dict[str, str]],
    ) -> tuple[Optional[str], List[Dict[str, Any]]]:
        """Convert OpenAI-style messages to Anthropic format.

        Anthropic separates system prompts and does not allow a ``system``
        role in the messages array. This method extracts system messages
        and converts the rest.

        Returns
        -------
        tuple[str | None, list[dict]]
            (system_prompt, anthropic_messages)
        """
        system_prompt: Optional[str] = None
        anthropic_messages: List[Dict[str, Any]] = []

        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")

            if role == "system":
                # Anthropic takes system prompt separately
                if system_prompt is not None:
                    system_prompt += "\n\n" + content
                else:
                    system_prompt = content
            elif role == "user":
                anthropic_messages.append({"role": "user", "content": content})
            elif role == "assistant":
                anthropic_messages.append({"role": "assistant", "content": content})
            elif role == "tool":
                # Anthropic uses tool_result content blocks
                # We'll convert to a user message with tool_result
                anthropic_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": m.get("tool_call_id", ""),
                        "content": content,
                    }],
                })
            else:
                # Unknown role — treat as user
                anthropic_messages.append({"role": "user", "content": content})

        return system_prompt, anthropic_messages

    @staticmethod
    def _convert_tools(
        tools: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Convert OpenAI-style tools to Anthropic format."""
        anthropic_tools: List[Dict[str, Any]] = []
        for tool in tools:
            if tool.get("type") == "function":
                func = tool["function"]
                anth_tool: Dict[str, Any] = {
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
                }
                anthropic_tools.append(anth_tool)
            else:
                anthropic_tools.append(tool)
        return anthropic_tools

    # -- Sync completion ----------------------------------------------------

    def _complete_sync(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> str:
        self.validate_messages(messages)
        system_prompt, anth_messages = self._convert_messages(messages)
        payload = self._build_payload(anth_messages, temperature, max_tokens,
                                       system=system_prompt, **kwargs)
        response = self._request_with_retry(payload)
        return self._extract_text(response)

    def _complete_sync_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> tuple[str, List[Dict[str, Any]]]:
        """Completion with tool calling."""
        self.validate_messages(messages)
        system_prompt, anth_messages = self._convert_messages(messages)
        anth_tools = self._convert_tools(tools)
        payload = self._build_payload(
            anth_messages, temperature, max_tokens,
            system=system_prompt, tools=anth_tools, **kwargs,
        )
        response = self._request_with_retry(payload)
        return self._extract_text_and_tools(response)

    # -- Async completion ---------------------------------------------------

    async def _complete_async(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> str:
        self.validate_messages(messages)
        system_prompt, anth_messages = self._convert_messages(messages)
        payload = self._build_payload(anth_messages, temperature, max_tokens,
                                       system=system_prompt, **kwargs)
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, self._request_with_retry, payload)
        return self._extract_text(response)

    # -- Streaming ----------------------------------------------------------

    async def stream(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream tokens from Anthropic Claude."""
        self.validate_messages(messages)
        temperature = kwargs.pop("temperature", self.temperature)
        max_tokens = kwargs.pop("max_tokens", self.max_tokens)
        system_prompt, anth_messages = self._convert_messages(messages)
        payload = self._build_payload(
            anth_messages, temperature, max_tokens,
            system=system_prompt, stream=True, **kwargs,
        )

        loop = asyncio.get_event_loop()

        def _do_stream():
            req = self._make_request(payload)
            try:
                resp = urllib.request.urlopen(req, timeout=self.timeout)
                current_line = ""
                for raw_line in resp:
                    decoded = raw_line.decode("utf-8").strip()
                    if not decoded.startswith("data: "):
                        continue
                    try:
                        chunk = json.loads(decoded[6:])
                        event_type = chunk.get("type", "")

                        if event_type == "content_block_delta":
                            delta = chunk.get("delta", {})
                            text = delta.get("text", "")
                            if text:
                                yield text
                    except json.JSONDecodeError:
                        continue
            except Exception as exc:
                raise LLMUnavailableError(f"Streaming error: {exc}") from exc

        chunks: List[str] = []
        for chunk in _do_stream():
            chunks.append(chunk)
        for chunk in chunks:
            yield chunk

    # -- HTTP layer ---------------------------------------------------------

    def _make_request(self, payload: Dict[str, Any]) -> urllib.request.Request:
        """Build a urllib Request for the Anthropic API."""
        url = f"{self.api_base}/v1/messages"
        data = json.dumps(payload).encode("utf-8")

        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "anthropic-version": self.anthropic_version,
            "x-api-key": self.api_key,
        }

        # Allow custom headers via kwargs
        custom_headers = self._extra.get("headers", {})
        headers.update(custom_headers)

        return urllib.request.Request(url, data=data, headers=headers, method="POST")

    def _request_with_retry(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send request with exponential backoff retry."""
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                req = self._make_request(payload)
                resp = urllib.request.urlopen(req, timeout=self.timeout)
                body = resp.read().decode("utf-8")
                data = json.loads(body)

                # Track usage
                usage = data.get("usage", {})
                self._last_usage = TokenUsage(
                    prompt_tokens=usage.get("input_tokens", 0),
                    completion_tokens=usage.get("output_tokens", 0),
                    total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                )

                return data

            except urllib.error.HTTPError as exc:
                status_code = exc.code
                body = exc.read().decode("utf-8", errors="replace")

                if status_code == 401 or status_code == 403:
                    raise LLMAuthError(
                        f"Authentication failed (HTTP {status_code}): {body}"
                    ) from exc

                if status_code == 429:
                    last_exc = exc
                    if attempt < self.max_retries:
                        wait = 2 ** attempt + 1
                        logger.warning(
                            "Rate limited, retrying in %ds (attempt %d/%d)",
                            wait, attempt + 1, self.max_retries,
                        )
                        time.sleep(wait)
                        continue
                    raise LLMRateLimitError(
                        f"Rate limited after {self.max_retries} retries: {body}"
                    ) from exc

                if status_code >= 500:
                    last_exc = exc
                    if attempt < self.max_retries:
                        wait = 2 ** attempt + 1
                        logger.warning(
                            "Server error HTTP %d, retrying in %ds (attempt %d/%d)",
                            status_code, wait, attempt + 1, self.max_retries,
                        )
                        time.sleep(wait)
                        continue
                    raise LLMUnavailableError(
                        f"Server error HTTP {status_code}: {body}"
                    ) from exc

                raise LLMError(f"HTTP error {status_code}: {body}") from exc

            except urllib.error.URLError as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    wait = 2 ** attempt + 1
                    logger.warning(
                        "Connection error, retrying in %ds (attempt %d/%d)",
                        wait, attempt + 1, self.max_retries,
                    )
                    time.sleep(wait)
                    continue
                raise LLMUnavailableError(f"Connection failed: {exc}") from exc

            except Exception as exc:
                raise LLMError(f"Unexpected error: {exc}") from exc

        raise LLMUnavailableError(f"All retries exhausted: {last_exc}")

    # -- Payload builders ---------------------------------------------------

    def _build_payload(
        self,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Build the Anthropic API request payload."""
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        for key in ("stream", "tools", "tool_choice", "top_p",
                     "top_k", "stop_sequences", "metadata"):
            if key in kwargs:
                payload[key] = kwargs[key]

        # System prompt is a top-level field in Anthropic
        if "system" in kwargs and kwargs["system"]:
            payload["system"] = kwargs["system"]

        return payload

    # -- Response parsing ---------------------------------------------------

    @staticmethod
    def _extract_text(response: Dict[str, Any]) -> str:
        """Extract text content from an Anthropic response."""
        try:
            content = response["content"]
            texts = []
            for block in content:
                if block.get("type") == "text":
                    texts.append(block["text"])
            return "\n".join(texts) if texts else ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Malformed response: {exc}") from exc

    @staticmethod
    def _extract_text_and_tools(response: Dict[str, Any]) -> tuple[str, List[Dict[str, Any]]]:
        """Extract text and tool use blocks from an Anthropic response."""
        try:
            content = response["content"]
            texts = []
            tool_calls = []

            for block in content:
                if block.get("type") == "text":
                    texts.append(block["text"])
                elif block.get("type") == "tool_use":
                    tool_calls.append({
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block.get("input", {})),
                        },
                    })

            return "\n".join(texts) if texts else "", tool_calls
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Malformed response: {exc}") from exc
