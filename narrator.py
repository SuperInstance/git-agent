"""
Commit Narrative Engine — Translates raw git history into human-readable stories.

Parses git logs, classifies commits, detects patterns (experiments, refactors,
stuck loops), and generates natural-language narratives in multiple styles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class CommitType(str, Enum):
    FEATURE = "feature"
    FIX = "fix"
    REFACTOR = "refactor"
    TEST = "test"
    DOCS = "docs"
    CHORE = "chore"
    EXPERIMENT = "experiment"
    REVERT = "revert"
    UNKNOWN = "unknown"


class NarrativeStyle(str, Enum):
    BRIEF = "brief"
    DETAILED = "detailed"
    TECHNICAL = "technical"
    STORY = "story"


@dataclass
class FileChange:
    """Represents a single file changed in a commit."""
    path: str
    status: str  # 'A' added, 'M' modified, 'D' deleted, 'R' renamed
    insertions: int = 0
    deletions: int = 0


@dataclass
class Commit:
    """Structured representation of a git commit."""
    hash: str
    short_hash: str
    author: str
    date: datetime
    message: str
    subject: str
    body: str
    commit_type: CommitType = CommitType.UNKNOWN
    files_changed: list[FileChange] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class Experiment:
    """Detected experiment pattern (attempt → failure → retry → success)."""
    commits: list[Commit]
    hypothesis: str
    attempts: int
    resolved: bool
    resolution_commit: Optional[Commit] = None


@dataclass
class Narrative:
    """Generated narrative output."""
    text: str
    style: NarrativeStyle
    commits_covered: int
    experiments_detected: int
    timeline: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CONVENTIONAL_RE = re.compile(
    r"^(?P<type>feat|fix|refactor|test|docs|chore|perf|style|build|ci|revert)"
    r"(?:\((?P<scope>[^)]+)\))?"
    r":\s*(?P<subject>.+)$",
    re.IGNORECASE,
)

_TYPE_MAP = {
    "feat": CommitType.FEATURE,
    "fix": CommitType.FIX,
    "refactor": CommitType.REFACTOR,
    "test": CommitType.TEST,
    "docs": CommitType.DOCS,
    "chore": CommitType.CHORE,
    "perf": CommitType.REFACTOR,
    "style": CommitType.CHORE,
    "build": CommitType.CHORE,
    "ci": CommitType.CHORE,
    "revert": CommitType.REVERT,
}

_EXPERIMENT_KEYWORDS = [
    "try", "attempt", "experiment", "prototype", "spike",
    "exploring", "wip", "poc", "proof of concept", "trial",
    "what if", "maybe", "let's see",
]

_FAILURE_KEYWORDS = [
    "fix", "revert", "oops", "undo", "roll back", "broke",
    "caused", "regression", "failed", "doesn't work", "wrong",
    "issue", "bug", "broken",
]

_SUCCESS_KEYWORDS = [
    "working", "resolved", "fixed", "success", "complete",
    "done", "achieved", "passing", "green", "stable",
    "correctly", "properly", "final",
]


def _parse_git_date(raw: str) -> datetime:
    """Parse a git log date string into a datetime object."""
    raw = raw.strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S %z",
        "%Y-%m-%d %H:%M:%S",
        "%a %b %d %H:%M:%S %Y %z",
        "%a %b %d %H:%M:%S %Y",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse git date: {raw!r}")


def _shorten_hash(h: str) -> str:
    return h[:7] if len(h) >= 7 else h


# ---------------------------------------------------------------------------
# CommitNarrator
# ---------------------------------------------------------------------------

class CommitNarrator:
    """Translates raw git history into structured, human-readable narratives."""

    def __init__(self) -> None:
        self._commit_cache: dict[str, list[Commit]] = {}

    # ---- Parsing ----------------------------------------------------------

    def parse_log(self, git_log_output: str) -> list[Commit]:
        """Parse the output of ``git log --format=...`` into structured Commits.

        Expects the caller to run something like::

            git log --format="COMMIT_START%nHash: %H%nShort: %h%nAuthor: %an%nDate: %aI%nSubject: %s%n%b%nCOMMIT_END"
        """
        commits: list[Commit] = []
        raw_blocks = re.split(r"^COMMIT_END\s*$", git_log_output, flags=re.MULTILINE)

        for block in raw_blocks:
            block = block.strip()
            if not block or not block.startswith("COMMIT_START"):
                continue

            lines = block.splitlines()
            fields: dict[str, str] = {}
            body_lines: list[str] = []

            in_body = False
            for line in lines:
                if line == "COMMIT_START":
                    continue
                if in_body:
                    body_lines.append(line)
                    continue
                match = re.match(r"^(Hash|Short|Author|Date|Subject):\s*(.+)$", line)
                if match:
                    fields[match.group(1)] = match.group(2).strip()
                elif ":" not in line or line.startswith("    "):
                    in_body = True
                    body_lines.append(line)

            h = fields.get("Hash", "")
            subject = fields.get("Subject", "")
            author = fields.get("Author", "unknown")
            date_raw = fields.get("Date", "")
            body = "\n".join(body_lines).strip()

            try:
                date = _parse_git_date(date_raw)
            except ValueError:
                date = datetime.now()

            commit = Commit(
                hash=h,
                short_hash=_shorten_hash(h),
                author=author,
                date=date,
                message=f"{subject}\n{body}".strip(),
                subject=subject,
                body=body,
            )
            commit.commit_type = self.classify_commit(subject, [])
            commits.append(commit)

        return commits

    # ---- Classification ---------------------------------------------------

    def classify_commit(
        self,
        message: str,
        files_changed: list[FileChange] | None = None,
    ) -> CommitType:
        """Classify a commit into a semantic type based on its message and files."""
        files_changed = files_changed or []
        msg_lower = message.lower().strip()

        # Conventional commit prefix
        conv_match = _CONVENTIONAL_RE.match(msg_lower)
        if conv_match:
            mapped = _TYPE_MAP.get(conv_match.group("type").lower())
            if mapped:
                return mapped

        # Keyword heuristics
        for kw in _EXPERIMENT_KEYWORDS:
            if kw in msg_lower:
                return CommitType.EXPERIMENT

        for kw in _FAILURE_KEYWORDS:
            if kw in msg_lower and "fix" in msg_lower:
                return CommitType.FIX

        if any("test" in f.path for f in files_changed):
            return CommitType.TEST
        if any(f.path.endswith((".md", ".rst", ".txt")) for f in files_changed):
            return CommitType.DOCS

        # Default guessing from message
        if any(w in msg_lower for w in ("add", "implement", "create", "introduce")):
            return CommitType.FEATURE
        if any(w in msg_lower for w in ("clean", "tidy", "organize", "move")):
            return CommitType.REFACTOR

        return CommitType.UNKNOWN

    # ---- Pattern detection ------------------------------------------------

    def detect_experiment(self, commit_sequence: list[Commit]) -> Optional[Experiment]:
        """Detect try/fail/succeed experimental patterns in a commit window.

        An experiment is a sequence where the agent tries something, encounters
        problems, and then resolves them — or fails to.
        """
        if len(commit_sequence) < 2:
            return None

        attempts: list[Commit] = []
        resolved = False
        resolution_commit: Optional[Commit] = None

        for commit in commit_sequence:
            msg_lower = commit.subject.lower()
            is_experiment = any(kw in msg_lower for kw in _EXPERIMENT_KEYWORDS)
            is_fix = any(kw in msg_lower for kw in _FAILURE_KEYWORDS)
            is_success = any(kw in msg_lower for kw in _SUCCESS_KEYWORDS)

            if is_success and attempts and not resolved:
                resolved = True
                resolution_commit = commit
                attempts.append(commit)
            elif is_experiment:
                attempts.append(commit)
            elif is_fix:
                attempts.append(commit)
            elif not resolved:
                attempts.append(commit)

        if len(attempts) < 2:
            return None

        hypothesis = attempts[0].subject
        return Experiment(
            commits=attempts,
            hypothesis=hypothesis,
            attempts=len(attempts),
            resolved=resolved,
            resolution_commit=resolution_commit,
        )

    def detect_refactor(self, commit_sequence: list[Commit]) -> bool:
        """Detect if a commit sequence represents a refactoring operation.

        Refactoring is characterized by many modified/deleted files without
        corresponding test additions and no new feature additions.
        """
        if not commit_sequence:
            return False

        refactor_count = 0
        feature_count = 0
        total = len(commit_sequence)

        for commit in commit_sequence:
            msg_lower = commit.subject.lower()
            if commit.commit_type == CommitType.REFACTOR:
                refactor_count += 1
            elif any(w in msg_lower for w in ("refactor", "rename", "restructure", "reorg", "extract")):
                refactor_count += 1
            elif commit.commit_type == CommitType.FEATURE or any(
                w in msg_lower for w in ("feat:", "add", "implement", "create", "introduce")
            ):
                feature_count += 1

        return refactor_count > total * 0.5 and feature_count == 0

    def detect_stuck_patterns(
        self,
        commits: list[Commit],
        window_size: int = 5,
    ) -> list[list[Commit]]:
        """Detect when an agent is stuck in a loop.

        Stuck patterns look like:
        - Similar commit messages repeating (e.g. "fix X", "fix X again", "fix X v3")
        - Reverts followed by identical re-apply
        - Circular modifications (modify file A, then B, then A again, then B...)
        """
        stuck_sequences: list[list[Commit]] = []

        for i in range(len(commits) - window_size + 1):
            window = commits[i : i + window_size]
            subjects = [c.subject.lower().strip() for c in window]

            # Check for near-duplicate subjects
            seen_subjects: dict[str, int] = {}
            for subj in subjects:
                # Normalize: strip version numbers like "v2", "v3", "again", "attempt 2"
                normalized = re.sub(r"\s*(v\d+|again|attempt\s*\d+|take\s*\d+|mark\s*\d+)\s*$", "", subj).strip()
                seen_subjects[normalized] = seen_subjects.get(normalized, 0) + 1

            duplicates = [s for s, cnt in seen_subjects.items() if cnt >= 3]
            if duplicates:
                stuck_sequences.append(window)
                continue

            # Check for revert-reapply cycles
            revert_count = sum(1 for c in window if c.commit_type == CommitType.REVERT)
            if revert_count >= 2:
                stuck_sequences.append(window)
                continue

            # Check for circular file modifications (approximate via commit type pattern)
            types = [c.commit_type for c in window]
            if types.count(CommitType.FIX) >= 3 and types.count(CommitType.FEATURE) == 0:
                stuck_sequences.append(window)

        return stuck_sequences

    # ---- Narrative generation ---------------------------------------------

    def generate_narrative(
        self,
        commits: list[Commit],
        style: NarrativeStyle = NarrativeStyle.STORY,
    ) -> Narrative:
        """Generate a narrative from a list of commits."""
        if not commits:
            return Narrative(
                text="No commits to narrate.",
                style=style,
                commits_covered=0,
                experiments_detected=0,
                timeline="",
            )

        experiments: list[Experiment] = []
        seen_experiment_hashes: set[str] = set()

        # Sliding window experiment detection
        window = 4
        for i in range(len(commits) - window + 1):
            seq = commits[i : i + window]
            if any(c.hash in seen_experiment_hashes for c in seq):
                continue
            exp = self.detect_experiment(seq)
            if exp:
                experiments.append(exp)
                for c in exp.commits:
                    seen_experiment_hashes.add(c.hash)

        timeline = self.generate_timeline(commits)

        if style == NarrativeStyle.BRIEF:
            text = self._narrate_brief(commits)
        elif style == NarrativeStyle.DETAILED:
            text = self._narrate_detailed(commits, experiments)
        elif style == NarrativeStyle.TECHNICAL:
            text = self._narrate_technical(commits)
        else:
            text = self._narrate_story(commits, experiments)

        return Narrative(
            text=text,
            style=style,
            commits_covered=len(commits),
            experiments_detected=len(experiments),
            timeline=timeline,
        )

    def _narrate_brief(self, commits: list[Commit]) -> str:
        """One-line per commit summary."""
        lines: list[str] = []
        for c in commits:
            date_str = c.date.strftime("%Y-%m-%d")
            type_tag = c.commit_type.value.upper()
            lines.append(f"[{date_str}] ({type_tag}) {c.subject} ({c.short_hash})")
        return "\n".join(lines)

    def _narrate_detailed(
        self, commits: list[Commit], experiments: list[Experiment]
    ) -> str:
        """Structured report with sections."""
        sections: list[str] = []

        # Overview
        type_counts: dict[str, int] = {}
        for c in commits:
            t = c.commit_type.value
            type_counts[t] = type_counts.get(t, 0) + 1

        sections.append("## Overview")
        sections.append(f"Total commits: {len(commits)}")
        sections.append(f"Date range: {commits[-1].date.strftime('%Y-%m-%d')} → {commits[0].date.strftime('%Y-%m-%d')}")
        sections.append("")
        sections.append("### Commit Types")
        for ctype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            sections.append(f"- {ctype}: {count}")

        # Experiments
        if experiments:
            sections.append("")
            sections.append(f"## Experiments Detected ({len(experiments)})")
            for idx, exp in enumerate(experiments, 1):
                status = "resolved" if exp.resolved else "unresolved"
                sections.append(f"### Experiment {idx}: \"{exp.hypothesis}\" [{status}]")
                sections.append(f"- Attempts: {exp.attempts}")
                for ec in exp.commits:
                    sections.append(f"  - {ec.short_hash}: {ec.subject}")
                if exp.resolution_commit:
                    sections.append(f"- Resolution: {exp.resolution_commit.short_hash}")

        # Commit log
        sections.append("")
        sections.append("## Commit Log")
        for c in commits:
            date_str = c.date.strftime("%Y-%m-%d %H:%M")
            sections.append(f"### {c.short_hash} — {date_str}")
            sections.append(f"**{c.subject}**")
            if c.body:
                sections.append(f"> {c.body}")
            sections.append("")

        return "\n".join(sections)

    def _narrate_technical(self, commits: list[Commit]) -> str:
        """Technical summary with type breakdown and statistics."""
        lines: list[str] = []
        type_counts: dict[str, int] = {}
        authors: dict[str, int] = {}

        for c in commits:
            t = c.commit_type.value
            type_counts[t] = type_counts.get(t, 0) + 1
            authors[c.author] = authors.get(c.author, 0) + 1

        lines.append("TECHNICAL REPORT")
        lines.append("=" * 60)
        lines.append(f"Commits: {len(commits)}")
        lines.append(f"Authors: {', '.join(authors.keys())}")
        lines.append("")
        lines.append("BREAKDOWN BY TYPE:")
        for ctype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            bar = "█" * count + "░" * (len(commits) - count)
            lines.append(f"  {ctype:<12} {bar} ({count})")

        lines.append("")
        lines.append("COMMITS:")
        for c in commits:
            lines.append(f"  {c.short_hash} [{c.commit_type.value:<10}] {c.subject}")

        # Stuck pattern check
        stuck = self.detect_stuck_patterns(commits)
        if stuck:
            lines.append("")
            lines.append(f"⚠ STUCK PATTERNS DETECTED: {len(stuck)}")
            for seq in stuck:
                lines.append(f"  Window around {seq[0].short_hash}–{seq[-1].short_hash}")

        return "\n".join(lines)

    def _narrate_story(
        self, commits: list[Commit], experiments: list[Experiment]
    ) -> str:
        """Natural-language story narrative."""
        paragraphs: list[str] = []

        if not commits:
            return "No activity to report."

        # Group commits by date for temporal flow
        by_date: dict[str, list[Commit]] = {}
        for c in commits:
            day = c.date.strftime("%A, %B %d, %Y")
            by_date.setdefault(day, []).append(c)

        sorted_days = sorted(by_date.keys())

        for day, day_commits in by_date.items():
            day_paragraphs: list[str] = [f"On {day},"]

            type_groups: dict[CommitType, list[Commit]] = {}
            for c in day_commits:
                type_groups.setdefault(c.commit_type, []).append(c)

            # Features
            if CommitType.FEATURE in type_groups:
                features = type_groups[CommitType.FEATURE]
                if len(features) == 1:
                    day_paragraphs.append(f"the agent added a new feature: {features[0].subject.lower()}.")
                else:
                    names = ", ".join(f.subject.lower() for f in features)
                    day_paragraphs.append(f"the agent implemented {len(features)} new features: {names}.")

            # Fixes
            if CommitType.FIX in type_groups:
                fixes = type_groups[CommitType.FIX]
                if len(fixes) == 1:
                    day_paragraphs.append(f"It fixed an issue: {fixes[0].subject.lower()}.")
                else:
                    day_paragraphs.append(f"It resolved {len(fixes)} issues.")

            # Experiments on this day
            day_experiments = [
                e for e in experiments
                if any(c in day_commits for c in e.commits)
            ]
            for exp in day_experiments:
                if exp.resolved:
                    day_paragraphs.append(
                        f"It ran an experiment ({exp.hypothesis.lower()}) that went through "
                        f"{exp.attempts} iterations before succeeding."
                    )
                else:
                    day_paragraphs.append(
                        f"It began experimenting with {exp.hypothesis.lower()} "
                        f"({exp.attempts} attempts so far, not yet resolved)."
                    )

            # Refactors
            if CommitType.REFACTOR in type_groups:
                refs = type_groups[CommitType.REFACTOR]
                day_paragraphs.append(
                    f"It performed {len(refs)} refactoring operation{'s' if len(refs) > 1 else ''} "
                    f"to improve code quality."
                )

            # Tests
            if CommitType.TEST in type_groups:
                tests = type_groups[CommitType.TEST]
                day_paragraphs.append(f"It added {len(tests)} test commit{'s' if len(tests) > 1 else ''}.")

            # Remaining (chore, docs, unknown, experiment)
            remaining = []
            for ct in (CommitType.CHORE, CommitType.DOCS, CommitType.UNKNOWN, CommitType.EXPERIMENT):
                if ct in type_groups:
                    remaining.extend(type_groups[ct])
            if remaining:
                day_paragraphs.append(
                    f"There were also {len(remaining)} other commits (maintenance, docs, experiments)."
                )

            # Join and clean up
            text = " ".join(day_paragraphs)
            text = text.replace("..", ".").replace("  ", " ")
            paragraphs.append(text)

        # Closing summary
        if experiments:
            resolved = sum(1 for e in experiments if e.resolved)
            unresolved = len(experiments) - resolved
            closing = f"\nIn total, {len(commits)} commits were made across {len(sorted_days)} day(s)."
            closing += f" {resolved} experiment(s) were completed successfully."
            if unresolved:
                closing += f" {unresolved} experiment(s) remain unresolved."
            paragraphs.append(closing)

        return "\n\n".join(paragraphs)

    # ---- Timeline ---------------------------------------------------------

    def generate_timeline(self, commits: list[Commit]) -> str:
        """Generate a visual timeline from commits."""
        if not commits:
            return "── No commits ──"

        lines: list[str] = []
        type_icons: dict[CommitType, str] = {
            CommitType.FEATURE: "🚀",
            CommitType.FIX: "🔧",
            CommitType.REFACTOR: "♻️",
            CommitType.TEST: "🧪",
            CommitType.DOCS: "📝",
            CommitType.CHORE: "⚙️",
            CommitType.EXPERIMENT: "🔬",
            CommitType.REVERT: "↩️",
            CommitType.UNKNOWN: "●",
        }

        lines.append(f"Timeline: {commits[-1].date.strftime('%Y-%m-%d')} → {commits[0].date.strftime('%Y-%m-%d')}")
        lines.append("=" * 70)

        prev_date = ""
        for c in commits:
            date_str = c.date.strftime("%Y-%m-%d")
            time_str = c.date.strftime("%H:%M")
            icon = type_icons.get(c.commit_type, "●")

            if date_str != prev_date:
                if prev_date:
                    lines.append("")
                lines.append(f"┌─ {date_str}")
                prev_date = date_str

            subject = c.subject[:55] + ("…" if len(c.subject) > 55 else "")
            lines.append(f"│ {time_str}  {icon} {c.short_hash}  {subject}")

        lines.append("└─ end")
        return "\n".join(lines)

    # ---- Comparison & Summaries -------------------------------------------

    def compare_timelines(
        self,
        agent_a: list[Commit],
        agent_b: list[Commit],
    ) -> str:
        """Compare two agents' work patterns side-by-side."""
        def stats(commits: list[Commit]) -> dict[str, str | int]:
            type_counts: dict[str, int] = {}
            for c in commits:
                t = c.commit_type.value
                type_counts[t] = type_counts.get(t, 0) + 1
            first = commits[-1].date.strftime("%Y-%m-%d") if commits else "N/A"
            last = commits[0].date.strftime("%Y-%m-%d") if commits else "N/A"
            return {
                "total": len(commits),
                "first": first,
                "last": last,
                "types": type_counts,
                "experiments": sum(1 for c in commits if c.commit_type == CommitType.EXPERIMENT),
            }

        sa, sb = stats(agent_a), stats(agent_b)
        lines: list[str] = [
            "COMPARISON REPORT",
            "=" * 60,
            f"  Agent A: {sa['total']} commits ({sa['first']} → {sa['last']})",
            f"  Agent B: {sb['total']} commits ({sb['first']} → {sb['last']})",
            "",
            "COMMIT TYPE BREAKDOWN:",
        ]

        all_types = sorted(set(list(sa["types"].keys()) + list(sb["types"].keys())))
        max_len = max(len(t) for t in all_types) if all_types else 5
        for t in all_types:
            ca = sa["types"].get(t, 0)
            cb = sb["types"].get(t, 0)
            lines.append(f"  {t:<{max_len}}  A: {ca:<4}  B: {cb:<4}")

        lines.append("")
        lines.append(f"  Experiments — A: {sa['experiments']}  B: {sb['experiments']}")
        return "\n".join(lines)

    def summarize_week(self, commits: list[Commit]) -> str:
        """Generate a weekly summary of commits."""
        by_week: dict[str, list[Commit]] = {}
        for c in commits:
            week_key = c.date.strftime("%Y-W%W")
            by_week.setdefault(week_key, []).append(c)

        lines: list[str] = ["WEEKLY SUMMARY", "=" * 60]
        for week, week_commits in sorted(by_week.items()):
            type_counts: dict[str, int] = {}
            for c in week_commits:
                t = c.commit_type.value
                type_counts[t] = type_counts.get(t, 0) + 1

            lines.append(f"\n{week}: {len(week_commits)} commits")
            for ct, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
                lines.append(f"  {ct}: {cnt}")

            # Top experiment
            experiments = []
            window = 4
            for i in range(len(week_commits) - window + 1):
                exp = self.detect_experiment(week_commits[i : i + window])
                if exp:
                    experiments.append(exp)
            if experiments:
                resolved = sum(1 for e in experiments if e.resolved)
                lines.append(f"  experiments: {len(experiments)} ({resolved} resolved)")

        return "\n".join(lines)

    # ---- Lessons ----------------------------------------------------------

    def extract_lessons(self, commits: list[Commit]) -> list[str]:
        """Extract lessons learned from trial-and-error patterns."""
        lessons: list[str] = []
        experiments: list[Experiment] = []

        window = 4
        for i in range(len(commits) - window + 1):
            exp = self.detect_experiment(commits[i : i + window])
            if exp and exp.resolved:
                experiments.append(exp)

        seen_hypotheses: set[str] = set()
        for exp in experiments:
            hyp_key = exp.hypothesis[:50].lower()
            if hyp_key in seen_hypotheses:
                continue
            seen_hypotheses.add(hyp_key)

            if exp.resolution_commit:
                lesson = (
                    f"When attempting \"{exp.hypothesis}\", "
                    f"it took {exp.attempts} iterations. "
                    f"The successful approach was: {exp.resolution_commit.subject}."
                )
                lessons.append(lesson)

        # Also extract patterns from stuck sequences
        stuck = self.detect_stuck_patterns(commits)
        if stuck:
            lessons.append(
                f"Detected {len(stuck)} stuck pattern(s) — the agent encountered "
                f"repeated failures and should consider a different approach."
            )

        return lessons

    # ---- Export -----------------------------------------------------------

    def export_markdown(self, narrative: Narrative) -> str:
        """Export a narrative to markdown format."""
        md: list[str] = []
        md.append("# Git Agent Narrative Report")
        md.append("")
        md.append(f"**Style**: {narrative.style.value}")
        md.append(f"**Commits covered**: {narrative.commits_covered}")
        md.append(f"**Experiments detected**: {narrative.experiments_detected}")
        md.append("")
        md.append("---")
        md.append("")
        md.append("## Narrative")
        md.append("")
        for line in narrative.text.splitlines():
            if line.startswith("##") or line.startswith("###"):
                md.append(line)
            else:
                md.append(line)
                md.append("")
        if narrative.timeline:
            md.append("## Timeline")
            md.append("")
            md.append("```")
            md.append(narrative.timeline)
            md.append("```")
        return "\n".join(md)
