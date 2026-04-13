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

__version__ = "0.1.0"
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
    "__version__",
]
