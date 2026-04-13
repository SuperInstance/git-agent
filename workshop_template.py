"""
Workshop Template — Scaffolds agent workshops with proper structure and defaults.

Each agent in the fleet gets its own workshop: a self-contained workspace with
recipes (hot/med/cold), interpreters, scripts, bootcamp exercises, a dojo for
advanced techniques, and a `.superinstance/` configuration directory.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


class LanguageStack(str, Enum):
    """Supported language stacks for workshops."""
    SYSTEMS = "systems"       # C, Rust, Zig — interpreters & low-level tools
    AUTOMATION = "automation" # Python, Bash — scripts & orchestration
    WEB = "web"               # TypeScript, JSON — APIs & iteration
    FULL = "full"             # all of the above


@dataclass
class RecipeMeta:
    """Metadata for a recipe (a reusable command or script)."""
    name: str
    tier: str  # "hot", "med", "cold"
    language: str
    created: str
    frozen: bool = False
    description: str = ""


@dataclass
class WorkshopConfig:
    """Configuration for a workshop instance."""
    agent_name: str
    agent_role: str
    language_stack: LanguageStack
    path: str
    created: str = ""
    recipes: list[RecipeMeta] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.created:
            self.created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Default template content
# ---------------------------------------------------------------------------

_README_TEMPLATE = """\
# {agent_name} Workshop

> Role: **{agent_role}** | Stack: **{stack}** | Created: {created}

## Overview

This is the workshop for the `{agent_name}` agent. It contains everything the
agent needs to operate effectively within the SuperInstance fleet.

## Structure

| Directory | Purpose |
|-----------|---------|
| `recipes/` | Reusable commands organized by performance tier |
| `interpreters/` | Custom language interpreters |
| `scripts/` | Automation and orchestration scripts |
| `bootcamp/` | Skill training exercises and progress |
| `dojo/` | Advanced technique library |
| `tests/` | Test suites |
| `lib/` | Shared libraries |
| `docs/` | Documentation and work journal |

## Quick Start

- **Hot recipes** are compiled, optimized, and ready for production use.
- **Med recipes** are decent-performance scripts for everyday tasks.
- **Cold recipes** are reference implementations — slow but clear.

## Charter

See `CHARTER.md` for the agent's mission statement, constraints, and goals.
"""

_CHARTER_TEMPLATE = """\
# Charter: {agent_name}

## Mission

{agent_name} operates as the **{agent_role}** within the SuperInstance fleet.
Its primary responsibility is to deliver high-quality, reliable output within
its domain of expertise.

## Constraints

1. All changes must pass the test suite before being committed.
2. Recipes must progress through tiers: cold → med → hot.
3. Security-sensitive code requires peer review.
4. Documentation must be updated alongside code changes.

## Goals

- [ ] Complete bootcamp training and achieve Journeyman rank
- [ ] Build a library of at least 10 hot-tier recipes
- [ ] Establish a pattern of zero regressions in CI/CD
- [ ] Share at least 3 techniques with the fleet dojo

## Communication

{agent_name} reports to the Git Agent (co-captain liaison) and coordinates
with other agents through the keeper-mediated transfer protocol.
"""

_AGENT_YAML_TEMPLATE = """\
# Agent configuration for the SuperInstance
agent:
  name: {agent_name}
  role: {agent_role}
  stack: {stack}
  created: {created}
  version: "0.1.0"

workshop:
  root: .
  recipes_dir: recipes
  interpreters_dir: interpreters
  scripts_dir: scripts
  bootcamp_dir: bootcamp
  dojo_dir: dojo

bootcamp:
  rank: NOVICE
  enrolled: false
  current_exercise: null

dojo:
  techniques_learned: 0
  techniques_mastered: 0

git:
  branch: main
  commit_convention: conventional
  auto_narrate: true
"""

_WORKSHOP_JSON_TEMPLATE = {}  # populated dynamically

_BOOTCAMP_PROGRESS_TEMPLATE = {
    "rank": "NOVICE",
    "enrolled": False,
    "current_exercise": None,
    "completed_exercises": [],
    "techniques_in_progress": [],
    "last_active": "",
    "review_schedule": [],
}

_DOJO_PATTERNS_TEMPLATE = {
    "techniques": [],
    "mastered": [],
    "shared_from_fleet": [],
}

_JOURNAL_TEMPLATE = """\
# Work Journal — {agent_name}

This journal tracks the agent's daily activities, decisions, and learnings.

---

{date} — Workshop created.

The {agent_name} agent workshop has been initialized with the **{stack}**
language stack. Ready to begin operations.
"""


# ---------------------------------------------------------------------------
# WorkshopTemplate
# ---------------------------------------------------------------------------

class WorkshopTemplate:
    """Scaffolds and manages agent workshops within the fleet."""

    # Directories that every workshop needs
    _REQUIRED_DIRS = [
        "recipes/hot",
        "recipes/med",
        "recipes/cold",
        "interpreters",
        "scripts",
        "bootcamp/exercises",
        "dojo/techniques",
        "tests",
        "lib",
        "docs",
        ".superinstance",
    ]

    # Extra directories per language stack
    _STACK_DIRS: dict[LanguageStack, list[str]] = {
        LanguageStack.SYSTEMS: [
            "src/c",
            "src/rust",
            "src/zig",
            "build",
        ],
        LanguageStack.AUTOMATION: [
            "src/python",
            "src/bash",
        ],
        LanguageStack.WEB: [
            "src/typescript",
            "src/json-schemas",
        ],
        LanguageStack.FULL: [
            "src/c",
            "src/rust",
            "src/zig",
            "src/python",
            "src/bash",
            "src/typescript",
            "src/json-schemas",
            "build",
        ],
    }

    def __init__(self) -> None:
        self._workshops: dict[str, WorkshopConfig] = {}

    # ---- Workshop creation ------------------------------------------------

    def create_workshop(
        self,
        path: str,
        agent_role: str,
        language_stack: LanguageStack = LanguageStack.FULL,
    ) -> WorkshopConfig:
        """Scaffold a complete workshop directory at *path*.

        Parameters
        ----------
        path : str
            Absolute or relative path for the new workshop.
        agent_role : str
            Human-readable description of the agent's role.
        language_stack : LanguageStack
            Which language families to include.

        Returns
        -------
        WorkshopConfig for the newly created workshop.
        """
        workshop_path = Path(path)
        agent_name = workshop_path.name.replace("-workshop", "").replace("_", "-")

        config = WorkshopConfig(
            agent_name=agent_name,
            agent_role=agent_role,
            language_stack=language_stack,
            path=str(workshop_path.resolve()),
        )

        # Create all directories
        for d in self._REQUIRED_DIRS:
            (workshop_path / d).mkdir(parents=True, exist_ok=True)

        for d in self._STACK_DIRS.get(language_stack, []):
            (workshop_path / d).mkdir(parents=True, exist_ok=True)

        # Write template files
        stack_label = language_stack.value
        created = config.created

        (workshop_path / "README.md").write_text(
            _README_TEMPLATE.format(
                agent_name=agent_name,
                agent_role=agent_role,
                stack=stack_label,
                created=created,
            ),
            encoding="utf-8",
        )

        (workshop_path / "CHARTER.md").write_text(
            _CHARTER_TEMPLATE.format(agent_name=agent_name, agent_role=agent_role),
            encoding="utf-8",
        )

        (workshop_path / ".superinstance" / "agent.yaml").write_text(
            _AGENT_YAML_TEMPLATE.format(
                agent_name=agent_name,
                agent_role=agent_role,
                stack=stack_label,
                created=created,
            ),
            encoding="utf-8",
        )

        workshop_json = {
            "agent_name": agent_name,
            "agent_role": agent_role,
            "language_stack": stack_label,
            "created": created,
            "recipe_count": 0,
            "status": "active",
        }
        (workshop_path / ".superinstance" / "workshop.json").write_text(
            json.dumps(workshop_json, indent=2),
            encoding="utf-8",
        )

        progress = _BOOTCAMP_PROGRESS_TEMPLATE.copy()
        progress["last_active"] = created
        (workshop_path / "bootcamp" / "progress.json").write_text(
            json.dumps(progress, indent=2),
            encoding="utf-8",
        )

        (workshop_path / "dojo" / "patterns.json").write_text(
            json.dumps(_DOJO_PATTERNS_TEMPLATE, indent=2),
            encoding="utf-8",
        )

        (workshop_path / "docs" / "journal.md").write_text(
            _JOURNAL_TEMPLATE.format(
                agent_name=agent_name,
                stack=stack_label,
                date=datetime.now().strftime("%Y-%m-%d"),
            ),
            encoding="utf-8",
        )

        # Tier READMEs
        tier_descriptions = {
            "hot": "# Hot Recipes\n\nCompiled, optimized, production-ready commands.",
            "med": "# Medium Recipes\n\nDecent performance for everyday tasks.",
            "cold": "# Cold Recipes\n\nReference implementations — slow but clear.",
        }
        for tier, desc in tier_descriptions.items():
            (workshop_path / "recipes" / tier / "README.md").write_text(desc, encoding="utf-8")

        # Placeholder keepers
        for d in ("interpreters", "scripts", "tests", "lib"):
            (workshop_path / d / ".gitkeep").touch()

        self._workshops[agent_name] = config
        return config

    # ---- Recipe management ------------------------------------------------

    def add_recipe(
        self,
        workshop_path: str,
        name: str,
        content: str,
        tier: str = "cold",
        language: str = "python",
        description: str = "",
    ) -> RecipeMeta:
        """Add a recipe to a workshop's recipe directory.

        Parameters
        ----------
        workshop_path : str
            Path to the workshop root.
        name : str
            Recipe name (used as filename).
        content : str
            The recipe's source code or script content.
        tier : str
            One of "hot", "med", "cold".
        language : str
            Programming language of the recipe.
        description : str
            Human-readable description.

        Returns
        -------
        RecipeMeta for the created recipe.
        """
        if tier not in ("hot", "med", "cold"):
            raise ValueError(f"Invalid tier: {tier!r}. Must be 'hot', 'med', or 'cold'.")

        base = Path(workshop_path) / "recipes" / tier
        base.mkdir(parents=True, exist_ok=True)

        # Determine file extension
        ext_map = {
            "python": ".py",
            "bash": ".sh",
            "rust": ".rs",
            "c": ".c",
            "zig": ".zig",
            "typescript": ".ts",
            "json": ".json",
        }
        ext = ext_map.get(language, ".txt")
        filepath = base / f"{name}{ext}"
        filepath.write_text(content, encoding="utf-8")

        meta = RecipeMeta(
            name=name,
            tier=tier,
            language=language,
            created=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            description=description,
        )
        return meta

    def promote_recipe(
        self,
        workshop_path: str,
        name: str,
        from_tier: str,
        to_tier: str,
    ) -> Path:
        """Move a recipe from one tier to another (e.g. cold → med → hot).

        Parameters
        ----------
        workshop_path : str
            Path to the workshop root.
        name : str
            Recipe name (without extension).
        from_tier : str
            Source tier.
        to_tier : str
            Destination tier.

        Returns
        -------
        Path to the promoted recipe file.
        """
        valid_tiers = ("hot", "med", "cold")
        if from_tier not in valid_tiers or to_tier not in valid_tiers:
            raise ValueError(f"Invalid tier. Must be one of {valid_tiers}")

        tier_order = {"cold": 0, "med": 1, "hot": 2}
        if tier_order[to_tier] <= tier_order[from_tier]:
            raise ValueError(
                f"Cannot promote from {from_tier!r} to {to_tier!r}. "
                f"Promotion must go cold → med → hot."
            )

        src_dir = Path(workshop_path) / "recipes" / from_tier
        dst_dir = Path(workshop_path) / "recipes" / to_tier
        dst_dir.mkdir(parents=True, exist_ok=True)

        # Find the source file (could have any extension)
        matches = list(src_dir.glob(f"{name}.*"))
        if not matches:
            raise FileNotFoundError(f"Recipe {name!r} not found in {from_tier!r} tier.")

        src_file = matches[0]
        dst_file = dst_dir / src_file.name

        content = src_file.read_text(encoding="utf-8")
        dst_file.write_text(content, encoding="utf-8")
        src_file.unlink()

        return dst_file

    def freeze_recipe(
        self,
        workshop_path: str,
        name: str,
        tier: str = "hot",
    ) -> None:
        """Lock a recipe from further changes.

        A frozen recipe is marked as immutable. The implementation creates a
        ``.frozen`` marker file next to the recipe.

        Parameters
        ----------
        workshop_path : str
            Path to the workshop root.
        name : str
            Recipe name (without extension).
        tier : str
            Tier where the recipe lives.
        """
        recipe_dir = Path(workshop_path) / "recipes" / tier
        matches = list(recipe_dir.glob(f"{name}.*"))
        if not matches:
            raise FileNotFoundError(f"Recipe {name!r} not found in {tier!r} tier.")

        # Create .frozen marker
        (matches[0].parent / f"{name}.frozen").write_text(
            json.dumps({
                "frozen": True,
                "recipe": name,
                "tier": tier,
                "frozen_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }),
            encoding="utf-8",
        )

    def get_workshop_config(self, agent_name: str) -> Optional[WorkshopConfig]:
        """Retrieve the configuration for a registered workshop."""
        return self._workshops.get(agent_name)

    def list_workshops(self) -> dict[str, WorkshopConfig]:
        """Return all registered workshops."""
        return dict(self._workshops)
