"""
git_agent.llm.router — Multi-provider routing with failover and optimization.

The router manages multiple LLM providers and routes requests based on:
    - **Capability matching**: Route to the best provider for the task
      (code generation, reasoning, vision, etc.)
    - **Cost optimization**: Use the cheapest provider that can handle the task
    - **Availability/failover**: Automatically fail over to backup providers
    - **Token budget tracking**: Monitor and enforce token spending limits
    - **Provider health monitoring**: Track provider uptime and error rates

Usage::

    router = LLMRouter()
    router.add_provider("openai", openai_provider, capabilities=["code", "chat"])
    router.add_provider("anthropic", anthropic_provider, capabilities=["reasoning", "chat"])
    router.add_provider("ollama", ollama_provider, capabilities=["code"], cost_tier="free")

    # Route by capability
    result = await router.acomplete(messages, capability="reasoning")

    # Route by name
    result = await router.acomplete(messages, provider="ollama")

    # Failover automatically
    result = await router.acomplete(messages, failover=True)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from .base import (
    LLMError,
    LLMProvider,
    ModelInfo,
    ProviderCapability,
    TokenUsage,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Routing config
# ---------------------------------------------------------------------------

class CostTier(str, Enum):
    """Cost tiers for provider selection."""
    FREE = "free"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    PREMIUM = "premium"

    def __lt__(self, other: object) -> bool:
        if isinstance(other, CostTier):
            order = list(CostTier)
            return order.index(self) < order.index(other)
        return NotImplemented


class RoutingStrategy(str, Enum):
    """How to select a provider."""
    CAPABILITY = "capability"     # Best provider for the task
    CHEAPEST = "cheapest"         # Lowest cost provider
    ROUND_ROBIN = "round_robin"   # Balance across providers
    PRIORITY = "priority"         # Use providers in priority order


@dataclass
class ProviderEntry:
    """A registered provider with metadata."""
    name: str
    provider: LLMProvider
    capabilities: List[str] = field(default_factory=lambda: ["chat"])
    cost_tier: CostTier = CostTier.MEDIUM
    priority: int = 0  # Higher = preferred
    max_retries: int = 2
    enabled: bool = True

    # -- Health tracking --
    total_requests: int = 0
    total_errors: int = 0
    total_tokens_used: int = 0
    last_success_time: Optional[float] = None
    last_error_time: Optional[float] = None
    consecutive_failures: int = 0

    @property
    def error_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_errors / self.total_requests

    @property
    def is_healthy(self) -> bool:
        """Consider unhealthy after 5 consecutive failures."""
        return self.consecutive_failures < 5

    @property
    def model_info_dict(self) -> Dict[str, Any]:
        try:
            return self.provider.model_info()
        except Exception:
            return {"name": self.name, "provider": "unknown", "context_window": 0}


@dataclass
class TokenBudget:
    """Token budget tracker for cost control."""
    max_tokens: int = 1_000_000  # 1M tokens default
    used_tokens: int = 0
    max_cost_usd: float = 100.0
    used_cost_usd: float = 0.0

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.max_tokens - self.used_tokens)

    @property
    def remaining_cost_usd(self) -> float:
        return max(0.0, self.max_cost_usd - self.used_cost_usd)

    @property
    def is_exhausted(self) -> bool:
        return self.remaining_tokens <= 0 or self.remaining_cost_usd <= 0.0

    def record_usage(self, tokens: int, cost_usd: float = 0.0) -> None:
        self.used_tokens += tokens
        self.used_cost_usd += cost_usd


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class LLMRouter:
    """Multi-provider LLM router with failover and optimization.

    Parameters
    ----------
    default_provider:
        Name of the default provider to use when no routing hint is given.
    strategy:
        Default routing strategy.
    budget:
        Optional token budget for cost control.
    """

    def __init__(
        self,
        default_provider: Optional[str] = None,
        strategy: RoutingStrategy = RoutingStrategy.CAPABILITY,
        budget: Optional[TokenBudget] = None,
    ) -> None:
        self._providers: Dict[str, ProviderEntry] = {}
        self.default_provider = default_provider
        self.strategy = strategy
        self.budget = budget or TokenBudget()
        self._round_robin_counter: Dict[str, int] = {}

    # -- Provider registration ----------------------------------------------

    def add_provider(
        self,
        name: str,
        provider: LLMProvider,
        capabilities: Optional[List[str]] = None,
        cost_tier: CostTier = CostTier.MEDIUM,
        priority: int = 0,
        **kwargs: Any,
    ) -> None:
        """Register a provider with the router."""
        self._providers[name] = ProviderEntry(
            name=name,
            provider=provider,
            capabilities=capabilities or ["chat"],
            cost_tier=cost_tier,
            priority=priority,
            **kwargs,
        )
        logger.info("Registered provider %s (capabilities: %s, cost_tier: %s)",
                     name, capabilities or ["chat"], cost_tier.value)

    def remove_provider(self, name: str) -> None:
        """Remove a provider from the router."""
        if name in self._providers:
            del self._providers[name]

    def get_provider(self, name: str) -> Optional[ProviderEntry]:
        """Get a registered provider by name."""
        return self._providers.get(name)

    def list_providers(self) -> List[str]:
        """List all registered provider names."""
        return list(self._providers.keys())

    def list_healthy_providers(self) -> List[str]:
        """List providers that are currently healthy."""
        return [
            name for name, entry in self._providers.items()
            if entry.enabled and entry.is_healthy
        ]

    # -- Provider selection -------------------------------------------------

    def _select_provider(
        self,
        capability: Optional[str] = None,
        provider: Optional[str] = None,
        strategy: Optional[RoutingStrategy] = None,
    ) -> ProviderEntry:
        """Select the best provider for a request."""
        strat = strategy or self.strategy

        # Direct name selection
        if provider:
            entry = self._providers.get(provider)
            if entry is None:
                raise LLMError(f"Unknown provider: {provider!r}")
            if not entry.enabled:
                raise LLMError(f"Provider {provider!r} is disabled")
            if not entry.is_healthy:
                logger.warning("Provider %s has %d consecutive failures", provider, entry.consecutive_failures)
            return entry

        # Default provider
        if self.default_provider and self.default_provider in self._providers:
            entry = self._providers[self.default_provider]
            if entry.enabled and entry.is_healthy:
                return entry

        # Strategy-based selection
        candidates = [
            e for e in self._providers.values()
            if e.enabled and e.is_healthy
        ]

        if not candidates:
            raise LLMError("No healthy providers available")

        if strat == RoutingStrategy.CHEAPEST:
            candidates.sort(key=lambda e: e.cost_tier)
            return candidates[0]

        if strat == RoutingStrategy.PRIORITY:
            candidates.sort(key=lambda e: e.priority, reverse=True)
            return candidates[0]

        if strat == RoutingStrategy.ROUND_ROBIN:
            cap = capability or "chat"
            if cap not in self._round_robin_counter:
                self._round_robin_counter[cap] = 0
            matching = [e for e in candidates if cap in e.capabilities] or candidates
            idx = self._round_robin_counter[cap] % len(matching)
            self._round_robin_counter[cap] += 1
            return matching[idx]

        if strat == RoutingStrategy.CAPABILITY:
            cap = capability or "chat"
            matching = [e for e in candidates if cap in e.capabilities]
            if matching:
                # Prefer higher priority, then lower cost
                matching.sort(key=lambda e: (-e.priority, e.cost_tier))
                return matching[0]
            # Fallback to any healthy provider
            candidates.sort(key=lambda e: (-e.priority, e.cost_tier))
            return candidates[0]

        # Fallback
        return candidates[0]

    def _get_failover_order(
        self,
        provider_name: Optional[str] = None,
        capability: Optional[str] = None,
    ) -> List[ProviderEntry]:
        """Get ordered list of providers to try for failover."""
        if provider_name:
            primary = self._providers.get(provider_name)
            if primary:
                # Get other healthy providers as fallbacks
                others = [
                    e for e in self._providers.values()
                    if e.name != provider_name and e.enabled and e.is_healthy
                ]
                others.sort(key=lambda e: (-e.priority, e.cost_tier))
                return [primary] + others

        candidates = [
            e for e in self._providers.values()
            if e.enabled and e.is_healthy
        ]
        candidates.sort(key=lambda e: (-e.priority, e.cost_tier))
        return candidates

    # -- Synchronous completion ---------------------------------------------

    def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        provider: Optional[str] = None,
        capability: Optional[str] = None,
        failover: bool = True,
        strategy: Optional[RoutingStrategy] = None,
        **kwargs: Any,
    ) -> str:
        """Route a completion request to the best provider.

        Parameters
        ----------
        messages:
            Chat messages.
        temperature:
            Override temperature.
        max_tokens:
            Override max tokens.
        provider:
            Force a specific provider.
        capability:
            Route to a provider with this capability.
        failover:
            Try other providers if the primary fails.
        strategy:
            Override routing strategy for this request.

        Returns
        -------
        str
            The generated text.
        """
        if failover:
            entries = self._get_failover_order(provider, capability)
        else:
            entry = self._select_provider(capability, provider, strategy)
            entries = [entry]

        last_error: Optional[Exception] = None
        for entry in entries:
            try:
                result = entry.provider.complete(
                    messages, temperature=temperature, max_tokens=max_tokens, **kwargs,
                )
                self._record_success(entry, messages, result)
                return result
            except Exception as exc:
                self._record_error(entry, exc)
                last_error = exc
                logger.warning(
                    "Provider %s failed: %s%s",
                    entry.name, exc,
                    " (trying next)" if failover and entry != entries[-1] else "",
                )

        raise LLMError(
            f"All providers failed. Last error: {last_error}"
        ) from last_error

    # -- Async completion ---------------------------------------------------

    async def acomplete(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> str:
        """Async version of :meth:`complete`."""
        failover = kwargs.pop("failover", True)
        provider = kwargs.pop("provider", None)
        capability = kwargs.pop("capability", None)
        strategy = kwargs.pop("strategy", None)

        if failover:
            entries = self._get_failover_order(provider, capability)
        else:
            entry = self._select_provider(capability, provider, strategy)
            entries = [entry]

        last_error: Optional[Exception] = None
        for entry in entries:
            try:
                result = await entry.provider.acomplete(messages, **kwargs)
                self._record_success(entry, messages, result)
                return result
            except Exception as exc:
                self._record_error(entry, exc)
                last_error = exc
                logger.warning(
                    "Provider %s failed: %s%s",
                    entry.name, exc,
                    " (trying next)" if failover and entry != entries[-1] else "",
                )

        raise LLMError(
            f"All providers failed. Last error: {last_error}"
        ) from last_error

    # -- Model info ---------------------------------------------------------

    def model_info(self, provider_name: Optional[str] = None) -> Dict[str, Any]:
        """Get model info for a specific provider or the default."""
        if provider_name:
            entry = self._providers.get(provider_name)
            if entry:
                return entry.model_info_dict
            raise LLMError(f"Unknown provider: {provider_name!r}")

        entry = self._select_provider()
        return entry.model_info_dict

    # -- Health monitoring --------------------------------------------------

    def get_health_report(self) -> Dict[str, Any]:
        """Get health status for all registered providers."""
        report: Dict[str, Any] = {
            "total_providers": len(self._providers),
            "healthy_providers": 0,
            "providers": {},
            "budget": {
                "used_tokens": self.budget.used_tokens,
                "remaining_tokens": self.budget.remaining_tokens,
                "used_cost_usd": self.budget.used_cost_usd,
                "remaining_cost_usd": self.budget.remaining_cost_usd,
                "is_exhausted": self.budget.is_exhausted,
            },
        }

        for name, entry in self._providers.items():
            if entry.is_healthy:
                report["healthy_providers"] += 1
            report["providers"][name] = {
                "enabled": entry.enabled,
                "healthy": entry.is_healthy,
                "error_rate": round(entry.error_rate, 4),
                "total_requests": entry.total_requests,
                "total_errors": entry.total_errors,
                "consecutive_failures": entry.consecutive_failures,
                "capabilities": entry.capabilities,
                "cost_tier": entry.cost_tier.value,
                "priority": entry.priority,
            }

        return report

    def reset_health(self, name: Optional[str] = None) -> None:
        """Reset health stats for a provider or all providers."""
        if name:
            entry = self._providers.get(name)
            if entry:
                entry.consecutive_failures = 0
        else:
            for entry in self._providers.values():
                entry.consecutive_failures = 0

    # -- Tracking helpers ---------------------------------------------------

    def _record_success(self, entry: ProviderEntry, messages: List[Dict[str, str]], result: str) -> None:
        """Record a successful request."""
        entry.total_requests += 1
        entry.last_success_time = time.time()
        entry.consecutive_failures = 0

        # Estimate tokens
        prompt_tokens = sum(len(m.get("content", "")) // 4 for m in messages)
        completion_tokens = len(result) // 4
        total_tokens = prompt_tokens + completion_tokens
        entry.total_tokens_used += total_tokens
        self.budget.record_usage(total_tokens)

    def _record_error(self, entry: ProviderEntry, exc: Exception) -> None:
        """Record a failed request."""
        entry.total_requests += 1
        entry.total_errors += 1
        entry.last_error_time = time.time()
        entry.consecutive_failures += 1

    def __repr__(self) -> str:
        return (
            f"LLMRouter(providers={list(self._providers.keys())}, "
            f"default={self.default_provider!r}, "
            f"strategy={self.strategy.value})"
        )
