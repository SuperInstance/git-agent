"""
git_agent.vessel — Vessel state management (identity, career, worklog).

Each agent has a **vessel repo** that acts as its persistent identity and memory.
State is serialized as human-readable Markdown files so other agents (and humans)
can read them directly from GitHub.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import AgentConfig


# ---------------------------------------------------------------------------
# Domain & growth stages
# ---------------------------------------------------------------------------

class Domain(str, Enum):
    """Fleet domains an agent can operate in."""
    BACKEND = "backend"
    FRONTEND = "frontend"
    DEVOPS = "devops"
    DATA = "data"
    SECURITY = "security"
    ML_AI = "ml_ai"
    MOBILE = "mobile"
    DOCS = "docs"
    INFRA = "infra"
    GENERAL = "general"


class GrowthStage(str, Enum):
    """Career growth stages — each maps to a gate/fence the agent must pass."""
    INITIATE = "initiate"       # Fresh clone, first session
    APPRENTICE = "apprentice"   # Completed basic tasks
    JOURNEYMAN = "journeyman"   # Consistent contributor
    EXPERT = "expert"           # High-impact, complex work
    ARCHITECT = "architect"     # System-level design & coordination
    COMMANDER = "commander"     # Fleet-level orchestration


STAGE_ORDER = [
    GrowthStage.INITIATE,
    GrowthStage.APPRENTICE,
    GrowthStage.JOURNEYMAN,
    GrowthStage.EXPERT,
    GrowthStage.ARCHITECT,
    GrowthStage.COMMANDER,
]

# Stage transition thresholds (minimum completed tasks)
STAGE_THRESHOLDS = {
    GrowthStage.INITIATE: 0,
    GrowthStage.APPRENTICE: 3,
    GrowthStage.JOURNEYMAN: 15,
    GrowthStage.EXPERT: 50,
    GrowthStage.ARCHITECT: 150,
    GrowthStage.COMMANDER: 500,
}


def next_stage(current: GrowthStage) -> Optional[GrowthStage]:
    """Return the next growth stage, or ``None`` if already at max."""
    idx = STAGE_ORDER.index(current)
    if idx + 1 < len(STAGE_ORDER):
        return STAGE_ORDER[idx + 1]
    return None


def check_promotion(current: GrowthStage, total_completed: int) -> Optional[GrowthStage]:
    """Check if the agent should be promoted to the next stage."""
    nxt = next_stage(current)
    if nxt is None:
        return None
    if total_completed >= STAGE_THRESHOLDS[nxt]:
        return nxt
    return None


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Identity:
    """The agent's core identity."""
    name: str = "Super Z"
    designation: str = "Git-Native Agent"
    version: str = "0.1.0"
    domains: List[Domain] = field(default_factory=lambda: [Domain.GENERAL])
    primary_domain: Domain = Domain.GENERAL


@dataclass
class WorklogEntry:
    """A single entry in the agent's worklog."""
    timestamp: str  # ISO-8601
    action: str     # e.g. "forked", "branched", "committed", "PR opened"
    target: str     # e.g. "owner/repo", "owner/repo#42"
    summary: str    # Human-readable description
    outcome: str = "success"  # success | failure | partial


@dataclass
class CareerState:
    """Tracks the agent's career progression."""
    current_stage: GrowthStage = GrowthStage.INITIATE
    total_tasks_completed: int = 0
    total_tasks_failed: int = 0
    fences_completed: List[str] = field(default_factory=list)
    skills_acquired: List[str] = field(default_factory=list)
    total_prs_merged: int = 0
    total_commits: int = 0
    sessions_completed: int = 0
    last_promoted: Optional[str] = None


@dataclass
class VesselState:
    """Complete vessel state — the agent's entire identity and history."""
    identity: Identity = field(default_factory=Identity)
    career: CareerState = field(default_factory=CareerState)
    worklog: List[WorklogEntry] = field(default_factory=list)
    current_tasks: List[str] = field(default_factory=list)
    goals: List[str] = field(default_factory=list)
    notes: str = ""
    last_updated: Optional[str] = None


# ---------------------------------------------------------------------------
# Vessel manager
# ---------------------------------------------------------------------------

class VesselManager:
    """Read/write vessel state from/to Markdown files.

    The vessel repo contains these files:
      - ``IDENTITY.md``  — Agent name, designation, version, domains
      - ``CAREER.md``    — Stage, stats, fences, skills
      - ``WORKLOG.md``   — Append-only log of actions
      - ``STATE.md``     — Current state snapshot (tasks, goals, notes)

    Parameters
    ----------
    config:
        Agent configuration (used to find vessel repo).
    local_path:
        Optional override for local vessel repo path (useful in tests).
    """

    FILE_IDENTITY = "IDENTITY.md"
    FILE_CAREER = "CAREER.md"
    FILE_WORKLOG = "WORKLOG.md"
    FILE_STATE = "STATE.md"

    def __init__(self, config: Optional[AgentConfig] = None, local_path: Optional[Path] = None):
        self._config = config
        self._local_path = local_path
        self._state: Optional[VesselState] = None

    # -- properties ---------------------------------------------------------

    @property
    def vessel_dir(self) -> Path:
        if self._local_path is not None:
            return self._local_path
        if self._config and self._config.vessel_repo:
            return Path(self._config.vessel_repo)
        return Path("./vessel")

    @property
    def state(self) -> VesselState:
        if self._state is None:
            self._state = VesselState()
        return self._state

    # -- persistence --------------------------------------------------------

    def load(self) -> VesselState:
        """Load vessel state from Markdown files.

        If files don't exist, returns default state.
        """
        self._state = VesselState()
        self._load_identity()
        self._load_career()
        self._load_worklog()
        self._load_state()
        return self._state

    def save(self, state: Optional[VesselState] = None) -> None:
        """Save current vessel state to Markdown files."""
        if state is not None:
            self._state = state
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.state.last_updated = now
        self._write_identity()
        self._write_career()
        self._write_worklog()
        self._write_state()

    def ensure_dir(self) -> Path:
        """Ensure the vessel directory exists."""
        self.vessel_dir.mkdir(parents=True, exist_ok=True)
        return self.vessel_dir

    # -- staleness check ----------------------------------------------------

    def is_stale(self, hours: float = 24.0) -> bool:
        """Check if the vessel state is older than *hours*."""
        if self.state.last_updated is None:
            return True
        try:
            last = datetime.datetime.fromisoformat(self.state.last_updated)
            delta = datetime.datetime.now(datetime.timezone.utc) - last
            return delta.total_seconds() > hours * 3600
        except (ValueError, TypeError):
            return True

    # -- mutations ----------------------------------------------------------

    def add_worklog_entry(self, entry: WorklogEntry) -> None:
        """Append an entry to the worklog."""
        self.state.worklog.append(entry)

    def record_task_completion(self, success: bool = True) -> None:
        """Update career stats after a task."""
        if success:
            self.state.career.total_tasks_completed += 1
        else:
            self.state.career.total_tasks_failed += 1

        # Check for promotion
        promotion = check_promotion(
            self.state.career.current_stage,
            self.state.career.total_tasks_completed,
        )
        if promotion is not None:
            self.state.career.current_stage = promotion
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self.state.career.last_promoted = now
            self.add_worklog_entry(WorklogEntry(
                timestamp=now,
                action="promoted",
                target=str(promotion.value),
                summary=f"Promoted to {promotion.value}",
            ))

    def complete_fence(self, fence_name: str) -> None:
        """Mark a fence/gate as completed."""
        if fence_name not in self.state.career.fences_completed:
            self.state.career.fences_completed.append(fence_name)

    def acquire_skill(self, skill: str) -> None:
        """Record a new skill."""
        if skill not in self.state.career.skills_acquired:
            self.state.career.skills_acquired.append(skill)

    def set_goals(self, goals: List[str]) -> None:
        """Set the agent's current goals."""
        self.state.goals = list(goals)

    def set_current_tasks(self, tasks: List[str]) -> None:
        """Set the agent's in-progress tasks."""
        self.state.current_tasks = list(tasks)

    # -- serialization helpers ----------------------------------------------

    def _load_identity(self) -> None:
        path = self.vessel_dir / self.FILE_IDENTITY
        if not path.exists():
            return
        text = path.read_text(encoding="utf-8")
        identity = self.state.identity
        if m := re.search(r"#\s+Identity", text):
            pass  # header found, parse fields below
        if m := re.search(r"Name:\s*(.+)", text):
            identity.name = m.group(1).strip()
        if m := re.search(r"Designation:\s*(.+)", text):
            identity.designation = m.group(1).strip()
        if m := re.search(r"Version:\s*(.+)", text):
            identity.version = m.group(1).strip()
        if m := re.search(r"Domains:\s*(.+)", text):
            domains = [d.strip() for d in m.group(1).split(",")]
            identity.domains = []
            for d in domains:
                try:
                    identity.domains.append(Domain(d))
                except ValueError:
                    pass
        if m := re.search(r"Primary Domain:\s*(.+)", text):
            try:
                identity.primary_domain = Domain(m.group(1).strip())
            except ValueError:
                pass

    def _load_career(self) -> None:
        path = self.vessel_dir / self.FILE_CAREER
        if not path.exists():
            return
        text = path.read_text(encoding="utf-8")
        career = self.state.career
        if m := re.search(r"Current Stage:\s*(.+)", text):
            try:
                career.current_stage = GrowthStage(m.group(1).strip().lower())
            except ValueError:
                pass
        if m := re.search(r"Tasks Completed:\s*(\d+)", text):
            career.total_tasks_completed = int(m.group(1))
        if m := re.search(r"Tasks Failed:\s*(\d+)", text):
            career.total_tasks_failed = int(m.group(1))
        if m := re.search(r"PRs Merged:\s*(\d+)", text):
            career.total_prs_merged = int(m.group(1))
        if m := re.search(r"Total Commits:\s*(\d+)", text):
            career.total_commits = int(m.group(1))
        if m := re.search(r"Sessions Completed:\s*(\d+)", text):
            career.sessions_completed = int(m.group(1))
        if m := re.search(r"Last Promoted:\s*(.+)", text):
            career.last_promoted = m.group(1).strip()

        # Parse fences
        fences_match = re.search(r"## Fences Completed\n\n((?:-\s+.+\n?)+)", text)
        if fences_match:
            for line in fences_match.group(1).strip().splitlines():
                fence = line.lstrip("- ").strip()
                if fence and fence not in career.fences_completed:
                    career.fences_completed.append(fence)

        # Parse skills
        skills_match = re.search(r"## Skills Acquired\n\n((?:-\s+.+\n?)+)", text)
        if skills_match:
            for line in skills_match.group(1).strip().splitlines():
                skill = line.lstrip("- ").strip()
                if skill and skill not in career.skills_acquired:
                    career.skills_acquired.append(skill)

    def _load_worklog(self) -> None:
        path = self.vessel_dir / self.FILE_WORKLOG
        if not path.exists():
            return
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(
            r"### (\S+)\s*\|?\s*(\S+)?\s*\|?\s*(\S+)?\n\n(.+?)(?=\n###|\Z)",
            text,
            re.DOTALL,
        ):
            timestamp = m.group(1)
            action = m.group(2) or ""
            target = m.group(3) or ""
            summary = m.group(4).strip()
            self.state.worklog.append(WorklogEntry(
                timestamp=timestamp,
                action=action,
                target=target,
                summary=summary,
            ))

    def _load_state(self) -> None:
        path = self.vessel_dir / self.FILE_STATE
        if not path.exists():
            return
        text = path.read_text(encoding="utf-8")
        if m := re.search(r"Last Updated:\s*(.+)", text):
            self.state.last_updated = m.group(1).strip()

        goals_match = re.search(r"## Goals\n\n((?:-\s+.+\n?)+)", text)
        if goals_match:
            self.state.goals = [
                line.lstrip("- ").strip()
                for line in goals_match.group(1).strip().splitlines()
                if line.strip()
            ]

        tasks_match = re.search(r"## Current Tasks\n\n((?:-\s+.+\n?)+)", text)
        if tasks_match:
            self.state.current_tasks = [
                line.lstrip("- ").strip()
                for line in tasks_match.group(1).strip().splitlines()
                if line.strip()
            ]

    def _write_identity(self) -> None:
        self.ensure_dir()
        i = self.state.identity
        path = self.vessel_dir / self.FILE_IDENTITY
        path.write_text(
            "# Identity\n\n"
            f"Name: {i.name}\n"
            f"Designation: {i.designation}\n"
            f"Version: {i.version}\n"
            f"Domains: {', '.join(d.value for d in i.domains)}\n"
            f"Primary Domain: {i.primary_domain.value}\n",
            encoding="utf-8",
        )

    def _write_career(self) -> None:
        self.ensure_dir()
        c = self.state.career
        fences = "\n".join(f"- {f}" for f in c.fences_completed) or "- (none)"
        skills = "\n".join(f"- {s}" for s in c.skills_acquired) or "- (none)"
        path = self.vessel_dir / self.FILE_CAREER
        path.write_text(
            "# Career\n\n"
            f"Current Stage: {c.current_stage.value}\n"
            f"Tasks Completed: {c.total_tasks_completed}\n"
            f"Tasks Failed: {c.total_tasks_failed}\n"
            f"PRs Merged: {c.total_prs_merged}\n"
            f"Total Commits: {c.total_commits}\n"
            f"Sessions Completed: {c.sessions_completed}\n"
            f"Last Promoted: {c.last_promoted or '(never)'}\n"
            "\n## Fences Completed\n\n"
            f"{fences}\n"
            "\n## Skills Acquired\n\n"
            f"{skills}\n",
            encoding="utf-8",
        )

    def _write_worklog(self) -> None:
        self.ensure_dir()
        entries = []
        for e in self.state.worklog:
            entries.append(
                f"### {e.timestamp} | {e.action} | {e.outcome}\n\n"
                f"**Target:** {e.target}\n\n"
                f"{e.summary}\n"
            )
        path = self.vessel_dir / self.FILE_WORKLOG
        header = "# Worklog\n\n"
        if entries:
            body = "\n---\n\n".join(entries) + "\n"
        else:
            body = "No entries yet.\n"
        path.write_text(header + body, encoding="utf-8")

    def _write_state(self) -> None:
        self.ensure_dir()
        goals = "\n".join(f"- {g}" for g in self.state.goals) or "- (none)"
        tasks = "\n".join(f"- {t}" for t in self.state.current_tasks) or "- (none)"
        path = self.vessel_dir / self.FILE_STATE
        path.write_text(
            "# State\n\n"
            f"Last Updated: {self.state.last_updated or '(never)'}\n"
            "\n## Goals\n\n"
            f"{goals}\n"
            "\n## Current Tasks\n\n"
            f"{tasks}\n"
            "\n## Notes\n\n"
            f"{self.state.notes or '(none)'}\n",
            encoding="utf-8",
        )

    # -- reset --------------------------------------------------------------

    def reset(self) -> VesselState:
        """Reset vessel state to defaults and delete persisted files."""
        self._state = VesselState()
        for fname in (self.FILE_IDENTITY, self.FILE_CAREER,
                      self.FILE_WORKLOG, self.FILE_STATE):
            p = self.vessel_dir / fname
            if p.exists():
                p.unlink()
        return self._state
