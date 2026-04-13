"""
git_agent.fleet.executor — Parallel task execution engine.

Handles the full lifecycle of task execution:
    1. Clone target repo
    2. Create feature branch
    3. Execute code changes (via LLM)
    4. Run tests
    5. Push and create PR
    6. Handle failures gracefully

Uses a thread pool for parallel execution.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of a single task execution."""
    task_id: str
    success: bool
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    commit_sha: Optional[str] = None
    branch: Optional[str] = None
    error: str = ""
    duration_seconds: float = 0.0
    files_changed: List[str] = field(default_factory=list)
    test_results: Optional[Dict[str, Any]] = None


@dataclass
class BatchResult:
    """Result of a batch of parallel task executions."""
    results: List[ExecutionResult] = field(default_factory=list)
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    total_duration: float = 0.0

    def summary(self) -> str:
        return (
            f"Batch execution: {self.succeeded}/{self.total} succeeded, "
            f"{self.failed} failed, {self.total_duration:.1f}s"
        )


class TaskExecutor:
    """Parallel task execution engine.

    Parameters
    ----------
    github:
        A GitHub API client.
    llm:
        An LLM provider for generating code changes.
    work_dir:
        Base directory for local clones.
    max_workers:
        Maximum number of parallel task executions.
    run_tests:
        Whether to run tests after making changes.
    """

    def __init__(
        self,
        github: Any,
        llm: Any,
        work_dir: Optional[Path] = None,
        max_workers: int = 4,
        run_tests: bool = True,
    ) -> None:
        self.github = github
        self.llm = llm
        self.work_dir = work_dir or Path(tempfile.mkdtemp(prefix="git-agent-exec-"))
        self.max_workers = max_workers
        self.run_tests = run_tests
        self._results: List[ExecutionResult] = []

    # ------------------------------------------------------------------
    # Single task execution
    # ------------------------------------------------------------------

    def execute_task(
        self,
        task_id: str,
        repo_full: str,
        description: str,
        context: str = "",
        branch: Optional[str] = None,
        base: str = "main",
        files: Optional[List[Dict[str, str]]] = None,
    ) -> ExecutionResult:
        """Execute a single task end-to-end.

        Parameters
        ----------
        task_id:
            Unique identifier for the task.
        repo_full:
            Full repo name (``owner/repo``).
        description:
            Task description.
        context:
            Additional context for the LLM.
        branch:
            Feature branch name (generated if None).
        base:
            Base branch to create PR against.
        files:
            Pre-defined files to push. If None, LLM generates them.

        Returns
        -------
        ExecutionResult
        """
        start = datetime.now(timezone.utc)
        result = ExecutionResult(task_id=task_id, success=False)

        if "/" not in repo_full:
            result.error = f"Invalid repo: {repo_full}"
            return result

        owner, repo = repo_full.split("/", 1)

        try:
            # 1. Generate branch name
            if branch is None:
                branch = self._generate_branch_name(task_id, description)

            result.branch = branch

            # 2. Fork and clone
            clone_path = self.work_dir / f"{repo}-{task_id}"
            self._clone_repo(owner, repo, clone_path, base)

            # 3. Create feature branch
            self._create_local_branch(clone_path, branch, base)

            # 4. Generate or use pre-defined files
            if files is None:
                files = self._generate_implementation(task_id, description, context, repo)

            if not files:
                result.error = "No files generated"
                return result

            # 5. Write files to disk
            changed_files = self._write_files(clone_path, files)
            result.files_changed = changed_files

            # 6. Run tests
            if self.run_tests:
                test_result = self._run_tests(clone_path)
                result.test_results = test_result

            # 7. Commit and push
            commit_sha = self._commit_and_push(clone_path, branch, description)
            result.commit_sha = commit_sha

            # 8. Create remote branch and PR
            self._push_to_remote(clone_path, branch)
            pr = self._create_pr(owner, repo, task_id, description, branch, base)
            result.pr_number = pr.get("number")
            result.pr_url = pr.get("html_url")
            result.success = True

        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            logger.error("Task %s failed: %s", task_id, traceback.format_exc())

        end = datetime.now(timezone.utc)
        result.duration_seconds = (end - start).total_seconds()
        return result

    # ------------------------------------------------------------------
    # Batch execution
    # ------------------------------------------------------------------

    def execute_batch(
        self,
        tasks: List[Dict[str, Any]],
    ) -> BatchResult:
        """Execute multiple tasks in parallel.

        Each task dict should have:
            - ``task_id``: str
            - ``repo``: str (owner/repo)
            - ``description``: str
            - ``context``: str (optional)
            - ``branch``: str (optional)
        """
        batch = BatchResult(total=len(tasks))
        start = datetime.now(timezone.utc)

        workers = min(self.max_workers, len(tasks))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(
                    self.execute_task,
                    t["task_id"],
                    t["repo"],
                    t["description"],
                    t.get("context", ""),
                    t.get("branch"),
                ): t
                for t in tasks
            }

            for future in as_completed(future_map):
                result = future.result()
                batch.results.append(result)
                if result.success:
                    batch.succeeded += 1
                else:
                    batch.failed += 1

        end = datetime.now(timezone.utc)
        batch.total_duration = (end - start).total_seconds()
        self._results.extend(batch.results)
        return batch

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _clone_repo(
        self, owner: str, repo: str, path: Path, branch: str = "main"
    ) -> None:
        """Clone a repo or use existing clone."""
        if path.exists() and (path / ".git").is_dir():
            logger.info("Using existing clone at %s", path)
            # Pull latest
            self._run_git(path, "fetch", "origin")
            self._run_git(path, "checkout", branch)
            self._run_git(path, "pull", "origin", branch)
            return

        url = f"https://github.com/{owner}/{repo}.git"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._run_git(path.parent, "clone", "--branch", branch, "--single-branch", url, str(path))

    def _create_local_branch(
        self, repo_path: Path, branch: str, from_branch: str = "main"
    ) -> None:
        """Create and checkout a new local branch."""
        self._run_git(repo_path, "checkout", "-b", branch, from_branch)

    def _generate_implementation(
        self, task_id: str, description: str, context: str, repo: str
    ) -> List[Dict[str, str]]:
        """Use the LLM to generate implementation files."""
        try:
            import json
            import re as _re

            prompt = (
                "You are an expert software engineer. Given a task, generate "
                "the implementation. Return JSON with keys: 'files' (list of "
                "{path, content}), 'summary' (string).\n\n"
                f"Task ID: {task_id}\n"
                f"Task: {description}\n"
                f"Context: {context}\n"
                f"Repo: {repo}\n\n"
                "Return valid JSON only."
            )

            response = self.llm.complete([
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Implement: {description}"},
            ])

            # Extract JSON from response
            json_match = _re.search(r"```(?:json)?\s*\n(.*?)\n```", response, _re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
            else:
                data = json.loads(response)

            return data.get("files", [])

        except Exception as exc:
            logger.warning("LLM implementation failed for %s: %s", task_id, exc)
            return []

    def _write_files(
        self, repo_path: Path, files: List[Dict[str, str]]
    ) -> List[str]:
        """Write files to the local repo. Returns list of changed paths."""
        changed = []
        for f in files:
            file_path = repo_path / f["path"]
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(f["content"], encoding="utf-8")
            changed.append(f["path"])
        return changed

    def _run_tests(self, repo_path: Path) -> Dict[str, Any]:
        """Run tests in a repo. Returns results dict."""
        results: Dict[str, Any] = {"ran": False, "passed": False, "output": ""}

        # Detect test runner
        test_commands = []

        if (repo_path / "pytest.ini").exists() or (repo_path / "pyproject.toml").exists():
            test_commands.append(["python", "-m", "pytest", "-x", "-q", "--tb=short"])
        if (repo_path / "package.json").exists():
            test_commands.append(["npm", "test", "--", "--passWithNoTests"])
        if (repo_path / "Makefile").exists():
            test_commands.append(["make", "test"])

        if not test_commands:
            results["output"] = "No test runner detected"
            return results

        for cmd in test_commands:
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=str(repo_path),
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                results["ran"] = True
                results["passed"] = proc.returncode == 0
                results["output"] = proc.stdout + proc.stderr
                results["command"] = " ".join(cmd)
                if results["passed"]:
                    break  # Tests passed, no need to try other runners
            except FileNotFoundError:
                continue
            except subprocess.TimeoutExpired:
                results["output"] = "Tests timed out"
                results["timed_out"] = True
                break
            except Exception as exc:
                results["output"] = str(exc)

        return results

    def _commit_and_push(
        self, repo_path: Path, branch: str, description: str
    ) -> str:
        """Stage, commit, and push changes. Returns commit SHA."""
        self._run_git(repo_path, "add", "-A")
        self._run_git(repo_path, "commit", "-m", f"feat: {description}")
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def _push_to_remote(self, repo_path: Path, branch: str) -> None:
        """Push a branch to the remote."""
        self._run_git(repo_path, "push", "--set-upstream", "origin", branch)

    def _create_pr(
        self,
        owner: str,
        repo: str,
        task_id: str,
        description: str,
        branch: str,
        base: str,
    ) -> Dict[str, Any]:
        """Create a PR via the GitHub API."""
        title = f"[task-{task_id}] {description[:80]}"
        body = (
            f"## Task: {description}\n\n"
            f"**Task ID:** {task_id}\n"
            f"**Branch:** `{branch}`\n\n"
            "---\n*Automated by git-agent.*"
        )
        return self.github.create_pull_request(owner, repo, title, body, branch, base)

    @staticmethod
    def _generate_branch_name(task_id: str, description: str) -> str:
        """Generate a safe branch name."""
        import re
        slug = re.sub(r"[^a-z0-9]+", "-", description.lower())[:40].strip("-")
        return f"agent/task-{task_id}-{slug}"

    @staticmethod
    def _run_git(repo_path: Path, *args: str) -> subprocess.CompletedProcess:
        """Run a git command."""
        cmd = ["git"] + list(args)
        result = subprocess.run(
            cmd,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
        return result
