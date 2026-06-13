"""
git_agent.github — GitHub API client and operations.

Provides a rate-limited, cached GitHub API wrapper with support for
repository operations, pull request management, and fleet communication.
"""

from .client import GitHubAPIClient
from .pr import PullRequestManager
from .repo import RepoManager

__all__ = [
    "GitHubAPIClient",
    "PullRequestManager",
    "RepoManager",
]
