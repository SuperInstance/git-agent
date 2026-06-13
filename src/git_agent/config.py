"""
git_agent.config — Configuration management for the Git Agent engine.

Supports loading from YAML, JSON, TOML, or environment variables.
Validates required fields and provides sensible defaults for optional ones.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LLMProviderConfig:
    """Configuration for a single LLM provider."""

    name: str
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    model: Optional[str] = None
    proxy_url: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentConfig:
    """Top-level agent configuration."""

    github_token: str
    llm_provider: str
    llm_api_key: Optional[str] = None
    llm_proxy_url: Optional[str] = None
    llm_api_base: Optional[str] = None
    llm_model: Optional[str] = None
    llm_temperature: float = 0.7
    llm_max_tokens: int = 4096
    fleet_org: Optional[str] = None
    vessel_repo: Optional[str] = None
    max_parallel_agents: int = 4
    work_hours: Optional[str] = None  # e.g. "9-17" or "always"
    extra_llm_providers: Dict[str, LLMProviderConfig] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)

    # -- derived helpers --------------------------------------------------

    @property
    def primary_llm(self) -> LLMProviderConfig:
        return LLMProviderConfig(
            name=self.llm_provider,
            api_key=self.llm_api_key,
            api_base=self.llm_api_base,
            model=self.llm_model,
            proxy_url=self.llm_proxy_url,
            temperature=self.llm_temperature,
            max_tokens=self.llm_max_tokens,
        )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ConfigError(Exception):
    """Raised when configuration is invalid or cannot be loaded."""


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

# env-var patterns: GITHUB_TOKEN, LLM_PROVIDER, LLM_API_KEY, …
_ENV_PREFIX = "GIT_AGENT_"
_ENV_MAP = {
    "github_token": "GITHUB_TOKEN",
    "llm_provider": "LLM_PROVIDER",
    "llm_api_key": "LLM_API_KEY",
    "llm_proxy_url": "LLM_PROXY_URL",
    "llm_api_base": "LLM_API_BASE",
    "llm_model": "LLM_MODEL",
    "llm_temperature": "LLM_TEMPERATURE",
    "llm_max_tokens": "LLM_MAX_TOKENS",
    "fleet_org": "FLEET_ORG",
    "vessel_repo": "VESSEL_REPO",
    "max_parallel_agents": "MAX_PARALLEL_AGENTS",
    "work_hours": "WORK_HOURS",
}


def _env_lookup(key: str) -> Optional[str]:
    """Look up a config key in environment variables.

    Checks both ``GIT_AGENT_<KEY>`` and bare ``<KEY>`` forms.
    """
    names = (f"{_ENV_PREFIX}{key}", _ENV_MAP.get(key, key.upper()))
    for name in names:
        val = os.environ.get(name)
        if val is not None:
            return val
    return None


def _coerce(value: str, hint: type) -> Any:
    """Coerce a string from env to the target Python type."""
    if hint is float:
        return float(value)
    if hint is int:
        return int(value)
    return value


def _apply_env_overrides(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Layer environment-variable overrides on top of *raw* dict."""
    merged = dict(raw)
    for key, env_name in _ENV_MAP.items():
        env_val = os.environ.get(env_name) or os.environ.get(f"{_ENV_PREFIX}{key.upper()}")
        if env_val is not None:
            merged[key] = env_val
    return merged


# ---------------------------------------------------------------------------
# Parsers for different formats
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> Dict[str, Any]:
    if yaml is None:
        raise ConfigError("PyYAML is required to load YAML config files.  pip install pyyaml")
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_toml(path: Path) -> Dict[str, Any]:
    if tomllib is None:
        raise ConfigError("tomllib (Python >=3.11) or tomli is required for TOML config.  pip install tomli")
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    # TOML may nest under [tool.git_agent] or [git_agent]
    if "git_agent" in data and isinstance(data["git_agent"], dict):
        return data["git_agent"]
    if "tool" in data and isinstance(data["tool"], dict) and "git_agent" in data["tool"]:
        return data["tool"]["git_agent"]
    return data


_LOADERS = {
    ".yaml": _load_yaml,
    ".yml": _load_yaml,
    ".json": _load_json,
    ".toml": _load_toml,
}


def load_config_file(path: Union[str, Path]) -> Dict[str, Any]:
    """Load configuration from a file (YAML / JSON / TOML).

    The format is detected by file extension.
    """
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"Configuration file not found: {p}")
    if not p.is_file():
        raise ConfigError(f"Configuration path is not a file: {p}")

    ext = p.suffix.lower()
    loader = _LOADERS.get(ext)
    if loader is None:
        raise ConfigError(f"Unsupported configuration file format: {ext}")

    return loader(p)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = ("github_token", "llm_provider")

# Either llm_api_key or llm_proxy_url must be present (or passed via env).
_AT_LEAST_ONE = [("llm_api_key", "llm_proxy_url")]


def _validate(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Validate required config fields and return cleaned dict.

    Raises ``ConfigError`` on problems.
    """
    missing: List[str] = []
    for key in _REQUIRED_FIELDS:
        if not raw.get(key):
            missing.append(key)

    for group in _AT_LEAST_ONE:
        if not any(raw.get(k) for k in group):
            missing.append(f"one of ({', '.join(group)})")

    if missing:
        raise ConfigError(
            f"Missing required configuration: {', '.join(missing)}.  "
            f"Set them in your config file or via environment variables."
        )

    # Type-coerce numeric fields
    for int_key in ("max_parallel_agents", "llm_max_tokens"):
        if int_key in raw and not isinstance(raw[int_key], int):
            try:
                raw[int_key] = int(raw[int_key])
            except (ValueError, TypeError):
                raise ConfigError(f"Config key '{int_key}' must be an integer, got {raw[int_key]!r}")

    for float_key in ("llm_temperature",):
        if float_key in raw and not isinstance(raw[float_key], float):
            try:
                raw[float_key] = float(raw[float_key])
            except (ValueError, TypeError):
                raise ConfigError(f"Config key '{float_key}' must be a float, got {raw[float_key]!r}")

    return raw


# ---------------------------------------------------------------------------
# Extra LLM providers
# ---------------------------------------------------------------------------

def _parse_extra_providers(raw: Dict[str, Any]) -> Dict[str, LLMProviderConfig]:
    providers: Dict[str, LLMProviderConfig] = {}
    section = raw.get("llm_providers") or raw.get("extra_llm_providers") or {}
    if not isinstance(section, dict):
        return providers
    for name, cfg in section.items():
        if not isinstance(cfg, dict):
            continue
        providers[name] = LLMProviderConfig(
            name=name,
            api_key=cfg.get("api_key"),
            api_base=cfg.get("api_base"),
            model=cfg.get("model"),
            proxy_url=cfg.get("proxy_url"),
            temperature=float(cfg.get("temperature", 0.7)),
            max_tokens=int(cfg.get("max_tokens", 4096)),
            extra={k: v for k, v in cfg.items() if k not in (
                "api_key", "api_base", "model", "proxy_url",
                "temperature", "max_tokens",
            )},
        )
    return providers


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def from_dict(raw: Dict[str, Any]) -> AgentConfig:
    """Build an :class:`AgentConfig` from a plain dict (already validated)."""
    raw = _apply_env_overrides(raw)
    raw = _validate(raw)
    return AgentConfig(
        github_token=raw["github_token"],
        llm_provider=raw["llm_provider"],
        llm_api_key=raw.get("llm_api_key"),
        llm_proxy_url=raw.get("llm_proxy_url"),
        llm_api_base=raw.get("llm_api_base"),
        llm_model=raw.get("llm_model"),
        llm_temperature=float(raw.get("llm_temperature", 0.7)),
        llm_max_tokens=int(raw.get("llm_max_tokens", 4096)),
        fleet_org=raw.get("fleet_org"),
        vessel_repo=raw.get("vessel_repo"),
        max_parallel_agents=int(raw.get("max_parallel_agents", 4)),
        work_hours=raw.get("work_hours"),
        extra_llm_providers=_parse_extra_providers(raw),
        extra={k: v for k, v in raw.items() if k not in (
            "github_token", "llm_provider", "llm_api_key", "llm_proxy_url",
            "llm_api_base", "llm_model", "llm_temperature", "llm_max_tokens",
            "fleet_org", "vessel_repo", "max_parallel_agents", "work_hours",
            "llm_providers", "extra_llm_providers",
        )},
    )


def load_config(path: Optional[Union[str, Path]] = None) -> AgentConfig:
    """Load configuration from file, env vars, or both.

    * If *path* is given, load from that file first, then layer env overrides.
    * If *path* is ``None``, look for common locations:
      ``./config.yaml``, ``./config.yml``, ``./config.json``, ``./config.toml``.
    * Finally, validate and return :class:`AgentConfig`.

    Raises :class:`ConfigError` on any problem.
    """
    raw: Dict[str, Any] = {}

    if path is not None:
        raw = load_config_file(path)
    else:
        for candidate in ("config.yaml", "config.yml", "config.json", "config.toml"):
            p = Path(candidate)
            if p.exists():
                raw = load_config_file(p)
                break

    return from_dict(raw)
