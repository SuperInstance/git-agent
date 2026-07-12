"""
git_agent — API-agnostic autonomous Git-Native Agent.

This package provides the core engine for building autonomous agents
that operate natively on GitHub through Git workflows.

Quick start::

    from git_agent import Agent, load_config

    config = load_config("config.yaml")
    agent = Agent(config, llm=my_llm, github=my_github_client)
    agent.run()
"""

from .agent import (
    Agent,
    GitHubClient,
    LLMProvider,
    Observation,
    Plan,
    Task,
    TaskPriority,
)
from .config import (
    AgentConfig,
    ConfigError,
    LLMProviderConfig,
    from_dict,
    load_config,
    load_config_file,
)
from .vessel import (
    Domain,
    GrowthStage,
    Identity,
    VesselManager,
    VesselState,
    WorklogEntry,
    check_promotion,
    next_stage,
)

__version__ = "0.1.2"


def create_provider(config) -> "LLMProvider":
    """Factory: create an LLM provider from config.

    Supports: openai, anthropic, ollama, proxy, mock.
    Also supports multi-provider routing via config.
    """
    from .llm.base import ProviderNotFoundError

    provider_name = getattr(config, "llm_provider", "openai")

    try:
        if provider_name == "openai":
            from .llm.openai_compat import OpenAICompatibleProvider
            return OpenAICompatibleProvider(
                api_key=config.llm_api_key or "",
                model=getattr(config, "llm_model", "gpt-4"),
                base_url=getattr(config, "llm_api_base", None),
            )
        elif provider_name == "anthropic":
            from .llm.anthropic import AnthropicProvider
            return AnthropicProvider(
                api_key=config.llm_api_key or "",
                model=getattr(config, "llm_model", "claude-3-sonnet-20240229"),
            )
        elif provider_name == "ollama":
            from .llm.ollama import OllamaProvider
            return OllamaProvider(
                base_url=getattr(config, "llm_proxy_url", "http://localhost:11434"),
                model=getattr(config, "llm_model", "llama3"),
            )
        elif provider_name == "proxy":
            from .llm.proxy import ProxyProvider
            return ProxyProvider(
                proxy_url=config.llm_proxy_url or "",
                api_key=config.llm_api_key or "",
                model=getattr(config, "llm_model", "default"),
            )
        elif provider_name == "mock":
            from .llm.mock import MockProvider
            return MockProvider()
        elif provider_name == "router":
            from .llm.router import LLMRouter
            providers_config = getattr(config, "llm_providers", {})
            return LLMRouter.from_config(providers_config)
        else:
            raise ProviderNotFoundError(f"Unknown provider: {provider_name}")
    except ImportError as e:
        raise ProviderNotFoundError(
            f"Provider '{provider_name}' requires extra dependencies. "
            f"Install with: pip install git-agent[{provider_name}]. Error: {e}"
        )
__all__ = [
    # Agent
    "Agent",
    "GitHubClient",
    "LLMProvider",
    "Observation",
    "Plan",
    "Task",
    "TaskPriority",
    # Config
    "AgentConfig",
    "ConfigError",
    "LLMProviderConfig",
    "from_dict",
    "load_config",
    "load_config_file",
    # Vessel
    "Domain",
    "GrowthStage",
    "Identity",
    "VesselManager",
    "VesselState",
    "WorklogEntry",
    "check_promotion",
    "next_stage",
    "create_provider",
    "__version__",
]
