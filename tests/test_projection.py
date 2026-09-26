"""
Behavioral tests for the captain's VIEW projection (git_agent.projection).

P0.3 of The Grand Quilt: given a vessel's WAL, render the one-page view a
human actually reads — identity, career trajectory, worklog digest, judgment
receipts, quality flags. The last mile is rendering, not archaeology.

Tests are golden-output on the real fixture stream: run the fixture events
through emitter+gate, render, assert structure. Offline by construction.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from git_agent.projection import render_state_md, render_state_json
from git_agent.jev_gate import JevGate
from git_agent.quilt_emit import QuiltEmitter

FIXTURES = Path("/tmp/git-agent/tests/fixtures")
EVENT_ORDER = ["session_start", "worklog", "task_completion", "promotion",
               "fence", "skill", "snapshot", "heartbeat", "session_end"]


class StubBackend:
    def __init__(self, score: float):
        self.score = score

    def available(self):
        return True

    def decide_batch(self, state, questions, model="jev-latest"):
        from git_agent.jev_gate import Judgment
        return ([Judgment(kind="noul", value=self.score,
                          confidence=self.score) for _ in questions],
                {"latency_ms": 0.1, "questions": len(questions)})


def build_stream(tmp_path, judge_score: float = 0.95):
    emitter = QuiltEmitter(wal_path=tmp_path / "quilt.jsonl")
    gate = JevGate(StubBackend(judge_score), threshold=0.5)
    for i, name in enumerate(EVENT_ORDER):
        ev = json.loads((FIXTURES / f"{name}.json").read_text())
        ev["event_id"] = f"evt-proj-{i:02d}"
        gate.ingest(emitter, ev)
    return emitter


@pytest.fixture()
def good_vessel(tmp_path):
    return build_stream(tmp_path, judge_score=0.95)


@pytest.fixture()
def flagged_vessel(tmp_path):
    return build_stream(tmp_path, judge_score=0.10)


# ── structure of the rendered view ───────────────────────────────────────

def test_markdown_view_has_all_sections(good_vessel):
    md = render_state_md(good_vessel)
    for section in ("# Vessel", "Identity", "Career", "Worklog", "Receipts"):
        assert section in md, f"missing section: {section}"


def test_identity_renders_from_bind_line(good_vessel):
    md = render_state_md(good_vessel)
    assert "Super Z" in md
    assert "Git-Native Agent" in md


def test_career_shows_stage_and_promotion(good_vessel):
    md = render_state_md(good_vessel)
    assert "initiate" in md and "apprentice" in md
    assert "first-pr" in md   # fence
    assert "code-review" in md  # skill


def test_worklog_digest_lists_actions(good_vessel):
    md = render_state_md(good_vessel)
    assert "branched" in md


def test_receipts_section_reports_judgment_scores(good_vessel):
    md = render_state_md(good_vessel)
    assert "0.95" in md  # judged worklog receipt


def test_flagged_work_is_visible_not_hidden(flagged_vessel):
    md = render_state_md(flagged_vessel)
    assert "FLAGGED" in md.upper()
    assert "1" in md  # flag count


def test_json_view_is_machine_readable(good_vessel):
    data = render_state_json(good_vessel)
    assert data["identity"]["name"] == "Super Z"
    assert data["career"]["promotions"] == [["initiate", "apprentice"]]
    assert data["worklog_count"] == 1
    assert data["flags"] == 0
    assert data["receipts"]["judged"] >= 1


def test_json_view_counts_flags(flagged_vessel):
    data = render_state_json(flagged_vessel)
    assert data["flags"] >= 1


def test_view_of_empty_vessel_is_honest(tmp_path):
    emitter = QuiltEmitter(wal_path=tmp_path / "quilt.jsonl")
    md = render_state_md(emitter)
    assert "no events" in md.lower()
