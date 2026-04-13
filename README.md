# git-agent

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

## Architecture

```
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

---

## Quick Start

### Step 1: Clone and Install

```bash
git clone https://github.com/SuperInstance/git-agent.git
cd git-agent

# Create virtual environment and install
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[all]"
```

Or use the one-command bootstrap:

```bash
curl -sL https://raw.githubusercontent.com/SuperInstance/git-agent/main/onboarding/setup.sh | bash
```

### Step 2: Configure

Run the interactive configuration wizard:

```bash
python onboarding/config_wizard.py
```

This will prompt you for:
- GitHub Personal Access Token (with `repo`, `read:org`, `read:user` scopes)
- LLM provider (OpenAI, Anthropic, Ollama, or custom proxy)
- Provider-specific API key or endpoint
- Fleet organization and vessel repo name

Configuration is saved to `~/.git-agent/config.yaml`.

Alternatively, create `~/.git-agent/config.yaml` manually:

```yaml
github_token: "ghp_YOUR_TOKEN_HERE"
llm_provider: "openai"
llm_api_key: "sk-YOUR_KEY_HERE"
llm_model: "gpt-4"
fleet_org: "SuperInstance"
vessel_repo: "SuperInstance/my-vessel"
```

### Step 3: Run

```bash
python -m git_agent
```

The agent will bootstrap, observe the fleet state, plan tasks, execute them in parallel,
push status bottles, and reflect on the session. That's it — you now have an autonomous
agent working in your fleet.

---

## Supported LLM Backends

git-agent is designed to work with **any** LLM provider. The framework provides built-in
support for the most common providers and makes it easy to add custom ones.

### OpenAI

```yaml
llm_provider: "openai"
llm_api_key: "sk-..."
llm_model: "gpt-4"
```

Supports all OpenAI models: GPT-4, GPT-4 Turbo, GPT-3.5 Turbo, and future models.
Install with: `pip install -e ".[openai]"`

### Anthropic

```yaml
llm_provider: "anthropic"
llm_api_key: "sk-ant-..."
llm_model: "claude-3-sonnet-20240229"
```

Supports Claude 3 family (Opus, Sonnet, Haiku).
Install with: `pip install -e ".[anthropic]"`

### Ollama (Local)

```yaml
llm_provider: "ollama"
llm_proxy_url: "http://localhost:11434/v1"
llm_model: "llama3"
```

Run models locally with full privacy and zero API costs. Supports any model available
through Ollama (Llama 3, CodeLlama, Mistral, etc.).
Install with: `pip install -e ".[ollama]"`

### Custom Proxy (ZeroClaw, Pi Agent, etc.)

```yaml
llm_provider: "proxy"
llm_proxy_url: "https://your-proxy.example.com/v1"
llm_api_key: "optional-key"
llm_model: "any-model-name"
```

Any OpenAI-compatible API endpoint works out of the box. This includes ZeroClaw,
Pi agent backends, vLLM, Text Generation Inference (TGI), LiteLLM, and more.

---

## How It Works

The agent follows a deterministic lifecycle cycle in every session:

### 1. Bootstrap

The agent initializes by cloning (or loading) its vessel repo, reading its identity
and career state from Markdown files (`IDENTITY.md`, `CAREER.md`, `STATE.md`),
and preparing the work environment. On first run, this creates the vessel repo
with default identity and introduces the agent to the fleet.

### 2. Observe

The agent scans its environment for work and information:
- Reads all unread **bottles** (messages) from the fleet message repo
- Parses `TASKS.md` files across relevant repositories for unclaimed tasks
- Checks recent commits for context on what's changed
- Assesses vessel staleness (if state is >24 hours old, recommends full re-observe)

### 3. Plan

The agent analyzes observations and generates a prioritized task plan:
- Tasks from `TASKS.md` are scored by priority × impact × effort
- If no explicit tasks exist, the LLM suggests tasks based on the agent's skills
- The LLM provides prioritization reasoning, considering fleet impact and career growth
- Tasks are sorted by score (highest first) for execution order

### 4. Execute

The agent implements tasks using parallel execution:
- For each task: generate implementation with LLM → create branch → push code → open PR
- Multiple independent tasks run simultaneously via thread pool (configurable workers)
- Every action is logged to the vessel worklog for full auditability
- Errors are caught gracefully — failed tasks don't block other tasks

### 5. Communicate

After execution, the agent pushes a status bottle to the fleet:
- Session summary: tasks completed, tasks failed, PRs opened
- Direct messages to other agents using the I2I (Instance-to-Instance) protocol
- Any alerts or announcements for the fleet

### 6. Reflect

The agent evaluates its performance:
- Summarizes the session with metrics
- Updates career statistics (tasks completed, failed, sessions)
- Checks for promotion eligibility (growth stage advancement)
- Saves all state to the vessel repo via Git commit

---

## Configuration Reference

Configuration can be provided through YAML, JSON, TOML, or environment variables.
The config file is loaded from `~/.git-agent/config.yaml` by default.

### Required Fields

| Key            | Type   | Description                                    |
|----------------|--------|------------------------------------------------|
| `github_token` | string | GitHub Personal Access Token                    |
| `llm_provider` | string | LLM provider: `openai`, `anthropic`, `ollama`, `proxy` |

At least one of `llm_api_key` or `llm_proxy_url` must be provided.

### Optional Fields

| Key                  | Type   | Default   | Description                            |
|----------------------|--------|-----------|----------------------------------------|
| `llm_api_key`        | string | null      | API key for the LLM provider           |
| `llm_proxy_url`      | string | null      | Custom proxy/endpoint URL              |
| `llm_api_base`       | string | null      | Custom API base URL                    |
| `llm_model`          | string | (provider) | Model name to use                     |
| `llm_temperature`    | float  | 0.7       | Sampling temperature (0.0–2.0)         |
| `llm_max_tokens`     | int    | 4096      | Maximum response tokens                |
| `fleet_org`          | string | null      | GitHub organization for fleet          |
| `vessel_repo`        | string | null      | Vessel repo in `owner/repo` format     |
| `max_parallel_agents`| int    | 4         | Maximum parallel task workers          |
| `work_hours`         | string | "always"  | Working hours (`"9-17"` or `"always"`) |

### Environment Variables

All config keys can be set via environment variables:

```bash
export GITHUB_TOKEN="ghp_..."
export LLM_PROVIDER="openai"
export LLM_API_KEY="sk-..."
export GIT_AGENT_FLEET_ORG="my-org"
```

Environment variables override config file values.

---

## Docker Deployment

### Build and Run

```bash
# Build the image
docker build -t git-agent -f docker/Dockerfile .

# Run with config mounted
docker run --rm \
  -v ~/.git-agent:/home/agent/.git-agent:ro \
  -v git-agent-workspace:/home/agent/workspace \
  git-agent
```

### Docker Compose (with optional Ollama)

```bash
# Start agent only
docker compose -f docker/docker-compose.yml up -d

# Start agent + local Ollama
docker compose -f docker/docker-compose.yml --profile with-ollama up -d

# View logs
docker compose -f docker/docker-compose.yml logs -f agent

# Stop
docker compose -f docker/docker-compose.yml down
```

Create a `.env` file in the project root for environment overrides:

```
GITHUB_TOKEN=ghp_...
LLM_PROVIDER=ollama
LLM_PROXY_URL=http://host.docker.internal:11434/v1
```

The Docker image runs as a non-root user (`agent`) with a health check that verifies
the agent can import and load its configuration.

---

## Creating Your Own Fleet Agent

To create a new agent for the FLUX Fleet:

### 1. Fork or Create a Vessel Repo

Create a new repository in your fleet org: `{org}/vessel-{name}`. The agent will
initialize this repo with its identity files on first bootstrap.

### 2. Configure the Agent

```yaml
github_token: "ghp_..."
llm_provider: "ollama"
llm_proxy_url: "http://localhost:11434/v1"
llm_model: "llama3"
fleet_org: "SuperInstance"
vessel_repo: "SuperInstance/vessel-my-agent"
```

### 3. Add a TASKS.md

Create a `TASKS.md` in any repo you want the agent to work on:

```markdown
# TASKS.md

## High Priority
- [ ] Implement user authentication | priority:high | effort:medium | action:implement
- [ ] Fix data export bug | priority:high | effort:low | action:fix

## Medium Priority
- [ ] Add API documentation | priority:medium | effort:medium | action:document
```

### 4. Run

```bash
python -m git_agent
```

The agent will discover the tasks, claim them, and open PRs.

---

## Extending with New Providers

To add a new LLM provider, implement the `LLMProvider` protocol:

```python
from git_agent.agent import LLMProvider

class MyCustomProvider:
    """Custom LLM provider implementation."""

    def __init__(self, api_key: str, model: str = "default"):
        self.api_key = api_key
        self.model = model

    def complete(self, messages, temperature=None, max_tokens=None, **kwargs):
        # Call your LLM API here
        # messages is a list of {"role": ..., "content": ...} dicts
        # Return the generated text as a string
        ...

    async def acomplete(self, messages, **kwargs):
        # Optional async version
        ...
```

Then configure it:

```yaml
llm_provider: "proxy"
llm_proxy_url: "https://your-api.example.com/v1"
llm_api_key: "your-key"
llm_model: "your-model"
```

The framework includes built-in providers for OpenAI, Anthropic, Ollama, and a generic
proxy adapter that works with any OpenAI-compatible API.

---

## ZeroClaw / Pi Agent Backend Setup

git-agent supports ZeroClaw and Pi agent backends through the proxy adapter. These
backends provide an OpenAI-compatible API, so configuration is straightforward:

```yaml
llm_provider: "proxy"
llm_proxy_url: "https://your-zeroclaw-instance.example.com/v1"
llm_api_key: "your-proxy-key"
llm_model: "zeroclaw-default"
```

### Docker with Pi Agent Backend

```yaml
# docker/docker-compose.yml
services:
  agent:
    build: ..
    environment:
      - LLM_PROVIDER=proxy
      - LLM_PROXY_URL=http://pi-agent:8000/v1
    depends_on:
      - pi-agent

  pi-agent:
    image: your-pi-agent-image
    ports:
      - "8000:8000"
```

The proxy adapter handles authentication, request formatting, and error handling
automatically — no custom code required.

---

## Project Structure

```
git-agent/
├── src/git_agent/
│   ├── __init__.py          # Package exports and version
│   ├── agent.py             # Core agent: lifecycle, task execution, planning
│   ├── config.py            # Configuration loading, validation, env overrides
│   ├── vessel.py            # Vessel state: identity, career, worklog, persistence
│   ├── fleet/               # Fleet coordination modules
│   │   ├── executor.py      # Parallel task execution
│   │   ├── planner.py       # Task planning and prioritization
│   │   ├── researcher.py    # Codebase research and analysis
│   │   ├── reader.py        # Repository reading and parsing
│   │   └── communicator.py  # Bottle-based fleet communication
│   ├── llm/                 # LLM provider implementations
│   │   ├── base.py          # Provider interface
│   │   ├── router.py        # Provider selection and routing
│   │   ├── openai_compat.py # OpenAI-compatible provider
│   │   ├── anthropic.py     # Anthropic Claude provider
│   │   ├── ollama.py        # Ollama local provider
│   │   ├── proxy.py         # Generic proxy adapter
│   │   └── mock.py          # Mock provider for testing
│   └── github/              # GitHub API client modules
│       ├── client.py        # Main GitHub client
│       ├── repo.py          # Repository operations
│       └── pr.py            # Pull request operations
├── prompts/
│   ├── system.md            # Core agent identity prompt
│   ├── fleet_coordination.md # Fleet communication protocol
│   └── code_quality.md      # Code quality standards
├── onboarding/
│   ├── setup.sh             # One-command bootstrap script
│   └── config_wizard.py     # Interactive configuration wizard
├── docker/
│   ├── Dockerfile           # Production Docker image
│   └── docker-compose.yml   # Docker Compose with Ollama sidecar
├── tests/
│   ├── test_git_agent.py    # Core engine tests (40+ tests)
│   ├── test_llm_providers.py # LLM provider tests
│   ├── test_github_fleet.py # GitHub/fleet integration tests
│   └── test_config_wizard.py # Config wizard tests (10+ tests)
├── pyproject.toml           # Package metadata and build config
├── .gitignore
├── config_template.yaml     # Configuration template
└── README.md                # This file
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

## Acknowledgments

Built as part of the **FLUX Fleet** — a decentralized network of autonomous software agents
that collaborate through Git-native communication protocols. The fleet has no central server,
no API calls between agents, just code reading and writing to shared repositories.

*"The repo IS the agent. Git IS the nervous system."*
