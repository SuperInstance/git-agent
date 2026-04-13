# Git Agent

**Co-captain liaison for the SuperInstance fleet.**

The Git Agent serves as the primary interface between human operators and the fleet of agents inside the SuperInstance. It manages workshops, narrates commit histories, creates and reviews pull requests, monitors CI/CD pipelines, and spawns new git-agents when needed.

## Features

- **Workshop Registry** — Track and manage agent workshops across the fleet
- **Commit Narrator** — Translate raw git history into human-readable narratives
- **PR Manager** — Create, review, and manage pull requests on behalf of agents
- **CI/CD Monitor** — Track build statuses, test results, deployment outcomes
- **Agent Spawner** — Create new git-agents that inherit workshop configuration
- **Bootcamp & Dojo** — Structured skill development with rank progression
- **Daily Reports** — Fleet activity summaries with commit breakdowns

## Quick Start

```bash
# Create a new workshop
python -m git_agent workshop create flux-scheduler --role "Scheduling agent" --stack full

# Show fleet status
python -m git_agent workshop status

# Enroll an agent in bootcamp
python -m git_agent bootcamp enroll flux-scheduler

# Generate a narrative
python -m git_agent narrate flux-scheduler --style story

# Extract lessons learned
python -m git_agent lessons flux-scheduler

# Generate fleet report
python -m git_agent fleet-report
```

## Architecture

```
git_agent.py          — Core Git Agent (co-captain liaison)
narrator.py           — Commit Narrative Engine
workshop_template.py  — Workshop Structure Generator
bootcamp.py           — Bootcamp & Dojo Framework
cli.py                — Command-line interface
```

## Language Stacks

| Stack | Languages | Use Case |
|-------|-----------|----------|
| `systems` | C, Rust, Zig | Interpreters & low-level tools |
| `automation` | Python, Bash | Scripts & orchestration |
| `web` | TypeScript, JSON | APIs & iteration |
| `full` | All | Complete agent workshop |

## Dependencies

- Python 3.10+
- PyYAML (optional, for YAML config support)
- stdlib only (subprocess for git operations)

## License

MIT
