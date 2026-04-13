"""
Bootcamp & Dojo Framework — Agent skill development and technique mastery.

The Bootcamp provides a structured progression path (NOVICE → MASTER) with
varied exercise types. The Dojo offers a technique library where agents learn,
practice, and master named patterns with spaced repetition.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enums and constants
# ---------------------------------------------------------------------------

class Rank(IntEnum):
    """Skill rank progression for bootcamp agents."""
    NOVICE = 1
    APPRENTICE = 2
    JOURNEYMAN = 3
    EXPERT = 4
    MASTER = 5

    @classmethod
    def from_string(cls, value: str) -> Rank:
        """Parse a rank from its string name."""
        try:
            return cls[value.upper()]
        except KeyError:
            return cls.NOVICE

    @property
    def label(self) -> str:
        return self.name


class ExerciseType(str, Enum):
    """Types of exercises available in bootcamp."""
    CODING_CHALLENGE = "coding_challenge"
    DEBUG_CHALLENGE = "debug_challenge"
    INTEGRATION_CHALLENGE = "integration_challenge"
    OPTIMIZATION_CHALLENGE = "optimization_challenge"
    SECURITY_CHALLENGE = "security_challenge"


# XP thresholds for rank advancement
_RANK_THRESHOLDS: dict[Rank, int] = {
    Rank.NOVICE: 0,
    Rank.APPRENTICE: 100,
    Rank.JOURNEYMAN: 300,
    Rank.EXPERT: 700,
    Rank.MASTER: 1500,
}

# XP rewards per exercise type
_EXERCISE_XP: dict[ExerciseType, int] = {
    ExerciseType.CODING_CHALLENGE: 20,
    ExerciseType.DEBUG_CHALLENGE: 25,
    ExerciseType.INTEGRATION_CHALLENGE: 30,
    ExerciseType.OPTIMIZATION_CHALLENGE: 35,
    ExerciseType.SECURITY_CHALLENGE: 40,
}

# Spaced repetition intervals (in days) for review
_SPACED_INTERVALS = [1, 3, 7, 14, 30, 60]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Exercise:
    """A bootcamp exercise definition."""
    name: str
    exercise_type: ExerciseType
    description: str
    difficulty: int = 1  # 1-5 scale
    xp_reward: int = 0
    required_rank: Rank = Rank.NOVICE
    hints: list[str] = field(default_factory=list)
    solution: str = ""

    def __post_init__(self) -> None:
        if self.xp_reward == 0:
            self.xp_reward = _EXERCISE_XP.get(self.exercise_type, 20)


@dataclass
class ExerciseResult:
    """Result of an agent completing an exercise."""
    exercise_name: str
    completed: bool
    xp_earned: int
    time_taken_seconds: int
    hints_used: int = 0
    feedback: str = ""
    completed_at: str = ""

    def __post_init__(self) -> None:
        if not self.completed_at:
            self.completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Technique:
    """A named pattern in the dojo technique library."""
    name: str
    description: str
    code: str
    category: str
    difficulty: int = 1  # 1-5
    mastery_level: float = 0.0  # 0.0 to 1.0
    times_practiced: int = 0
    review_count: int = 0
    next_review: str = ""
    mastered: bool = False
    created: str = ""
    shared_from: Optional[str] = None  # agent name if learned via transfer

    def __post_init__(self) -> None:
        if not self.created:
            self.created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not self.next_review:
            self.next_review = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class AgentProgress:
    """Tracks an agent's progress through bootcamp and dojo."""
    agent_name: str
    rank: Rank = Rank.NOVICE
    xp: int = 0
    exercises_completed: list[str] = field(default_factory=list)
    exercises_failed: list[str] = field(default_factory=list)
    current_exercise: Optional[str] = None
    review_schedule: list[dict[str, str]] = field(default_factory=list)
    enrolled: bool = False
    enrolled_at: str = ""
    last_active: str = ""


# ---------------------------------------------------------------------------
# Bootcamp
# ---------------------------------------------------------------------------

class Bootcamp:
    """Manages agent skill development through structured exercises.

    Agents progress from NOVICE to MASTER by completing exercises of increasing
    difficulty. XP is earned for each completion, and rank advancement is
    automatic when thresholds are met.
    """

    def __init__(self, progress_dir: str | None = None) -> None:
        """Initialize the bootcamp.

        Parameters
        ----------
        progress_dir : str, optional
            Directory to persist progress JSON files. If None, progress is
            kept in memory only.
        """
        self._progress_dir = Path(progress_dir) if progress_dir else None
        self._exercises: list[Exercise] = []
        self._agents: dict[str, AgentProgress] = {}
        self._load_default_exercises()

    def _load_default_exercises(self) -> None:
        """Pre-populate with a set of standard bootcamp exercises."""
        defaults = [
            Exercise(
                name="hello_workshop",
                exercise_type=ExerciseType.CODING_CHALLENGE,
                description="Write a script that prints the workshop name and current timestamp.",
                difficulty=1,
                required_rank=Rank.NOVICE,
                hints=["Use datetime module", "Read from CHARTER.md"],
            ),
            Exercise(
                name="parse_config",
                exercise_type=ExerciseType.CODING_CHALLENGE,
                description="Parse the agent.yaml configuration file and print the agent's name, role, and stack.",
                difficulty=1,
                required_rank=Rank.NOVICE,
            ),
            Exercise(
                name="recipe_runner",
                exercise_type=ExerciseType.INTEGRATION_CHALLENGE,
                description="Build a script that discovers and runs all recipes in a given tier.",
                difficulty=2,
                required_rank=Rank.APPRENTICE,
            ),
            Exercise(
                name="log_analyzer",
                exercise_type=ExerciseType.DEBUG_CHALLENGE,
                description="Given a sample error log, identify the root cause and suggest a fix.",
                difficulty=2,
                required_rank=Rank.APPRENTICE,
            ),
            Exercise(
                name="api_bridge",
                exercise_type=ExerciseType.INTEGRATION_CHALLENGE,
                description="Create a bridge that connects two services using a shared protocol.",
                difficulty=3,
                required_rank=Rank.JOURNEYMAN,
            ),
            Exercise(
                name="perf_bottleneck",
                exercise_type=ExerciseType.OPTIMIZATION_CHALLENGE,
                description="Identify and fix a performance bottleneck in a provided codebase.",
                difficulty=3,
                required_rank=Rank.JOURNEYMAN,
            ),
            Exercise(
                name="secret_scanner",
                exercise_type=ExerciseType.SECURITY_CHALLENGE,
                description="Build a tool that scans code for hardcoded secrets and credentials.",
                difficulty=4,
                required_rank=Rank.EXPERT,
            ),
            Exercise(
                name="interpreter_core",
                exercise_type=ExerciseType.CODING_CHALLENGE,
                description="Implement the core eval loop of a minimal expression interpreter.",
                difficulty=5,
                required_rank=Rank.EXPERT,
            ),
        ]
        self._exercises.extend(defaults)

    # ---- Enrollment -------------------------------------------------------

    def enroll(self, agent_name: str) -> AgentProgress:
        """Enroll an agent in the bootcamp.

        Parameters
        ----------
        agent_name : str
            The agent's identifier.

        Returns
        -------
        AgentProgress for the enrolled agent.
        """
        if agent_name in self._agents:
            return self._agents[agent_name]

        progress = AgentProgress(
            agent_name=agent_name,
            enrolled=True,
            enrolled_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            last_active=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        self._agents[agent_name] = progress
        self._save_progress(agent_name)
        return progress

    # ---- Exercises --------------------------------------------------------

    def add_exercise(self, exercise: Exercise) -> None:
        """Register a new exercise in the bootcamp."""
        self._exercises.append(exercise)

    def get_available_exercises(self, agent_name: str) -> list[Exercise]:
        """Return exercises available for the given agent based on their rank."""
        progress = self._agents.get(agent_name)
        if not progress or not progress.enrolled:
            return []

        completed = set(progress.exercises_completed)
        return [
            ex for ex in self._exercises
            if ex.required_rank <= progress.rank and ex.name not in completed
        ]

    def start_exercise(self, agent_name: str, exercise_name: str) -> Optional[Exercise]:
        """Start an exercise for an agent.

        Returns the Exercise if the agent can attempt it, None otherwise.
        """
        exercise = self._find_exercise(exercise_name)
        if not exercise:
            return None

        progress = self._agents.get(agent_name)
        if not progress or not progress.enrolled:
            return None

        if exercise.required_rank > progress.rank:
            return None

        if exercise_name in progress.exercises_completed:
            return None

        progress.current_exercise = exercise_name
        return exercise

    def complete_exercise(
        self,
        agent_name: str,
        exercise_name: str,
        time_taken_seconds: int = 0,
        hints_used: int = 0,
        feedback: str = "",
    ) -> ExerciseResult:
        """Record an exercise completion and award XP.

        Parameters
        ----------
        agent_name : str
            The agent's identifier.
        exercise_name : str
            The exercise that was completed.
        time_taken_seconds : int
            How long the exercise took.
        hints_used : int
            How many hints were used (reduces XP by 10% per hint).
        feedback : str
            Optional feedback from the agent.

        Returns
        -------
        ExerciseResult with the completion details.
        """
        exercise = self._find_exercise(exercise_name)
        if not exercise:
            raise ValueError(f"Exercise {exercise_name!r} not found.")

        progress = self._agents.get(agent_name)
        if not progress:
            raise ValueError(f"Agent {agent_name!r} is not enrolled.")

        # Calculate XP (penalty for hints)
        xp_multiplier = max(0.5, 1.0 - (hints_used * 0.1))
        xp_earned = int(exercise.xp_reward * xp_multiplier)

        result = ExerciseResult(
            exercise_name=exercise_name,
            completed=True,
            xp_earned=xp_earned,
            time_taken_seconds=time_taken_seconds,
            hints_used=hints_used,
            feedback=feedback,
        )

        progress.xp += xp_earned
        progress.exercises_completed.append(exercise_name)
        progress.current_exercise = None
        progress.last_active = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Check for rank advancement
        self._check_rank_advancement(progress)

        self._save_progress(agent_name)
        return result

    def fail_exercise(
        self,
        agent_name: str,
        exercise_name: str,
        feedback: str = "",
    ) -> None:
        """Record a failed exercise attempt."""
        progress = self._agents.get(agent_name)
        if not progress:
            raise ValueError(f"Agent {agent_name!r} is not enrolled.")

        progress.exercises_failed.append(exercise_name)
        progress.last_active = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ---- Progress ---------------------------------------------------------

    def get_progress(self, agent_name: str) -> Optional[AgentProgress]:
        """Get an agent's current progress."""
        return self._agents.get(agent_name)

    def get_rank(self, agent_name: str) -> Rank:
        """Get an agent's current rank."""
        progress = self._agents.get(agent_name)
        return progress.rank if progress else Rank.NOVICE

    def xp_to_next_rank(self, agent_name: str) -> Optional[int]:
        """Return XP needed to reach the next rank, or None if already MASTER."""
        progress = self._agents.get(agent_name)
        if not progress or progress.rank == Rank.MASTER:
            return None

        next_rank = Rank(progress.rank + 1)
        threshold = _RANK_THRESHOLDS[next_rank]
        return max(0, threshold - progress.xp)

    def _check_rank_advancement(self, progress: AgentProgress) -> bool:
        """Check and apply rank advancement if XP threshold is met."""
        for rank in Rank:
            if rank > progress.rank and progress.xp >= _RANK_THRESHOLDS[rank]:
                progress.rank = rank
                return True
        return False

    def _find_exercise(self, name: str) -> Optional[Exercise]:
        for ex in self._exercises:
            if ex.name == name:
                return ex
        return None

    # ---- Persistence ------------------------------------------------------

    def _save_progress(self, agent_name: str) -> None:
        """Save agent progress to disk."""
        if not self._progress_dir:
            return

        self._progress_dir.mkdir(parents=True, exist_ok=True)
        progress = self._agents[agent_name]
        data = {
            "agent_name": progress.agent_name,
            "rank": progress.rank.label,
            "xp": progress.xp,
            "exercises_completed": progress.exercises_completed,
            "exercises_failed": progress.exercises_failed,
            "current_exercise": progress.current_exercise,
            "enrolled": progress.enrolled,
            "enrolled_at": progress.enrolled_at,
            "last_active": progress.last_active,
            "review_schedule": progress.review_schedule,
        }
        filepath = self._progress_dir / f"{agent_name}.json"
        filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_progress(self, agent_name: str) -> Optional[AgentProgress]:
        """Load agent progress from disk."""
        if not self._progress_dir:
            return self._agents.get(agent_name)

        filepath = self._progress_dir / f"{agent_name}.json"
        if not filepath.exists():
            return None

        data = json.loads(filepath.read_text(encoding="utf-8"))
        progress = AgentProgress(
            agent_name=data["agent_name"],
            rank=Rank.from_string(data.get("rank", "NOVICE")),
            xp=data.get("xp", 0),
            exercises_completed=data.get("exercises_completed", []),
            exercises_failed=data.get("exercises_failed", []),
            current_exercise=data.get("current_exercise"),
            enrolled=data.get("enrolled", True),
            enrolled_at=data.get("enrolled_at", ""),
            last_active=data.get("last_active", ""),
            review_schedule=data.get("review_schedule", []),
        )
        self._agents[agent_name] = progress
        return progress

    def get_all_progress(self) -> list[AgentProgress]:
        """Return progress for all enrolled agents."""
        return list(self._agents.values())


# ---------------------------------------------------------------------------
# Dojo
# ---------------------------------------------------------------------------

class Dojo:
    """Technique library where agents learn, practice, and master patterns.

    Techniques follow a spaced repetition schedule. Mastery is achieved after
    sufficient practice and successful reviews.
    """

    MASTERY_THRESHOLD = 0.9

    def __init__(self, progress_dir: str | None = None) -> None:
        self._progress_dir = Path(progress_dir) if progress_dir else None
        self._techniques: dict[str, Technique] = {}

    # ---- Technique management ---------------------------------------------

    def learn_technique(
        self,
        name: str,
        code: str,
        description: str,
        category: str = "general",
        difficulty: int = 1,
        shared_from: Optional[str] = None,
    ) -> Technique:
        """Add a new technique to the dojo.

        Parameters
        ----------
        name : str
            Unique technique name.
        code : str
            Code example demonstrating the technique.
        description : str
            Explanation of when and why to use this technique.
        category : str
            Category grouping (e.g., "error-handling", "optimization").
        difficulty : int
            Difficulty level (1-5).
        shared_from : str, optional
            Name of the agent that shared this technique (keeper-mediated transfer).

        Returns
        -------
        The created Technique.
        """
        technique = Technique(
            name=name,
            code=code,
            description=description,
            category=category,
            difficulty=difficulty,
            shared_from=shared_from,
        )
        self._techniques[name] = technique
        self._save_techniques()
        return technique

    def practice_technique(self, name: str, context: str = "") -> Technique:
        """Record a practice session for a technique.

        Updates the mastery level and schedules the next review based on
        spaced repetition intervals.

        Parameters
        ----------
        name : str
            Technique name.
        context : str
            Description of the context in which the technique was practiced.

        Returns
        -------
        Updated Technique.
        """
        technique = self._techniques.get(name)
        if not technique:
            raise ValueError(f"Technique {name!r} not found in the dojo.")

        technique.times_practiced += 1
        technique.review_count += 1

        # Increase mastery with diminishing returns
        old_mastery = technique.mastery_level
        increment = (1.0 - old_mastery) * 0.3  # 30% of remaining gap
        technique.mastery_level = min(1.0, old_mastery + increment)

        # Schedule next review using spaced repetition
        interval_index = min(technique.review_count - 1, len(_SPACED_INTERVALS) - 1)
        interval_days = _SPACED_INTERVALS[interval_index]

        from datetime import timedelta
        next_review = datetime.now(timezone.utc) + timedelta(days=interval_days)
        technique.next_review = next_review.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Check mastery
        if technique.mastery_level >= self.MASTERY_THRESHOLD:
            technique.mastered = True

        self._save_techniques()
        return technique

    def master_technique(self, name: str) -> Technique:
        """Manually mark a technique as mastered."""
        technique = self._techniques.get(name)
        if not technique:
            raise ValueError(f"Technique {name!r} not found in the dojo.")

        technique.mastered = True
        technique.mastery_level = 1.0
        self._save_techniques()
        return technique

    # ---- Queries ----------------------------------------------------------

    def get_technique(self, name: str) -> Optional[Technique]:
        """Retrieve a technique by name."""
        return self._techniques.get(name)

    def list_techniques(
        self,
        category: Optional[str] = None,
        mastered_only: bool = False,
    ) -> list[Technique]:
        """List techniques, optionally filtered."""
        techniques = list(self._techniques.values())

        if category:
            techniques = [t for t in techniques if t.category == category]
        if mastered_only:
            techniques = [t for t in techniques if t.mastered]

        return sorted(techniques, key=lambda t: t.name)

    def get_review_queue(self) -> list[Technique]:
        """Return techniques that are due for review."""
        now = datetime.now(timezone.utc)
        queue: list[Technique] = []
        for technique in self._techniques.values():
            if technique.mastered:
                continue
            if not technique.next_review:
                queue.append(technique)
                continue
            try:
                next_dt = datetime.fromisoformat(technique.next_review.replace("Z", "+00:00"))
                if next_dt <= now:
                    queue.append(technique)
            except ValueError:
                queue.append(technique)
        return sorted(queue, key=lambda t: t.next_review)

    def get_stats(self) -> dict[str, Any]:
        """Return dojo statistics."""
        total = len(self._techniques)
        mastered = sum(1 for t in self._techniques.values() if t.mastered)
        shared = sum(1 for t in self._techniques.values() if t.shared_from)
        categories: dict[str, int] = {}
        for t in self._techniques.values():
            categories[t.category] = categories.get(t.category, 0) + 1

        return {
            "total_techniques": total,
            "mastered": mastered,
            "in_progress": total - mastered,
            "shared_from_fleet": shared,
            "categories": categories,
            "review_queue_size": len(self.get_review_queue()),
        }

    # ---- Persistence ------------------------------------------------------

    def _save_techniques(self) -> None:
        """Persist all techniques to disk."""
        if not self._progress_dir:
            return

        self._progress_dir.mkdir(parents=True, exist_ok=True)
        data = {
            name: {
                "name": t.name,
                "description": t.description,
                "code": t.code,
                "category": t.category,
                "difficulty": t.difficulty,
                "mastery_level": t.mastery_level,
                "times_practiced": t.times_practiced,
                "review_count": t.review_count,
                "next_review": t.next_review,
                "mastered": t.mastered,
                "created": t.created,
                "shared_from": t.shared_from,
            }
            for name, t in self._techniques.items()
        }
        filepath = self._progress_dir / "dojo_techniques.json"
        filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_techniques(self) -> int:
        """Load techniques from disk. Returns the number loaded."""
        if not self._progress_dir:
            return 0

        filepath = self._progress_dir / "dojo_techniques.json"
        if not filepath.exists():
            return 0

        data = json.loads(filepath.read_text(encoding="utf-8"))
        for name, td in data.items():
            self._techniques[name] = Technique(
                name=td["name"],
                description=td["description"],
                code=td["code"],
                category=td.get("category", "general"),
                difficulty=td.get("difficulty", 1),
                mastery_level=td.get("mastery_level", 0.0),
                times_practiced=td.get("times_practiced", 0),
                review_count=td.get("review_count", 0),
                next_review=td.get("next_review", ""),
                mastered=td.get("mastered", False),
                created=td.get("created", ""),
                shared_from=td.get("shared_from"),
            )
        return len(self._techniques)
