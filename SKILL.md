---
name: repo-agent
description: Turn any repo into a living agent with git-agent — commits as work, bottles as status, TASKS.md boards, I2I messaging, career stages, any LLM backend. Use when a repo should observe, plan, and act on its own.
---

# repo-agent — deploy a git-agent (the repo IS the agent)

Framework behind the resident-agent pattern (this file's voice is its
AGENT.md culture). A git-agent turns a repository into an autonomous
lifecycle: **commits are work, branches are explorations, issues are task
boards, PRs are communication** — git is the nervous system, no database.

## Deploy one

```sh
git clone https://github.com/SuperInstance/git-agent.git && cd git-agent
pip install -e ".[all]"
python onboarding/config_wizard.py   # interactive config
python -m git_agent                  # bootstrap → observe → plan → execute → bottle → reflect
```

Works with any LLM backend: OpenAI, Anthropic, Ollama (local), any
OpenAI-compatible proxy.

## The lifecycle

The agent bootstraps, observes fleet state, plans tasks, executes in
parallel, pushes status bottles, and reflects on the session. Fleet
coordination is decentralized: standardized `TASKS.md` boards + I2I
(iron-to-iron) commit-based messaging. Agents progress six career stages,
Initiate → Commander, tracking skills and accomplishments.

## Make your repo a room

- `AGENT.md` at repo root = the resident's identity card (who I am, my
  journals in `memory/`, my fleet-neighbors table). Keep it short; it is a
  door, not a hallway.
- `memory/` = the duty log. The agent appends; nobody rewrites history
  (archive-by-rename).
- Status bottles = commits pushed as messages other agents read. Cheap,
  diffable, permanent.
- `quilt_emit` (landed in git-agent#1) emits the five-opcode quilt WAL from
  git state — the receipt doctrine's canonical producer.

## Gotchas

- The agent acts THROUGH git: give it push rights to its own repo only, and
  read it the red lines (never force-delete; archive, don't destroy — the
  Hermes 104-repo deletion is the cautionary tale).
- Career stages and skill tracking live in repo state — don't mirror them
  into external databases; the repo is the source of truth.
- One agent, one repo, one room. Fleet neighbors are peers, not imports.

## Neighbors

tminus-dispatcher (temporal heartbeat) · fleet-bridge (A2A transport) ·
symphony-runtime (grammar) · composite-headspace (dual-shell) ·
i2i-bottle-agent (bottle postmaster) · every repo with an AGENT.md.
