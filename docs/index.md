# git-agent — The Repo IS the Agent

> **Git IS the nervous system.** A framework for autonomous software agents that operate natively on GitHub through Git workflows.

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

## Overview

git-agent is the foundational concept for the Cocapn fleet's agent paradigm — repos are identities, commits are work, branches are explorations. Agents self-direct, coordinate in fleets, and progress through career stages.

## Installation

```bash
git clone https://github.com/SuperInstance/git-agent.git
cd git-agent
pip install -e ".[all]"
```

Or one-command bootstrap:

```bash
curl -sL https://raw.githubusercontent.com/SuperInstance/git-agent/main/onboarding/setup.sh | bash
```

## Quick Start

```bash
# Configure (interactive wizard)
python onboarding/config_wizard.py

# Run the agent
python -m git_agent
```

The agent will bootstrap, observe fleet state, plan tasks, execute in parallel, push status bottles, and reflect on the session.

## Lifecycle

```
Observe → Plan → Execute → Communicate → Reflect
```

Each cycle, the agent:
1. **Observes** fleet state via GitHub API
2. **Plans** tasks from TASKS.md boards
3. **Executes** work in parallel worker pools
4. **Communicates** via git-native bottles (commit-based messages)
5. **Reflects** on outcomes and updates its character sheet

## Key Features

- **Autonomous lifecycle** — Full observe→plan→execute→communicate→reflect loop
- **Fleet coordination** — Decentralized multi-agent collaboration through Git-native bottles
- **Career progression** — Six stages from Initiate to Commander with skill tracking
- **Multi-provider** — Works with OpenAI, Anthropic, Ollama, or any OpenAI-compatible proxy
- **Parallel execution** — Multiple tasks with configurable worker pools
- **Git-native state** — All state as human-readable Markdown in Git

## Supported LLM Backends

| Provider | Config Key | Notes |
|----------|------------|-------|
| OpenAI | `llm_provider: "openai"` | GPT-4, GPT-3.5 Turbo |
| Anthropic | `llm_provider: "anthropic"` | Claude 3 family |
| Ollama | `llm_provider: "ollama"` | Local, private, zero cost |
| Custom Proxy | `llm_provider: "proxy"` | Any OpenAI-compatible endpoint |

## Resources

- [GitHub Repository](https://github.com/SuperInstance/git-agent)
- [FLUX Runtime](https://github.com/SuperInstance/flux-runtime) — Bytecode VM for agent logic
- [SuperInstance Ecosystem](https://github.com/SuperInstance/SuperInstance)
- [Onboarding Guide](https://github.com/SuperInstance/git-agent/blob/main/onboarding/)

---

*Part of the [SuperInstance](https://github.com/SuperInstance) ecosystem.*
