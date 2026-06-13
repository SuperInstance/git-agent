"""
git_agent.fleet.planner — Task planning and scoring.

Scores tasks by priority × impact ÷ effort, matches tasks to agent
capabilities, detects dependencies, and generates execution order.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from ..agent import Plan, Task, TaskPriority
from .reader import FleetTask

logger = logging.getLogger(__name__)


# Scoring constants
PRIORITY_WEIGHTS = {
    TaskPriority.CRITICAL: 10.0,
    TaskPriority.HIGH: 7.0,
    TaskPriority.MEDIUM: 4.0,
    TaskPriority.LOW: 2.0,
    TaskPriority.INFO: 1.0,
}

IMPACT_WEIGHTS = {
    "high": 3.0,
    "medium": 2.0,
    "low": 1.0,
}

EFFORT_WEIGHTS = {
    "high": 1.0,
    "medium": 2.0,
    "low": 3.0,
}

SKILL_KEYWORDS = {
    "python": {"python", "py", "pip", "pytest"},
    "javascript": {"javascript", "js", "node", "npm", "typescript", "ts"},
    "rust": {"rust", "cargo", "rustc"},
    "devops": {"docker", "kubernetes", "k8s", "ci", "cd", "terraform", "ansible"},
    "frontend": {"react", "vue", "angular", "css", "html", "tailwind"},
    "backend": {"api", "rest", "graphql", "database", "sql"},
    "docs": {"readme", "documentation", "docs", "md"},
    "testing": {"test", "pytest", "jest", "unit test", "integration test"},
}


@dataclass
class ScoredTask:
    """A task with its computed score and metadata."""
    task: FleetTask
    score: float
    skill_match: float = 0.0
    dependencies: List[str] = field(default_factory=list)
    blocked_by: List[str] = field(default_factory=list)
    execution_order: int = 0


@dataclass
class AgentCapabilities:
    """An agent's capabilities for task matching."""
    name: str
    skills: List[str] = field(default_factory=list)
    domains: List[str] = field(default_factory=list)
    max_concurrent: int = 4
    current_load: int = 0

    @property
    def available_slots(self) -> int:
        return max(0, self.max_concurrent - self.current_load)


class FleetPlanner:
    """Task planning and scoring engine.

    Parameters
    ----------
    agent_skills:
        Skills this agent possesses.
    agent_name:
        Name of the agent (for workload tracking).
    max_concurrent:
        Maximum number of concurrent tasks.
    """

    def __init__(
        self,
        agent_skills: Optional[List[str]] = None,
        agent_name: str = "agent",
        max_concurrent: int = 4,
    ) -> None:
        self.agent_capabilities = AgentCapabilities(
            name=agent_name,
            skills=agent_skills or [],
            max_concurrent=max_concurrent,
        )

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score_task(self, task: FleetTask) -> float:
        """Score a task by priority × impact × effort.

        Low-effort tasks get a higher effort multiplier (3) than
        high-effort tasks (1), so easier tasks score higher.
        Higher scores mean higher priority.
        """
        p = PRIORITY_WEIGHTS.get(task.priority, 4.0)
        imp = IMPACT_WEIGHTS.get(task.impact, 2.0)
        eff = EFFORT_WEIGHTS.get(task.effort, 2.0)
        return p * imp * eff

    def score_all_tasks(self, tasks: List[FleetTask]) -> List[ScoredTask]:
        """Score all tasks and return them sorted by score (highest first)."""
        scored: List[ScoredTask] = []
        for task in tasks:
            score = self.score_task(task)
            skill_match = self._compute_skill_match(task)
            scored.append(ScoredTask(
                task=task,
                score=score,
                skill_match=skill_match,
            ))

        # Sort by combined score (base score + skill bonus)
        scored.sort(key=lambda s: s.score + s.skill_match, reverse=True)
        return scored

    def _compute_skill_match(self, task: FleetTask) -> float:
        """Compute how well a task matches the agent's skills.

        Returns a bonus score (0.0 to 5.0).
        """
        if not self.agent_capabilities.skills:
            return 0.0

        task_text = f"{task.task} {' '.join(task.skills)}".lower()
        matched_skills: Set[str] = set()

        for skill in self.agent_capabilities.skills:
            skill_lower = skill.lower()
            keywords = SKILL_KEYWORDS.get(skill_lower, {skill_lower})
            if any(kw in task_text for kw in keywords):
                matched_skills.add(skill)

        if not matched_skills:
            return 0.0

        # Bonus proportional to skill match ratio
        ratio = len(matched_skills) / max(1, len(task.skills) if task.skills else 1)
        return min(5.0, ratio * 5.0)

    # ------------------------------------------------------------------
    # Skill matching
    # ------------------------------------------------------------------

    def match_task_to_agent(self, task: FleetTask) -> float:
        """Return a compatibility score (0.0–1.0) between task and agent."""
        if not task.skills and not self.agent_capabilities.skills:
            return 0.5  # No info — neutral

        if not task.skills:
            return 0.3  # Task has no skill requirements

        task_skills_lower = {s.lower() for s in task.skills}
        agent_skills_lower = {s.lower() for s in self.agent_capabilities.skills}

        # Direct overlap
        overlap = task_skills_lower & agent_skills_lower
        if overlap:
            return len(overlap) / len(task_skills_lower)

        # Keyword matching
        task_text = f"{task.task} {' '.join(task.skills)}".lower()
        for skill in self.agent_capabilities.skills:
            keywords = SKILL_KEYWORDS.get(skill.lower(), {skill.lower()})
            if any(kw in task_text for kw in keywords):
                return 0.7  # Partial match

        return 0.1  # No match but agent can still try

    def filter_compatible_tasks(
        self,
        tasks: List[FleetTask],
        min_score: float = 0.2,
    ) -> List[FleetTask]:
        """Filter tasks to those compatible with the agent."""
        return [
            t for t in tasks
            if self.match_task_to_agent(t) >= min_score
        ]

    # ------------------------------------------------------------------
    # Dependencies
    # ------------------------------------------------------------------

    def detect_dependencies(self, tasks: List[FleetTask]) -> Dict[str, List[str]]:
        """Detect dependencies between tasks based on repo and skill overlap.

        Returns a dict mapping task_id → list of dependency task_ids.
        """
        deps: Dict[str, List[str]] = {}

        # Group by repo
        repo_tasks: Dict[str, List[FleetTask]] = {}
        for t in tasks:
            repo_tasks.setdefault(t.repo, []).append(t)

        # Tasks in the same repo may have ordering dependencies
        for repo, repo_task_list in repo_tasks.items():
            if len(repo_task_list) <= 1:
                continue

            # Sort by priority (critical first) — they may need to go first
            sorted_by_priority = sorted(
                repo_task_list,
                key=lambda t: PRIORITY_WEIGHTS.get(t.priority, 4.0),
                reverse=True,
            )

            # Later tasks depend on earlier (higher priority) tasks in same repo
            for i, task in enumerate(sorted_by_priority):
                task_deps = []
                for dep_task in sorted_by_priority[:i]:
                    # Only add dependency if they share skills or the dep is critical
                    if dep_task.priority in (TaskPriority.CRITICAL, TaskPriority.HIGH):
                        if set(task.skills) & set(dep_task.skills) or not task.skills:
                            task_deps.append(dep_task.id)
                if task_deps:
                    deps[task.id] = task_deps

        return deps

    # ------------------------------------------------------------------
    # Execution order
    # ------------------------------------------------------------------

    def generate_execution_order(
        self,
        tasks: List[FleetTask],
        available_time: Optional[int] = None,
    ) -> List[ScoredTask]:
        """Generate an ordered execution plan.

        Considers:
            1. Task scores (priority × impact / effort)
            2. Skill matching bonus
            3. Dependencies (must execute deps first)
            4. Available agent capacity

        Parameters
        ----------
        tasks:
            Tasks to plan.
        available_time:
            Maximum number of tasks to plan (None = no limit).

        Returns
        -------
        List[ScoredTask]
            Tasks in execution order.
        """
        scored = self.score_all_tasks(tasks)
        deps = self.detect_dependencies(tasks)

        # Apply dependencies
        scored = self._resolve_dependencies(scored, deps)

        # Apply available capacity
        max_tasks = available_time or self.agent_capabilities.available_slots
        if max_tasks > 0:
            scored = scored[:max(1, max_tasks)]

        # Assign execution order
        for i, st in enumerate(scored):
            st.execution_order = i + 1

        return scored

    def _resolve_dependencies(
        self,
        scored: List[ScoredTask],
        deps: Dict[str, List[str]],
    ) -> List[ScoredTask]:
        """Re-order scored tasks to respect dependencies.

        Uses a topological sort-like approach: tasks with dependencies
        are placed after their dependencies.
        """
        task_map = {st.task.id: st for st in scored}
        visited: Set[str] = set()
        ordered: List[ScoredTask] = []

        def visit(task_id: str) -> None:
            if task_id in visited:
                return
            visited.add(task_id)
            for dep_id in deps.get(task_id, []):
                if dep_id in task_map:
                    visit(dep_id)
            if task_id in task_map:
                ordered.append(task_map[task_id])

        for st in scored:
            visit(st.task.id)

        return ordered

    # ------------------------------------------------------------------
    # Convert to Plan
    # ------------------------------------------------------------------

    def to_plan(self, scored: List[ScoredTask]) -> Plan:
        """Convert scored tasks into a Plan object for the Agent."""
        tasks: List[Task] = []
        for st in scored:
            ft = st.task
            tasks.append(Task(
                id=ft.id,
                description=ft.task,
                priority=ft.priority,
                repo=ft.repo if ft.repo else None,
                effort_estimate=ft.effort,
                impact_estimate=ft.impact,
                metadata={"score": st.score, "skill_match": st.skill_match},
            ))
        plan = Plan(tasks=tasks)
        plan.sort_by_score()
        return plan

    # ------------------------------------------------------------------
    # Workload balancing
    # ------------------------------------------------------------------

    def balance_workload(
        self,
        tasks: List[FleetTask],
        agents: List[AgentCapabilities],
    ) -> Dict[str, List[FleetTask]]:
        """Distribute tasks across multiple agents based on skills and capacity.

        Returns a dict mapping agent name → list of assigned tasks.
        """
        assignments: Dict[str, List[FleetTask]] = {a.name: [] for a in agents}
        agent_loads = {a.name: 0 for a in agents}

        scored = self.score_all_tasks(tasks)

        for st in scored:
            best_agent = None
            best_score = -1

            for agent in agents:
                if agent_loads[agent.name] >= agent.max_concurrent:
                    continue

                # Compute match score for this agent
                match = 0.0
                if st.task.skills and agent.skills:
                    task_skills_lower = {s.lower() for s in st.task.skills}
                    agent_skills_lower = {s.lower() for s in agent.skills}
                    overlap = task_skills_lower & agent_skills_lower
                    match = len(overlap) / max(1, len(task_skills_lower))

                combined = st.score + match * 5.0
                if combined > best_score:
                    best_score = combined
                    best_agent = agent

            if best_agent:
                assignments[best_agent.name].append(st.task)
                agent_loads[best_agent.name] += 1

        return assignments
