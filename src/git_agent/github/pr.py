"""
git_agent.github.pr — Pull request creation and management.

Provides a higher-level interface for PR operations, building on top
of the raw API client from :mod:`git_agent.github.client`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PRInfo:
    """Parsed pull request information."""
    number: int
    title: str
    body: str
    state: str
    html_url: str
    head_ref: str
    base_ref: str
    draft: bool = False
    merged: bool = False
    mergeable: Optional[bool] = None
    labels: List[str] = field(default_factory=list)
    task_id: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> PRInfo:
        """Create PRInfo from a GitHub API pull request response."""
        labels = [l["name"] for l in data.get("labels", [])]
        task_id = cls._extract_task_id(data.get("title", ""))
        return cls(
            number=data.get("number", 0),
            title=data.get("title", ""),
            body=data.get("body", "") or "",
            state=data.get("state", "open"),
            html_url=data.get("html_url", ""),
            head_ref=data.get("head", {}).get("ref", ""),
            base_ref=data.get("base", {}).get("ref", ""),
            draft=data.get("draft", False),
            merged=data.get("merged", False),
            mergeable=data.get("mergeable"),
            labels=labels,
            task_id=task_id,
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

    @staticmethod
    def _extract_task_id(title: str) -> Optional[str]:
        """Extract a task ID from a PR title.

        Looks for patterns like ``[TASK-123]``, ``task-123``, ``#123``.
        """
        # Pattern: [TASK-123] or [task-123]
        m = re.search(r"\[(?:TASK|task)[-_](\w+)\]", title)
        if m:
            return m.group(1)
        # Pattern: #123 at start or after space
        m = re.search(r"(?:^|\s)#(\d+)", title)
        if m:
            return m.group(1)
        return None


class PullRequestManager:
    """Higher-level PR management operations.

    Wraps the raw GitHub API client to provide task-aware PR operations.

    Parameters
    ----------
    client:
        A ``GitHubAPIClient`` (or any object with the same interface).
    default_base:
        Default base branch for PRs (default ``"main"``).
    """

    def __init__(self, client: Any, default_base: str = "main") -> None:
        self.client = client
        self.default_base = default_base

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_pr(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: Optional[str] = None,
        draft: bool = False,
    ) -> PRInfo:
        """Create a pull request.

        If *draft* is True, the PR is created as a draft.
        """
        base = base or self.default_base
        data = self.client.create_pull_request(owner, repo, title, body, head, base)
        return PRInfo.from_api_response(data)

    def create_pr_for_task(
        self,
        owner: str,
        repo: str,
        task_id: str,
        task_description: str,
        branch: str,
        body: str = "",
        context: str = "",
        base: Optional[str] = None,
    ) -> PRInfo:
        """Create a PR that references a task ID in the title.

        The title is formatted as ``[task-{id}] {description}``.
        """
        title = f"[task-{task_id}] {task_description[:80]}"
        full_body = (
            f"## Task: {task_description}\n\n"
            f"**Task ID:** {task_id}\n\n"
        )
        if context:
            full_body += f"**Context:**\n{context}\n\n"
        if body:
            full_body += f"{body}\n"

        return self.create_pr(owner, repo, title, full_body, branch, base=base)

    # ------------------------------------------------------------------
    # List / Query
    # ------------------------------------------------------------------

    def list_prs(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        head: Optional[str] = None,
        base: Optional[str] = None,
    ) -> List[PRInfo]:
        """List pull requests, optionally filtered.

        Parameters
        ----------
        state:
            ``"open"``, ``"closed"``, or ``"all"``.
        head:
            Filter by head branch (e.g. ``"my-fork:my-branch"``).
        base:
            Filter by base branch.
        """
        params: Dict[str, Any] = {"state": state}
        if head:
            params["head"] = head
        if base:
            params["base"] = base

        raw_prs = self.client.list_pull_requests(owner, repo, state=state)
        return [PRInfo.from_api_response(pr) for pr in raw_prs]

    def list_open_prs(self, owner: str, repo: str) -> List[PRInfo]:
        """List open pull requests."""
        return self.list_prs(owner, repo, state="open")

    def list_closed_prs(self, owner: str, repo: str) -> List[PRInfo]:
        """List closed/merged pull requests."""
        return self.list_prs(owner, repo, state="closed")

    def get_pr(self, owner: str, repo: str, number: int) -> PRInfo:
        """Get details for a specific PR."""
        data = self.client._request("GET", f"/repos/{owner}/{repo}/pulls/{number}")
        return PRInfo.from_api_response(data)

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    def add_comment(
        self, owner: str, repo: str, pull_number: int, body: str
    ) -> Dict[str, Any]:
        """Add a comment to a pull request."""
        return self.client.add_comment(owner, repo, pull_number, body)

    def list_comments(
        self, owner: str, repo: str, pull_number: int
    ) -> List[Dict[str, Any]]:
        """List comments on a pull request."""
        return self.client._request(
            "GET",
            f"/repos/{owner}/{repo}/issues/{pull_number}/comments",
        )

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------

    def merge_pr(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        commit_title: Optional[str] = None,
        merge_method: str = "merge",
    ) -> Dict[str, Any]:
        """Merge a pull request."""
        return self.client.merge_pull_request(
            owner, repo, pull_number, commit_title, merge_method
        )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def build_pr_body(
        self,
        description: str,
        files_changed: Optional[List[str]] = None,
        task_id: Optional[str] = None,
        testing_notes: str = "",
    ) -> str:
        """Build a well-formatted PR body."""
        parts = [f"## Summary\n\n{description}"]

        if task_id:
            parts.insert(0, f"**Task ID:** {task_id}")

        if files_changed:
            parts.append("\n## Files Changed\n")
            for f in files_changed:
                parts.append(f"- `{f}`")

        if testing_notes:
            parts.append(f"\n## Testing\n\n{testing_notes}")

        parts.append(
            "\n---\n*This PR was created by git-agent.*"
        )
        return "\n".join(parts)
