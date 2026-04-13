"""
git_agent.llm.openai_compat — OpenAI-compatible LLM provider.

Works with any backend that implements the OpenAI Chat Completions API:
    - OpenAI (gpt-4, gpt-3.5-turbo, etc.)
    - Azure OpenAI
    - Together AI
    - Groq
    - DeepSeek
    - Local models via OpenAI-compatible servers
    - Proxies (ZeroClaw, LiteLLM, etc.)

Features:
    - Synchronous and async completion
    - Streaming (async generator)
    - Tool/function calling
    - Retry with exponential backoff
    - Token counting / usage tracking
    - Configurable temperature, max_tokens, top_p, etc.
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
    LLMContextError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    ModelInfo,
    TokenUsage,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Known model defaults
# ---------------------------------------------------------------------------

_MODEL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "gpt-4o": {
        "context_window": 128000,
        "max_output_tokens": 16384,
        "supports_tools": True,
        "supports_streaming": True,
        "supports_vision": True,
        "cost_per_1k_prompt_tokens": 0.005,
        "cost_per_1k_completion_tokens": 0.015,
    },
    "gpt-4o-mini": {
        "context_window": 128000,
        "max_output_tokens": 16384,
        "supports_tools": True,
        "supports_streaming": True,
        "supports_vision": True,
        "cost_per_1k_prompt_tokens": 0.00015,
        "cost_per_1k_completion_tokens": 0.0006,
    },
    "gpt-4-turbo": {
        "context_window": 128000,
        "max_output_tokens": 4096,
        "supports_tools": True,
        "supports_streaming": True,
        "supports_vision": True,
        "cost_per_1k_prompt_tokens": 0.01,
        "cost_per_1k_completion_tokens": 0.03,
    },
    "gpt-4": {
        "context_window": 8192,
        "max_output_tokens": 8192,
        "supports_tools": True,
        "supports_streaming": True,
        "supports_vision": False,
        "cost_per_1k_prompt_tokens": 0.03,
        "cost_per_1k_completion_tokens": 0.06,
    },
    "gpt-3.5-turbo": {
        "context_window": 16385,
        "max_output_tokens": 4096,
        "supports_tools": True,
        "supports_streaming": True,
        "supports_vision": False,
        "cost_per_1k_prompt_tokens": 0.0005,
        "cost_per_1k_completion_tokens": 0.0015,
    },
    "deepseek-chat": {
        "context_window": 65536,
        "max_output_tokens": 8192,
        "supports_tools": True,
        "supports_streaming": True,
        "supports_vision": False,
        "cost_per_1k_prompt_tokens": 0.00014,
        "cost_per_1k_completion_tokens": 0.00028,
    },
    "deepseek-reasoner": {
        "context_window": 65536,
        "max_output_tokens": 8192,
        "supports_tools": False,
        "supports_streaming": True,
        "supports_vision": False,
        "cost_per_1k_prompt_tokens": 0.00055,
        "cost_per_1k_completion_tokens": 0.00219,
    },
}

_DEFAULT_MODEL_INFO: Dict[str, Any] = {
    "context_window": 4096,
    "max_output_tokens": 4096,
    "supports_tools": False,
    "supports_streaming": True,
    "supports_vision": False,
    "cost_per_1k_prompt_tokens": 0.0,
    "cost_per_1k_completion_tokens": 0.0,
}


# ---------------------------------------------------------------------------
# OpenAI-Compatible Provider
# ---------------------------------------------------------------------------

class OpenAICompatibleProvider(BaseLLMProvider):
    """OpenAI-compatible LLM provider.

    Works with OpenAI, Azure OpenAI, Together AI, Groq, DeepSeek,
    any OpenAI-compatible server, and proxies (ZeroClaw, LiteLLM, etc.).

    Parameters
    ----------
    model:
        Model name (e.g. "gpt-4o", "deepseek-chat").
    api_key:
        API key for authentication.
    api_base:
        Base URL for the API. Defaults to ``https://api.openai.com/v1``.
    temperature:
        Default sampling temperature.
    max_tokens:
        Default max response tokens.
    top_p:
        Default nucleus sampling parameter.
    max_retries:
        Maximum retry attempts with exponential backoff.
    timeout:
        Request timeout in seconds.
    **kwargs:
        Additional parameters passed to the API (e.g. ``organization``,
        ``user``, custom headers).
    """

    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        top_p: float = 1.0,
        max_retries: int = 3,
        timeout: float = 60.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            max_retries=max_retries,
            timeout=timeout,
            **kwargs,
        )
        self.api_key = api_key or ""
        self.api_base = (api_base or self.DEFAULT_BASE_URL).rstrip("/")
        self.top_p = top_p
        self.max_retries = max_retries
        self.timeout = timeout
        self._last_usage: Optional[TokenUsage] = None

    # -- Model info ---------------------------------------------------------

    def _get_model_info(self) -> ModelInfo:
        info = _MODEL_REGISTRY.get(self.model, _DEFAULT_MODEL_INFO)
        return ModelInfo(
            name=self.model,
            provider="openai_compatible",
            **info,
        )

    def get_last_usage(self) -> Optional[TokenUsage]:
        """Return token usage from the last API call."""
        return self._last_usage

    # -- Sync completion ----------------------------------------------------

    def _complete_sync(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> str:
        self.validate_messages(messages)
        payload = self._build_payload(messages, temperature, max_tokens, **kwargs)
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
        payload = self._build_payload(messages, temperature, max_tokens, tools=tools, **kwargs)
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
        payload = self._build_payload(messages, temperature, max_tokens, **kwargs)
        # Run sync HTTP in a thread to avoid blocking
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, self._request_with_retry, payload)
        return self._extract_text(response)

    # -- Streaming ----------------------------------------------------------

    async def stream(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream tokens from the model."""
        self.validate_messages(messages)
        temperature = kwargs.pop("temperature", self.temperature)
        max_tokens = kwargs.pop("max_tokens", self.max_tokens)
        payload = self._build_payload(messages, temperature, max_tokens, stream=True, **kwargs)

        # Use sync HTTP with streaming in an executor
        loop = asyncio.get_event_loop()

        def _do_stream():
            req = self._make_request(payload)
            try:
                resp = urllib.request.urlopen(req, timeout=self.timeout)
                for line in resp:
                    decoded = line.decode("utf-8").strip()
                    if not decoded or decoded == "data: [DONE]":
                        continue
                    if decoded.startswith("data: "):
                        try:
                            chunk = json.loads(decoded[6:])
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue
            except Exception as exc:
                raise LLMUnavailableError(f"Streaming error: {exc}") from exc

        # Since we can't directly yield from a thread, we collect
        # and yield from the main thread
        chunks: List[str] = []
        for chunk in _do_stream():
            chunks.append(chunk)
        for chunk in chunks:
            yield chunk

    # -- HTTP layer ---------------------------------------------------------

    def _make_request(self, payload: Dict[str, Any]) -> urllib.request.Request:
        """Build a urllib Request for the API."""
        url = f"{self.api_base}/chat/completions"
        data = json.dumps(payload).encode("utf-8")

        headers: Dict[str, str] = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

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
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
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

        # Should not reach here, but just in case
        raise LLMUnavailableError(f"All retries exhausted: {last_exc}")

    # -- Payload builders ---------------------------------------------------

    def _build_payload(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Build the API request payload."""
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": self.top_p,
        }

        # Add optional fields
        for key in ("stream", "tools", "tool_choice", "response_format",
                     "frequency_penalty", "presence_penalty", "stop",
                     "logit_bias", "user", "seed"):
            if key in kwargs:
                payload[key] = kwargs[key]

        return payload

    # -- Response parsing ---------------------------------------------------

    @staticmethod
    def _extract_text(response: Dict[str, Any]) -> str:
        """Extract the text content from a chat completion response."""
        try:
            return response["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Malformed response: {exc}") from exc

    @staticmethod
    def _extract_text_and_tools(response: Dict[str, Any]) -> tuple[str, List[Dict[str, Any]]]:
        """Extract text and tool calls from a chat completion response."""
        try:
            message = response["choices"][0]["message"]
            text = message.get("content") or ""
            tool_calls = message.get("tool_calls") or []
            return text, tool_calls
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Malformed response: {exc}") from exc
