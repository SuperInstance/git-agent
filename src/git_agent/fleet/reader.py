"""
git_agent.fleet.reader — Read fleet state from repos.

Reads:
    - TASKS.md from oracle1-index
    - Bottles from message-in-a-bottle/
    - Fleet status (THE-FLEET.md, STATUS.md)
    - Org repos with metadata
    - Recent activity
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..agent import Task, TaskPriority

logger = logging.getLogger(__name__)


@dataclass
class FleetTask:
    """A task parsed from TASKS.md."""
    id: str
    repo: str
    task: str
    skills: List[str] = field(default_factory=list)
    priority: TaskPriority = TaskPriority.MEDIUM
    effort: str = "medium"
    impact: str = "medium"
    status: str = "pending"  # pending, in_progress, completed


@dataclass
class Bottle:
    """A message from the fleet message system."""
    title: str
    content: str
    sender: str = ""
    timestamp: str = ""
    path: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Bottle:
        sender = ""
        timestamp = ""
        content = data.get("content", "")
        # Parse sender and timestamp from bottle content
        m = re.search(r"\*\*From:\*\*\s*(.+)", content)
        if m:
            sender = m.group(1).strip()
        m = re.search(r"\*\*Time:\*\*\s*(.+)", content)
        if m:
            timestamp = m.group(1).strip()
        return cls(
            title=data.get("title", ""),
            content=content,
            sender=sender,
            timestamp=timestamp,
            path=data.get("path", ""),
        )


@dataclass
class FleetStatus:
    """Current fleet status."""
    agents: List[Dict[str, Any]] = field(default_factory=list)
    active_tasks: int = 0
    total_prs: int = 0
    last_activity: str = ""
    notes: str = ""


@dataclass
class OrgRepo:
    """An organization repository with metadata."""
    full_name: str
    description: str = ""
    language: str = ""
    stars: int = 0
    updated_at: str = ""
    topics: List[str] = field(default_factory=list)
    private: bool = False


class FleetReader:
    """Read fleet state from GitHub repos.

    Parameters
    ----------
    github:
        A GitHub API client (implements the ``GitHubClient`` protocol).
    fleet_org:
        The fleet organization name.
    index_repo:
        The index/oracle repo name (default ``"oracle1-index"``).
    """

    def __init__(
        self,
        github: Any,
        fleet_org: str,
        index_repo: str = "oracle1-index",
    ) -> None:
        self.github = github
        self.fleet_org = fleet_org
        self.index_repo = index_repo

    # ------------------------------------------------------------------
    # TASKS.md
    # ------------------------------------------------------------------

    def read_tasks(self) -> List[FleetTask]:
        """Read and parse TASKS.md from the index repo."""
        content = self.github.get_file_contents(
            self.fleet_org, self.index_repo, "TASKS.md"
        )
        if content is None:
            logger.debug("No TASKS.md found in %s/%s", self.fleet_org, self.index_repo)
            return []
        return self._parse_tasks_md(content)

    def _parse_tasks_md(self, content: str) -> List[FleetTask]:
        """Parse TASKS.md content into FleetTask objects.

        Expected format (table or checkbox list):

        Table format::
            | ID | Repo | Task | Skills | Priority |
            |----|------|------|--------|----------|
            | T1 | repo1 | Fix bug | python | critical |

        Checkbox format::
            - [ ] T1 | repo1 | Fix bug | python | critical
        """
        tasks: List[FleetTask] = []

        # Try table format first
        table_tasks = self._parse_table_format(content)
        if table_tasks:
            return table_tasks

        # Fall back to checkbox format
        task_counter = 0
        for line in content.splitlines():
            line = line.strip()
            if not line.startswith("- [ ]") and not line.startswith("- [x]"):
                continue
            if line.startswith("- [x]"):
                continue

            desc_match = re.match(r"- \[ \]\s*(.+)", line)
            if not desc_match:
                continue

            full_desc = desc_match.group(1).strip()
            parts = [p.strip() for p in full_desc.split("|")]

            task_id = parts[0] if parts else f"task-{len(tasks) + 1}"
            repo = parts[1] if len(parts) > 1 else self.index_repo
            description = parts[2] if len(parts) > 2 else full_desc
            skills = [s.strip() for s in parts[3].split(",")] if len(parts) > 3 else []
            priority = self._parse_priority(parts[4]) if len(parts) > 4 else TaskPriority.MEDIUM
            effort = "medium"
            impact = "medium"

            # Check for effort/impact in description
            if "effort:low" in full_desc.lower():
                effort = "low"
            elif "effort:high" in full_desc.lower():
                effort = "high"
            if "impact:high" in full_desc.lower():
                impact = "high"
            elif "impact:low" in full_desc.lower():
                impact = "low"

            task_counter += 1
            tasks.append(FleetTask(
                id=task_id,
                repo=repo,
                task=description,
                skills=skills,
                priority=priority,
                effort=effort,
                impact=impact,
            ))

        return tasks

    def _parse_table_format(self, content: str) -> List[FleetTask]:
        """Try to parse TASKS.md as a Markdown table."""
        tasks: List[FleetTask] = []
        lines = content.splitlines()

        # Find table header
        header_idx = None
        for i, line in enumerate(lines):
            if "|" in line and ("ID" in line or "Task" in line):
                # Check next line is separator
                if i + 1 < len(lines) and re.match(r"^\|[-|]+\|", lines[i + 1].strip()):
                    header_idx = i
                    break

        if header_idx is None:
            return []

        # Parse header columns
        header = [h.strip().lower() for h in lines[header_idx].split("|")[1:-1]]
        col_map = {
            "id": header.index("id") if "id" in header else 0,
            "repo": header.index("repo") if "repo" in header else 1,
            "task": header.index("task") if "task" in header else 2,
            "skills": header.index("skills") if "skills" in header else 3,
            "priority": header.index("priority") if "priority" in header else 4,
        }

        # Parse rows
        for line in lines[header_idx + 2:]:  # skip header and separator
            if not line.strip() or "|" not in line:
                continue
            cols = [c.strip() for c in line.split("|")[1:-1]]
            if len(cols) < 3:
                continue

            task_id = cols[col_map["id"]] if len(cols) > col_map["id"] else f"task-{len(tasks) + 1}"
            repo = cols[col_map["repo"]] if len(cols) > col_map["repo"] else self.index_repo
            task_desc = cols[col_map["task"]] if len(cols) > col_map["task"] else ""
            skills = [s.strip() for s in cols[col_map["skills"]].split(",")] if len(cols) > col_map["skills"] else []
            priority = self._parse_priority(cols[col_map["priority"]]) if len(cols) > col_map["priority"] else TaskPriority.MEDIUM

            if not task_desc:
                continue

            tasks.append(FleetTask(
                id=task_id,
                repo=repo,
                task=task_desc,
                skills=skills,
                priority=priority,
            ))

        return tasks

    @staticmethod
    def _parse_priority(raw: str) -> TaskPriority:
        """Parse a priority string."""
        raw = raw.strip().lower()
        mapping = {
            "critical": TaskPriority.CRITICAL,
            "high": TaskPriority.HIGH,
            "medium": TaskPriority.MEDIUM,
            "low": TaskPriority.LOW,
            "info": TaskPriority.INFO,
        }
        return mapping.get(raw, TaskPriority.MEDIUM)

    # ------------------------------------------------------------------
    # Bottles
    # ------------------------------------------------------------------

    def read_bottles(self, repo: Optional[str] = None) -> List[Bottle]:
        """Read bottles from a fleet repo."""
        if repo is None:
            repo = "fleet-msgs"
        raw_bottles = self.github.get_bottles(self.fleet_org, repo)
        return [Bottle.from_dict(b) for b in raw_bottles]

    # ------------------------------------------------------------------
    # Fleet status
    # ------------------------------------------------------------------

    def read_fleet_status(self) -> FleetStatus:
        """Read fleet status from THE-FLEET.md or STATUS.md."""
        status = FleetStatus()

        # Try THE-FLEET.md
        fleet_md = self.github.get_file_contents(
            self.fleet_org, self.index_repo, "THE-FLEET.md"
        )
        if fleet_md:
            status = self._parse_fleet_md(fleet_md, status)

        # Try STATUS.md
        status_md = self.github.get_file_contents(
            self.fleet_org, self.index_repo, "STATUS.md"
        )
        if status_md:
            status = self._parse_status_md(status_md, status)

        return status

    def _parse_fleet_md(self, content: str, status: FleetStatus) -> FleetStatus:
        """Parse THE-FLEET.md content."""
        # Extract agent entries
        for m in re.finditer(r"##\s+(.+?)\n\n((?:.+?\n?)*?)(?=\n##|\Z)", content, re.DOTALL):
            agent_name = m.group(1).strip()
            agent_body = m.group(2)
            agent_info: Dict[str, Any] = {"name": agent_name}

            stage_m = re.search(r"Stage:\s*(\w+)", agent_body)
            if stage_m:
                agent_info["stage"] = stage_m.group(1)

            tasks_m = re.search(r"Active Tasks:\s*(\d+)", agent_body)
            if tasks_m:
                agent_info["active_tasks"] = int(tasks_m.group(1))
                status.active_tasks += int(tasks_m.group(1))

            status.agents.append(agent_info)

        return status

    def _parse_status_md(self, content: str, status: FleetStatus) -> FleetStatus:
        """Parse STATUS.md content."""
        prs_m = re.search(r"Total PRs:\s*(\d+)", content)
        if prs_m:
            status.total_prs = int(prs_m.group(1))

        activity_m = re.search(r"Last Activity:\s*(.+)", content)
        if activity_m:
            status.last_activity = activity_m.group(1).strip()

        return status

    # ------------------------------------------------------------------
    # Org repos
    # ------------------------------------------------------------------

    def list_org_repos(self) -> List[OrgRepo]:
        """List all repos in the fleet org with metadata."""
        raw_repos = self.github.list_org_repos(self.fleet_org)
        repos: List[OrgRepo] = []
        for r in raw_repos:
            repos.append(OrgRepo(
                full_name=r.get("full_name", ""),
                description=r.get("description", "") or "",
                language=r.get("language", "") or "",
                stars=r.get("stargazers_count", 0),
                updated_at=r.get("updated_at", ""),
                topics=r.get("topics", []),
                private=r.get("private", False),
            ))
        return repos

    # ------------------------------------------------------------------
    # Recent activity
    # ------------------------------------------------------------------

    def check_recent_activity(self, days: int = 7) -> List[Dict[str, Any]]:
        """Check recent activity across org repos.

        Returns a list of recent commits across repos.
        """
        activity: List[Dict[str, Any]] = []
        repos = self.list_org_repos()

        for repo in repos[:20]:  # limit to top 20 repos
            if "/" not in repo.full_name:
                continue
            owner, name = repo.full_name.split("/", 1)
            try:
                commits = self.github.list_commits(owner, name, per_page=5)
                for commit in commits:
                    date_str = commit.get("commit", {}).get("author", {}).get("date", "")
                    if date_str:
                        commit_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
                        if commit_date.timestamp() >= cutoff:
                            activity.append({
                                "repo": repo.full_name,
                                "sha": commit.get("sha", ""),
                                "message": commit.get("commit", {}).get("message", "").split("\n")[0],
                                "author": commit.get("commit", {}).get("author", {}).get("name", ""),
                                "date": date_str,
                            })
            except Exception as exc:
                logger.debug("Could not get commits for %s: %s", repo.full_name, exc)

        return activity
