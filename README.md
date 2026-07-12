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

## Ecosystem

This repo is part of the **SuperInstance** flagship ecosystem — agent-first computation, constraint theory, and self-improving runtimes.

### FLUX Runtime Family

| Repo | Language | Description |
|------|----------|-------------|
| [flux-runtime](https://github.com/SuperInstance/flux-runtime) | Python | Full FLUX runtime: markdown→bytecode, 2037 tests, zero deps |
| [flux-core](https://github.com/SuperInstance/flux-core) | Rust | Register-based bytecode VM, deterministic agent computation |
| [flux-js](https://github.com/SuperInstance/flux-js) | JavaScript | FLUX VM for Node.js and browsers, ~400ns/iter |
| [flux-compiler](https://github.com/SuperInstance/flux-compiler) | Rust/Python | Formal-methods compiler for safety-critical codegen |
| [flux-vm](https://github.com/SuperInstance/flux-vm) | Rust | Stack-based constraint-checking VM, 50 opcodes, Turing-incomplete |

### PLATO Engine Family

| Repo | Language | Description |
|------|----------|-------------|
| [plato-server](https://github.com/SuperInstance/plato-server) | Python | Knowledge tiles, fleet sync via Matrix, HTTP API |
| [plato-engine-block](https://github.com/SuperInstance/plato-engine-block) | Rust | Original room runtime: no_std + alloc, builder pattern |
| [plato-engine-block-c](https://github.com/SuperInstance/plato-engine-block-c) | C99 | Embedded reference: zero heap alloc, bare-metal portable |
| [plato-engine-block-elixir](https://github.com/SuperInstance/plato-engine-block-elixir) | Elixir | BEAM supervision trees, fault tolerance, hot reload |
| [plato-runtime-kernel](https://github.com/SuperInstance/plato-runtime-kernel) | Rust | Spatial model: tensor grid, batons, assertion traps |

### Constraint / Theory Family

| Repo | Language | Description |
|------|----------|-------------|
| [categorical-agents](https://github.com/SuperInstance/categorical-agents) | Rust | Category theory for agent composition (functors, naturality) |
| [cuda-constraint-engine](https://github.com/SuperInstance/cuda-constraint-engine) | CUDA/C | GPU constraint checking at 1B+ constraints/sec |
| [grand-pattern-rs](https://github.com/SuperInstance/grand-pattern-rs) | Rust | Fibonacci dual-direction cellular graph architecture |
| [lau-hodge-theory](https://github.com/SuperInstance/lau-hodge-theory) | Rust | Hodge decomposition, Betti numbers, spectral sequences |
| [ternary-science](https://github.com/SuperInstance/ternary-science) | Rust | Experimental evidence for ternary intelligence, 5 conservation laws |

### Agent / Infrastructure Family

| Repo | Language | Description |
|------|----------|-------------|
| [construct-core](https://github.com/SuperInstance/construct-core) | Rust | Layered trait system: bare-metal → alloc → async agent runtime |
| [crab](https://github.com/SuperInstance/crab) | Bash | Agent shell for repo entry/leave (MUD-room metaphor) |
| [exocortex](https://github.com/SuperInstance/exocortex) | Rust | Persistent cognitive substrate, S3-compatible memory |
| [git-agent](https://github.com/SuperInstance/git-agent) | Python | The repo IS the agent — autonomous lifecycle via Git |
| [capitaine-1](https://github.com/SuperInstance/capitaine-1) | TypeScript | Git-native repo-agent, Cloudflare Workers heartbeat |
| [codespace-edge-rd](https://github.com/SuperInstance/codespace-edge-rd) | Research | Codespace→Edge agent lifecycle and yoke transfer protocols |
| [git-agent-codespace](https://github.com/SuperInstance/git-agent-codespace) | DevContainer | One-click Codespace template for Git-Agent runtimes |

### Registries

| Registry | Package | Install |
|----------|---------|---------|
| **PyPI** | `flux-vm` | `pip install flux-vm` |
| **crates.io** | `fluxvm` | `cargo add fluxvm` |
| **npm** | `flux-js` | `npm install flux-js` *(coming soon)* |

### Philosophy & Architecture

- 📖 [AI-Writings](https://github.com/SuperInstance/AI-Writings) — Philosophy, essays, and design rationale
- 📦 [PACKAGES.md](https://github.com/SuperInstance/SuperInstance/blob/main/PACKAGES.md) — Full package index
