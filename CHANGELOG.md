# Changelog

All notable changes to this project will be documented in this file.

## [0.1.2] - 2025-01-01

### Added
- Full package structure under `src/git_agent/`
- Multi-provider LLM support: OpenAI, Anthropic, Ollama, proxy, mock
- LLM router with failover and cost optimization
- GitHub API client with rate limiting and caching
- Fleet modules: reader, planner, executor, communicator, researcher
- Vessel manager with growth stages and promotion logic
- Config wizard for onboarding
- PLATO modules: scout, scholar, librarian, quality
- Standalone CLI with chat, onboard, and start commands

### Fixed
- Version sync: `__init__.py` now matches `pyproject.toml` (0.1.2)
- Root-level `__init__.py` annotated as legacy backwards-compat shim
