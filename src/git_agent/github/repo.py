"""
git_agent.github.repo — Repository operations (fork, clone, branch, push).

Provides a higher-level interface for common repository operations,
building on top of :mod:`git_agent.github.client`.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class RepoInfo:
    """Parsed repository information."""
    full_name: str
    owner: str
    name: str
    description: str = ""
    private: bool = False
    fork: bool = False
    default_branch: str = "main"
    language: str = ""
    stars: int = 0
    forks_count: int = 0
    html_url: str = ""
    topics: List[str] = field(default_factory=list)
    updated_at: str = ""

    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> RepoInfo:
        """Create RepoInfo from a GitHub API repository response."""
        full_name = data.get("full_name", "")
        owner, name = full_name.split("/", 1) if "/" in full_name else ("", full_name)
        return cls(
            full_name=full_name,
            owner=owner,
            name=name,
            description=data.get("description", "") or "",
            private=data.get("private", False),
            fork=data.get("fork", False),
            default_branch=data.get("default_branch", "main"),
            language=data.get("language", "") or "",
            stars=data.get("stargazers_count", 0),
            forks_count=data.get("forks_count", 0),
            html_url=data.get("html_url", ""),
            topics=data.get("topics", []),
            updated_at=data.get("updated_at", ""),
        )


class RepoManager:
    """High-level repository operations.

    Parameters
    ----------
    client:
        A ``GitHubAPIClient`` (or any object with the same interface).
    work_dir:
        Base directory for local clones. Defaults to a temp directory.
    """

    def __init__(
        self,
        client: Any,
        work_dir: Optional[Path] = None,
    ) -> None:
        self.client = client
        self.work_dir = work_dir or Path(tempfile.mkdtemp(prefix="git-agent-"))

    # ------------------------------------------------------------------
    # Fork
    # ------------------------------------------------------------------

    def fork_repo(self, owner: str, repo: str) -> RepoInfo:
        """Fork a repository and return the fork info."""
        data = self.client.fork_repo(owner, repo)
        # The fork may not be immediately ready; get fresh info
        fork_owner = data.get("owner", {}).get("login", owner)
        fork_name = data.get("name", repo)
        return self.get_repo(fork_owner, fork_name)

    def fork_and_clone(
        self,
        owner: str,
        repo: str,
        branch: Optional[str] = None,
    ) -> Path:
        """Fork a repo and clone the fork locally.

        Returns the path to the local clone.
        """
        fork_info = self.fork_repo(owner, repo)
        clone_url = f"https://github.com/{fork_info.full_name}.git"
        clone_path = self.work_dir / fork_info.name
        return self.clone_repo(clone_url, clone_path, branch=branch)

    # ------------------------------------------------------------------
    # Clone
    # ------------------------------------------------------------------

    def clone_repo(
        self,
        url: str,
        path: Optional[Path] = None,
        branch: Optional[str] = None,
    ) -> Path:
        """Clone a repository locally.

        Parameters
        ----------
        url:
            The clone URL (HTTPS or SSH).
        path:
            Local path to clone into. Defaults to ``work_dir / repo_name``.
        branch:
            Specific branch to checkout.
        """
        if path is None:
            repo_name = url.rstrip("/").split("/")[-1].replace(".git", "")
            path = self.work_dir / repo_name

        path = Path(path)
        if path.exists() and any(path.iterdir()):
            logger.info("Repo already exists at %s, skipping clone.", path)
            return path

        return self.client.clone(url, path, branch=branch)

    # ------------------------------------------------------------------
    # Branch
    # ------------------------------------------------------------------

    def create_branch(
        self,
        owner: str,
        repo: str,
        branch: str,
        from_branch: str = "main",
    ) -> Dict[str, Any]:
        """Create a new branch on a remote repository."""
        return self.client.create_branch(owner, repo, branch, from_branch)

    def create_local_branch(
        self,
        repo_path: Path,
        branch_name: str,
        from_branch: str = "main",
    ) -> None:
        """Create a new branch in a local git repo."""
        self._run_git(repo_path, "checkout", from_branch)
        self._run_git(repo_path, "checkout", "-b", branch_name)

    # ------------------------------------------------------------------
    # Push
    # ------------------------------------------------------------------

    def push_to_remote(
        self,
        repo_path: Path,
        branch: str,
        remote: str = "origin",
        set_upstream: bool = True,
    ) -> None:
        """Push a local branch to a remote."""
        cmd = ["git", "push", remote, branch]
        if set_upstream:
            cmd = ["git", "push", "--set-upstream", remote, branch]
        self._run_git(repo_path, *cmd[1:])

    def commit_and_push(
        self,
        repo_path: Path,
        message: str,
        branch: str,
        files: Optional[List[str]] = None,
        push: bool = True,
    ) -> str:
        """Stage, commit, and optionally push files.

        Returns the commit SHA.
        """
        # Stage files
        if files:
            for f in files:
                self._run_git(repo_path, "add", f)
        else:
            self._run_git(repo_path, "add", "-A")

        # Commit
        self._run_git(repo_path, "commit", "-m", message)

        # Get commit SHA
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=True,
        )
        sha = result.stdout.strip()

        # Push
        if push:
            self.push_to_remote(repo_path, branch)

        return sha

    # ------------------------------------------------------------------
    # Repo info
    # ------------------------------------------------------------------

    def get_repo(self, owner: str, repo: str) -> RepoInfo:
        """Get repository information."""
        data = self.client.get_repo(owner, repo)
        return RepoInfo.from_api_response(data)

    def list_org_repos(
        self,
        org: str,
        per_page: int = 100,
    ) -> List[RepoInfo]:
        """List all repos for an organization."""
        raw = self.client.list_org_repos(org, per_page=per_page)
        return [RepoInfo.from_api_response(r) for r in raw]

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    def list_files(
        self,
        owner: str,
        repo: str,
        path: str = "",
        ref: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List files/directories in a repo."""
        return self.client.list_files(owner, repo, path, ref=ref)

    def read_file(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: Optional[str] = None,
    ) -> Optional[str]:
        """Read file contents from GitHub API."""
        return self.client.get_file_contents(owner, repo, path, ref=ref)

    def create_file(
        self,
        owner: str,
        repo: str,
        path: str,
        content: str,
        message: str,
        branch: str,
        sha: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create or update a file via GitHub API."""
        return self.client.create_or_update_file(
            owner, repo, path, content, message, branch, sha=sha,
        )

    # ------------------------------------------------------------------
    # Git helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _run_git(repo_path: Path, *args: str) -> subprocess.CompletedProcess:
        """Run a git command in a repo directory."""
        cmd = ["git"] + list(args)
        logger.debug("Running: %s (cwd=%s)", " ".join(cmd), repo_path)
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

    def get_current_branch(self, repo_path: Path) -> str:
        """Get the current branch name of a local repo."""
        result = self._run_git(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
        return result.stdout.strip()
