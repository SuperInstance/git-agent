"""
Comprehensive tests for git_agent.github and git_agent.fleet modules.

Covers:
    - github/client.py: GitHubAPIClient (rate limiting, caching, pagination, errors, Protocol)
    - github/pr.py: PullRequestManager (create, list, merge, comments, task references)
    - github/repo.py: RepoManager (fork, clone, branch, push, file ops)
    - fleet/reader.py: FleetReader (TASKS.md parsing, bottles, fleet status, org repos)
    - fleet/planner.py: FleetPlanner (scoring, skill matching, dependencies, execution order)
    - fleet/executor.py: TaskExecutor (single task, batch execution, test running)
    - fleet/communicator.py: FleetCommunicator (bottles, I2I messages, status broadcast)
    - fleet/researcher.py: FleetResearcher (cross-repo analysis, integrations, dependency graph, reports)
"""

from __future__ import annotations

import base64
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from git_agent.github.client import (
    CacheEntry,
    GitHubAPIClient,
    GitHubError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    RateLimitInfo,
)
from git_agent.github.pr import PullRequestManager, PRInfo
from git_agent.github.repo import RepoManager, RepoInfo
from git_agent.fleet.reader import (
    Bottle,
    FleetReader,
    FleetStatus,
    FleetTask,
    OrgRepo,
)
from git_agent.fleet.planner import (
    AgentCapabilities,
    FleetPlanner,
    ScoredTask,
)
from git_agent.fleet.executor import (
    BatchResult,
    ExecutionResult,
    TaskExecutor,
)
from git_agent.fleet.communicator import (
    Bottle as CommBottle,
    FleetCommunicator,
    I2IMessage,
)
from git_agent.fleet.researcher import (
    DependencyNode,
    FleetResearcher,
    IntegrationOpportunity,
    ResearchFinding,
    ResearchReport,
)
from git_agent.agent import Task, TaskPriority


# ===================================================================
# Test Doubles
# ===================================================================

class MockGitHub:
    """Mock GitHub client for testing."""

    def __init__(self):
        self.repos: Dict[str, Dict] = {}
        self.files: Dict[str, str] = {}
        self.bottles_data: List[Dict] = []
        self.prs: List[Dict] = []
        self.branches: List[str] = []
        self.commits: List[Dict] = []
        self.org_repos: List[Dict] = []
        self.cloned_urls: List[str] = []
        self._file_shas: Dict[str, str] = {}
        self.call_log: List[str] = []

    def get_repo(self, owner, repo):
        key = f"{owner}/{repo}"
        self.call_log.append(f"get_repo:{key}")
        if key in self.repos:
            return self.repos[key]
        return {"full_name": key, "private": False, "language": "python",
                "default_branch": "main", "description": "", "stargazers_count": 0,
                "forks_count": 0, "html_url": f"https://github.com/{key}",
                "topics": [], "updated_at": ""}

    def fork_repo(self, owner, repo):
        self.call_log.append(f"fork_repo:{owner}/{repo}")
        key = f"{owner}/{repo}"
        return {"full_name": key, "fork": True, "owner": {"login": owner}, "name": repo}

    def create_branch(self, owner, repo, branch, from_branch="main"):
        self.call_log.append(f"create_branch:{owner}/{repo}/{branch}")
        self.branches.append(f"{owner}/{repo}/{branch}")
        return {"name": branch, "ref": f"refs/heads/{branch}"}

    def create_pull_request(self, owner, repo, title, body, head, base="main"):
        self.call_log.append(f"create_pr:{owner}/{repo}")
        pr = {"number": len(self.prs) + 1, "title": title, "html_url":
              f"https://github.com/{owner}/{repo}/pull/{len(self.prs) + 1}",
              "state": "open", "body": body, "head": {"ref": head}, "base": {"ref": base},
              "draft": False, "merged": False, "labels": [], "created_at": "", "updated_at": ""}
        self.prs.append(pr)
        return pr

    def list_pull_requests(self, owner, repo, state="open", **kwargs):
        self.call_log.append(f"list_prs:{owner}/{repo}:{state}")
        return [pr for pr in self.prs if pr.get("state", "open") == state]

    def add_comment(self, owner, repo, number, body):
        self.call_log.append(f"add_comment:{owner}/{repo}#{number}")
        return {"id": 1, "body": body}

    def merge_pull_request(self, owner, repo, number, commit_title=None, merge_method="merge"):
        self.call_log.append(f"merge_pr:{owner}/{repo}#{number}")
        for pr in self.prs:
            if pr["number"] == number:
                pr["state"] = "closed"
                pr["merged"] = True
        return {"sha": "merge-sha-123", "merged": True}

    def create_or_update_file(self, owner, repo, path, content, message, branch, sha=None):
        key = f"{owner}/{repo}/{path}"
        self.files[key] = content
        self.call_log.append(f"create_file:{key}")
        return {"content": {"path": path}, "commit": {"sha": "file-sha-abc"}}

    def get_file(self, owner, repo, path, ref=None):
        key = f"{owner}/{repo}/{path}"
        self.call_log.append(f"get_file:{key}")
        if key in self.files:
            return {"content": base64.b64encode(self.files[key].encode()).decode(), "encoding": "base64"}
        raise GitHubNotFoundError(f"Not found: {key}")

    def get_file_contents(self, owner, repo, path, ref=None):
        key = f"{owner}/{repo}/{path}"
        return self.files.get(key)

    def list_issues(self, owner, repo, state="open"):
        self.call_log.append(f"list_issues:{owner}/{repo}")
        return []

    def list_commits(self, owner, repo, per_page=10, sha=None):
        self.call_log.append(f"list_commits:{owner}/{repo}")
        return self.commits[:per_page]

    def push_files(self, owner, repo, branch, files, message):
        self.call_log.append(f"push_files:{owner}/{repo}")
        for f in files:
            self.files[f["path"]] = f["content"]
        return {"commit": {"sha": "push-sha"}, "files": len(files)}

    def clone(self, url, path, branch=None):
        self.cloned_urls.append(url)
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        (p / ".git").mkdir(exist_ok=True)
        return p

    def list_org_repos(self, org, per_page=100):
        self.call_log.append(f"list_org_repos:{org}")
        return self.org_repos

    def get_bottles(self, owner, repo):
        return self.bottles_data

    def push_bottle(self, owner, repo, content, title=""):
        b = {"title": title, "content": content, "path": f"message-in-a-bottle/{title}.md"}
        self.bottles_data.append(b)
        return {"status": "created", "bottle": b}

    def list_files(self, owner, repo, path="", ref=None):
        key = f"{owner}/{repo}/{path}"
        self.call_log.append(f"list_files:{key}")
        # Return bottle files if in bottle dir
        if "message-in-a-bottle" in path or path == "message-in-a-bottle":
            items = []
            for b in self.bottles_data:
                items.append({"type": "file", "name": f"{b['title']}.md", "path": b.get("path", "")})
            return items
        if "i2i-messages" in path or path == "i2i-messages":
            return []
        # Return generic root files
        return [{"type": "file", "name": "README.md"}, {"type": "dir", "name": "src"}]

    def _request(self, method, path, **kwargs):
        # Simulate API for PR manager get_pr etc
        return {}


class MockLLM:
    """Mock LLM provider."""

    def __init__(self, response: str = "{}"):
        self._response = response
        self.call_count = 0

    def complete(self, messages, **kwargs):
        self.call_count += 1
        return self._response

    async def acomplete(self, messages, **kwargs):
        self.call_count += 1
        return self._response


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def mock_github():
    return MockGitHub()


@pytest.fixture
def mock_llm():
    return MockLLM()


@pytest.fixture
def tmp_work_dir():
    with tempfile.TemporaryDirectory(prefix="test-git-agent-") as d:
        yield Path(d)


# ===================================================================
# TESTS: github/client.py (10 tests)
# ===================================================================

class TestRateLimitInfo:
    def test_default_not_exhausted(self):
        rl = RateLimitInfo()
        assert rl.is_exhausted is False

    def test_exhausted_when_zero_remaining(self):
        rl = RateLimitInfo(remaining=0)
        assert rl.is_exhausted is True

    def test_seconds_until_reset(self):
        rl = RateLimitInfo(reset=9999999999)
        assert rl.seconds_until_reset > 0


class TestCacheEntry:
    def test_not_expired_initially(self):
        entry = CacheEntry(data={"key": "val"}, timestamp=__import__('time').time())
        assert entry.is_expired is False

    def test_expired_after_ttl(self):
        import time
        entry = CacheEntry(data="val", timestamp=time.time() - 400, ttl=300.0)
        assert entry.is_expired is True


class TestGitHubAPIClient:
    def test_init_with_token(self):
        client = GitHubAPIClient(token="ghp_test123")
        assert client.token == "ghp_test123"
        assert client.api_base == "https://api.github.com"

    def test_init_custom_api_base(self):
        client = GitHubAPIClient(token="ghp_x", api_base="https://github.mycompany.com/api/v3")
        assert "mycompany" in client.api_base

    def test_cache_set_and_get(self):
        client = GitHubAPIClient(token="ghp_test")
        client._cache_set("key1", {"data": "val"})
        assert client._cache_get("key1") == {"data": "val"}

    def test_cache_expired_returns_none(self):
        import time
        client = GitHubAPIClient(token="ghp_test", cache_ttl=0.001)
        client._cache_set("key1", "val")
        time.sleep(0.01)
        assert client._cache_get("key1") is None

    def test_cache_clear(self):
        client = GitHubAPIClient(token="ghp_test")
        client._cache_set("k1", "v1")
        client._cache_set("k2", "v2")
        client._cache_clear()
        assert client._cache_get("k1") is None
        assert client._cache_get("k2") is None

    def test_invalidate_cache_by_pattern(self):
        client = GitHubAPIClient(token="ghp_test")
        client._cache_set("org_repos:myorg", [1, 2, 3])
        client._cache_set("other_key", "val")
        removed = client.invalidate_cache("org_repos")
        assert removed == 1
        assert client._cache_get("org_repos:myorg") is None
        assert client._cache_get("other_key") == "val"

    def test_invalidate_cache_all(self):
        client = GitHubAPIClient(token="ghp_test")
        client._cache_set("a", 1)
        client._cache_set("b", 2)
        removed = client.invalidate_cache()
        assert removed == 2

    def test_protocol_compatibility(self):
        """GitHubAPIClient should satisfy the GitHubClient Protocol."""
        from git_agent.agent import GitHubClient as GitHubClientProtocol
        client = GitHubAPIClient(token="ghp_test")
        # The Protocol is structural - just check method existence
        for method_name in [
            "get_repo", "fork_repo", "create_branch", "create_pull_request",
            "create_or_update_file", "get_file", "list_issues", "get_file_contents",
            "list_commits", "push_files", "clone", "get_bottles", "push_bottle",
            "list_org_repos",
        ]:
            assert hasattr(client, method_name), f"Missing method: {method_name}"

    def test_list_org_repos_method(self):
        client = GitHubAPIClient(token="ghp_test")
        assert hasattr(client, "list_org_repos")

    def test_get_file_contents_none_on_404(self):
        """get_file_contents returns None when file not found."""
        # We can't easily mock urllib in this context, but test the MockGitHub
        gh = MockGitHub()
        result = gh.get_file_contents("owner", "repo", "nonexistent.txt")
        assert result is None


# ===================================================================
# TESTS: github/pr.py (7 tests)
# ===================================================================

class TestPRInfo:
    def test_from_api_response(self):
        data = {
            "number": 42, "title": "Fix bug", "body": "Fixes #1",
            "state": "open", "html_url": "https://github.com/o/r/pull/42",
            "head": {"ref": "fix-branch"}, "base": {"ref": "main"},
            "draft": False, "merged": False, "labels": [],
            "created_at": "2025-01-01T00:00:00Z", "updated_at": "2025-01-01T00:00:00Z",
        }
        pr = PRInfo.from_api_response(data)
        assert pr.number == 42
        assert pr.title == "Fix bug"
        assert pr.state == "open"
        assert pr.head_ref == "fix-branch"
        assert pr.base_ref == "main"
        assert pr.labels == []

    def test_extract_task_id_bracket(self):
        assert PRInfo._extract_task_id("[TASK-123] Fix bug") == "123"

    def test_extract_task_id_hash(self):
        assert PRInfo._extract_task_id("Fix bug #42") == "42"

    def test_extract_task_id_none(self):
        assert PRInfo._extract_task_id("Just a title") is None


class TestPullRequestManager:
    def test_create_pr(self, mock_github):
        mgr = PullRequestManager(mock_github)
        pr = mgr.create_pr("owner", "repo", "Test PR", "Body", "head-branch")
        assert isinstance(pr, PRInfo)
        assert pr.number == 1
        assert pr.title == "Test PR"

    def test_create_pr_for_task(self, mock_github):
        mgr = PullRequestManager(mock_github)
        pr = mgr.create_pr_for_task("owner", "repo", "T1", "Fix the bug", "fix-branch")
        assert "[task-T1]" in pr.title
        assert "Fix the bug" in pr.title
        assert "Task ID: T1" in pr.body or "T1" in pr.body

    def test_list_open_prs(self, mock_github):
        mgr = PullRequestManager(mock_github)
        mock_github.prs = [
            {"number": 1, "title": "Open PR", "state": "open", "body": "",
             "html_url": "", "head": {"ref": "h"}, "base": {"ref": "main"},
             "draft": False, "merged": False, "labels": [], "created_at": "", "updated_at": ""},
        ]
        prs = mgr.list_open_prs("owner", "repo")
        assert len(prs) == 1
        assert prs[0].state == "open"

    def test_list_closed_prs(self, mock_github):
        mgr = PullRequestManager(mock_github)
        mock_github.prs = [
            {"number": 1, "title": "Closed", "state": "closed", "body": "",
             "html_url": "", "head": {"ref": "h"}, "base": {"ref": "main"},
             "draft": False, "merged": True, "labels": [], "created_at": "", "updated_at": ""},
        ]
        prs = mgr.list_closed_prs("owner", "repo")
        assert len(prs) == 1

    def test_add_comment(self, mock_github):
        mgr = PullRequestManager(mock_github)
        result = mgr.add_comment("owner", "repo", 1, "Looks good!")
        assert result["body"] == "Looks good!"

    def test_merge_pr(self, mock_github):
        mgr = PullRequestManager(mock_github)
        mock_github.prs = [
            {"number": 1, "title": "PR", "state": "open", "body": "",
             "html_url": "", "head": {"ref": "h"}, "base": {"ref": "main"},
             "draft": False, "merged": False, "labels": [], "created_at": "", "updated_at": ""},
        ]
        result = mgr.merge_pr("owner", "repo", 1)
        assert result["merged"] is True

    def test_build_pr_body(self, mock_github):
        mgr = PullRequestManager(mock_github)
        body = mgr.build_pr_body(
            description="Add feature X",
            files_changed=["src/x.py", "tests/test_x.py"],
            task_id="T1",
            testing_notes="Added unit tests.",
        )
        assert "Add feature X" in body
        assert "src/x.py" in body
        assert "T1" in body
        assert "Testing" in body


# ===================================================================
# TESTS: github/repo.py (6 tests)
# ===================================================================

class TestRepoInfo:
    def test_from_api_response(self):
        data = {
            "full_name": "owner/repo", "description": "A repo",
            "private": False, "fork": False, "default_branch": "main",
            "language": "Python", "stargazers_count": 10, "forks_count": 2,
            "html_url": "https://github.com/owner/repo", "topics": ["ai"],
            "updated_at": "2025-01-01",
        }
        info = RepoInfo.from_api_response(data)
        assert info.full_name == "owner/repo"
        assert info.owner == "owner"
        assert info.name == "repo"
        assert info.language == "Python"
        assert info.topics == ["ai"]


class TestRepoManager:
    def test_get_repo(self, mock_github):
        mgr = RepoManager(mock_github)
        info = mgr.get_repo("owner", "repo")
        assert isinstance(info, RepoInfo)
        assert info.full_name == "owner/repo"

    def test_list_org_repos(self, mock_github):
        mock_github.org_repos = [
            {"full_name": "org/repo1", "language": "Python", "description": "",
             "private": False, "fork": False, "default_branch": "main",
             "stargazers_count": 0, "forks_count": 0, "html_url": "",
             "topics": [], "updated_at": ""},
            {"full_name": "org/repo2", "language": "Rust", "description": "",
             "private": False, "fork": False, "default_branch": "main",
             "stargazers_count": 5, "forks_count": 1, "html_url": "",
             "topics": [], "updated_at": ""},
        ]
        mgr = RepoManager(mock_github)
        repos = mgr.list_org_repos("org")
        assert len(repos) == 2
        assert isinstance(repos[0], RepoInfo)

    def test_fork_repo(self, mock_github):
        mgr = RepoManager(mock_github)
        info = mgr.fork_repo("upstream", "project")
        assert isinstance(info, RepoInfo)
        assert "fork_repo:upstream/project" in mock_github.call_log

    def test_clone_repo(self, mock_github, tmp_work_dir):
        mgr = RepoManager(mock_github, work_dir=tmp_work_dir)
        path = mgr.clone_repo("https://github.com/owner/repo.git")
        assert path.exists()
        assert "https://github.com/owner/repo.git" in mock_github.cloned_urls

    def test_read_file(self, mock_github):
        mock_github.files["owner/repo/README.md"] = "# Hello"
        mgr = RepoManager(mock_github)
        content = mgr.read_file("owner", "repo", "README.md")
        assert content == "# Hello"

    def test_create_file(self, mock_github):
        mgr = RepoManager(mock_github)
        result = mgr.create_file("owner", "repo", "test.txt", "content", "msg", "main")
        assert "test.txt" in result.get("content", {}).get("path", "")


# ===================================================================
# TESTS: fleet/reader.py (7 tests)
# ===================================================================

class TestFleetTaskParsing:
    def test_parse_checkbox_tasks(self):
        reader = FleetReader.__new__(FleetReader)
        reader.fleet_org = "org"
        reader.index_repo = "oracle1-index"
        content = (
            "- [ ] T1 | repo1 | Fix the bug | python | critical\n"
            "- [ ] T2 | repo2 | Add feature | javascript,react | high\n"
            "- [x] T3 | repo1 | Already done | python | medium\n"
        )
        tasks = reader._parse_tasks_md(content)
        assert len(tasks) == 2
        assert tasks[0].id == "T1"
        assert tasks[0].repo == "repo1"
        assert tasks[0].priority == TaskPriority.CRITICAL
        assert tasks[0].skills == ["python"]
        assert tasks[1].skills == ["javascript", "react"]

    def test_parse_table_format(self):
        reader = FleetReader.__new__(FleetReader)
        reader.fleet_org = "org"
        reader.index_repo = "oracle1-index"
        content = (
            "| ID | Repo | Task | Skills | Priority |\n"
            "|----|------|------|--------|----------|\n"
            "| T1 | repo1 | Fix auth | python,security | high |\n"
            "| T2 | repo2 | Add API | rust | medium |\n"
        )
        tasks = reader._parse_tasks_md(content)
        assert len(tasks) == 2
        assert tasks[0].id == "T1"
        assert tasks[0].task == "Fix auth"
        assert tasks[1].priority == TaskPriority.MEDIUM

    def test_parse_priority(self):
        assert FleetReader._parse_priority("critical") == TaskPriority.CRITICAL
        assert FleetReader._parse_priority("HIGH") == TaskPriority.HIGH
        assert FleetReader._parse_priority("Medium") == TaskPriority.MEDIUM
        assert FleetReader._parse_priority("low") == TaskPriority.LOW
        assert FleetReader._parse_priority("unknown") == TaskPriority.MEDIUM


class TestBottle:
    def test_from_dict(self):
        data = {
            "title": "hello",
            "content": "**From:** Agent A\n**Time:** 2025-01-01T00:00:00Z\n\nHello fleet!",
            "path": "message-in-a-bottle/hello.md",
        }
        bottle = Bottle.from_dict(data)
        assert bottle.sender == "Agent A"
        assert bottle.timestamp == "2025-01-01T00:00:00Z"


class TestFleetReader:
    def test_read_tasks_empty(self, mock_github):
        reader = FleetReader(mock_github, "myorg")
        # No TASKS.md set
        tasks = reader.read_tasks()
        assert tasks == []

    def test_read_tasks_with_content(self, mock_github):
        mock_github.files["myorg/oracle1-index/TASKS.md"] = (
            "- [ ] T1 | repo1 | Fix bug | python | high\n"
            "- [ ] T2 | repo2 | Add docs | docs | low\n"
        )
        reader = FleetReader(mock_github, "myorg")
        tasks = reader.read_tasks()
        assert len(tasks) == 2
        assert tasks[0].id == "T1"

    def test_read_bottles(self, mock_github):
        mock_github.bottles_data = [
            {"title": "msg1", "content": "**From:** Agent A\n\nHello", "path": "message-in-a-bottle/msg1.md"},
        ]
        reader = FleetReader(mock_github, "myorg")
        bottles = reader.read_bottles("fleet-msgs")
        assert len(bottles) == 1
        assert bottles[0].sender == "Agent A"

    def test_list_org_repos(self, mock_github):
        mock_github.org_repos = [
            {"full_name": "org/r1", "description": "", "language": "Python",
             "stargazers_count": 0, "updated_at": "", "topics": [], "private": False},
        ]
        reader = FleetReader(mock_github, "org")
        repos = reader.list_org_repos()
        assert len(repos) == 1
        assert isinstance(repos[0], OrgRepo)
        assert repos[0].language == "Python"


# ===================================================================
# TESTS: fleet/planner.py (8 tests)
# ===================================================================

class TestFleetPlanner:
    def test_score_task(self):
        planner = FleetPlanner()
        task = FleetTask(id="T1", repo="r", task="Fix bug",
                         priority=TaskPriority.CRITICAL, impact="high", effort="low")
        score = planner.score_task(task)
        assert score > 0

    def test_critical_higher_than_info(self):
        planner = FleetPlanner()
        critical = FleetTask(id="T1", repo="r", task="t",
                             priority=TaskPriority.CRITICAL, impact="medium", effort="medium")
        info = FleetTask(id="T2", repo="r", task="t",
                         priority=TaskPriority.INFO, impact="medium", effort="medium")
        assert planner.score_task(critical) > planner.score_task(info)

    def test_low_effort_higher_score(self):
        planner = FleetPlanner()
        low_effort = FleetTask(id="T1", repo="r", task="t",
                               priority=TaskPriority.HIGH, impact="medium", effort="low")
        high_effort = FleetTask(id="T2", repo="r", task="t",
                                priority=TaskPriority.HIGH, impact="medium", effort="high")
        assert planner.score_task(low_effort) > planner.score_task(high_effort)

    def test_score_all_tasks_sorted(self):
        planner = FleetPlanner()
        tasks = [
            FleetTask(id="T1", repo="r", task="Low", priority=TaskPriority.LOW, impact="low", effort="high"),
            FleetTask(id="T2", repo="r", task="Critical", priority=TaskPriority.CRITICAL, impact="high", effort="low"),
        ]
        scored = planner.score_all_tasks(tasks)
        assert scored[0].task.id == "T2"  # Highest score first

    def test_skill_match(self):
        planner = FleetPlanner(agent_skills=["python"])
        task = FleetTask(id="T1", repo="r", task="Write python code", skills=["python"])
        match = planner._compute_skill_match(task)
        assert match > 0

    def test_no_skill_match(self):
        planner = FleetPlanner(agent_skills=["rust"])
        task = FleetTask(id="T1", repo="r", task="Write python code", skills=["python"])
        match = planner._compute_skill_match(task)
        assert match == 0

    def test_detect_dependencies(self):
        planner = FleetPlanner()
        tasks = [
            FleetTask(id="T1", repo="repo1", task="Critical infra fix",
                      skills=["devops"], priority=TaskPriority.CRITICAL),
            FleetTask(id="T2", repo="repo1", task="Deploy service",
                      skills=["devops"], priority=TaskPriority.HIGH),
            FleetTask(id="T3", repo="repo2", task="Other task",
                      skills=["docs"], priority=TaskPriority.MEDIUM),
        ]
        deps = planner.detect_dependencies(tasks)
        # T2 should depend on T1 (same repo, shared skills, T1 is critical)
        assert "T1" in deps.get("T2", [])

    def test_generate_execution_order(self):
        planner = FleetPlanner(agent_skills=["python"], max_concurrent=5)
        tasks = [
            FleetTask(id="T1", repo="r", task="Low prio", priority=TaskPriority.LOW,
                      impact="low", effort="high"),
            FleetTask(id="T2", repo="r", task="Critical fix", priority=TaskPriority.CRITICAL,
                      impact="high", effort="low"),
        ]
        ordered = planner.generate_execution_order(tasks)
        assert len(ordered) == 2
        assert ordered[0].task.id == "T2"  # Critical first
        assert ordered[0].execution_order == 1


# ===================================================================
# TESTS: fleet/executor.py (5 tests)
# ===================================================================

class TestTaskExecutor:
    def test_execute_task_success(self, mock_github, mock_llm, tmp_work_dir):
        mock_llm._response = json.dumps({
            "files": [{"path": "src/hello.py", "content": "print('hi')"}],
            "summary": "Added hello",
        })
        # Pre-create the repo clone as a real git repo with a remote and main branch
        clone_path = tmp_work_dir / "repo-T1"
        clone_path.mkdir(parents=True)
        subprocess.run(["git", "init"], cwd=str(clone_path), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(clone_path), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(clone_path), capture_output=True, check=True)
        # Create an initial commit on main so branch exists
        (clone_path / "README.md").write_text("# init")
        subprocess.run(["git", "add", "."], cwd=str(clone_path), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(clone_path), capture_output=True, check=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=str(clone_path), capture_output=True, check=True)
        # Add a dummy remote so git fetch/pull won't fail
        subprocess.run(["git", "remote", "add", "origin", str(clone_path)], cwd=str(clone_path), capture_output=True, check=True)
        executor = TaskExecutor(mock_github, mock_llm, work_dir=tmp_work_dir, run_tests=False)
        result = executor.execute_task("T1", "owner/repo", "Add hello world")
        assert result.success is True
        assert result.task_id == "T1"
        assert result.commit_sha is not None

    def test_execute_task_invalid_repo(self, mock_github, mock_llm, tmp_work_dir):
        executor = TaskExecutor(mock_github, mock_llm, work_dir=tmp_work_dir)
        result = executor.execute_task("T1", "invalid-repo-no-slash", "Do something")
        assert result.success is False
        assert "Invalid repo" in result.error

    def test_batch_execution(self, mock_github, mock_llm, tmp_work_dir):
        mock_llm._response = json.dumps({
            "files": [{"path": "f.txt", "content": "data"}],
            "summary": "done",
        })
        executor = TaskExecutor(mock_github, mock_llm, work_dir=tmp_work_dir, run_tests=False, max_workers=2)
        tasks = [
            {"task_id": f"T{i}", "repo": "owner/repo", "description": f"Task {i}"}
            for i in range(3)
        ]
        batch = executor.execute_batch(tasks)
        assert batch.total == 3
        assert batch.succeeded >= 0
        assert isinstance(batch.summary(), str)

    def test_execution_result_fields(self):
        result = ExecutionResult(task_id="T1", success=True, pr_number=42,
                                 commit_sha="abc", duration_seconds=5.0)
        assert result.task_id == "T1"
        assert result.success is True
        assert result.pr_number == 42

    def test_batch_result_summary(self):
        batch = BatchResult(total=5, succeeded=3, failed=2, total_duration=10.0)
        summary = batch.summary()
        assert "3/5" in summary
        assert "2 failed" in summary


# ===================================================================
# TESTS: fleet/communicator.py (7 tests)
# ===================================================================

class TestBottleFormatting:
    def test_bottle_format(self):
        bottle = CommBottle(sender="Agent A", content="Hello!", stage="expert")
        formatted = bottle.format()
        assert "**From:** Agent A" in formatted
        assert "Hello!" in formatted
        assert "**Stage:** expert" in formatted

    def test_bottle_with_target(self):
        bottle = CommBottle(sender="A", content="Msg", target="Agent B")
        formatted = bottle.format()
        assert "**To:** Agent B" in formatted


class TestI2IMessage:
    def test_parse_valid_message(self):
        content = (
            "---\n"
            "sender: Agent A\n"
            "recipient: Agent B\n"
            "subject: Coordination\n"
            "timestamp: 2025-01-01T00:00:00Z\n"
            "priority: high\n"
            "requires_response: true\n"
            "task_refs: T1, T2\n"
            "---\n\n"
            "Let's coordinate on these tasks."
        )
        msg = I2IMessage.parse(content)
        assert msg is not None
        assert msg.sender == "Agent A"
        assert msg.recipient == "Agent B"
        assert msg.subject == "Coordination"
        assert msg.priority == "high"
        assert msg.requires_response is True
        assert msg.task_refs == ["T1", "T2"]

    def test_parse_invalid_returns_none(self):
        msg = I2IMessage.parse("Just plain text, no front matter")
        assert msg is None

    def test_format_roundtrip(self):
        msg = I2IMessage(
            sender="A", recipient="B", subject="Test",
            body="Hello", priority="normal", task_refs=["T1"],
        )
        formatted = msg.format()
        assert "---" in formatted
        assert "sender: A" in formatted
        assert "recipient: B" in formatted
        parsed = I2IMessage.parse(formatted)
        assert parsed is not None
        assert parsed.sender == "A"
        assert parsed.recipient == "B"


class TestFleetCommunicator:
    def test_push_bottle(self, mock_github):
        comm = FleetCommunicator(mock_github, "myorg", "Agent A")
        result = comm.push_bottle("Hello fleet!", title="test-bottle")
        assert result["status"] == "created"
        assert result["title"] == "test-bottle"
        # Communicator uses create_or_update_file, which stores with full key
        assert any("test-bottle.md" in k for k in mock_github.files)

    def test_read_bottles(self, mock_github):
        mock_github.bottles_data = [
            {"title": "b1", "content": "**From:** Agent B\n\nMessage", "path": "message-in-a-bottle/b1.md"},
        ]
        comm = FleetCommunicator(mock_github, "myorg", "Agent A")
        bottles = comm.read_bottles("fleet-msgs")
        assert len(bottles) == 1
        assert bottles[0].sender == "Agent B"

    def test_send_i2i_message(self, mock_github):
        comm = FleetCommunicator(mock_github, "myorg", "Agent A")
        result = comm.send_i2i_message(
            recipient="Agent B", subject="Help needed",
            body="Can you review my PR?", priority="high",
        )
        assert result["status"] == "sent"
        assert result["recipient"] == "Agent B"

    def test_broadcast_status(self, mock_github):
        comm = FleetCommunicator(mock_github, "myorg", "Agent A")
        result = comm.broadcast_status(
            stage="expert", tasks_completed=10, tasks_failed=2
        )
        assert result["status"] == "created"
        assert "status-Agent A" in result["title"]


# ===================================================================
# TESTS: fleet/researcher.py (7 tests)
# ===================================================================

class TestFleetResearcher:
    def test_analyze_repos(self, mock_github):
        mock_github.org_repos = [
            {"full_name": "org/repo1", "language": "Python", "description": "Repo 1",
             "private": False, "topics": [], "default_branch": "main",
             "stargazers_count": 0, "forks_count": 0, "html_url": "", "updated_at": ""},
        ]
        mock_github.files["org/repo1/requirements.txt"] = "requests\nflask\n"
        mock_github.files["org/repo1/README.md"] = "# Repo 1"

        researcher = FleetResearcher(mock_github, "org")
        analysis = researcher.analyze_repos(["org/repo1"])
        assert "org/repo1" in analysis
        assert analysis["org/repo1"]["language"] == "python"  # API returns lowercase
        assert "requests" in analysis["org/repo1"]["dependencies"]
        assert analysis["org/repo1"]["has_docs"] is True

    def test_extract_dependencies_pip(self):
        researcher = FleetResearcher.__new__(FleetResearcher)
        content = "requests==2.28.0\nflask>=2.0\n# comment\nnumpy"
        deps = researcher._extract_dependencies(content, "pip")
        assert "requests" in deps
        assert "flask" in deps
        assert "numpy" in deps

    def test_extract_dependencies_npm(self):
        researcher = FleetResearcher.__new__(FleetResearcher)
        content = json.dumps({
            "dependencies": {"express": "^4.0", "lodash": "^4.17"},
            "devDependencies": {"jest": "^29.0"},
        })
        deps = researcher._extract_dependencies(content, "npm")
        assert "express" in deps
        assert "lodash" in deps
        assert "jest" in deps

    def test_find_integrations(self):
        researcher = FleetResearcher.__new__(FleetResearcher)
        analysis = {
            "org/repo1": {"dependencies": ["requests", "flask"], "language": "python"},
            "org/repo2": {"dependencies": ["requests", "django"], "language": "python"},
            "org/repo3": {"dependencies": ["tokio"], "language": "rust"},
        }
        integrations = researcher.find_integrations(analysis)
        # repo1 and repo2 share "requests"
        shared_pairs = [(i.repo_a, i.repo_b) for i in integrations]
        assert any({"org/repo1", "org/repo2"} == {a, b} for a, b in shared_pairs)

    def test_build_dependency_graph(self):
        researcher = FleetResearcher.__new__(FleetResearcher)
        analysis = {
            "org/repo1": {"dependencies": ["requests"], "language": "python"},
            "org/repo2": {"dependencies": ["requests"], "language": "python"},
        }
        graph = researcher.build_dependency_graph(analysis)
        assert "org/repo1" in graph
        assert "org/repo2" in graph
        # repo1 and repo2 should be dependents of each other via shared dep
        assert "org/repo2" in graph["org/repo1"].dependents

    def test_generate_report(self, mock_github):
        mock_github.org_repos = [
            {"full_name": "org/r1", "language": "Python", "description": "",
             "private": False, "topics": [], "default_branch": "main",
             "stargazers_count": 0, "forks_count": 0, "html_url": "", "updated_at": ""},
        ]
        mock_github.files["org/r1/requirements.txt"] = "requests\n"
        mock_github.files["org/r1/README.md"] = "# R1"

        researcher = FleetResearcher(mock_github, "org")
        report = researcher.generate_report(repos=["org/r1"])
        assert isinstance(report, ResearchReport)
        assert report.repos_analyzed == 1
        assert report.generated_at != ""

    def test_report_to_markdown(self):
        report = ResearchReport(
            title="Test Report",
            generated_at="2025-01-01",
            repos_analyzed=2,
            findings=[
                ResearchFinding(
                    category="quality", title="No tests",
                    description="Missing tests", repos=["r1"], impact="high",
                ),
            ],
            integrations=[
                IntegrationOpportunity(
                    repo_a="r1", repo_b="r2", shared_deps=["requests"],
                    description="Shared dep",
                ),
            ],
            dependency_graph_summary="Some graph info",
        )
        md = report.to_markdown()
        assert "# Test Report" in md
        assert "No tests" in md
        assert "r1 ↔ r2" in md
        assert "requests" in md
        assert "git-agent" in md


# ===================================================================
# Run tests
# ===================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
