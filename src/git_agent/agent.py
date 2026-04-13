"""
git_agent.agent — The Agent Brain.

This is the core autonomous agent that follows the cycle:
    Bootstrap → Observe → Plan → Execute → Communicate → Reflect

Design principles:
- **API-agnostic**: Uses dependency injection for LLM and GitHub clients.
- **Git-native**: All state is stored in Git repos (vessel repo, fleet repo).
- **Observable**: Every action is logged to the vessel worklog.
- **Resilient**: Handles failures gracefully and recovers state on restart.
"""

from __future__ import annotations

import abc
import asyncio
import concurrent.futures
import datetime
import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

from .config import AgentConfig, LLMProviderConfig
from .vessel import (
    Domain,
    GrowthStage,
    WorklogEntry,
    VesselManager,
    VesselState,
    check_promotion,
    next_stage,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocols (dependency injection interfaces)
# ---------------------------------------------------------------------------

class LLMProvider(Protocol):
    """Protocol for LLM providers — any API can implement this."""

    def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        """Generate a completion from a message list.

        Parameters
        ----------
        messages:
            List of ``{"role": ..., "content": ...}`` dicts.
        temperature:
            Override sampling temperature.
        max_tokens:
            Override max response tokens.

        Returns
        -------
        str
            The generated text.
        """
        ...

    async def acomplete(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> str:
        """Async version of :meth:`complete`."""
        ...


class GitHubClient(Protocol):
    """Protocol for GitHub API clients."""

    def get_repo(self, owner: str, repo: str) -> Dict[str, Any]:
        """Get repository metadata."""
        ...

    def fork_repo(self, owner: str, repo: str) -> Dict[str, Any]:
        """Fork a repository."""
        ...

    def create_branch(self, owner: str, repo: str, branch: str, from_branch: str = "main") -> Dict[str, Any]:
        """Create a new branch."""
        ...

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> Dict[str, Any]:
        """Create a pull request."""
        ...

    def create_or_update_file(
        self,
        owner: str,
        repo: str,
        path: str,
        content: str,
        message: str,
        branch: str,
        sha: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create or update a file in a repo."""
        ...

    def get_file(self, owner: str, repo: str, path: str, ref: Optional[str] = None) -> Dict[str, Any]:
        """Get file contents."""
        ...

    def list_issues(self, owner: str, repo: str, state: str = "open") -> List[Dict[str, Any]]:
        """List issues / PRs."""
        ...

    def get_file_contents(self, owner: str, repo: str, path: str) -> Optional[str]:
        """Get decoded file contents as string, or None if not found."""
        ...

    def list_commits(self, owner: str, repo: str, per_page: int = 10) -> List[Dict[str, Any]]:
        """List recent commits."""
        ...

    def push_files(
        self,
        owner: str,
        repo: str,
        branch: str,
        files: List[Dict[str, str]],
        message: str,
    ) -> Dict[str, Any]:
        """Push multiple files in a single commit."""
        ...

    def clone(self, url: str, path: Path, branch: Optional[str] = None) -> Path:
        """Clone a repo to a local path. Returns the path."""
        ...

    def get_bottles(self, owner: str, repo: str) -> List[Dict[str, Any]]:
        """List 'bottles' (messages) from a fleet repo."""
        ...

    def push_bottle(self, owner: str, repo: str, content: str, title: str = "") -> Dict[str, Any]:
        """Push a new bottle (message) to a fleet repo."""
        ...


# ---------------------------------------------------------------------------
# Task model
# ---------------------------------------------------------------------------

class TaskPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class Task:
    """A unit of work the agent can execute."""
    id: str
    description: str
    priority: TaskPriority = TaskPriority.MEDIUM
    repo: Optional[str] = None         # "owner/repo"
    action: str = "implement"          # implement, fix, review, document, refactor
    branch_name: Optional[str] = None
    context: str = ""                  # Additional context / instructions
    effort_estimate: str = "medium"    # low, medium, high
    impact_estimate: str = "medium"    # low, medium, high
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"            # pending, in_progress, completed, failed

    @property
    def score(self) -> float:
        """Priority score: higher = do first."""
        priority_map = {
            TaskPriority.CRITICAL: 10,
            TaskPriority.HIGH: 7,
            TaskPriority.MEDIUM: 4,
            TaskPriority.LOW: 2,
            TaskPriority.INFO: 1,
        }
        impact_map = {"high": 3, "medium": 2, "low": 1}
        effort_map = {"high": 1, "medium": 2, "low": 3}
        p = priority_map.get(self.priority, 4)
        imp = impact_map.get(self.impact_estimate, 2)
        eff = effort_map.get(self.effort_estimate, 2)
        return p * imp * eff


@dataclass
class Plan:
    """A prioritized plan of tasks."""
    tasks: List[Task] = field(default_factory=list)
    reasoning: str = ""
    created_at: str = ""

    def sort_by_score(self) -> None:
        """Sort tasks by priority score (highest first)."""
        self.tasks.sort(key=lambda t: t.score, reverse=True)


# ---------------------------------------------------------------------------
# Observation result
# ---------------------------------------------------------------------------

@dataclass
class Observation:
    """Snapshot of the fleet/world state."""
    bottles: List[Dict[str, Any]] = field(default_factory=list)
    open_tasks: List[Task] = field(default_factory=list)
    recent_commits: List[Dict[str, Any]] = field(default_factory=list)
    fleet_status: Dict[str, Any] = field(default_factory=dict)
    vessel_state: Optional[VesselState] = None
    notes: str = ""


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class Agent:
    """The core autonomous Git-Native Agent.

    The agent follows a lifecycle cycle:
        ``bootstrap → observe → plan → execute → communicate → reflect``

    Parameters
    ----------
    config:
        Agent configuration.
    llm:
        An LLM provider implementation.
    github:
        A GitHub API client implementation.
    vessel:
        Vessel state manager (optional; created from config if not given).
    """

    def __init__(
        self,
        config: AgentConfig,
        llm: LLMProvider,
        github: GitHubClient,
        vessel: Optional[VesselManager] = None,
    ) -> None:
        self.config = config
        self.llm = llm
        self.github = github
        self.vessel = vessel or VesselManager(config=config)
        self._observation: Optional[Observation] = None
        self._plan: Optional[Plan] = None
        self._session_start: Optional[str] = None
        self._logger = logging.getLogger(f"{__name__}.{self.config.vessel_repo or 'agent'}")

    # ===================================================================
    # Lifecycle methods
    # ===================================================================

    def bootstrap(self) -> None:
        """First-run setup: clone vessel repo, read state, introduce self.

        If the vessel repo already exists locally, just loads state.
        """
        self._session_start = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._logger.info("Bootstrapping agent %s …", self.config.vessel_repo or "(no vessel repo)")

        # Ensure vessel dir
        self.vessel.ensure_dir()

        # Clone if we have a remote vessel repo and it's not already cloned
        if self.config.vessel_repo and "/" in self.config.vessel_repo:
            owner, repo = self.config.vessel_repo.split("/", 1)
            vessel_path = self.vessel.vessel_dir
            if not any(vessel_path.iterdir()):
                try:
                    url = f"https://github.com/{owner}/{repo}.git"
                    self.github.clone(url, vessel_path)
                    self._logger.info("Cloned vessel repo from %s", url)
                except Exception as exc:
                    self._logger.warning("Could not clone vessel repo (will work locally): %s", exc)

        # Load state (or get defaults)
        state = self.vessel.load()

        # If fresh vessel, record introduction
        if not state.last_updated:
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self.vessel.add_worklog_entry(WorklogEntry(
                timestamp=now,
                action="bootstrapped",
                target=self.config.vessel_repo or "local",
                summary=f"Agent {state.identity.name} initialized for the first time.",
            ))

        self._logger.info(
            "Agent %s (stage: %s) ready.",
            state.identity.name,
            state.career.current_stage.value,
        )

    def observe(self) -> Observation:
        """Read fleet state: bottles, tasks, repos, recent commits."""
        self._logger.info("Observing fleet state …")
        obs = Observation()

        # Load vessel state
        obs.vessel_state = self.vessel.state

        # Read bottles from fleet repo (if configured)
        if self.config.fleet_org:
            try:
                obs.bottles = self.github.get_bottles(self.config.fleet_org, "fleet-msgs")
            except Exception as exc:
                self._logger.warning("Could not read bottles: %s", exc)

        # Read tasks from TASKS.md in relevant repos
        repos_to_check = self._get_repos_to_observe()
        for repo_full in repos_to_check:
            if "/" not in repo_full:
                continue
            owner, repo = repo_full.split("/", 1)
            try:
                tasks_content = self.github.get_file_contents(owner, repo, "TASKS.md")
                if tasks_content:
                    parsed = self._parse_tasks_md(tasks_content, repo_full)
                    obs.open_tasks.extend(parsed)
            except Exception as exc:
                self._logger.debug("No TASKS.md in %s: %s", repo_full, exc)

            # Get recent commits
            try:
                commits = self.github.list_commits(owner, repo, per_page=5)
                obs.recent_commits.extend(commits)
            except Exception as exc:
                self._logger.debug("Could not list commits for %s: %s", repo_full, exc)

        # Check for stale vessel state
        if self.vessel.is_stale():
            obs.notes += "Vessel state is stale (>24h). Recommend full re-observe.\n"

        self._observation = obs
        self._logger.info(
            "Observation complete: %d bottles, %d tasks, %d commits.",
            len(obs.bottles), len(obs.open_tasks), len(obs.recent_commits),
        )
        return obs

    def plan(self) -> Plan:
        """Analyze observations and generate a prioritized task plan.

        Uses the LLM to reason about priorities and potentially discover
        new tasks not explicitly listed.
        """
        self._logger.info("Planning …")

        # Gather tasks from observation
        tasks: List[Task] = []
        if self._observation:
            tasks = list(self._observation.open_tasks)

        # If we have no tasks from observation, ask the LLM
        if not tasks:
            tasks = self._ask_llm_for_tasks()

        plan = Plan(
            tasks=tasks,
            reasoning="",
            created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )

        # Ask LLM to help prioritize
        if tasks and self._observation:
            try:
                reasoning = self._ask_llm_to_prioritize(tasks, self._observation)
                plan.reasoning = reasoning
            except Exception as exc:
                self._logger.warning("LLM prioritization failed (%s), using defaults.", exc)

        plan.sort_by_score()
        self._plan = plan
        self._logger.info(
            "Plan created: %d tasks. Top priority: %s",
            len(plan.tasks),
            plan.tasks[0].description[:60] if plan.tasks else "(none)",
        )
        return plan

    def execute_task(self, task: Task) -> bool:
        """Execute a single task: fork, branch, code, push PR.

        Returns ``True`` on success, ``False`` on failure.
        """
        self._logger.info("Executing task: %s", task.description[:80])
        task.status = "in_progress"
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        try:
            if not task.repo or "/" not in task.repo:
                self._logger.warning("Task %s has no valid repo, skipping.", task.id)
                task.status = "failed"
                self.vessel.record_task_completion(success=False)
                self.vessel.add_worklog_entry(WorklogEntry(
                    timestamp=now, action="execute", target=task.id,
                    summary=f"Failed: no valid repo for task '{task.description}'",
                    outcome="failure",
                ))
                return False

            owner, repo = task.repo.split("/", 1)

            # 1. Generate implementation with LLM
            implementation = self._ask_llm_to_implement(task)
            if not implementation:
                self._logger.warning("LLM could not generate implementation for %s", task.id)
                task.status = "failed"
                self.vessel.record_task_completion(success=False)
                return False

            # 2. Create a branch
            branch_name = task.branch_name or self._generate_branch_name(task)
            self.github.create_branch(owner, repo, branch_name)

            # 3. Push files
            files = self._parse_implementation_to_files(implementation, task)
            if files:
                commit_msg = f"feat: {task.description}"
                self.github.push_files(owner, repo, branch_name, files, commit_msg)
                self.vessel.state.career.total_commits += len(files)

            # 4. Create PR
            pr_body = f"## Task: {task.description}\n\n{task.context}\n\n{implementation.get('summary', '')}"
            pr = self.github.create_pull_request(
                owner, repo,
                title=f"[agent] {task.description[:80]}",
                body=pr_body,
                head=branch_name,
            )

            task.status = "completed"
            task.metadata["pr_number"] = pr.get("number")
            task.metadata["pr_url"] = pr.get("html_url")
            self.vessel.record_task_completion(success=True)
            self.vessel.add_worklog_entry(WorklogEntry(
                timestamp=now, action="PR opened",
                target=f"{owner}/{repo}#{pr.get('number', '?')}",
                summary=f"Completed: {task.description}",
                outcome="success",
            ))
            return True

        except Exception as exc:
            self._logger.error("Task %s failed: %s", task.id, exc)
            task.status = "failed"
            self.vessel.record_task_completion(success=False)
            self.vessel.add_worklog_entry(WorklogEntry(
                timestamp=now, action="execute", target=task.id,
                summary=f"Failed: {exc}",
                outcome="failure",
            ))
            return False

    def execute_parallel(self, tasks: List[Task], max_workers: Optional[int] = None) -> Dict[str, bool]:
        """Execute multiple tasks in parallel using a thread pool.

        Returns a dict mapping task.id → success (bool).
        """
        workers = max_workers or self.config.max_parallel_agents
        self._logger.info("Executing %d tasks with %d workers", len(tasks), workers)

        # Limit to configured max
        tasks_to_run = tasks[:workers]

        results: Dict[str, bool] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(self.execute_task, t): t
                for t in tasks_to_run
            }
            for future in concurrent.futures.as_completed(future_map):
                task = future_map[future]
                try:
                    results[task.id] = future.result()
                except Exception as exc:
                    self._logger.error("Parallel task %s crashed: %s", task.id, exc)
                    results[task.id] = False

        return results

    def push_bottle(self, content: str, title: str = "") -> Dict[str, Any]:
        """Send a message to the fleet via a 'bottle'."""
        if not self.config.fleet_org:
            self._logger.warning("No fleet_org configured, cannot push bottle.")
            return {"status": "skipped", "reason": "no fleet_org"}

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        agent_name = self.vessel.state.identity.name
        bottle_title = title or f"Message from {agent_name}"
        bottle_content = (
            f"**From:** {agent_name}\n"
            f"**Time:** {now}\n"
            f"**Stage:** {self.vessel.state.career.current_stage.value}\n\n"
            f"{content}\n"
        )

        try:
            result = self.github.push_bottle(self.config.fleet_org, "fleet-msgs", bottle_content, bottle_title)
            self.vessel.add_worklog_entry(WorklogEntry(
                timestamp=now, action="bottle sent",
                target=self.config.fleet_org,
                summary=f"Sent bottle: {bottle_title[:60]}",
            ))
            return result
        except Exception as exc:
            self._logger.error("Failed to push bottle: %s", exc)
            return {"status": "error", "reason": str(exc)}

    def update_vessel(self) -> None:
        """Persist current vessel state to disk / repo."""
        self._logger.info("Updating vessel state …")
        self.vessel.save()

    def reflect(self) -> str:
        """End-of-session reflection: summarize what was done, plan next steps.

        Returns a reflection summary string.
        """
        self._logger.info("Reflecting on session …")
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        state = self.vessel.state

        # Update session count
        state.career.sessions_completed += 1

        # Build reflection
        completed = [t for t in (self._plan.tasks if self._plan else []) if t.status == "completed"]
        failed = [t for t in (self._plan.tasks if self._plan else []) if t.status == "failed"]
        pending = [t for t in (self._plan.tasks if self._plan else []) if t.status == "pending"]

        reflection = (
            f"# Session Reflection\n\n"
            f"**Time:** {now}\n"
            f"**Stage:** {state.career.current_stage.value}\n"
            f"**Tasks completed:** {len(completed)}\n"
            f"**Tasks failed:** {len(failed)}\n"
            f"**Tasks remaining:** {len(pending)}\n"
            f"**Career total completed:** {state.career.total_tasks_completed}\n\n"
        )

        if completed:
            reflection += "## Completed\n\n"
            for t in completed:
                pr_url = t.metadata.get("pr_url", "")
                reflection += f"- {t.description}"
                if pr_url:
                    reflection += f" ([PR]({pr_url}))"
                reflection += "\n"

        if failed:
            reflection += "\n## Failed\n\n"
            for t in failed:
                reflection += f"- {t.description}\n"

        if pending:
            reflection += "\n## Next Session\n\n"
            for t in pending[:5]:
                reflection += f"- [ ] {t.description}\n"

        # Check for promotion
        promotion = check_promotion(state.career.current_stage, state.career.total_tasks_completed)
        if promotion:
            reflection += f"\n🎉 **Promotion eligible:** {promotion.value}\n"

        self.vessel.add_worklog_entry(WorklogEntry(
            timestamp=now, action="session_end",
            target="self",
            summary=f"Session complete. {len(completed)} done, {len(failed)} failed.",
        ))

        self.vessel.save()
        self._logger.info("Reflection complete.")
        return reflection

    def run(self, max_tasks: int = 10) -> str:
        """Main agent loop: observe → plan → execute → communicate → reflect.

        This is the single entry point for autonomous operation.

        Parameters
        ----------
        max_tasks:
            Maximum number of tasks to execute in this run.

        Returns
        -------
        str
            Session reflection summary.
        """
        self._logger.info("=== Agent run starting ===")
        self.bootstrap()

        # Observe
        obs = self.observe()

        # Plan
        plan = self.plan()

        # Execute (up to max_tasks)
        tasks_to_execute = plan.tasks[:max_tasks]
        for task in tasks_to_execute:
            self.execute_task(task)

        # Communicate — push a status bottle
        completed_count = sum(1 for t in tasks_to_execute if t.status == "completed")
        self.push_bottle(
            f"Session complete. Executed {len(tasks_to_execute)} tasks, "
            f"{completed_count} successful. Stage: {self.vessel.state.career.current_stage.value}.",
            title=f"Status update from {self.vessel.state.identity.name}",
        )

        # Update vessel
        self.update_vessel()

        # Reflect
        reflection = self.reflect()

        self._logger.info("=== Agent run complete ===")
        return reflection

    # ===================================================================
    # Private helpers
    # ===================================================================

    def _get_repos_to_observe(self) -> List[str]:
        """Determine which repos to observe based on config and state."""
        repos: List[str] = []
        if self.config.vessel_repo and "/" in self.config.vessel_repo:
            repos.append(self.config.vessel_repo)
        # Add repos from current tasks
        if self.vessel.state.current_tasks:
            for t in self.vessel.state.current_tasks:
                if "/" in t:
                    repos.append(t)
        return list(dict.fromkeys(repos))  # deduplicate preserving order

    def _parse_tasks_md(self, content: str, repo: str) -> List[Task]:
        """Parse a TASKS.md file into Task objects.

        Expected format:
            - [ ] Task description | priority:high | effort:low
            - [x] Already done task
        """
        tasks: List[Task] = []
        task_counter = 0
        for line in content.splitlines():
            line = line.strip()
            if not line.startswith("- [ ]") and not line.startswith("- [x]"):
                continue
            # Skip completed tasks
            if line.startswith("- [x]"):
                continue

            # Extract description (everything after the checkbox)
            desc_match = re.match(r"- \[ \]\s*(.+)", line)
            if not desc_match:
                continue

            full_desc = desc_match.group(1).strip()

            # Parse metadata from description
            priority = TaskPriority.MEDIUM
            effort = "medium"
            impact = "medium"
            action = "implement"

            if "| priority:critical" in full_desc.lower():
                priority = TaskPriority.CRITICAL
            elif "| priority:high" in full_desc.lower():
                priority = TaskPriority.HIGH
            elif "| priority:low" in full_desc.lower():
                priority = TaskPriority.LOW
            elif "| priority:info" in full_desc.lower():
                priority = TaskPriority.INFO

            if "| effort:low" in full_desc.lower():
                effort = "low"
            elif "| effort:high" in full_desc.lower():
                effort = "high"

            if "| impact:low" in full_desc.lower():
                impact = "low"
            elif "| impact:high" in full_desc.lower():
                impact = "high"

            if "| action:" in full_desc.lower():
                m = re.search(r"\|\s*action:(\w+)", full_desc.lower())
                if m:
                    action = m.group(1)

            # Clean description (remove metadata)
            clean_desc = re.split(r"\|", full_desc)[0].strip()

            task_counter += 1
            tasks.append(Task(
                id=f"{repo}#task-{task_counter}",
                description=clean_desc,
                priority=priority,
                repo=repo,
                action=action,
                effort_estimate=effort,
                impact_estimate=impact,
            ))
        return tasks

    def _generate_branch_name(self, task: Task) -> str:
        """Generate a safe branch name from a task description."""
        slug = re.sub(r"[^a-z0-9]+", "-", task.description.lower())[:40].strip("-")
        return f"agent/{slug}"

    def _ask_llm_for_tasks(self) -> List[Task]:
        """Ask the LLM to suggest tasks based on the agent's current context."""
        try:
            response = self.llm.complete([
                {"role": "system", "content": (
                    "You are a git-native autonomous agent. Based on your current state "
                    "and the fleet context, suggest concrete tasks to work on. "
                    "Return one task per line in format: DESCRIPTION | priority:HIGH|LOW|MEDIUM | effort:LOW|MEDIUM|HIGH"
                )},
                {"role": "user", "content": (
                    f"Agent stage: {self.vessel.state.career.current_stage.value}\n"
                    f"Current goals: {', '.join(self.vessel.state.goals) or '(none)'}\n"
                    f"Domains: {', '.join(d.value for d in self.vessel.state.identity.domains)}\n"
                    "Suggest 3-5 tasks."
                )},
            ])
            return self._parse_tasks_md(response, "__llm_suggested__")
        except Exception as exc:
            self._logger.warning("LLM task generation failed: %s", exc)
            return []

    def _ask_llm_to_prioritize(self, tasks: List[Task], obs: Observation) -> str:
        """Ask the LLM to reason about task priorities."""
        task_descriptions = "\n".join(
            f"- [{t.priority.value}] {t.description} (effort: {t.effort_estimate}, impact: {t.impact_estimate})"
            for t in tasks
        )
        response = self.llm.complete([
            {"role": "system", "content": (
                "You are a task prioritization engine. Analyze the tasks and provide "
                "brief reasoning for the priority order. Consider impact, effort, "
                "dependencies, and current agent stage. Be concise."
            )},
            {"role": "user", "content": (
                f"Agent stage: {obs.vessel_state.career.current_stage.value if obs.vessel_state else 'unknown'}\n"
                f"Recent commits: {len(obs.recent_commits)}\n"
                f"Open bottles: {len(obs.bottles)}\n\n"
                f"Tasks:\n{task_descriptions}\n\n"
                "Provide priority reasoning in 2-3 sentences."
            )},
        ])
        return response

    def _ask_llm_to_implement(self, task: Task) -> Optional[Dict[str, Any]]:
        """Ask the LLM to generate implementation details for a task."""
        try:
            response = self.llm.complete([
                {"role": "system", "content": (
                    "You are an expert software engineer. Given a task description, "
                    "generate the implementation. Return JSON with keys: "
                    "files (list of {path, content}), summary (string)."
                )},
                {"role": "user", "content": (
                    f"Task: {task.description}\n"
                    f"Action: {task.action}\n"
                    f"Context: {task.context}\n"
                    f"Repo: {task.repo}\n\n"
                    "Generate implementation as JSON."
                )},
            ])
            # Try to parse JSON from response
            import json
            # Extract JSON block from markdown if present
            json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))
            return json.loads(response)
        except Exception as exc:
            self._logger.warning("LLM implementation failed: %s", exc)
            return None

    def _parse_implementation_to_files(
        self, implementation: Dict[str, Any], task: Task
    ) -> List[Dict[str, str]]:
        """Parse LLM implementation output into file dicts for the GitHub API."""
        files: List[Dict[str, str]] = []
        raw_files = implementation.get("files", [])
        if isinstance(raw_files, list):
            for f in raw_files:
                if isinstance(f, dict) and "path" in f and "content" in f:
                    files.append({"path": f["path"], "content": f["content"]})
        return files
