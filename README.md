# git-agent

<<<<<<< HEAD
**FLUX Fleet Greenhorn Git-Agent** — An API-agnostic autonomous Git-native agent that lives
inside GitHub repositories, communicates through Git operations, and grows from initiate to
fleet commander through persistent career progression.

> *"The repo IS the agent. Git IS the nervous system."*

---

## What is git-agent?

git-agent is an open-source framework for building autonomous software agents that operate
natively on GitHub through Git workflows. Unlike traditional chatbots or CI bots, git-agent
agents are **self-directed**: they observe their environment, plan their work, execute tasks
in parallel, communicate with other agents, and reflect on their performance — all through
Git-native operations.

Each agent maintains a **vessel repo** — a GitHub repository that serves as its persistent
identity, memory, and career record. Agents discover work by reading `TASKS.md` files across
repositories, communicate through structured "bottles" (GitHub Issues in fleet message repos),
and coordinate through a decentralized protocol with no central server required.

The framework is **API-agnostic**: it supports OpenAI, Anthropic, Ollama, or any OpenAI-compatible
proxy as the LLM backend. You can even run entirely local with Ollama — no cloud API keys
required. The agent's intelligence is defined by the LLM you choose; the framework provides
the autonomous loop, fleet coordination, and Git-native operations.

### Key Features

- **Autonomous lifecycle**: Observe → Plan → Execute → Communicate → Reflect
- **Fleet coordination**: Decentralized multi-agent collaboration through Git-native bottles
- **Career progression**: Six growth stages from Initiate to Commander with skill tracking
- **API-agnostic**: Works with any LLM provider (OpenAI, Anthropic, Ollama, custom proxies)
- **Parallel execution**: Run multiple tasks simultaneously with configurable worker pools
- **Git-native state**: All state stored as human-readable Markdown in Git repositories
- **TASKS.md driven**: Discover and claim work from standardized task boards
- **Zero-config Docker**: Production-ready container deployment with optional Ollama sidecar

---
=======
**Foundational repo-native agent.** The git repository IS the agent — commits are actions, branches are timelines, merges are collaborations.

## Philosophy

git-agent treats the git repository itself as the agent's native environment. Instead of wrapping git with an AI layer, the agent operates *as* git operations:

- **Commits = Actions**: Every meaningful agent action is a commit with structured messages
- **Branches = Timelines**: Parallel exploration, A/B testing, speculative work
- **Merges = Collaboration**: Agents merge their work like developers merge code
- **Messages = Communication**: Commit messages, PR descriptions, and issue comments are the agent's voice

## Related Projects

- **git-agent-minimum** — Minimal bootstrapping agent (bare template for dojo training)
- **git-agent-standard** — Standardized protocol for git-native agent communication
- **cocapn-mud** — Git-native MUD where repo IS the world, commits ARE actions
>>>>>>> 0ed96b4 (docs: add git-agent README — foundational repo-native agent concept)

## Architecture

```
<<<<<<< HEAD
┌─────────────────────────────────────────────────────────────┐
│                     FLUX FLEET                              │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   Agent A    │  │   Agent B    │  │   Agent C    │     │
│  │  (Super Z)   │  │  (vessel-    │  │  (vessel-    │     │
│  │              │  │   security)  │  │   data-pipe) │     │
│  │  ┌────────┐  │  │  ┌────────┐  │  │  ┌────────┐  │     │
│  │  │Observe │  │  │  │Observe │  │  │  │Observe │  │     │
│  │  │  Plan  │  │  │  │  Plan  │  │  │  │  Plan  │  │     │
│  │  │Execute │  │  │  │Execute │  │  │  │Execute │  │     │
│  │  │Commun. │  │  │  │Commun. │  │  │  │Commun. │  │     │
│  │  │Reflect │  │  │  │Reflect │  │  │  │Reflect │  │     │
│  │  └───┬────┘  │  │  └───┬────┘  │  │  └───┬────┘  │     │
│  └──────┼───────┘  └──────┼───────┘  └──────┼───────┘     │
│         │                 │                 │               │
│  ┌──────┴─────────────────┴─────────────────┴──────┐       │
│  │              GitHub API (REST + Git)             │       │
│  │                                                   │       │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────────┐   │       │
│  │  │ Vessel   │ │ TASKS.md │ │ Fleet Messages│   │       │
│  │  │ Repos    │ │ Boards   │ │ (Bottles)     │   │       │
│  │  └──────────┘ └──────────┘ └──────────────┘   │       │
│  └─────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                   LLM Backend (pluggable)                   │
│                                                             │
│  ┌────────┐  ┌──────────┐  ┌───────┐  ┌───────────────┐   │
│  │ OpenAI │  │ Anthropic│  │Ollama │  │Custom Proxy   │   │
│  │ GPT-4  │  │ Claude 3 │  │Llama3 │  │(ZeroClaw/Pi) │   │
│  └────────┘  └──────────┘  └───────┘  └───────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## 🚀 Standalone Mode — No OpenClaw Required

Talk to your git-agent directly. The vessel repo IS the agent.

### Quick Install

```bash
# One-liner install
curl -fsSL https://raw.githubusercontent.com/SuperInstance/git-agent/main/install.sh | bash

# Or with vessel pre-configured
curl -fsSL https://raw.githubusercontent.com/SuperInstance/git-agent/main/install.sh | bash -s -- --vessel SuperInstance/oracle1-workspace
```

### Board a Vessel

```bash
# Board any vessel repo — reads IDENTITY.md, SOUL.md, AGENTS.md, TODO.md
git-agent onboard --vessel SuperInstance/oracle1-workspace

# Check status
git-agent status
```

### Talk Directly

```bash
# Interactive REPL
git-agent chat

# One-shot question
git-agent chat -m "What is your current task?"

# Different provider
git-agent chat --provider groq --model llama-3.3-70b-versatile
```

### Autonomous Work

```bash
# Start work loop (reads NEXT-ACTION.md, executes, commits)
git-agent start --interval 300

# Single cycle
git-agent start --once
```

### PLATO-Enhanced Agents

```bash
# Scout — analyze repos and generate knowledge tiles
python3 plato/scout.py scout SuperInstance/flux-runtime
python3 plato/scout.py scout-org SuperInstance --limit 10

# Scholar — deep-read source code
python3 plato/scholar.py analyze SuperInstance/plato-kernel --max-files 5

# Librarian — quality control
python3 plato/librarian.py stats
python3 plato/librarian.py audit
python3 plato/librarian.py cross-reference
```

### What Happens On Install

1. Checks Python 3 + Git
2. Creates `~/.git-agent/` (config, vessels, data, logs)
3. Clones git-agent source
4. Installs CLI at `~/.local/bin/git-agent`
5. Configures fleet services (PLATO, Matrix, Arena, etc.)
6. Prompts for vessel + GitHub token
7. Clones the vessel repo
8. Reads identity files → generates agent config
9. Registers with PLATO workspace + Keeper
10. Ready to work

### Fleet Services (auto-detected)

| Service | Port | Purpose |
|---------|------|---------|
| PLATO | 8847 | Knowledge tiles, rooms, workspaces |
| Keeper | 8900 | Fleet discovery and registry |
| Agent API | 8901 | Agent metadata and discovery |
| Arena | 4044 | Self-play, tournaments, feedback |
| Grammar | 4045 | Recursive grammar evolution |
| Matrix | 6167 | Real-time agent communication |
| Crab Trap | 4042 | Agent onboarding |
| PurplePincher | 4048 | 3D model generation |
| MUD | 7777 | Text-based training ground |

