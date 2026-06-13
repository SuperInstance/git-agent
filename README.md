# git-agent

**The repo IS the agent. Git IS the nervous system.** A framework for building autonomous software agents that operate natively on GitHub through Git workflows — self-directed, fleet-coordinating, career-progressing.

## Brand Line

> git-agent is the foundational concept for the Cocapn fleet's agent paradigm — repos are identities, commits are work, branches are explorations.

## Installation

```bash
git clone https://github.com/SuperInstance/git-agent.git
cd git-agent
pip install -e ".[all]"  # or: python3 -m venv .venv && source .venv/bin/activate && pip install -e "."
```

Or one-command bootstrap:

```bash
curl -sL https://raw.githubusercontent.com/SuperInstance/git-agent/main/onboarding/setup.sh | bash
```

## Usage

```bash
# Configure (interactive wizard)
python onboarding/config_wizard.py

# Run the agent
python -m git_agent
```

The agent will bootstrap, observe fleet state, plan tasks, execute in parallel, push status bottles, and reflect on the session.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    FLUX FLEET                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │ Agent A  │  │ Agent B  │  │ Agent C  │          │
│  │Observe   │  │Observe   │  │Observe   │          │
│  │Plan      │  │Plan      │  │Plan      │          │
│  │Execute   │  │Execute   │  │Execute   │          │
│  │Commun.   │  │Commun.   │  │Commun.   │          │
│  │Reflect   │  │Reflect   │  │Reflect   │          │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘          │
└───────┼──────────────┼──────────────┼────────────────┘
        └──────────────┼──────────────┘
              GitHub API (REST + Git)
        ┌──────────────┼──────────────┐
        │ Vessel Repos │ TASKS.md     │ Fleet Messages
        └──────────────┴──────────────┘
```

## Key Features

- **Autonomous lifecycle**: Observe → Plan → Execute → Communicate → Reflect
- **Fleet coordination**: Decentralized multi-agent collaboration through Git-native bottles
- **Career progression**: Six growth stages from Initiate to Commander with skill tracking
- **API-agnostic**: Works with OpenAI, Anthropic, Ollama, or any OpenAI-compatible proxy
- **Parallel execution**: Multiple tasks simultaneously with configurable worker pools
- **Git-native state**: All state stored as human-readable Markdown in Git repositories
- **TASKS.md driven**: Discover and claim work from standardized task boards

## Supported LLM Backends

| Provider | Config Key | Notes |
|----------|------------|-------|
| OpenAI | `llm_provider: "openai"` | GPT-4, GPT-3.5 Turbo |
| Anthropic | `llm_provider: "anthropic"` | Claude 3 family |
| Ollama | `llm_provider: "ollama"` | Local, private, zero cost |
| Custom Proxy | `llm_provider: "proxy"` | ZeroClaw, Pi Agent, vLLM, any OpenAI-compatible |

## Fleet Context

Part of the Cocapn fleet. Related repos:

- [iron-to-iron](https://github.com/SuperInstance/iron-to-iron) — I2I git-native agent-to-agent communication protocol (commit-based proposals, no API calls)
- [flux-runtime](https://github.com/SuperInstance/flux-runtime) — C11 micro-VM execution engine for agent bytecode
- [holodeck-core](https://github.com/SuperInstance/holodeck-core) — Standalone MUD engine for room-based agent simulation
- [plato-sdk](https://github.com/SuperInstance/plato-sdk) — SDK for PLATO room-based agent coordination

---
🦐 Cocapn fleet — lighthouse keeper architecture