"""
Comprehensive tests for the git_agent core engine.

Covers config (loading, validation, env overrides), vessel (state management,
serialization, promotion logic), and agent (lifecycle, task execution, planning).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

import pytest

# Ensure src is importable
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from git_agent.config import (
    AgentConfig,
    ConfigError,
    LLMProviderConfig,
    from_dict,
    load_config,
    load_config_file,
)
from git_agent.vessel import (
    CareerState,
    Domain,
    GrowthStage,
    Identity,
    VesselManager,
    VesselState,
    WorklogEntry,
    check_promotion,
    next_stage,
    STAGE_ORDER,
    STAGE_THRESHOLDS,
)
from git_agent.agent import (
    Agent,
    GitHubClient,
    LLMProvider,
    Observation,
    Plan,
    Task,
    TaskPriority,
)


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory."""
    return tmp_path


@pytest.fixture
def vessel_dir(tmp_dir):
    """Provide a temporary vessel directory."""
    d = tmp_dir / "vessel"
    d.mkdir()
    return d


@pytest.fixture
def base_config_dict():
    """Minimal valid config dict."""
    return {
        "github_token": "ghp_test123",
        "llm_provider": "openai",
        "llm_api_key": "sk-test",
    }


@pytest.fixture
def agent_config(base_config_dict):
    """AgentConfig instance from minimal dict."""
    return from_dict(base_config_dict)


@pytest.fixture
def minimal_vessel(vessel_dir):
    """VesselManager with local path override."""
    return VesselManager(local_path=vessel_dir)


# ===================================================================
# Dummy implementations for testing
# ===================================================================

class DummyLLM:
    """A minimal LLM provider for testing."""

    def __init__(self, response: str = "test response"):
        self._response = response
        self.call_count = 0
        self.last_messages: Optional[List[Dict[str, str]]] = None

    def complete(self, messages, temperature=None, max_tokens=None, **kwargs):
        self.call_count += 1
        self.last_messages = messages
        return self._response

    async def acomplete(self, messages, **kwargs):
        self.call_count += 1
        self.last_messages = messages
        return self._response


class DummyGitHub:
    """A minimal GitHub client for testing."""

    def __init__(self):
        self.forks: List[str] = []
        self.branches: List[str] = []
        self.prs: List[Dict[str, Any]] = []
        self.commits: List[Dict[str, Any]] = []
        self.files: Dict[str, str] = {}
        self.bottles: List[Dict[str, Any]] = []
        self.cloned: List[str] = []

    def get_repo(self, owner, repo):
        return {"full_name": f"{owner}/{repo}", "private": False}

    def fork_repo(self, owner, repo):
        key = f"{owner}/{repo}"
        self.forks.append(key)
        return {"full_name": f"{owner}/{repo}", "fork": True}

    def create_branch(self, owner, repo, branch, from_branch="main"):
        self.branches.append(f"{owner}/{repo}/{branch}")
        return {"name": branch, "ref": f"refs/heads/{branch}"}

    def create_pull_request(self, owner, repo, title, body, head, base="main"):
        pr = {"number": len(self.prs) + 1, "title": title, "html_url": f"https://github.com/{owner}/{repo}/pull/{len(self.prs) + 1}"}
        self.prs.append(pr)
        return pr

    def create_or_update_file(self, owner, repo, path, content, message, branch, sha=None):
        self.files[path] = content
        return {"content": {"path": path}, "commit": {"sha": "abc123"}}

    def get_file(self, owner, repo, path, ref=None):
        key = f"{owner}/{repo}/{path}"
        if key in self.files:
            return {"content": self.files[key], "encoding": "utf-8"}
        raise FileNotFoundError(f"File not found: {key}")

    def get_file_contents(self, owner, repo, path):
        key = f"{owner}/{repo}/{path}"
        return self.files.get(key)

    def list_issues(self, owner, repo, state="open"):
        return []

    def list_commits(self, owner, repo, per_page=10):
        return self.commits

    def push_files(self, owner, repo, branch, files, message):
        for f in files:
            self.files[f["path"]] = f["content"]
        return {"commit": {"sha": "def456"}, "files": len(files)}

    def clone(self, url, path, branch=None):
        self.cloned.append(url)
        path.mkdir(parents=True, exist_ok=True)
        (path / ".git").mkdir(exist_ok=True)
        return path

    def get_bottles(self, owner, repo):
        return self.bottles

    def push_bottle(self, owner, repo, content, title=""):
        bottle = {"title": title, "content": content}
        self.bottles.append(bottle)
        return {"status": "created", "bottle": bottle}


# ===================================================================
# TESTS: config.py (15 tests)
# ===================================================================

class TestConfigLoading:
    """Test configuration loading from various sources."""

    def test_from_dict_minimal(self, base_config_dict):
        """Minimal dict should produce valid config."""
        cfg = from_dict(base_config_dict)
        assert cfg.github_token == "ghp_test123"
        assert cfg.llm_provider == "openai"
        assert cfg.llm_api_key == "sk-test"
        assert cfg.llm_proxy_url is None
        assert cfg.max_parallel_agents == 4

    def test_from_dict_all_fields(self):
        """All fields should be parsed correctly."""
        raw = {
            "github_token": "ghp_x",
            "llm_provider": "anthropic",
            "llm_api_key": "sk-ant",
            "llm_proxy_url": "https://proxy.example.com",
            "llm_api_base": "https://api.example.com",
            "llm_model": "claude-3",
            "llm_temperature": 0.5,
            "llm_max_tokens": 8192,
            "fleet_org": "my-org",
            "vessel_repo": "my-org/vessel",
            "max_parallel_agents": 8,
            "work_hours": "9-17",
        }
        cfg = from_dict(raw)
        assert cfg.llm_provider == "anthropic"
        assert cfg.llm_proxy_url == "https://proxy.example.com"
        assert cfg.llm_model == "claude-3"
        assert cfg.llm_temperature == 0.5
        assert cfg.llm_max_tokens == 8192
        assert cfg.fleet_org == "my-org"
        assert cfg.vessel_repo == "my-org/vessel"
        assert cfg.max_parallel_agents == 8
        assert cfg.work_hours == "9-17"

    def test_from_dict_missing_github_token_raises(self):
        """Missing github_token should raise ConfigError."""
        with pytest.raises(ConfigError, match="github_token"):
            from_dict({"llm_provider": "openai", "llm_api_key": "sk-x"})

    def test_from_dict_missing_llm_provider_raises(self):
        """Missing llm_provider should raise ConfigError."""
        with pytest.raises(ConfigError, match="llm_provider"):
            from_dict({"github_token": "ghp_x", "llm_api_key": "sk-x"})

    def test_from_dict_missing_api_key_and_proxy_raises(self):
        """Missing both api_key and proxy_url should raise ConfigError."""
        with pytest.raises(ConfigError, match="one of"):
            from_dict({"github_token": "ghp_x", "llm_provider": "openai"})

    def test_from_dict_proxy_url_satisfies_auth(self):
        """llm_proxy_url alone should satisfy auth requirement."""
        cfg = from_dict({"github_token": "ghp_x", "llm_provider": "openai", "llm_proxy_url": "https://proxy"})
        assert cfg.llm_proxy_url == "https://proxy"

    def test_env_override_github_token(self, base_config_dict, monkeypatch):
        """Environment variable should override config file value."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_override")
        cfg = from_dict(base_config_dict)
        assert cfg.github_token == "ghp_override"
        monkeypatch.delenv("GITHUB_TOKEN")

    def test_env_override_llm_provider(self, base_config_dict, monkeypatch):
        """Environment variable should override llm_provider."""
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        cfg = from_dict(base_config_dict)
        assert cfg.llm_provider == "anthropic"
        monkeypatch.delenv("LLM_PROVIDER")

    def test_env_override_git_agent_prefix(self, base_config_dict, monkeypatch):
        """GIT_AGENT_ prefixed env vars should also work."""
        monkeypatch.setenv("GIT_AGENT_FLEET_ORG", "test-org")
        cfg = from_dict(base_config_dict)
        assert cfg.fleet_org == "test-org"
        monkeypatch.delenv("GIT_AGENT_FLEET_ORG")

    def test_load_config_yaml(self, tmp_dir):
        """Loading from a YAML file should work."""
        cfg_path = tmp_dir / "config.yaml"
        cfg_path.write_text(
            "github_token: ghp_yaml\n"
            "llm_provider: ollama\n"
            "llm_api_key: ignored\n"
        )
        cfg = load_config(str(cfg_path))
        assert cfg.github_token == "ghp_yaml"
        assert cfg.llm_provider == "ollama"

    def test_load_config_json(self, tmp_dir):
        """Loading from a JSON file should work."""
        cfg_path = tmp_dir / "config.json"
        cfg_path.write_text(json.dumps({
            "github_token": "ghp_json",
            "llm_provider": "custom",
            "llm_proxy_url": "https://proxy",
        }))
        cfg = load_config(str(cfg_path))
        assert cfg.github_token == "ghp_json"
        assert cfg.llm_proxy_url == "https://proxy"

    def test_load_config_file_not_found(self):
        """Non-existent config file should raise ConfigError."""
        with pytest.raises(ConfigError, match="not found"):
            load_config_file("/nonexistent/path/config.yaml")

    def test_load_config_unsupported_format(self, tmp_dir):
        """Unsupported file format should raise ConfigError."""
        cfg_path = tmp_dir / "config.xml"
        cfg_path.write_text("<config/>")
        with pytest.raises(ConfigError, match="Unsupported"):
            load_config_file(str(cfg_path))

    def test_extra_llm_providers(self):
        """Extra LLM providers should be parsed into LLMProviderConfig objects."""
        raw = {
            "github_token": "ghp_x",
            "llm_provider": "openai",
            "llm_api_key": "sk-x",
            "llm_providers": {
                "reviewer": {
                    "api_key": "sk-review",
                    "model": "gpt-4",
                    "temperature": 0.2,
                },
                "local": {
                    "api_base": "http://localhost:11434",
                    "model": "codellama",
                },
            },
        }
        cfg = from_dict(raw)
        assert "reviewer" in cfg.extra_llm_providers
        assert cfg.extra_llm_providers["reviewer"].model == "gpt-4"
        assert cfg.extra_llm_providers["reviewer"].temperature == 0.2
        assert cfg.extra_llm_providers["local"].api_base == "http://localhost:11434"

    def test_primary_llm_property(self, base_config_dict):
        """primary_llm should return a LLMProviderConfig from top-level settings."""
        cfg = from_dict(base_config_dict)
        llm = cfg.primary_llm
        assert isinstance(llm, LLMProviderConfig)
        assert llm.name == "openai"
        assert llm.api_key == "sk-test"
        assert llm.temperature == 0.7
        assert llm.max_tokens == 4096

    def test_numeric_type_coercion(self):
        """String numbers in config should be coerced to proper types."""
        raw = {
            "github_token": "ghp_x",
            "llm_provider": "openai",
            "llm_api_key": "sk-x",
            "max_parallel_agents": "8",
            "llm_max_tokens": "2048",
            "llm_temperature": "0.3",
        }
        cfg = from_dict(raw)
        assert isinstance(cfg.max_parallel_agents, int)
        assert isinstance(cfg.llm_max_tokens, int)
        assert isinstance(cfg.llm_temperature, float)
        assert cfg.max_parallel_agents == 8
        assert cfg.llm_max_tokens == 2048
        assert cfg.llm_temperature == 0.3


# ===================================================================
# TESTS: vessel.py (13 tests)
# ===================================================================

class TestVesselState:
    """Test vessel state model basics."""

    def test_default_state(self):
        """Default VesselState should have sensible defaults."""
        state = VesselState()
        assert state.identity.name == "Super Z"
        assert state.career.current_stage == GrowthStage.INITIATE
        assert state.career.total_tasks_completed == 0
        assert state.worklog == []
        assert state.goals == []

    def test_identity_defaults(self):
        """Identity should have defaults."""
        ident = Identity()
        assert ident.name == "Super Z"
        assert ident.designation == "Git-Native Agent"
        assert ident.version == "0.1.0"
        assert Domain.GENERAL in ident.domains

    def test_career_state_defaults(self):
        """CareerState should start at INITIATE with zero counts."""
        career = CareerState()
        assert career.current_stage == GrowthStage.INITIATE
        assert career.total_tasks_completed == 0
        assert career.total_tasks_failed == 0
        assert career.fences_completed == []
        assert career.skills_acquired == []


class TestGrowthStages:
    """Test growth stage progression logic."""

    def test_stage_order(self):
        """Stages should be in the correct order."""
        assert STAGE_ORDER == [
            GrowthStage.INITIATE,
            GrowthStage.APPRENTICE,
            GrowthStage.JOURNEYMAN,
            GrowthStage.EXPERT,
            GrowthStage.ARCHITECT,
            GrowthStage.COMMANDER,
        ]

    def test_next_stage_initiate(self):
        assert next_stage(GrowthStage.INITIATE) == GrowthStage.APPRENTICE

    def test_next_stage_commander_is_none(self):
        assert next_stage(GrowthStage.COMMANDER) is None

    def test_check_promotion_no_promotion(self):
        """0 completed tasks should not promote from INITIATE."""
        assert check_promotion(GrowthStage.INITIATE, 0) is None

    def test_check_promotion_apprentice(self):
        """3 completed tasks should promote to APPRENTICE."""
        assert check_promotion(GrowthStage.INITIATE, 3) == GrowthStage.APPRENTICE

    def test_check_promotion_not_enough(self):
        """2 completed tasks should not promote to APPRENTICE (needs 3)."""
        assert check_promotion(GrowthStage.INITIATE, 2) is None

    def test_check_promotion_journeyman(self):
        """15 tasks should promote to JOURNEYMAN."""
        assert check_promotion(GrowthStage.APPRENTICE, 15) == GrowthStage.JOURNEYMAN

    def test_check_promotion_max_stage(self):
        """COMMANDER cannot be promoted further."""
        assert check_promotion(GrowthStage.COMMANDER, 10000) is None


class TestVesselManager:
    """Test vessel manager read/write operations."""

    def test_save_creates_files(self, minimal_vessel):
        """Saving should create all four Markdown files."""
        minimal_vessel.save()
        for fname in ("IDENTITY.md", "CAREER.md", "WORKLOG.md", "STATE.md"):
            assert (minimal_vessel.vessel_dir / fname).exists()

    def test_save_and_load_roundtrip(self, minimal_vessel):
        """State should survive a save → load cycle."""
        state = minimal_vessel.state
        state.identity.name = "Test Agent"
        state.career.total_tasks_completed = 42
        state.goals = ["Build the thing", "Ship it"]
        minimal_vessel.save()

        # Fresh manager loading from same dir
        manager2 = VesselManager(local_path=minimal_vessel.vessel_dir)
        loaded = manager2.load()
        assert loaded.identity.name == "Test Agent"
        assert loaded.career.total_tasks_completed == 42
        assert "Build the thing" in loaded.goals
        assert "Ship it" in loaded.goals

    def test_add_worklog_entry(self, minimal_vessel):
        """Worklog entries should be persistable."""
        entry = WorklogEntry(
            timestamp="2025-01-01T00:00:00+00:00",
            action="forked",
            target="owner/repo",
            summary="Forked the main repo",
        )
        minimal_vessel.add_worklog_entry(entry)
        minimal_vessel.save()

        manager2 = VesselManager(local_path=minimal_vessel.vessel_dir)
        loaded = manager2.load()
        assert len(loaded.worklog) == 1
        assert loaded.worklog[0].action == "forked"

    def test_record_task_completion_success(self, minimal_vessel):
        """Successful completion should increment counter."""
        minimal_vessel.record_task_completion(success=True)
        minimal_vessel.save()

        manager2 = VesselManager(local_path=minimal_vessel.vessel_dir)
        loaded = manager2.load()
        assert loaded.career.total_tasks_completed == 1
        assert loaded.career.total_tasks_failed == 0

    def test_record_task_completion_failure(self, minimal_vessel):
        """Failed task should increment failure counter."""
        minimal_vessel.record_task_completion(success=False)
        minimal_vessel.save()

        manager2 = VesselManager(local_path=minimal_vessel.vessel_dir)
        loaded = manager2.load()
        assert loaded.career.total_tasks_completed == 0
        assert loaded.career.total_tasks_failed == 1

    def test_auto_promotion_on_task_completion(self, minimal_vessel):
        """Completing enough tasks should auto-promote."""
        for _ in range(3):
            minimal_vessel.record_task_completion(success=True)
        assert minimal_vessel.state.career.current_stage == GrowthStage.APPRENTICE
        assert minimal_vessel.state.career.last_promoted is not None

    def test_complete_fence(self, minimal_vessel):
        """Fences should be recorded without duplicates."""
        minimal_vessel.complete_fence("gate-1")
        minimal_vessel.complete_fence("gate-1")  # duplicate
        minimal_vessel.complete_fence("gate-2")
        assert minimal_vessel.state.career.fences_completed == ["gate-1", "gate-2"]

    def test_acquire_skill(self, minimal_vessel):
        """Skills should be recorded without duplicates."""
        minimal_vessel.acquire_skill("Python")
        minimal_vessel.acquire_skill("Python")
        minimal_vessel.acquire_skill("Rust")
        assert minimal_vessel.state.career.skills_acquired == ["Python", "Rust"]

    def test_staleness_fresh_state(self, minimal_vessel):
        """Fresh state (no last_updated) should be stale."""
        assert minimal_vessel.is_stale() is True

    def test_staleness_recent_state(self, minimal_vessel):
        """State updated recently should not be stale."""
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        minimal_vessel.state.last_updated = now
        assert minimal_vessel.is_stale() is False

    def test_reset_clears_files(self, minimal_vessel):
        """Reset should remove all persisted files."""
        minimal_vessel.save()
        assert (minimal_vessel.vessel_dir / "IDENTITY.md").exists()

        minimal_vessel.reset()
        assert not (minimal_vessel.vessel_dir / "IDENTITY.md").exists()
        assert minimal_vessel.state.career.total_tasks_completed == 0


# ===================================================================
# TESTS: agent.py (13 tests)
# ===================================================================

class TestTaskModel:
    """Test Task data model and scoring."""

    def test_default_task(self):
        t = Task(id="t1", description="Do something")
        assert t.priority == TaskPriority.MEDIUM
        assert t.status == "pending"
        assert t.score > 0

    def task_score_priorities(self):
        """Critical tasks should score higher than info tasks."""
        critical = Task(id="t1", description="x", priority=TaskPriority.CRITICAL)
        info = Task(id="t2", description="x", priority=TaskPriority.INFO)
        assert critical.score > info.score

    def test_task_score_impact(self):
        """High-impact tasks should score higher."""
        high = Task(id="t1", description="x", impact_estimate="high")
        low = Task(id="t2", description="x", impact_estimate="low")
        assert high.score > low.score

    def test_task_score_effort(self):
        """Low-effort tasks should score higher than high-effort."""
        low = Task(id="t1", description="x", effort_estimate="low")
        high = Task(id="t2", description="x", effort_estimate="high")
        assert low.score > high.score


class TestPlan:
    """Test Plan sorting."""

    def test_sort_by_score(self):
        plan = Plan(tasks=[
            Task(id="t1", description="low", priority=TaskPriority.INFO),
            Task(id="t2", description="critical", priority=TaskPriority.CRITICAL),
            Task(id="t3", description="medium", priority=TaskPriority.MEDIUM),
        ])
        plan.sort_by_score()
        assert plan.tasks[0].id == "t2"
        assert plan.tasks[-1].id == "t1"


class TestAgent:
    """Test Agent lifecycle methods."""

    def _make_agent(self, vessel_dir, llm_response="test"):
        config = from_dict({
            "github_token": "ghp_test",
            "llm_provider": "openai",
            "llm_api_key": "sk-test",
            "vessel_repo": "test/vessel",
            "fleet_org": "test-org",
        })
        llm = DummyLLM(response=llm_response)
        github = DummyGitHub()
        vessel = VesselManager(local_path=vessel_dir, config=config)
        return Agent(config=config, llm=llm, github=github, vessel=vessel), github, llm

    def test_bootstrap_creates_vessel(self, vessel_dir):
        """Bootstrap should ensure vessel directory exists."""
        agent, _, _ = self._make_agent(vessel_dir)
        agent.bootstrap()
        assert vessel_dir.exists()

    def test_bootstrap_records_intro(self, vessel_dir):
        """Bootstrap should log an introduction worklog entry."""
        agent, _, _ = self._make_agent(vessel_dir)
        agent.bootstrap()
        assert len(agent.vessel.state.worklog) >= 1
        assert agent.vessel.state.worklog[0].action == "bootstrapped"

    def test_observe_empty(self, vessel_dir):
        """Observe with no fleet data should return empty observation."""
        agent, github, _ = self._make_agent(vessel_dir)
        agent.bootstrap()
        obs = agent.observe()
        assert isinstance(obs, Observation)
        assert obs.vessel_state is not None

    def test_observe_reads_bottles(self, vessel_dir):
        """Observe should read bottles from fleet repo."""
        agent, github, _ = self._make_agent(vessel_dir)
        github.bottles = [{"title": "hello", "content": "world"}]
        agent.bootstrap()
        obs = agent.observe()
        assert len(obs.bottles) == 1

    def test_observe_reads_tasks_md(self, vessel_dir):
        """Observe should parse TASKS.md from repos."""
        agent, github, _ = self._make_agent(vessel_dir)
        github.files["test/vessel/TASKS.md"] = (
            "- [ ] Fix the bug | priority:high | effort:low\n"
            "- [ ] Add feature | priority:medium\n"
            "- [x] Already done\n"
        )
        agent.bootstrap()
        obs = agent.observe()
        # The vessel_repo is "test/vessel" — it should observe its own TASKS.md
        assert len(obs.open_tasks) >= 2
        assert any("Fix the bug" in t.description for t in obs.open_tasks)

    def test_plan_generates_plan(self, vessel_dir):
        """Plan should produce a Plan object."""
        agent, _, llm = self._make_agent(vessel_dir)
        agent.bootstrap()
        agent.observe()
        plan = agent.plan()
        assert isinstance(plan, Plan)
        assert isinstance(plan.created_at, str)
        assert len(plan.created_at) > 0

    def test_push_bottle_no_fleet(self, vessel_dir):
        """Push bottle without fleet_org should return skipped."""
        config = from_dict({
            "github_token": "ghp_test",
            "llm_provider": "openai",
            "llm_api_key": "sk-test",
        })
        llm = DummyLLM()
        github = DummyGitHub()
        vessel = VesselManager(local_path=vessel_dir, config=config)
        agent = Agent(config=config, llm=llm, github=github, vessel=vessel)
        result = agent.push_bottle("hello")
        assert result["status"] == "skipped"

    def test_push_bottle_with_fleet(self, vessel_dir):
        """Push bottle with fleet_org should call github client."""
        agent, github, _ = self._make_agent(vessel_dir)
        agent.bootstrap()
        result = agent.push_bottle("Hello fleet!", title="Test")
        assert result["status"] == "created"
        assert len(github.bottles) == 1

    def test_update_vessel_persists(self, vessel_dir):
        """update_vessel should write files to disk."""
        agent, _, _ = self._make_agent(vessel_dir)
        agent.bootstrap()
        agent.vessel.state.identity.name = "Updated Name"
        agent.update_vessel()

        # Re-load and verify
        mgr = VesselManager(local_path=vessel_dir)
        loaded = mgr.load()
        assert loaded.identity.name == "Updated Name"

    def test_reflect_updates_career(self, vessel_dir):
        """Reflect should increment session count and save."""
        agent, _, _ = self._make_agent(vessel_dir)
        agent.bootstrap()
        agent.observe()
        agent.plan()

        reflection = agent.reflect()
        assert "Session Reflection" in reflection
        assert agent.vessel.state.career.sessions_completed == 1

    def test_run_full_cycle(self, vessel_dir):
        """Run should complete the full observe→plan→execute→communicate→reflect cycle."""
        agent, github, llm = self._make_agent(vessel_dir, llm_response="No tasks to suggest.")
        agent.bootstrap()

        # Provide a TASKS.md for observation
        github.files["test/vessel/TASKS.md"] = (
            "- [ ] Simple task | priority:high | effort:low\n"
        )

        reflection = agent.run(max_tasks=1)
        assert "Session Reflection" in reflection
        assert agent.vessel.state.career.sessions_completed == 1
        assert llm.call_count > 0

    def test_execute_task_success(self, vessel_dir):
        """Executing a valid task should create a branch and PR."""
        agent, github, llm = self._make_agent(vessel_dir, llm_response=json.dumps({
            "files": [{"path": "src/hello.py", "content": "print('hello')"}],
            "summary": "Added hello",
        }))
        agent.bootstrap()

        task = Task(
            id="t1",
            description="Add hello world",
            repo="test/vessel",
            priority=TaskPriority.HIGH,
        )
        success = agent.execute_task(task)
        assert success is True
        assert task.status == "completed"
        assert len(github.branches) == 1
        assert len(github.prs) == 1
        assert agent.vessel.state.career.total_tasks_completed == 1

    def test_execute_task_no_repo(self, vessel_dir):
        """Executing a task without a repo should fail gracefully."""
        agent, _, _ = self._make_agent(vessel_dir)
        agent.bootstrap()

        task = Task(id="t2", description="No repo task", repo=None)
        success = agent.execute_task(task)
        assert success is False
        assert task.status == "failed"

    def test_parse_tasks_md(self, vessel_dir):
        """TASKS.md parsing should extract tasks with correct metadata."""
        agent, _, _ = self._make_agent(vessel_dir)
        agent.bootstrap()

        tasks_md = (
            "- [ ] Critical fix | priority:critical | effort:low | impact:high\n"
            "- [ ] Normal task | priority:medium\n"
            "- [ ] Info item | priority:info | effort:high\n"
            "- [x] Completed task | priority:high\n"
            "- Regular text line\n"
        )
        tasks = agent._parse_tasks_md(tasks_md, "owner/repo")

        assert len(tasks) == 3  # 3 unchecked tasks
        assert tasks[0].priority == TaskPriority.CRITICAL
        assert tasks[0].effort_estimate == "low"
        assert tasks[0].impact_estimate == "high"
        assert tasks[1].priority == TaskPriority.MEDIUM
        assert tasks[2].priority == TaskPriority.INFO
        assert tasks[2].effort_estimate == "high"

    def test_parallel_execution(self, vessel_dir):
        """execute_parallel should run multiple tasks and return results."""
        agent, github, llm = self._make_agent(vessel_dir, llm_response=json.dumps({
            "files": [{"path": "f.txt", "content": "data"}],
            "summary": "done",
        }))
        agent.bootstrap()

        tasks = [
            Task(id=f"p{i}", description=f"Parallel task {i}", repo="test/vessel")
            for i in range(3)
        ]
        results = agent.execute_parallel(tasks, max_workers=2)
        assert len(results) == 2  # capped by workers
        assert all(isinstance(v, bool) for v in results.values())

    def test_generate_branch_name(self, vessel_dir):
        """Branch names should be safe git refs."""
        agent, _, _ = self._make_agent(vessel_dir)
        task = Task(id="t1", description="Fix bug in user auth flow!")
        name = agent._generate_branch_name(task)
        assert name.startswith("agent/")
        assert "!" not in name
        assert len(name) <= 60


# ===================================================================
# Run tests
# ===================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
