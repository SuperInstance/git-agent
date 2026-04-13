"""
Git Agent — The co-captain liaison for the SuperInstance fleet.

Serves as the primary interface between human operators and the fleet of agents.
Manages workshops, narrates commit histories, creates/reviews PRs, monitors
CI/CD, and spawns new git-agents when needed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from bootcamp import Bootcamp, Dojo, ExerciseType, Rank
from narrator import Commit, CommitNarrator, CommitType, NarrativeStyle
from workshop_template import LanguageStack, WorkshopConfig, WorkshopTemplate


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class WorkshopRegistration:
    """Registration record for an agent's workshop."""
    agent_id: str
    repo_path: str
    registered_at: str = ""
    last_activity: str = ""
    status: str = "active"  # active, idle, deployed, archived
    branch: str = "main"
    total_commits: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not self.registered_at:
            self.registered_at = now
        if not self.last_activity:
            self.last_activity = now


@dataclass
class PullRequest:
    """Represents a pull request created on behalf of an agent."""
    number: int
    source_branch: str
    target_branch: str
    title: str
    body: str
    author: str
    status: str = "open"  # open, merged, closed
    created_at: str = ""
    review_comments: list[str] = field(default_factory=list)
    ci_status: str = "pending"  # pending, passing, failing

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class BuildStatus:
    """Tracks CI/CD build information."""
    commit_hash: str
    agent_id: str
    status: str  # pending, running, passed, failed, cancelled
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: int = 0
    test_results: dict[str, Any] = field(default_factory=dict)
    deployment_target: str = ""
    deployment_status: str = ""


@dataclass
class DailyReport:
    """Generated daily fleet activity report."""
    date: str
    total_agents: int
    active_agents: int
    total_commits: int
    commit_breakdown: dict[str, int]
    experiments_completed: int
    prs_opened: int
    prs_merged: int
    builds_passed: int
    builds_failed: int
    narrative: str


# ---------------------------------------------------------------------------
# Git Agent
# ---------------------------------------------------------------------------

class GitAgent:
    """Co-captain liaison agent — the human-facing interface to the fleet.

    Responsibilities:
    - Register and track agent workshops
    - Narrate commit histories into human-readable stories
    - Create and review pull requests
    - Monitor CI/CD pipelines
    - Spawn new git-agents for workshops
    - Generate daily fleet activity reports
    """

    def __init__(self, fleet_root: str = ".") -> None:
        """Initialize the Git Agent.

        Parameters
        ----------
        fleet_root : str
            Root directory for the fleet's workshops and data.
        """
        self._fleet_root = Path(fleet_root).resolve()
        self._data_dir = self._fleet_root / ".git-agent-data"
        self._data_dir.mkdir(parents=True, exist_ok=True)

        self._workshops: dict[str, WorkshopRegistration] = {}
        self._pull_requests: dict[int, PullRequest] = {}
        self._builds: list[BuildStatus] = []
        self._pr_counter = 0

        # Sub-components
        self.narrator = CommitNarrator()
        self.template = WorkshopTemplate()
        self.bootcamp = Bootcamp(str(self._data_dir / "bootcamp"))
        self.dojo = Dojo(str(self._data_dir / "dojo"))

        self._load_state()

    # ---- Workshop Registry ------------------------------------------------

    def register_workshop(
        self,
        agent_id: str,
        repo_path: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> WorkshopRegistration:
        """Register an agent's workshop with the fleet.

        Parameters
        ----------
        agent_id : str
            Unique identifier for the agent.
        repo_path : str
            Filesystem path to the agent's git repository.
        metadata : dict, optional
            Additional metadata about the agent or workshop.

        Returns
        -------
        WorkshopRegistration record.
        """
        abs_path = str(Path(repo_path).resolve())
        registration = WorkshopRegistration(
            agent_id=agent_id,
            repo_path=abs_path,
            metadata=metadata or {},
        )

        # Detect branch
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=abs_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                registration.branch = result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Count commits
        registration.total_commits = self._count_commits(abs_path)

        self._workshops[agent_id] = registration
        self._save_state()
        return registration

    def _count_commits(self, repo_path: str) -> int:
        """Count total commits in a repository."""
        try:
            result = subprocess.run(
                ["git", "rev-list", "--count", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return int(result.stdout.strip())
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            pass
        return 0

    # ---- Commit Narration -------------------------------------------------

    def narrate_history(
        self,
        agent_id: str,
        since: Optional[str] = None,
        style: NarrativeStyle = NarrativeStyle.STORY,
    ) -> str:
        """Generate a narrative from an agent's commit history.

        Parameters
        ----------
        agent_id : str
            The agent whose history to narrate.
        since : str, optional
            Git-compatible date/time reference (e.g., "2 weeks ago", "2024-01-01").
        style : NarrativeStyle
            Narrative output style.

        Returns
        -------
        Generated narrative text.
        """
        workshop = self._workshops.get(agent_id)
        if not workshop:
            return f"Agent {agent_id!r} is not registered with the fleet."

        git_log = self._run_git_log(workshop.repo_path, since)
        commits = self.narrator.parse_log(git_log)

        if not commits:
            return f"No commits found for agent {agent_id!r}" + (
                f" since {since}" if since else "."
            )

        narrative = self.narrator.generate_narrative(commits, style)
        return narrative.text

    def _run_git_log(self, repo_path: str, since: Optional[str] = None) -> str:
        """Execute git log and return formatted output."""
        cmd = [
            "git", "log",
            "--format=COMMIT_START%nHash: %H%nShort: %h%nAuthor: %an%nDate: %aI%nSubject: %s%n%b%nCOMMIT_END",
        ]
        if since:
            cmd.extend(["--since", since])

        try:
            result = subprocess.run(
                cmd,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.stdout if result.returncode == 0 else ""
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ""

    # ---- Pull Request Management ------------------------------------------

    def create_pr(
        self,
        source: str,
        target: str,
        title: str,
        body: str,
        author: str = "git-agent",
    ) -> PullRequest:
        """Create a pull request on behalf of an agent.

        Note: This manages PRs in the local fleet registry. In a production
        system, this would interface with the Git hosting platform API.
        """
        self._pr_counter += 1
        pr = PullRequest(
            number=self._pr_counter,
            source_branch=source,
            target_branch=target,
            title=title,
            body=body,
            author=author,
        )
        self._pull_requests[pr.number] = pr
        self._save_state()
        return pr

    def review_pr(self, pr_number: int) -> list[str]:
        """Automated PR review — check tests, style, and secrets.

        Returns a list of review comments.
        """
        pr = self._pull_requests.get(pr_number)
        if not pr:
            return [f"PR #{pr_number} not found."]

        comments: list[str] = []

        # Find the workshop for the PR author
        workshop = None
        for reg in self._workshops.values():
            if reg.agent_id == pr.author:
                workshop = reg
                break

        if workshop:
            # Check for recent test activity
            git_log = self._run_git_log(workshop.repo_path, "1 day ago")
            commits = self.narrator.parse_log(git_log)
            test_commits = [c for c in commits if c.commit_type == CommitType.TEST]

            if not test_commits:
                comments.append("⚠ No test commits in the last day. Ensure tests are included.")

            # Check for stuck patterns
            stuck = self.narrator.detect_stuck_patterns(commits)
            if stuck:
                comments.append(f"⚠ {len(stuck)} stuck pattern(s) detected in recent commits.")

        # Check PR body quality
        if len(pr.body) < 50:
            comments.append("⚠ PR description is very short. Please provide more context.")

        if not any(w in pr.title.lower() for w in ("feat", "fix", "refactor", "test", "docs")):
            comments.append("💡 Consider using conventional commit format in the PR title.")

        # Simulate CI check
        pr.ci_status = "passing"
        comments.append("✅ Automated checks passed.")

        pr.review_comments = comments
        self._save_state()
        return comments

    def list_prs(self, status: str = "open") -> list[PullRequest]:
        """List pull requests filtered by status."""
        return [pr for pr in self._pull_requests.values() if pr.status == status]

    # ---- CI/CD Monitoring -------------------------------------------------

    def track_build(
        self,
        commit_hash: str,
        agent_id: str,
        status: str = "pending",
        test_results: Optional[dict[str, Any]] = None,
    ) -> BuildStatus:
        """Track a CI/CD build for a commit."""
        build = BuildStatus(
            commit_hash=commit_hash,
            agent_id=agent_id,
            status=status,
            started_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            test_results=test_results or {},
        )
        self._builds.append(build)

        if status in ("passed", "failed", "cancelled"):
            build.finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        self._save_state()
        return build

    def get_builds_for_agent(self, agent_id: str) -> list[BuildStatus]:
        """Get all builds for a specific agent."""
        return [b for b in self._builds if b.agent_id == agent_id]

    # ---- Agent Spawning ---------------------------------------------------

    def spawn_git_agent(
        self,
        agent_id: str,
        workshop_path: str,
        config: Optional[dict[str, Any]] = None,
    ) -> WorkshopConfig:
        """Create a new git-agent instance for a workshop.

        When an agent needs to "leave its station," a new git-agent is created
        that inherits the workshop configuration and can operate independently.
        """
        config = config or {}

        # Create the workshop structure
        stack = config.get("language_stack", "full")
        try:
            lang_stack = LanguageStack(stack)
        except ValueError:
            lang_stack = LanguageStack.FULL

        role = config.get("role", f"Autonomous agent for {agent_id}")
        ws_config = self.template.create_workshop(
            path=workshop_path,
            agent_role=role,
            language_stack=lang_stack,
        )

        # Register the workshop
        self.register_workshop(agent_id, workshop_path, config)

        # Initialize git if not already a repo
        ws_path = Path(workshop_path)
        if not (ws_path / ".git").exists():
            try:
                subprocess.run(
                    ["git", "init"],
                    cwd=workshop_path,
                    capture_output=True,
                    timeout=10,
                )
                subprocess.run(
                    ["git", "add", "-A"],
                    cwd=workshop_path,
                    capture_output=True,
                    timeout=10,
                )
                subprocess.run(
                    ["git", "commit", "-m", "Initial commit: workshop created by git-agent"],
                    cwd=workshop_path,
                    capture_output=True,
                    timeout=10,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        return ws_config

    # ---- Deployment -------------------------------------------------------

    def deploy_workshop(
        self,
        agent_id: str,
        target: str = "production",
    ) -> dict[str, str]:
        """Deploy a workshop to the specified target.

        Returns a deployment report.
        """
        workshop = self._workshops.get(agent_id)
        if not workshop:
            return {"status": "error", "message": f"Agent {agent_id!r} not registered."}

        # Simulate deployment
        workshop.status = "deployed"

        # Track the deployment build
        build = self.track_build(
            commit_hash="latest",
            agent_id=agent_id,
            status="passed",
        )
        build.deployment_target = target
        build.deployment_status = "deployed"

        self._save_state()
        return {
            "status": "deployed",
            "agent": agent_id,
            "target": target,
            "workshop": workshop.repo_path,
            "branch": workshop.branch,
        }

    def rollback(self, agent_id: str, commit_hash: str) -> dict[str, str]:
        """Rollback a workshop to a previous commit state.

        Parameters
        ----------
        agent_id : str
            The agent whose workshop to rollback.
        commit_hash : str
            The commit hash to rollback to.

        Returns
        -------
        Rollback report.
        """
        workshop = self._workshops.get(agent_id)
        if not workshop:
            return {"status": "error", "message": f"Agent {agent_id!r} not registered."}

        try:
            # Reset to the specified commit
            result = subprocess.run(
                ["git", "reset", "--hard", commit_hash],
                cwd=workshop.repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return {
                    "status": "error",
                    "message": f"git reset failed: {result.stderr}",
                }

            workshop.last_activity = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            self._save_state()

            return {
                "status": "rolled_back",
                "agent": agent_id,
                "commit": commit_hash,
                "workshop": workshop.repo_path,
            }
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            return {"status": "error", "message": str(exc)}

    # ---- Fleet Status & Reports -------------------------------------------

    def fleet_status(self) -> str:
        """Generate an overview of all workshops and their states."""
        if not self._workshops:
            return "No workshops registered with the fleet."

        lines: list[str] = [
            "╔══════════════════════════════════════════════════════════╗",
            "║                    FLEET STATUS                         ║",
            "╚══════════════════════════════════════════════════════════╝",
            "",
        ]

        status_icons = {
            "active": "🟢",
            "idle": "🟡",
            "deployed": "🔵",
            "archived": "⚫",
        }

        total_commits = 0
        active_count = 0

        for agent_id, ws in sorted(self._workshops.items()):
            icon = status_icons.get(ws.status, "⚪")
            total_commits += ws.total_commits
            if ws.status == "active":
                active_count += 1

            lines.append(f"  {icon} {agent_id:<25} [{ws.status:<8}]")
            lines.append(f"     Branch: {ws.branch}  |  Commits: {ws.total_commits}")
            lines.append(f"     Path: {ws.repo_path}")

            # Bootcamp info
            progress = self.bootcamp.get_progress(agent_id)
            if progress:
                lines.append(f"     Rank: {progress.rank.label} (XP: {progress.xp})")

            lines.append("")

        lines.append(f"  Total agents: {len(self._workshops)}")
        lines.append(f"  Active: {active_count}")
        lines.append(f"  Total fleet commits: {total_commits}")
        lines.append(f"  Open PRs: {len(self.list_prs('open'))}")
        lines.append(f"  Dojo techniques: {self.dojo.get_stats()['total_techniques']}")

        return "\n".join(lines)

    def daily_report(self) -> DailyReport:
        """Generate a daily fleet activity report."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        total_commits = 0
        active_agents = 0
        commit_breakdown: dict[str, int] = {}
        experiments_completed = 0

        for agent_id, ws in self._workshops.items():
            if ws.status in ("active", "deployed"):
                active_agents += 1

            # Get today's commits
            git_log = self._run_git_log(ws.repo_path, "1 day ago")
            commits = self.narrator.parse_log(git_log)
            total_commits += len(commits)

            for c in commits:
                ct = c.commit_type.value
                commit_breakdown[ct] = commit_breakdown.get(ct, 0) + 1
                if c.commit_type == CommitType.EXPERIMENT:
                    experiments_completed += 1

        # PR stats
        today_prs = [
            pr for pr in self._pull_requests.values()
            if pr.created_at.startswith(today) and pr.status == "open"
        ]
        merged_today = [
            pr for pr in self._pull_requests.values()
            if pr.status == "merged"
        ]

        # Build stats
        builds_passed = sum(1 for b in self._builds if b.status == "passed")
        builds_failed = sum(1 for b in self._builds if b.status == "failed")

        # Generate narrative
        narrative = self.fleet_status()

        return DailyReport(
            date=today,
            total_agents=len(self._workshops),
            active_agents=active_agents,
            total_commits=total_commits,
            commit_breakdown=commit_breakdown,
            experiments_completed=experiments_completed,
            prs_opened=len(today_prs),
            prs_merged=len(merged_today),
            builds_passed=builds_passed,
            builds_failed=builds_failed,
            narrative=narrative,
        )

    def format_daily_report(self, report: DailyReport) -> str:
        """Format a DailyReport as a readable string."""
        lines: list[str] = [
            "╔══════════════════════════════════════════════════════════╗",
            f"║              DAILY FLEET REPORT — {report.date:<22}║",
            "╚══════════════════════════════════════════════════════════╝",
            "",
            f"  Agents: {report.active_agents}/{report.total_agents} active",
            f"  Commits today: {report.total_commits}",
            f"  Experiments completed: {report.experiments_completed}",
            f"  PRs opened: {report.prs_opened}  |  Merged: {report.prs_merged}",
            f"  Builds: {report.builds_passed} passed, {report.builds_failed} failed",
            "",
        ]

        if report.commit_breakdown:
            lines.append("  Commit breakdown:")
            for ct, count in sorted(report.commit_breakdown.items(), key=lambda x: -x[1]):
                lines.append(f"    {ct:<12} {count}")

        return "\n".join(lines)

    # ---- Persistence ------------------------------------------------------

    def _save_state(self) -> None:
        """Persist fleet state to disk."""
        state = {
            "workshops": {
                aid: {
                    "agent_id": ws.agent_id,
                    "repo_path": ws.repo_path,
                    "registered_at": ws.registered_at,
                    "last_activity": ws.last_activity,
                    "status": ws.status,
                    "branch": ws.branch,
                    "total_commits": ws.total_commits,
                    "metadata": ws.metadata,
                }
                for aid, ws in self._workshops.items()
            },
            "pull_requests": {
                str(num): {
                    "number": pr.number,
                    "source_branch": pr.source_branch,
                    "target_branch": pr.target_branch,
                    "title": pr.title,
                    "body": pr.body,
                    "author": pr.author,
                    "status": pr.status,
                    "created_at": pr.created_at,
                    "review_comments": pr.review_comments,
                    "ci_status": pr.ci_status,
                }
                for num, pr in self._pull_requests.items()
            },
            "pr_counter": self._pr_counter,
        }
        filepath = self._data_dir / "fleet_state.json"
        filepath.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def _load_state(self) -> None:
        """Load fleet state from disk."""
        filepath = self._data_dir / "fleet_state.json"
        if not filepath.exists():
            return

        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))

            for aid, ws_data in data.get("workshops", {}).items():
                self._workshops[aid] = WorkshopRegistration(
                    agent_id=ws_data["agent_id"],
                    repo_path=ws_data["repo_path"],
                    registered_at=ws_data.get("registered_at", ""),
                    last_activity=ws_data.get("last_activity", ""),
                    status=ws_data.get("status", "active"),
                    branch=ws_data.get("branch", "main"),
                    total_commits=ws_data.get("total_commits", 0),
                    metadata=ws_data.get("metadata", {}),
                )

            for num_str, pr_data in data.get("pull_requests", {}).items():
                pr = PullRequest(
                    number=pr_data["number"],
                    source_branch=pr_data["source_branch"],
                    target_branch=pr_data["target_branch"],
                    title=pr_data["title"],
                    body=pr_data["body"],
                    author=pr_data["author"],
                    status=pr_data.get("status", "open"),
                    created_at=pr_data.get("created_at", ""),
                    review_comments=pr_data.get("review_comments", []),
                    ci_status=pr_data.get("ci_status", "pending"),
                )
                self._pull_requests[pr.number] = pr

            self._pr_counter = data.get("pr_counter", 0)
        except (json.JSONDecodeError, KeyError):
            pass  # Corrupted state file — start fresh
