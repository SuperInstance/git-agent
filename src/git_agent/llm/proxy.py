"""
git_agent.llm.proxy — Generic proxy passthrough provider.

This provider sends requests through a proxy that exposes an
OpenAI-compatible API. This is how ZeroClaw, Pi agent backends,
LiteLLM, or any custom gateway works.

The proxy provider:
    - Takes a base URL and optional API key
    - Sends requests in OpenAI-compatible format through the proxy
    - Inherits all capabilities from OpenAICompatibleProvider
    - Adds proxy-specific metadata (proxy name, health checks)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .openai_compat import OpenAICompatibleProvider
from .base import ModelInfo

logger = logging.getLogger(__name__)


class ProxyProvider(OpenAICompatibleProvider):
    """Generic proxy passthrough LLM provider.

    Wraps an OpenAI-compatible provider but routes all requests
    through a proxy endpoint. Useful for:
        - ZeroClaw proxy
        - Pi agent backends
        - LiteLLM gateway
        - Custom corporate proxies
        - Local model servers with OpenAI-compatible APIs

    Parameters
    ----------
    proxy_url:
        The proxy's base URL (e.g. "https://zeroclaw.example.com/v1").
    api_key:
        API key for the proxy (if required).
    model:
        Model name to request from the proxy.
    proxy_name:
        Human-readable name for this proxy (for logging/metrics).
    temperature:
        Default sampling temperature.
    max_tokens:
        Default max response tokens.
    **kwargs:
        Additional parameters forwarded to OpenAICompatibleProvider.
    """

    def __init__(
        self,
        proxy_url: str,
        api_key: Optional[str] = None,
        model: str = "default",
        proxy_name: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            model=model,
            api_key=api_key,
            api_base=proxy_url,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        self.proxy_url = proxy_url.rstrip("/")
        self.proxy_name = proxy_name or proxy_url

    def _get_model_info(self) -> ModelInfo:
        """Return model info with proxy metadata."""
        info = super()._get_model_info()
        # Override provider to indicate proxy
        return ModelInfo(
            name=self.model,
            provider=f"proxy({self.proxy_name})",
            context_window=info.context_window,
            max_output_tokens=info.max_output_tokens,
            supports_tools=info.supports_tools,
            supports_streaming=info.supports_streaming,
            supports_vision=info.supports_vision,
            cost_per_1k_prompt_tokens=info.cost_per_1k_prompt_tokens,
            cost_per_1k_completion_tokens=info.cost_per_1k_completion_tokens,
        )

    def __repr__(self) -> str:
        return (
            f"ProxyProvider(proxy_url={self.proxy_url!r}, "
            f"model={self.model!r}, proxy_name={self.proxy_name!r})"
        )
