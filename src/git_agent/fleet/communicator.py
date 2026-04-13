"""
git_agent.fleet.communicator — Fleet inter-agent communication.

Handles:
    - Push bottles to oracle1-index
    - Read bottles from other agents
    - Create I2I (inter-agent) messages
    - Parse I2I message format
    - Broadcast fleet status
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BOTTLE_DIR = "message-in-a-bottle"
I2I_DIR = "i2i-messages"


@dataclass
class Bottle:
    """A message in the fleet bottle system."""
    sender: str
    content: str
    title: str = ""
    timestamp: str = ""
    stage: str = ""
    path: str = ""
    target: Optional[str] = None  # Specific agent or None for broadcast

    def format(self) -> str:
        """Format bottle content as Markdown."""
        now = self.timestamp or datetime.now(timezone.utc).isoformat()
        parts = [
            f"**From:** {self.sender}",
            f"**Time:** {now}",
        ]
        if self.stage:
            parts.append(f"**Stage:** {self.stage}")
        if self.target:
            parts.append(f"**To:** {self.target}")
        parts.append("")
        parts.append(self.content)
        return "\n".join(parts)


@dataclass
class I2IMessage:
    """An inter-agent message."""
    sender: str
    recipient: str
    subject: str
    body: str
    timestamp: str = ""
    priority: str = "normal"  # normal, high, urgent
    task_refs: List[str] = field(default_factory=list)
    requires_response: bool = False

    I2I_FORMAT = (
        "---\n"
        "sender: {sender}\n"
        "recipient: {recipient}\n"
        "subject: {subject}\n"
        "timestamp: {timestamp}\n"
        "priority: {priority}\n"
        "requires_response: {requires_response}\n"
        "task_refs: {task_refs}\n"
        "---\n\n"
        "{body}"
    )

    @classmethod
    def parse(cls, content: str) -> Optional[I2IMessage]:
        """Parse an I2I message from markdown content.

        Expected format (YAML front matter)::

            ---
            sender: Agent A
            recipient: Agent B
            subject: Coordination needed
            timestamp: 2025-01-01T00:00:00Z
            priority: normal
            requires_response: true
            task_refs: T1, T2
            ---

            Message body here.
        """
        match = re.search(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
        if not match:
            return None

        front_matter = match.group(1)
        body = match.group(2).strip()

        fields: Dict[str, str] = {}
        for line in front_matter.strip().splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip()] = value.strip()

        task_refs = []
        if "task_refs" in fields and fields["task_refs"]:
            task_refs = [t.strip() for t in fields["task_refs"].split(",") if t.strip()]

        requires_response = fields.get("requires_response", "false").lower() == "true"

        return cls(
            sender=fields.get("sender", ""),
            recipient=fields.get("recipient", ""),
            subject=fields.get("subject", ""),
            body=body,
            timestamp=fields.get("timestamp", ""),
            priority=fields.get("priority", "normal"),
            task_refs=task_refs,
            requires_response=requires_response,
        )

    def format(self) -> str:
        """Format as I2I markdown with front matter."""
        now = self.timestamp or datetime.now(timezone.utc).isoformat()
        return self.I2I_FORMAT.format(
            sender=self.sender,
            recipient=self.recipient,
            subject=self.subject,
            timestamp=now,
            priority=self.priority,
            requires_response=str(self.requires_response).lower(),
            task_refs=", ".join(self.task_refs),
            body=self.body,
        )


class FleetCommunicator:
    """Fleet communication manager.

    Handles sending and receiving bottles and I2I messages.

    Parameters
    ----------
    github:
        A GitHub API client.
    fleet_org:
        Fleet organization name.
    agent_name:
        Name of this agent.
    index_repo:
        Index repo name (default ``"oracle1-index"``).
    """

    def __init__(
        self,
        github: Any,
        fleet_org: str,
        agent_name: str = "Super Z",
        index_repo: str = "oracle1-index",
    ) -> None:
        self.github = github
        self.fleet_org = fleet_org
        self.agent_name = agent_name
        self.index_repo = index_repo

    # ------------------------------------------------------------------
    # Bottles
    # ------------------------------------------------------------------

    def push_bottle(
        self,
        content: str,
        title: Optional[str] = None,
        stage: str = "",
        target: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Push a bottle (broadcast message) to the fleet.

        Parameters
        ----------
        content:
            Message content.
        title:
            Bottle title. Generated if None.
        stage:
            Agent's current stage (for context).
        target:
            Specific agent name, or None for broadcast.
        """
        now = datetime.now(timezone.utc).isoformat()
        bottle = Bottle(
            sender=self.agent_name,
            content=content,
            title=title or f"bottle-{now.strftime('%Y%m%d-%H%M%S')}",
            timestamp=now,
            stage=stage,
            target=target,
        )

        formatted = bottle.format()
        path = f"{BOTTLE_DIR}/{bottle.title}.md"
        message = f"Add bottle: {bottle.title}"

        result = self.github.create_or_update_file(
            self.fleet_org, self.index_repo,
            path, formatted, message, "main",
        )

        logger.info("Pushed bottle: %s", bottle.title)
        return {
            "status": "created",
            "title": bottle.title,
            "path": path,
            "target": target,
            "commit": result,
        }

    def read_bottles(
        self, repo: Optional[str] = None, since: Optional[str] = None
    ) -> List[Bottle]:
        """Read bottles from the fleet.

        Parameters
        ----------
        repo:
            Repo to read from (default fleet-msgs).
        since:
            Only return bottles after this ISO timestamp.
        """
        if repo is None:
            repo = "fleet-msgs"

        raw_bottles = self.github.get_bottles(self.fleet_org, repo)
        bottles: List[Bottle] = []

        for raw in raw_bottles:
            content = raw.get("content", "")
            title = raw.get("title", "")

            # Parse fields from content
            sender = ""
            timestamp = ""
            target = None
            stage = ""

            m = re.search(r"\*\*From:\*\*\s*(.+)", content)
            if m:
                sender = m.group(1).strip()
            m = re.search(r"\*\*Time:\*\*\s*(.+)", content)
            if m:
                timestamp = m.group(1).strip()
            m = re.search(r"\*\*To:\*\*\s*(.+)", content)
            if m:
                target = m.group(1).strip()
            m = re.search(r"\*\*Stage:\*\*\s*(.+)", content)
            if m:
                stage = m.group(1).strip()

            # Filter by timestamp if requested
            if since and timestamp:
                try:
                    bottle_time = datetime.fromisoformat(timestamp)
                    since_time = datetime.fromisoformat(since)
                    if bottle_time < since_time:
                        continue
                except (ValueError, TypeError):
                    pass

            bottles.append(Bottle(
                sender=sender,
                content=content,
                title=title,
                timestamp=timestamp,
                stage=stage,
                target=target,
                path=raw.get("path", ""),
            ))

        return bottles

    # ------------------------------------------------------------------
    # I2I Messages
    # ------------------------------------------------------------------

    def send_i2i_message(
        self,
        recipient: str,
        subject: str,
        body: str,
        priority: str = "normal",
        task_refs: Optional[List[str]] = None,
        requires_response: bool = False,
    ) -> Dict[str, Any]:
        """Send an I2I message to a specific agent.

        Parameters
        ----------
        recipient:
            Name of the target agent.
        subject:
            Message subject.
        body:
            Message body.
        priority:
            ``"normal"``, ``"high"``, or ``"urgent"``.
        task_refs:
            Task IDs referenced in this message.
        requires_response:
            Whether the recipient should respond.
        """
        msg = I2IMessage(
            sender=self.agent_name,
            recipient=recipient,
            subject=subject,
            body=body,
            timestamp=datetime.now(timezone.utc).isoformat(),
            priority=priority,
            task_refs=task_refs or [],
            requires_response=requires_response,
        )

        formatted = msg.format()
        filename = f"{msg.sender}-to-{msg.recipient}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.md"
        path = f"{I2I_DIR}/{filename}"
        message = f"I2I: {msg.subject}"

        result = self.github.create_or_update_file(
            self.fleet_org, self.index_repo,
            path, formatted, message, "main",
        )

        logger.info("Sent I2I to %s: %s", recipient, subject)
        return {
            "status": "sent",
            "recipient": recipient,
            "subject": subject,
            "path": path,
            "commit": result,
        }

    def read_i2i_messages(self, agent_name: Optional[str] = None) -> List[I2IMessage]:
        """Read I2I messages, optionally filtering for a specific agent.

        Parameters
        ----------
        agent_name:
            If given, only return messages addressed to this agent.
        """
        try:
            contents = self.github.list_files(
                self.fleet_org, self.index_repo, path=I2I_DIR
            )
        except Exception:
            return []

        messages: List[I2IMessage] = []
        for item in contents:
            if item.get("type") != "file" or not item.get("name", "").endswith(".md"):
                continue

            content = self.github.get_file_contents(
                self.fleet_org, self.index_repo, f"{I2I_DIR}/{item['name']}"
            )
            if not content:
                continue

            msg = I2IMessage.parse(content)
            if msg is None:
                continue

            # Filter by recipient if requested
            if agent_name and msg.recipient.lower() != agent_name.lower():
                continue

            messages.append(msg)

        # Sort by timestamp (most recent first)
        messages.sort(key=lambda m: m.timestamp, reverse=True)
        return messages

    # ------------------------------------------------------------------
    # Fleet status broadcast
    # ------------------------------------------------------------------

    def broadcast_status(
        self,
        stage: str = "",
        tasks_completed: int = 0,
        tasks_failed: int = 0,
        current_task: str = "",
        notes: str = "",
    ) -> Dict[str, Any]:
        """Broadcast the agent's current status to the fleet."""
        content = (
            f"**Stage:** {stage}\n"
            f"**Tasks Completed:** {tasks_completed}\n"
            f"**Tasks Failed:** {tasks_failed}\n"
        )
        if current_task:
            content += f"**Current Task:** {current_task}\n"
        if notes:
            content += f"\n{notes}\n"

        return self.push_bottle(
            content=content,
            title=f"status-{self.agent_name}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
            stage=stage,
        )
