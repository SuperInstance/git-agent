"""
git_agent.github.client — Rate-limited GitHub API client.

Features:
    - Authentication via PAT token
    - Auto-pagination for list endpoints
    - Cache layer to avoid redundant API calls
    - Error handling with retries
    - Rate limit tracking and respect
"""

from __future__ import annotations

import base64
import json
import logging
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class GitHubError(Exception):
    """Base exception for GitHub API errors."""

    def __init__(self, message: str, status_code: int = 0, response_body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class GitHubRateLimitError(GitHubError):
    """Raised when the API rate limit is exceeded."""


class GitHubNotFoundError(GitHubError):
    """Raised when a resource is not found (404)."""


@dataclass
class CacheEntry:
    """A cached API response."""
    data: Any
    timestamp: float
    ttl: float = 300.0  # 5 minutes default

    @property
    def is_expired(self) -> bool:
        return time.time() - self.timestamp > self.ttl


@dataclass
class RateLimitInfo:
    """GitHub API rate limit information."""
    limit: int = 5000
    remaining: int = 5000
    reset: int = 0
    used: int = 0

    @property
    def is_exhausted(self) -> bool:
        return self.remaining <= 0

    @property
    def seconds_until_reset(self) -> int:
        if self.reset <= 0:
            return 0
        return max(0, self.reset - int(time.time()))


class GitHubAPIClient:
    """Rate-limited GitHub API client with caching.

    Implements the ``GitHubClient`` Protocol from :mod:`git_agent.agent`.

    Parameters
    ----------
    token:
        GitHub Personal Access Token.
    api_base:
        GitHub API base URL (for GitHub Enterprise).
    cache_ttl:
        Default TTL for cached responses in seconds.
    max_retries:
        Maximum number of retries for transient errors.
    timeout:
        Request timeout in seconds.
    """

    def __init__(
        self,
        token: str,
        api_base: str = GITHUB_API_BASE,
        cache_ttl: float = 300.0,
        max_retries: int = 3,
        timeout: int = 30,
    ) -> None:
        self.token = token
        self.api_base = api_base.rstrip("/")
        self.cache_ttl = cache_ttl
        self.max_retries = max_retries
        self.timeout = timeout
        self._cache: Dict[str, CacheEntry] = {}
        self._rate_limit = RateLimitInfo()

    # ------------------------------------------------------------------
    # Core HTTP methods
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Make an authenticated API request with retries.

        Raises :class:`GitHubError` (or subclass) on failure.
        """
        url = f"{self.api_base}{path}"

        # Add query parameters
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
            if query:
                url += f"?{query}"

        payload = json.dumps(data).encode("utf-8") if data else None

        req_headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "git-agent/0.1.0",
        }
        if headers:
            req_headers.update(headers)
        if data:
            req_headers["Content-Type"] = "application/json"

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            # Check rate limit before requesting
            if self._rate_limit.is_exhausted:
                wait = self._rate_limit.seconds_until_reset + 1
                logger.warning("Rate limit exhausted, waiting %ds", wait)
                time.sleep(min(wait, 60))

            try:
                req = urllib.request.Request(url, data=payload, headers=req_headers, method=method)
                resp = urllib.request.urlopen(req, timeout=self.timeout)
                body = resp.read().decode("utf-8")
                self._update_rate_limit(resp.headers)
                if body:
                    return json.loads(body)
                return {}
            except urllib.error.HTTPError as exc:
                self._update_rate_limit(exc.headers)
                body = exc.read().decode("utf-8", errors="replace")
                status = exc.code

                if status == 403 and "rate limit" in body.lower():
                    raise GitHubRateLimitError(
                        f"Rate limit exceeded: {body[:200]}",
                        status_code=status,
                        response_body=body,
                    )
                if status == 404:
                    raise GitHubNotFoundError(
                        f"Not found: {path}",
                        status_code=status,
                        response_body=body,
                    )
                if status >= 500 and attempt < self.max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning("Server error %d, retrying in %ds: %s", status, wait, path)
                    time.sleep(wait)
                    last_error = exc
                    continue
                raise GitHubError(
                    f"HTTP {status} for {method} {path}: {body[:200]}",
                    status_code=status,
                    response_body=body,
                )
            except urllib.error.URLError as exc:
                if attempt < self.max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning("URL error, retrying in %ds: %s", wait, exc)
                    time.sleep(wait)
                    last_error = exc
                    continue
                raise GitHubError(f"URL error for {path}: {exc}")
            except Exception as exc:
                raise GitHubError(f"Request failed for {path}: {exc}")

        raise GitHubError(f"Max retries exceeded for {method} {path}: {last_error}")

    def _update_rate_limit(self, headers) -> None:
        """Update rate limit info from response headers."""
        if headers.get("X-RateLimit-Limit"):
            self._rate_limit.limit = int(headers["X-RateLimit-Limit"])
        if headers.get("X-RateLimit-Remaining"):
            self._rate_limit.remaining = int(headers["X-RateLimit-Remaining"])
        if headers.get("X-RateLimit-Reset"):
            self._rate_limit.reset = int(headers["X-RateLimit-Reset"])
        if headers.get("X-RateLimit-Used"):
            self._rate_limit.used = int(headers["X-RateLimit-Used"])

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def _paginated_request(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        per_page: int = 100,
        max_pages: int = 10,
    ) -> List[Dict[str, Any]]:
        """Fetch all pages of a paginated endpoint.

        Returns a flat list of all items across pages.
        """
        all_items: List[Dict[str, Any]] = []
        if params is None:
            params = {}

        for page in range(1, max_pages + 1):
            page_params = {**params, "per_page": per_page, "page": page}
            response = self._request("GET", path, params=page_params)

            if isinstance(response, list):
                items = response
            elif isinstance(response, dict):
                items = response.get("items", [])
            else:
                items = []

            all_items.extend(items)

            # If we got fewer than per_page, we're on the last page
            if len(items) < per_page:
                break

        return all_items

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _cache_get(self, key: str) -> Optional[Any]:
        """Get a value from cache, returning None if expired or missing."""
        entry = self._cache.get(key)
        if entry is None:
            return None
        if entry.is_expired:
            del self._cache[key]
            return None
        return entry.data

    def _cache_set(self, key: str, data: Any, ttl: Optional[float] = None) -> None:
        """Store a value in cache."""
        self._cache[key] = CacheEntry(
            data=data,
            timestamp=time.time(),
            ttl=ttl or self.cache_ttl,
        )

    def _cache_clear(self) -> None:
        """Clear the entire cache."""
        self._cache.clear()

    def invalidate_cache(self, pattern: Optional[str] = None) -> int:
        """Invalidate cache entries. If *pattern* is given, only keys
        containing that substring are removed. Returns count of removed entries.
        """
        if pattern is None:
            count = len(self._cache)
            self._cache.clear()
            return count
        keys_to_remove = [k for k in self._cache if pattern in k]
        for k in keys_to_remove:
            del self._cache[k]
        return len(keys_to_remove)

    # ------------------------------------------------------------------
    # Repository operations
    # ------------------------------------------------------------------

    def get_repo(self, owner: str, repo: str) -> Dict[str, Any]:
        """Get repository metadata."""
        return self._request("GET", f"/repos/{owner}/{repo}")

    def list_org_repos(self, org: str, per_page: int = 100) -> List[Dict[str, Any]]:
        """List all repositories for an organization."""
        cache_key = f"org_repos:{org}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        repos = self._paginated_request(f"/orgs/{org}/repos", per_page=per_page)
        self._cache_set(cache_key, repos)
        return repos

    def fork_repo(self, owner: str, repo: str) -> Dict[str, Any]:
        """Fork a repository."""
        result = self._request("POST", f"/repos/{owner}/{repo}/forks")
        self.invalidate_cache("org_repos")
        return result

    def create_branch(
        self, owner: str, repo: str, branch: str, from_branch: str = "main"
    ) -> Dict[str, Any]:
        """Create a new branch from an existing ref."""
        # Get the SHA of the source branch
        ref_data = self._request("GET", f"/repos/{owner}/{repo}/git/ref/heads/{from_branch}")
        sha = ref_data["object"]["sha"]

        return self._request("POST", f"/repos/{owner}/{repo}/git/refs", data={
            "ref": f"refs/heads/{branch}",
            "sha": sha,
        })

    def list_branches(self, owner: str, repo: str, per_page: int = 100) -> List[Dict[str, Any]]:
        """List branches in a repository."""
        return self._paginated_request(f"/repos/{owner}/{repo}/branches", per_page=per_page)

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def get_file(
        self, owner: str, repo: str, path: str, ref: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get file metadata and contents (base64 encoded)."""
        params = {}
        if ref:
            params["ref"] = ref
        return self._request("GET", f"/repos/{owner}/{repo}/contents/{path}", params=params)

    def get_file_contents(
        self, owner: str, repo: str, path: str, ref: Optional[str] = None
    ) -> Optional[str]:
        """Get decoded file contents as a string, or None if not found."""
        try:
            result = self.get_file(owner, repo, path, ref=ref)
            encoding = result.get("encoding", "utf-8")
            content = result.get("content", "")
            if encoding == "base64":
                return base64.b64decode(content).decode("utf-8", errors="replace")
            return content
        except GitHubNotFoundError:
            return None
        except Exception as exc:
            logger.debug("Could not read file %s/%s/%s: %s", owner, repo, path, exc)
            return None

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
        """Create or update a file via the GitHub API."""
        data: Dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
            "branch": branch,
        }
        if sha:
            data["sha"] = sha
        result = self._request("PUT", f"/repos/{owner}/{repo}/contents/{path}", data=data)
        self.invalidate_cache(f"{owner}/{repo}")
        return result

    def list_files(
        self, owner: str, repo: str, path: str = "", ref: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List files/directories in a repo path."""
        params: Dict[str, Any] = {}
        if ref:
            params["ref"] = ref
        return self._request("GET", f"/repos/{owner}/{repo}/contents/{path}", params=params)

    # ------------------------------------------------------------------
    # Pull request operations
    # ------------------------------------------------------------------

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
        return self._request("POST", f"/repos/{owner}/{repo}/pulls", data={
            "title": title,
            "body": body,
            "head": head,
            "base": base,
        })

    def list_pull_requests(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        per_page: int = 100,
    ) -> List[Dict[str, Any]]:
        """List pull requests. State can be 'open', 'closed', or 'all'."""
        return self._paginated_request(
            f"/repos/{owner}/{repo}/pulls",
            params={"state": state},
            per_page=per_page,
        )

    def add_comment(
        self, owner: str, repo: str, pull_number: int, body: str
    ) -> Dict[str, Any]:
        """Add a comment to a pull request or issue."""
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{pull_number}/comments",
            data={"body": body},
        )

    def merge_pull_request(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        commit_title: Optional[str] = None,
        merge_method: str = "merge",
    ) -> Dict[str, Any]:
        """Merge a pull request."""
        data: Dict[str, Any] = {"merge_method": merge_method}
        if commit_title:
            data["commit_title"] = commit_title
        return self._request(
            "PUT",
            f"/repos/{owner}/{repo}/pulls/{pull_number}/merge",
            data=data,
        )

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    def list_issues(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        per_page: int = 100,
    ) -> List[Dict[str, Any]]:
        """List issues (and PRs — use list_pull_requests for PRs only)."""
        return self._paginated_request(
            f"/repos/{owner}/{repo}/issues",
            params={"state": state},
            per_page=per_page,
        )

    # ------------------------------------------------------------------
    # Commits
    # ------------------------------------------------------------------

    def list_commits(
        self,
        owner: str,
        repo: str,
        per_page: int = 10,
        sha: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List recent commits."""
        params: Dict[str, Any] = {"per_page": per_page}
        if sha:
            params["sha"] = sha
        return self._request("GET", f"/repos/{owner}/{repo}/commits", params=params)

    # ------------------------------------------------------------------
    # Push multiple files in a single commit
    # ------------------------------------------------------------------

    def push_files(
        self,
        owner: str,
        repo: str,
        branch: str,
        files: List[Dict[str, str]],
        message: str,
    ) -> Dict[str, Any]:
        """Push multiple files in a single commit using the Git Trees API.

        Each file in *files* should be ``{"path": "...", "content": "..."}``.
        """
        # 1. Get the current commit SHA of the branch
        ref = self._request("GET", f"/repos/{owner}/{repo}/git/ref/heads/{branch}")
        base_sha = ref["object"]["sha"]

        # 2. Get the tree SHA of that commit
        commit = self._request("GET", f"/repos/{owner}/{repo}/git/commits/{base_sha}")
        base_tree = commit["tree"]["sha"]

        # 3. Create blobs for each file
        tree_items = []
        for f in files:
            blob = self._request("POST", f"/repos/{owner}/{repo}/git/blobs", data={
                "content": f["content"],
                "encoding": "utf-8",
            })
            tree_items.append({
                "path": f["path"],
                "mode": "100644",
                "type": "blob",
                "sha": blob["sha"],
            })

        # 4. Create a new tree
        new_tree = self._request("POST", f"/repos/{owner}/{repo}/git/trees", data={
            "base_tree": base_tree,
            "tree": tree_items,
        })

        # 5. Create a commit
        new_commit = self._request("POST", f"/repos/{owner}/{repo}/git/commits", data={
            "message": message,
            "tree": new_tree["sha"],
            "parents": [base_sha],
        })

        # 6. Update the branch reference
        self._request("PATCH", f"/repos/{owner}/{repo}/git/refs/heads/{branch}", data={
            "sha": new_commit["sha"],
        })

        self.invalidate_cache(f"{owner}/{repo}")
        return {
            "commit": {"sha": new_commit["sha"]},
            "files": len(files),
            "tree": new_tree["sha"],
        }

    # ------------------------------------------------------------------
    # Local clone
    # ------------------------------------------------------------------

    def clone(self, url: str, path: Path, branch: Optional[str] = None) -> Path:
        """Clone a repository to a local path using subprocess.

        Returns the path to the cloned repo.
        """
        import subprocess

        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)

        cmd = ["git", "clone"]
        if branch:
            cmd.extend(["--branch", branch, "--single-branch"])
        cmd.extend([url, str(path)])

        logger.info("Cloning: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise GitHubError(f"Clone failed: {result.stderr}")
        return path

    # ------------------------------------------------------------------
    # Fleet bottles
    # ------------------------------------------------------------------

    def get_bottles(self, owner: str, repo: str) -> List[Dict[str, Any]]:
        """List 'bottles' (messages) from a fleet repo.

        Reads markdown files from the ``message-in-a-bottle/`` directory.
        """
        try:
            contents = self.list_files(owner, repo, path="message-in-a-bottle")
        except GitHubNotFoundError:
            return []

        bottles: List[Dict[str, Any]] = []
        for item in contents:
            if item.get("type") == "file" and item.get("name", "").endswith(".md"):
                content = self.get_file_contents(owner, repo, f"message-in-a-bottle/{item['name']}")
                if content:
                    bottles.append({
                        "title": item["name"].replace(".md", ""),
                        "content": content,
                        "path": item["path"],
                        "sha": item.get("sha", ""),
                    })
        return bottles

    def push_bottle(
        self, owner: str, repo: str, content: str, title: str = ""
    ) -> Dict[str, Any]:
        """Push a new bottle (message) to a fleet repo."""
        import datetime as _dt

        if not title:
            title = f"bottle-{_dt.datetime.now(_dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}"

        path = f"message-in-a-bottle/{title}.md"
        message = f"Add bottle: {title}"

        result = self.create_or_update_file(owner, repo, path, content, message, "main")
        return {"status": "created", "bottle": {"title": title, "path": path}, "commit": result}

    # ------------------------------------------------------------------
    # Rate limit info
    # ------------------------------------------------------------------

    @property
    def rate_limit(self) -> RateLimitInfo:
        """Current rate limit information."""
        return self._rate_limit

    def check_rate_limit(self) -> Dict[str, Any]:
        """Get current rate limit status from GitHub."""
        return self._request("GET", "/rate_limit")
