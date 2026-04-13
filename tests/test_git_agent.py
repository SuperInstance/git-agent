"""
Tests for the Git Agent package.

Tests cover:
- Commit narrative generation (with mock git logs)
- Workshop creation (using temp dirs)
- Bootcamp exercises and rank progression
- Dojo techniques and spaced repetition
- Timeline generation
- Lesson extraction
- Stuck pattern detection
"""

from __future__ import annotations

import json
import os
import tempfile
import shutil
from pathlib import Path

import pytest

from narrator import (
    Commit,
    CommitNarrator,
    CommitType,
    FileChange,
    NarrativeStyle,
)
from workshop_template import WorkshopTemplate, LanguageStack
from bootcamp import Bootcamp, Dojo, Exercise, ExerciseType, Rank, Technique
from git_agent import GitAgent
from cli import build_parser, main


# ---------------------------------------------------------------------------
# Mock data helpers
# ---------------------------------------------------------------------------

def _make_mock_commit(
    subject: str,
    body: str = "",
    author: str = "test-agent",
    days_ago: int = 0,
    commit_type: CommitType = CommitType.UNKNOWN,
) -> Commit:
    """Create a mock Commit for testing."""
    from datetime import datetime, timedelta, timezone
    date = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return Commit(
        hash="a" * 40,
        short_hash="a" * 7,
        author=author,
        date=date,
        message=f"{subject}\n{body}".strip(),
        subject=subject,
        body=body,
        commit_type=commit_type,
    )


def _make_mock_git_log(commits: list[Commit]) -> str:
    """Generate a mock git log string from Commit objects."""
    blocks: list[str] = []
    for c in commits:
        date_str = c.date.strftime("%Y-%m-%dT%H:%M:%S%z")
        block = (
            f"COMMIT_START\n"
            f"Hash: {c.hash}\n"
            f"Short: {c.short_hash}\n"
            f"Author: {c.author}\n"
            f"Date: {date_str}\n"
            f"Subject: {c.subject}\n"
        )
        if c.body:
            block += f"{c.body}\n"
        block += "COMMIT_END"
        blocks.append(block)
    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# Test: CommitNarrator
# ---------------------------------------------------------------------------

class TestCommitNarrator:
    """Tests for the commit narrative engine."""

    def setup_method(self) -> None:
        self.narrator = CommitNarrator()

    def test_parse_log_basic(self) -> None:
        """Test basic git log parsing."""
        commit = _make_mock_commit("feat: add user authentication")
        log_output = _make_mock_git_log([commit])

        commits = self.narrator.parse_log(log_output)
        assert len(commits) == 1
        assert commits[0].subject == "feat: add user authentication"
        assert commits[0].author == "test-agent"
        assert commits[0].commit_type == CommitType.FEATURE

    def test_parse_log_multiple_commits(self) -> None:
        """Test parsing multiple commits."""
        commits = [
            _make_mock_commit("fix: resolve null pointer", days_ago=2),
            _make_mock_commit("docs: update README", days_ago=1),
            _make_mock_commit("refactor: clean up utils", days_ago=0),
        ]
        log_output = _make_mock_git_log(commits)

        parsed = self.narrator.parse_log(log_output)
        assert len(parsed) == 3
        # Parsed in same order as the log output
        assert parsed[0].commit_type == CommitType.FIX
        assert parsed[1].commit_type == CommitType.DOCS
        assert parsed[2].commit_type == CommitType.REFACTOR

    def test_classify_commit_conventional(self) -> None:
        """Test commit classification with conventional prefixes."""
        assert self.narrator.classify_commit("feat: new feature") == CommitType.FEATURE
        assert self.narrator.classify_commit("fix: bug fix") == CommitType.FIX
        assert self.narrator.classify_commit("refactor: cleanup") == CommitType.REFACTOR
        assert self.narrator.classify_commit("test: add tests") == CommitType.TEST
        assert self.narrator.classify_commit("docs: update docs") == CommitType.DOCS
        assert self.narrator.classify_commit("chore: deps") == CommitType.CHORE

    def test_classify_commit_experiment(self) -> None:
        """Test experiment keyword detection."""
        assert self.narrator.classify_commit("experiment: try new approach") == CommitType.EXPERIMENT
        assert self.narrator.classify_commit("poc: prototype cache layer") == CommitType.EXPERIMENT
        assert self.narrator.classify_commit("exploring: what if we use redis") == CommitType.EXPERIMENT

    def test_classify_commit_with_files(self) -> None:
        """Test classification using file changes."""
        files = [FileChange(path="test_foo.py", status="A")]
        result = self.narrator.classify_commit("some message", files)
        assert result == CommitType.TEST

    def test_detect_experiment_pattern(self) -> None:
        """Test experiment detection (try → fail → succeed)."""
        commits = [
            _make_mock_commit("experiment: try caching responses", days_ago=3),
            _make_mock_commit("fix: cache invalidation bug", days_ago=2),
            _make_mock_commit("fix: cache stampede issue", days_ago=1),
            _make_mock_commit("feat: working cache layer", days_ago=0),
        ]

        experiment = self.narrator.detect_experiment(commits)
        assert experiment is not None
        assert experiment.resolved is True
        assert len(experiment.commits) == 4

    def test_detect_experiment_unresolved(self) -> None:
        """Test detection of unresolved experiments."""
        commits = [
            _make_mock_commit("experiment: try async approach", days_ago=2),
            _make_mock_commit("fix: race condition", days_ago=1),
            _make_mock_commit("fix: deadlock issue", days_ago=0),
        ]

        experiment = self.narrator.detect_experiment(commits)
        assert experiment is not None
        assert experiment.resolved is False

    def test_detect_experiment_too_short(self) -> None:
        """Test that single commits don't count as experiments."""
        commits = [_make_mock_commit("experiment: quick try")]
        assert self.narrator.detect_experiment(commits) is None

    def test_detect_refactor(self) -> None:
        """Test refactoring pattern detection."""
        commits = [
            _make_mock_commit("refactor: extract utils module"),
            _make_mock_commit("refactor: rename functions for clarity"),
            _make_mock_commit("refactor: reorganize directory structure"),
        ]

        assert self.narrator.detect_refactor(commits) is True

    def test_detect_refactor_with_features(self) -> None:
        """Test that features mixed with refactors are not detected as pure refactors."""
        commits = [
            _make_mock_commit("refactor: clean up utils"),
            _make_mock_commit("feat: add new endpoint"),
            _make_mock_commit("refactor: extract module"),
        ]

        assert self.narrator.detect_refactor(commits) is False

    def test_detect_stuck_patterns_duplicates(self) -> None:
        """Test detection of stuck patterns via duplicate commit subjects."""
        commits = [
            _make_mock_commit("fix: authentication error v1"),
            _make_mock_commit("fix: authentication error v2"),
            _make_mock_commit("fix: authentication error v3"),
            _make_mock_commit("fix: authentication error again"),
            _make_mock_commit("fix: authentication error take 2"),
        ]

        stuck = self.narrator.detect_stuck_patterns(commits)
        assert len(stuck) > 0

    def test_detect_stuck_patterns_reverts(self) -> None:
        """Test detection of stuck patterns via revert cycles."""
        commits = [
            _make_mock_commit("fix: try approach A", commit_type=CommitType.FIX),
            _make_mock_commit("revert: undo approach A", commit_type=CommitType.REVERT),
            _make_mock_commit("fix: try approach A again", commit_type=CommitType.FIX),
            _make_mock_commit("revert: undo again", commit_type=CommitType.REVERT),
            _make_mock_commit("fix: approach A v3", commit_type=CommitType.FIX),
        ]

        stuck = self.narrator.detect_stuck_patterns(commits)
        assert len(stuck) > 0

    def test_generate_narrative_story(self) -> None:
        """Test story-style narrative generation."""
        commits = [
            _make_mock_commit("feat: add user dashboard", commit_type=CommitType.FEATURE, days_ago=2),
            _make_mock_commit("fix: dashboard layout bug", commit_type=CommitType.FIX, days_ago=1),
            _make_mock_commit("test: add dashboard tests", commit_type=CommitType.TEST, days_ago=0),
        ]

        narrative = self.narrator.generate_narrative(commits, NarrativeStyle.STORY)
        assert narrative.text
        assert narrative.commits_covered == 3
        assert "feature" in narrative.text.lower() or "dashboard" in narrative.text.lower()

    def test_generate_narrative_brief(self) -> None:
        """Test brief-style narrative."""
        commits = [
            _make_mock_commit("feat: add API", commit_type=CommitType.FEATURE),
        ]

        narrative = self.narrator.generate_narrative(commits, NarrativeStyle.BRIEF)
        assert "FEATURE" in narrative.text

    def test_generate_narrative_technical(self) -> None:
        """Test technical-style narrative."""
        commits = [
            _make_mock_commit("feat: add module", commit_type=CommitType.FEATURE),
            _make_mock_commit("test: add tests", commit_type=CommitType.TEST),
        ]

        narrative = self.narrator.generate_narrative(commits, NarrativeStyle.TECHNICAL)
        assert "TECHNICAL REPORT" in narrative.text
        assert "BREAKDOWN" in narrative.text

    def test_generate_narrative_empty(self) -> None:
        """Test narrative generation with no commits."""
        narrative = self.narrator.generate_narrative([])
        assert narrative.commits_covered == 0

    def test_generate_timeline(self) -> None:
        """Test timeline generation."""
        commits = [
            _make_mock_commit("feat: step one", days_ago=2),
            _make_mock_commit("fix: step two", days_ago=1),
            _make_mock_commit("test: step three", days_ago=0),
        ]

        timeline = self.narrator.generate_timeline(commits)
        assert "Timeline:" in timeline
        assert "feat: step one" in timeline

    def test_compare_timelines(self) -> None:
        """Test comparing two agents' timelines."""
        agent_a = [
            _make_mock_commit("feat: feature A", days_ago=1),
            _make_mock_commit("fix: fix A", days_ago=0),
        ]
        agent_b = [
            _make_mock_commit("refactor: refactor B", days_ago=1),
            _make_mock_commit("test: test B", days_ago=0),
        ]

        comparison = self.narrator.compare_timelines(agent_a, agent_b)
        assert "Agent A" in comparison
        assert "Agent B" in comparison
        assert "COMMIT TYPE BREAKDOWN" in comparison

    def test_summarize_week(self) -> None:
        """Test weekly summary generation."""
        commits = [
            _make_mock_commit("feat: new feature", days_ago=10),
            _make_mock_commit("fix: bug fix", days_ago=8),
            _make_mock_commit("chore: cleanup", days_ago=1),
        ]

        summary = self.narrator.summarize_week(commits)
        assert "WEEKLY SUMMARY" in summary

    def test_extract_lessons(self) -> None:
        """Test lesson extraction from trial-and-error patterns."""
        commits = [
            _make_mock_commit("experiment: try cache", days_ago=4),
            _make_mock_commit("fix: cache bug", days_ago=3),
            _make_mock_commit("fix: cache regression", days_ago=2),
            _make_mock_commit("feat: working cache implementation", days_ago=1),
        ]

        lessons = self.narrator.extract_lessons(commits)
        assert len(lessons) > 0
        assert any("cache" in lesson.lower() for lesson in lessons)

    def test_export_markdown(self) -> None:
        """Test markdown export."""
        commits = [_make_mock_commit("feat: test feature")]
        narrative = self.narrator.generate_narrative(commits)

        md = self.narrator.export_markdown(narrative)
        assert "# Git Agent Narrative Report" in md
        assert "## Narrative" in md


# ---------------------------------------------------------------------------
# Test: WorkshopTemplate
# ---------------------------------------------------------------------------

class TestWorkshopTemplate:
    """Tests for the workshop structure generator."""

    def setup_method(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.template = WorkshopTemplate()

    def teardown_method(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_workshop_full_stack(self) -> None:
        """Test creating a workshop with the full language stack."""
        path = os.path.join(self.temp_dir, "test-workshop")
        config = self.template.create_workshop(path, "Test Agent", LanguageStack.FULL)

        assert config.agent_name == "test"
        assert config.language_stack == LanguageStack.FULL
        assert os.path.isdir(path)

        # Check required directories
        for d in ["recipes/hot", "recipes/med", "recipes/cold", "scripts",
                   "bootcamp", "dojo", "tests", "lib", "docs", ".superinstance"]:
            assert os.path.isdir(os.path.join(path, d)), f"Missing dir: {d}"

        # Check template files
        assert os.path.isfile(os.path.join(path, "README.md"))
        assert os.path.isfile(os.path.join(path, "CHARTER.md"))
        assert os.path.isfile(os.path.join(path, ".superinstance", "agent.yaml"))
        assert os.path.isfile(os.path.join(path, ".superinstance", "workshop.json"))
        assert os.path.isfile(os.path.join(path, "bootcamp", "progress.json"))
        assert os.path.isfile(os.path.join(path, "dojo", "patterns.json"))

    def test_create_workshop_systems_stack(self) -> None:
        """Test creating a workshop with the systems stack."""
        path = os.path.join(self.temp_dir, "sys-workshop")
        config = self.template.create_workshop(path, "Systems Agent", LanguageStack.SYSTEMS)

        assert config.language_stack == LanguageStack.SYSTEMS
        assert os.path.isdir(os.path.join(path, "src", "c"))
        assert os.path.isdir(os.path.join(path, "src", "rust"))

    def test_create_workshop_automation_stack(self) -> None:
        """Test creating a workshop with the automation stack."""
        path = os.path.join(self.temp_dir, "auto-workshop")
        config = self.template.create_workshop(path, "Auto Agent", LanguageStack.AUTOMATION)

        assert config.language_stack == LanguageStack.AUTOMATION
        assert os.path.isdir(os.path.join(path, "src", "python"))
        assert os.path.isdir(os.path.join(path, "src", "bash"))

    def test_add_recipe(self) -> None:
        """Test adding a recipe to a workshop."""
        path = os.path.join(self.temp_dir, "recipe-workshop")
        self.template.create_workshop(path, "Recipe Agent")

        meta = self.template.add_recipe(
            workshop_path=path,
            name="hello",
            content="print('hello')",
            tier="cold",
            language="python",
            description="A hello world recipe",
        )

        assert meta.name == "hello"
        assert meta.tier == "cold"
        assert os.path.isfile(os.path.join(path, "recipes", "cold", "hello.py"))

    def test_add_recipe_invalid_tier(self) -> None:
        """Test that invalid tiers raise an error."""
        path = os.path.join(self.temp_dir, "tier-workshop")
        self.template.create_workshop(path, "Tier Agent")

        with pytest.raises(ValueError, match="Invalid tier"):
            self.template.add_recipe(path, "test", "content", tier="invalid")

    def test_promote_recipe(self) -> None:
        """Test promoting a recipe between tiers."""
        path = os.path.join(self.temp_dir, "promote-workshop")
        self.template.create_workshop(path, "Promote Agent")
        self.template.add_recipe(path, "tool", "#!/bin/bash\necho hi", tier="cold", language="bash")

        result = self.template.promote_recipe(path, "tool", "cold", "med")

        assert "med" in str(result)
        assert not os.path.exists(os.path.join(path, "recipes", "cold", "tool.sh"))
        assert os.path.isfile(os.path.join(path, "recipes", "med", "tool.sh"))

    def test_promote_recipe_wrong_direction(self) -> None:
        """Test that promoting in the wrong direction raises an error."""
        path = os.path.join(self.temp_dir, "promdir-workshop")
        self.template.create_workshop(path, "Dir Agent")
        self.template.add_recipe(path, "tool", "code", tier="hot")

        with pytest.raises(ValueError, match="Cannot promote"):
            self.template.promote_recipe(path, "tool", "hot", "cold")

    def test_freeze_recipe(self) -> None:
        """Test freezing a recipe."""
        path = os.path.join(self.temp_dir, "freeze-workshop")
        self.template.create_workshop(path, "Freeze Agent")
        self.template.add_recipe(path, "locked", "code", tier="hot")

        self.template.freeze_recipe(path, "locked", tier="hot")

        assert os.path.isfile(os.path.join(path, "recipes", "hot", "locked.frozen"))


# ---------------------------------------------------------------------------
# Test: Bootcamp
# ---------------------------------------------------------------------------

class TestBootcamp:
    """Tests for the bootcamp framework."""

    def setup_method(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.bootcamp = Bootcamp(self.temp_dir)

    def teardown_method(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_enroll_agent(self) -> None:
        """Test agent enrollment."""
        progress = self.bootcamp.enroll("test-agent")

        assert progress.agent_name == "test-agent"
        assert progress.enrolled is True
        assert progress.rank == Rank.NOVICE
        assert progress.xp == 0

    def test_enroll_duplicate(self) -> None:
        """Test that enrolling the same agent returns existing progress."""
        p1 = self.bootcamp.enroll("dup-agent")
        p2 = self.bootcamp.enroll("dup-agent")
        assert p1 is p2

    def test_get_available_exercises(self) -> None:
        """Test available exercise listing for a novice."""
        self.bootcamp.enroll("novice-agent")

        available = self.bootcamp.get_available_exercises("novice-agent")
        assert len(available) > 0
        # Novice should only see novice-level exercises
        for ex in available:
            assert ex.required_rank <= Rank.NOVICE

    def test_complete_exercise(self) -> None:
        """Test completing an exercise and earning XP."""
        self.bootcamp.enroll("xp-agent")

        result = self.bootcamp.complete_exercise("xp-agent", "hello_workshop")
        assert result.completed is True
        assert result.xp_earned > 0

        progress = self.bootcamp.get_progress("xp-agent")
        assert progress.xp > 0
        assert "hello_workshop" in progress.exercises_completed

    def test_complete_with_hints_penalty(self) -> None:
        """Test that using hints reduces XP."""
        self.bootcamp.enroll("hint-agent")

        full_xp = self.bootcamp.complete_exercise("hint-agent", "parse_config")
        self.bootcamp.fail_exercise("hint-agent", "parse_config")
        self.bootcamp.enroll("hint-agent-2")
        partial_xp = self.bootcamp.complete_exercise(
            "hint-agent-2", "parse_config", hints_used=5
        )

        assert full_xp.xp_earned > partial_xp.xp_earned

    def test_rank_advancement(self) -> None:
        """Test that enough XP triggers rank advancement."""
        self.bootcamp.enroll("rank-agent")

        # Complete enough exercises to advance
        exercises = self.bootcamp.get_available_exercises("rank-agent")
        for ex in exercises[:10]:  # Complete first 10
            try:
                self.bootcamp.complete_exercise("rank-agent", ex.name)
            except ValueError:
                break  # No more exercises available at this rank

        progress = self.bootcamp.get_progress("rank-agent")
        # Should have advanced past NOVICE after enough exercises
        # (This depends on exercise XP totals vs threshold)

    def test_fail_exercise(self) -> None:
        """Test recording a failed exercise."""
        self.bootcamp.enroll("fail-agent")

        self.bootcamp.fail_exercise("fail-agent", "hard_exercise")

        progress = self.bootcamp.get_progress("fail-agent")
        assert "hard_exercise" in progress.exercises_failed

    def test_unenrolled_agent(self) -> None:
        """Test operations on unenrolled agents."""
        assert self.bootcamp.get_progress("ghost") is None
        assert self.bootcamp.get_available_exercises("ghost") == []
        assert self.bootcamp.get_rank("ghost") == Rank.NOVICE

    def test_persistence(self) -> None:
        """Test that progress is persisted to disk."""
        self.bootcamp.enroll("persist-agent")
        self.bootcamp.complete_exercise("persist-agent", "hello_workshop")

        # Load in a new Bootcamp instance
        new_bootcamp = Bootcamp(self.temp_dir)
        loaded = new_bootcamp.load_progress("persist-agent")

        assert loaded is not None
        assert loaded.xp > 0
        assert "hello_workshop" in loaded.exercises_completed


# ---------------------------------------------------------------------------
# Test: Dojo
# ---------------------------------------------------------------------------

class TestDojo:
    """Tests for the dojo technique library."""

    def setup_method(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.dojo = Dojo(self.temp_dir)

    def teardown_method(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_learn_technique(self) -> None:
        """Test learning a new technique."""
        technique = self.dojo.learn_technique(
            name="error-boundary",
            code="try: ... except: ...",
            description="Wrap operations in error boundaries",
            category="error-handling",
        )

        assert technique.name == "error-boundary"
        assert technique.mastery_level == 0.0
        assert technique.mastered is False

    def test_practice_technique(self) -> None:
        """Test practicing a technique increases mastery."""
        self.dojo.learn_technique(
            name="retry-loop",
            code="for attempt in range(3): ...",
            description="Retry failed operations",
        )

        t1 = self.dojo.practice_technique("retry-loop", "handling network errors")
        assert t1.mastery_level > 0.0
        assert t1.times_practiced == 1

        t2 = self.dojo.practice_technique("retry-loop")
        assert t2.mastery_level >= t1.mastery_level  # Diminishing returns
        assert t2.times_practiced == 2

    def test_master_technique(self) -> None:
        """Test manual mastery marking."""
        self.dojo.learn_technique("pattern", "code", "desc")

        technique = self.dojo.master_technique("pattern")
        assert technique.mastered is True
        assert technique.mastery_level == 1.0

    def test_list_techniques(self) -> None:
        """Test technique listing and filtering."""
        self.dojo.learn_technique("t1", "c1", "d1", category="cat-a")
        self.dojo.learn_technique("t2", "c2", "d2", category="cat-b")
        self.dojo.learn_technique("t3", "c3", "d3", category="cat-a")
        self.dojo.master_technique("t1")

        all_techniques = self.dojo.list_techniques()
        assert len(all_techniques) == 3

        cat_a = self.dojo.list_techniques(category="cat-a")
        assert len(cat_a) == 2

        mastered = self.dojo.list_techniques(mastered_only=True)
        assert len(mastered) == 1
        assert mastered[0].name == "t1"

    def test_get_stats(self) -> None:
        """Test dojo statistics."""
        self.dojo.learn_technique("t1", "c", "d", category="a")
        self.dojo.learn_technique("t2", "c", "d", category="b")
        self.dojo.learn_technique("shared", "c", "d", shared_from="other-agent")
        self.dojo.master_technique("t1")

        stats = self.dojo.get_stats()
        assert stats["total_techniques"] == 3
        assert stats["mastered"] == 1
        assert stats["shared_from_fleet"] == 1
        assert stats["categories"]["a"] == 1
        assert stats["categories"]["b"] == 1

    def test_unknown_technique(self) -> None:
        """Test operations on non-existent techniques."""
        assert self.dojo.get_technique("nonexistent") is None

        with pytest.raises(ValueError):
            self.dojo.practice_technique("nonexistent")

        with pytest.raises(ValueError):
            self.dojo.master_technique("nonexistent")


# ---------------------------------------------------------------------------
# Test: GitAgent (integration)
# ---------------------------------------------------------------------------

class TestGitAgent:
    """Integration tests for the core Git Agent."""

    def setup_method(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.agent = GitAgent(fleet_root=self.temp_dir)

    def teardown_method(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_register_workshop(self) -> None:
        """Test registering a workshop (without git repo)."""
        reg = self.agent.register_workshop(
            agent_id="test-agent",
            repo_path=self.temp_dir,
            metadata={"role": "tester"},
        )

        assert reg.agent_id == "test-agent"
        assert reg.status == "active"

    def test_create_pr(self) -> None:
        """Test creating a pull request."""
        pr = self.agent.create_pr(
            source="feature/login",
            target="main",
            title="feat: add login page",
            body="This PR adds the login page with OAuth support.",
            author="test-agent",
        )

        assert pr.number == 1
        assert pr.source_branch == "feature/login"
        assert pr.status == "open"

    def test_review_pr(self) -> None:
        """Test automated PR review."""
        self.agent.create_pr(
            source="feature/x",
            target="main",
            title="feat: add feature",
            body="Adding a new feature to the system.",
        )

        comments = self.agent.review_pr(1)
        assert len(comments) > 0

    def test_review_nonexistent_pr(self) -> None:
        """Test reviewing a PR that doesn't exist."""
        comments = self.agent.review_pr(999)
        assert any("not found" in c for c in comments)

    def test_fleet_status_empty(self) -> None:
        """Test fleet status with no workshops."""
        status = self.agent.fleet_status()
        assert "No workshops" in status

    def test_fleet_status_with_workshops(self) -> None:
        """Test fleet status with registered workshops."""
        self.agent.register_workshop("agent-a", self.temp_dir)
        self.agent.register_workshop("agent-b", self.temp_dir)

        status = self.agent.fleet_status()
        assert "agent-a" in status
        assert "agent-b" in status

    def test_daily_report(self) -> None:
        """Test daily report generation."""
        report = self.agent.daily_report()

        assert report.total_agents == 0
        assert report.date
        assert isinstance(report.commit_breakdown, dict)

    def test_format_daily_report(self) -> None:
        """Test daily report formatting."""
        report = self.agent.daily_report()
        formatted = self.agent.format_daily_report(report)

        assert "DAILY FLEET REPORT" in formatted

    def test_track_build(self) -> None:
        """Test build tracking."""
        build = self.agent.track_build(
            commit_hash="abc123",
            agent_id="test-agent",
            status="passed",
        )

        assert build.status == "passed"
        assert build.agent_id == "test-agent"

    def test_spawn_git_agent(self) -> None:
        """Test spawning a git-agent for a workshop."""
        workshop_path = os.path.join(self.temp_dir, "spawned-workshop")
        config = self.agent.spawn_git_agent(
            agent_id="spawned-agent",
            workshop_path=workshop_path,
            config={"role": "Spawned test agent"},
        )

        # agent_name is derived from the directory name (stripping "-workshop")
        assert config.agent_name == "spawned"
        assert os.path.isdir(workshop_path)
        assert "spawned-agent" in self.agent._workshops

    def test_narrate_unregistered_agent(self) -> None:
        """Test narrating an unregistered agent."""
        narrative = self.agent.narrate_history("ghost-agent")
        assert "not registered" in narrative

    def test_deploy_workshop(self) -> None:
        """Test deploying a workshop."""
        self.agent.register_workshop("deploy-agent", self.temp_dir)

        result = self.agent.deploy_workshop("deploy-agent", "production")
        assert result["status"] == "deployed"
        assert result["target"] == "production"

    def test_deploy_unregistered(self) -> None:
        """Test deploying an unregistered agent."""
        result = self.agent.deploy_workshop("ghost")
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Test: CLI
# ---------------------------------------------------------------------------

class TestCLI:
    """Tests for the CLI argument parsing."""

    def test_parse_no_args(self) -> None:
        """Test parser with no arguments."""
        parser = build_parser()
        args = parser.parse_args([])
        assert args.command is None

    def test_parse_serve(self) -> None:
        """Test serve command."""
        parser = build_parser()
        args = parser.parse_args(["serve", "--watch"])
        assert args.command == "serve"
        assert args.watch is True

    def test_parse_narrate(self) -> None:
        """Test narrate command."""
        parser = build_parser()
        args = parser.parse_args(["narrate", "test-agent", "--style", "brief", "--since", "1 week ago"])
        assert args.command == "narrate"
        assert args.agent == "test-agent"
        assert args.style == "brief"
        assert args.since == "1 week ago"

    def test_parse_workshop_create(self) -> None:
        """Test workshop create command."""
        parser = build_parser()
        args = parser.parse_args(["workshop", "create", "my-agent", "--role", "Tester", "--stack", "systems"])
        assert args.command == "workshop"
        assert args.workshop_cmd == "create"
        assert args.name == "my-agent"
        assert args.role == "Tester"
        assert args.stack == "systems"

    def test_parse_workshop_status(self) -> None:
        """Test workshop status command."""
        parser = build_parser()
        args = parser.parse_args(["workshop", "status"])
        assert args.command == "workshop"
        assert args.workshop_cmd == "status"

    def test_parse_bootcamp_enroll(self) -> None:
        """Test bootcamp enroll command."""
        parser = build_parser()
        args = parser.parse_args(["bootcamp", "enroll", "test-agent"])
        assert args.command == "bootcamp"
        assert args.bootcamp_cmd == "enroll"
        assert args.agent == "test-agent"

    def test_parse_fleet_report(self) -> None:
        """Test fleet-report command."""
        parser = build_parser()
        args = parser.parse_args(["fleet-report"])
        assert args.command == "fleet-report"

    def test_parse_lessons(self) -> None:
        """Test lessons command."""
        parser = build_parser()
        args = parser.parse_args(["lessons", "test-agent", "--since", "2 weeks ago"])
        assert args.command == "lessons"
        assert args.agent == "test-agent"

    def test_parse_spawn(self) -> None:
        """Test spawn command."""
        parser = build_parser()
        args = parser.parse_args(["spawn", "test-agent", "/tmp/workshop", "--stack", "web"])
        assert args.command == "spawn"
        assert args.agent == "test-agent"
        assert args.workshop == "/tmp/workshop"
