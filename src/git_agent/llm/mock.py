"""
git_agent.llm.mock — Mock LLM provider for testing.

Returns canned responses for deterministic testing with:
    - Configurable canned responses (static or per-message-pattern)
    - Configurable artificial delay (for testing timeouts)
    - Full call logging (messages, kwargs, call count)
    - Optional error simulation
"""

from __future__ import annotations

import asyncio
import logging
import time
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .base import (
    BaseLLMProvider,
    LLMError,
    ModelInfo,
)

logger = logging.getLogger(__name__)


@dataclass
class CallRecord:
    """Record of a single LLM call."""
    index: int
    messages: List[Dict[str, str]]
    kwargs: Dict[str, Any]
    timestamp: float
    response: str
    duration_ms: float


class MockProvider(BaseLLMProvider):
    """Mock LLM provider for testing.

    Parameters
    ----------
    response:
        Default canned response string.
    responses:
        Dict mapping message content patterns (regex) to responses.
        If a message matches, that response is returned instead of
        the default.
    delay:
        Artificial delay in seconds per call (simulates slow APIs).
    error_on_call:
        If set, raise LLMError on the Nth call (1-indexed).
    error_on_messages:
        If set, raise LLMError when any message content matches this regex.
    token_limit:
        Simulate token limit errors when the input exceeds this token count.
    model_name:
        Model name to report in model_info().
    """

    def __init__(
        self,
        response: str = "Mock response",
        responses: Optional[Dict[str, str]] = None,
        delay: float = 0.0,
        error_on_call: Optional[int] = None,
        error_on_messages: Optional[str] = None,
        token_limit: Optional[int] = None,
        model_name: str = "mock-model",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            model=model_name,
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 4096),
            **kwargs,
        )
        self._default_response = response
        self._pattern_responses = responses or {}
        self._delay = delay
        self._error_on_call = error_on_call
        self._error_on_messages = error_on_messages
        self._token_limit = token_limit

        # Call tracking
        self.call_count: int = 0
        self.call_log: List[CallRecord] = []
        self.last_messages: Optional[List[Dict[str, str]]] = None
        self.last_kwargs: Dict[str, Any] = {}

    # -- Model info ---------------------------------------------------------

    def _get_model_info(self) -> ModelInfo:
        return ModelInfo(
            name=self.model,
            provider="mock",
            context_window=4096,
            max_output_tokens=4096,
            supports_tools=False,
            supports_streaming=False,
            supports_vision=False,
            cost_per_1k_prompt_tokens=0.0,
            cost_per_1k_completion_tokens=0.0,
        )

    # -- Response selection -------------------------------------------------

    def _select_response(self, messages: List[Dict[str, str]]) -> str:
        """Select the response based on message patterns."""
        for pattern, response in self._pattern_responses.items():
            for m in messages:
                content = m.get("content", "")
                if re.search(pattern, content):
                    return response
        return self._default_response

    # -- Error simulation ---------------------------------------------------

    def _check_errors(self, messages: List[Dict[str, str]]) -> None:
        """Check if we should simulate an error."""
        self.call_count += 1

        # Error on specific call number
        if self._error_on_call and self.call_count >= self._error_on_call:
            raise LLMError(f"Mock error on call #{self.call_count}")

        # Error on matching message content
        if self._error_on_messages:
            for m in messages:
                content = m.get("content", "")
                if re.search(self._error_on_messages, content):
                    raise LLMError(f"Mock error: message matched {self._error_on_messages!r}")

    # -- Sync completion ----------------------------------------------------

    def _complete_sync(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> str:
        start = time.time()

        # Simulate delay
        if self._delay > 0:
            time.sleep(self._delay)

        # Check for simulated errors
        self._check_errors(messages)

        # Check token limit
        if self._token_limit is not None:
            token_count = self.count_tokens(messages)
            if token_count > self._token_limit:
                raise LLMError(f"Token limit exceeded: {token_count} > {self._token_limit}")

        # Select and record response
        response = self._select_response(messages)
        duration_ms = (time.time() - start) * 1000

        self.last_messages = messages
        self.last_kwargs = {"temperature": temperature, "max_tokens": max_tokens, **kwargs}

        record = CallRecord(
            index=self.call_count,
            messages=list(messages),
            kwargs=dict(self.last_kwargs),
            timestamp=time.time(),
            response=response,
            duration_ms=duration_ms,
        )
        self.call_log.append(record)

        return response

    # -- Async completion ---------------------------------------------------

    async def _complete_async(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> str:
        if self._delay > 0:
            await asyncio.sleep(self._delay)

        self._check_errors(messages)

        if self._token_limit is not None:
            token_count = self.count_tokens(messages)
            if token_count > self._token_limit:
                raise LLMError(f"Token limit exceeded: {token_count} > {self._token_limit}")

        response = self._select_response(messages)
        self.last_messages = messages
        self.last_kwargs = {"temperature": temperature, "max_tokens": max_tokens, **kwargs}

        record = CallRecord(
            index=self.call_count,
            messages=list(messages),
            kwargs=dict(self.last_kwargs),
            timestamp=time.time(),
            response=response,
            duration_ms=0.0,
        )
        self.call_log.append(record)

        return response

    # -- Testing helpers ----------------------------------------------------

    def assert_called(self, min_calls: int = 1) -> None:
        """Assert the provider was called at least N times."""
        assert self.call_count >= min_calls, (
            f"Expected at least {min_calls} calls, got {self.call_count}"
        )

    def assert_not_called(self) -> None:
        """Assert the provider was never called."""
        assert self.call_count == 0, f"Expected 0 calls, got {self.call_count}"

    def assert_last_messages_contain(self, text: str) -> None:
        """Assert the last call's messages contain the given text."""
        assert self.last_messages is not None, "No calls recorded"
        found = any(text in m.get("content", "") for m in self.last_messages)
        assert found, f"Text {text!r} not found in last messages"

    def reset(self) -> None:
        """Reset call tracking."""
        self.call_count = 0
        self.call_log.clear()
        self.last_messages = None
        self.last_kwargs = {}

    def __repr__(self) -> str:
        return (
            f"MockProvider(model={self.model!r}, calls={self.call_count}, "
            f"response={self._default_response!r})"
        )
