"""
git_agent.llm.base — Abstract LLM Provider Protocol and base classes.

This module defines the canonical interface that ALL LLM providers must
implement. The ``LLMProvider`` Protocol matches the interface in
``agent.py`` (``complete``, ``acomplete``) and extends it with
``complete_with_tools`` and ``model_info`` for richer functionality.

Design principles:
- **Synchronous + Async**: Every provider implements both sync ``complete``
  and async ``acomplete``.
- **Tool Use**: Optional ``complete_with_tools`` for function-calling models.
- **Model Info**: Every provider reports its model name, context window, and
  cost metadata via ``model_info``.
- **Streaming**: Providers may optionally support ``stream`` for token-by-token
  output via an async generator.
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    runtime_checkable,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TokenUsage:
    """Token usage statistics from an API call."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @property
    def cost_usd(self) -> float:
        """Cost in USD (requires model info for per-token pricing)."""
        return 0.0


@dataclass
class ToolCall:
    """A tool/function call from the model."""
    id: str
    name: str
    arguments: str  # JSON string

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.arguments,
            },
        }


@dataclass
class ChatMessage:
    """A structured chat message."""
    role: str
    content: str
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_openai_dict(self) -> Dict[str, Any]:
        """Convert to OpenAI-compatible message dict."""
        d: Dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d

    @classmethod
    def from_openai_dict(cls, d: Dict[str, Any]) -> ChatMessage:
        """Create from OpenAI-compatible message dict."""
        tool_calls = None
        if d.get("tool_calls"):
            tool_calls = [
                ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=tc["function"]["arguments"],
                )
                for tc in d["tool_calls"]
            ]
        return cls(
            role=d["role"],
            content=d.get("content", ""),
            tool_calls=tool_calls,
            tool_call_id=d.get("tool_call_id"),
            name=d.get("name"),
        )


@dataclass(frozen=True)
class ModelInfo:
    """Information about a model's capabilities."""
    name: str
    provider: str
    context_window: int = 4096
    max_output_tokens: int = 4096
    supports_tools: bool = False
    supports_streaming: bool = True
    supports_vision: bool = False
    cost_per_1k_prompt_tokens: float = 0.0
    cost_per_1k_completion_tokens: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "provider": self.provider,
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "supports_tools": self.supports_tools,
            "supports_streaming": self.supports_streaming,
            "supports_vision": self.supports_vision,
            "cost_per_1k_prompt_tokens": self.cost_per_1k_prompt_tokens,
            "cost_per_1k_completion_tokens": self.cost_per_1k_completion_tokens,
        }


class ProviderCapability(str, Enum):
    """Capabilities a provider/model might have."""
    CHAT = "chat"
    CODE_GENERATION = "code_generation"
    REASONING = "reasoning"
    VISION = "vision"
    TOOLS = "tools"
    STREAMING = "streaming"
    JSON_MODE = "json_mode"
    SYSTEM_PROMPT = "system_prompt"


# ---------------------------------------------------------------------------
# LLMProvider Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers — any API can implement this.

    This matches the ``LLMProvider`` Protocol in ``agent.py`` and extends it
    with tool-calling, model info, and streaming support.

    Required methods:
        complete(messages, **kwargs) -> str
        acomplete(messages, **kwargs) -> Awaitable[str]
        model_info() -> dict

    Optional methods:
        complete_with_tools(messages, tools, **kwargs) -> tuple[str, list[dict]]
        stream(messages, **kwargs) -> AsyncIterator[str]
    """

    def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        """Generate a completion from a message list.

        Parameters
        ----------
        messages:
            List of ``{"role": ..., "content": ...}`` dicts.
        temperature:
            Override sampling temperature.
        max_tokens:
            Override max response tokens.

        Returns
        -------
        str
            The generated text.
        """
        ...

    async def acomplete(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> str:
        """Async version of :meth:`complete`."""
        ...

    def model_info(self) -> Dict[str, Any]:
        """Return model metadata.

        Must include at minimum:
            - ``name`` (str): Model identifier
            - ``provider`` (str): Provider name
            - ``context_window`` (int): Maximum context tokens
        """
        ...


@runtime_checkable
class ToolCapableProvider(LLMProvider, Protocol):
    """Extended protocol for providers that support tool/function calling."""

    def complete_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> tuple[str, List[Dict[str, Any]]]:
        """Generate a completion that may invoke tools.

        Returns
        -------
        tuple[str, list[dict]]
            (text_response, list_of_tool_call_dicts)
        """
        ...

    async def acomplete_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> tuple[str, List[Dict[str, Any]]]:
        """Async version of :meth:`complete_with_tools`."""
        ...


@runtime_checkable
class StreamingProvider(LLMProvider, Protocol):
    """Extended protocol for providers that support streaming."""

    async def stream(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream tokens from the model.

        Yields
        ------
        str
            Token chunks as they arrive.
        """
        ...  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Abstract base class (optional convenience)
# ---------------------------------------------------------------------------

class BaseLLMProvider(abc.ABC):
    """Abstract base class providing common LLM provider infrastructure.

    Implementations should subclass this and implement:
        - ``_complete_sync``
        - ``_complete_async``
        - ``_get_model_info``
    """

    def __init__(
        self,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._extra = kwargs

    # -- Public API (matches Protocol) --------------------------------------

    def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        """Synchronous completion."""
        return self._complete_sync(
            messages,
            temperature=temperature if temperature is not None else self.temperature,
            max_tokens=max_tokens if max_tokens is not None else self.max_tokens,
            **{**self._extra, **kwargs},
        )

    async def acomplete(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> str:
        """Async completion."""
        temperature = kwargs.pop("temperature", self.temperature)
        max_tokens = kwargs.pop("max_tokens", self.max_tokens)
        return await self._complete_async(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **{**self._extra, **kwargs},
        )

    def model_info(self) -> Dict[str, Any]:
        """Return model metadata dict."""
        return self._get_model_info().to_dict()

    # -- Hooks for subclasses -----------------------------------------------

    @abc.abstractmethod
    def _complete_sync(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> str:
        """Implement synchronous completion."""
        ...

    @abc.abstractmethod
    async def _complete_async(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> str:
        """Implement async completion."""
        ...

    @abc.abstractmethod
    def _get_model_info(self) -> ModelInfo:
        """Return ModelInfo for this provider."""
        ...

    # -- Optional overrides -------------------------------------------------

    def count_tokens(self, messages: List[Dict[str, str]]) -> int:
        """Rough token count estimation (4 chars ≈ 1 token)."""
        total_chars = sum(len(m.get("content", "")) for m in messages)
        return total_chars // 4

    def validate_messages(self, messages: List[Dict[str, str]]) -> None:
        """Validate message format. Raises ValueError on bad input."""
        if not messages:
            raise ValueError("messages must be a non-empty list")
        for i, m in enumerate(messages):
            if not isinstance(m, dict):
                raise ValueError(f"messages[{i}] must be a dict")
            if "role" not in m:
                raise ValueError(f"messages[{i}] missing 'role' key")
            if "content" not in m:
                raise ValueError(f"messages[{i}] missing 'content' key")
            if m["role"] not in ("system", "user", "assistant", "tool"):
                raise ValueError(
                    f"messages[{i}] has invalid role: {m['role']!r}"
                )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LLMError(Exception):
    """Base exception for LLM provider errors."""
    pass


class LLMRateLimitError(LLMError):
    """Raised when the provider returns a rate-limit error (HTTP 429)."""
    pass


class LLMAuthError(LLMError):
    """Raised when authentication fails (HTTP 401/403)."""
    pass


class LLMContextError(LLMError):
    """Raised when the input exceeds the model's context window."""
    pass


class LLMTimeoutError(LLMError):
    """Raised when a request times out."""
    pass


class LLMUnavailableError(LLMError):
    """Raised when the provider is unavailable."""
    pass
