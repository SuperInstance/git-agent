"""
git_agent.llm — Pluggable LLM provider layer.

This package provides an API-agnostic LLM abstraction that works with
ANY backend. Providers implement a common Protocol and can be routed,
failed-over, and cost-optimized through the LLMRouter.

Supported providers:
    - **OpenAICompatibleProvider**: OpenAI, Azure, Together AI, Groq, DeepSeek, local models
    - **AnthropicProvider**: Claude (claude-sonnet-4, claude-3-opus, claude-3-haiku, etc.)
    - **OllamaProvider**: Local Ollama server
    - **ProxyProvider**: Generic proxy passthrough (ZeroClaw, LiteLLM, Pi agent backends)
    - **MockProvider**: Canned responses for testing
    - **LLMRouter**: Multi-provider routing with failover, cost optimization, and capability matching

Quick start::

    from git_agent.llm import OpenAICompatibleProvider, LLMRouter, MockProvider

    # Direct provider usage
    provider = OpenAICompatibleProvider(model="gpt-4o", api_key="sk-...")
    result = provider.complete([{"role": "user", "content": "Hello!"}])

    # Multi-provider routing
    router = LLMRouter(default_provider="openai")
    router.add_provider("openai", openai_provider, capabilities=["code", "chat"])
    router.add_provider("ollama", ollama_provider, capabilities=["code"], cost_tier="free")
    result = router.complete(messages, capability="code")
"""

from .base import (
    BaseLLMProvider,
    ChatMessage,
    LLMAuthError,
    LLMContextError,
    LLMError,
    LLMProvider,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    ModelInfo,
    ProviderCapability,
    StreamingProvider,
    TokenUsage,
    ToolCall,
    ToolCapableProvider,
)
from .openai_compat import OpenAICompatibleProvider
from .anthropic import AnthropicProvider
from .ollama import OllamaProvider
from .proxy import ProxyProvider
from .router import (
    CostTier,
    LLMRouter,
    ProviderEntry,
    RoutingStrategy,
    TokenBudget,
)
from .mock import CallRecord, MockProvider

__all__ = [
    # Base / Protocol
    "BaseLLMProvider",
    "ChatMessage",
    "LLMAuthError",
    "LLMContextError",
    "LLMError",
    "LLMProvider",
    "LLMRateLimitError",
    "LLMTimeoutError",
    "LLMUnavailableError",
    "ModelInfo",
    "ProviderCapability",
    "StreamingProvider",
    "TokenUsage",
    "ToolCall",
    "ToolCapableProvider",
    # Providers
    "OpenAICompatibleProvider",
    "AnthropicProvider",
    "OllamaProvider",
    "ProxyProvider",
    "MockProvider",
    "CallRecord",
    # Router
    "CostTier",
    "LLMRouter",
    "ProviderEntry",
    "RoutingStrategy",
    "TokenBudget",
]
