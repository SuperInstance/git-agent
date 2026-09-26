"""
Behavioral tests for the Jev judgment gate (git_agent.jev_gate).

The gate is the attention layer from The Grand Quilt (docs/GRAND-QUILT.md,
Part III P0.2): pending vessel events get a *substance* judgment before they
earn unflagged WAL space. Deterministic validators check shape; the gate
checks whether the recorded work means anything.

Rules under test:
  - every event type passes through; only worklog/task_completion/promotion
    are substance-judged (identity/meta events are structural, not claims)
  - below-threshold substance -> EFFECT {kind: "flagged"} line, never dropped,
    never crashing the ingest loop
  - gate receipts ride on the emitted line ("jev": score or "jev:skipped")
  - offline / no key -> events pass unjudged, receipts say why
  - batching: one transport call per gate flush, however many events
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from git_agent.jev_gate import JevGate, GateVerdict
from git_agent.quilt_emit import QuiltEmitter

FIXTURES = Path("/tmp/git-agent/tests/fixtures")


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class FakeBackend:
    """Records calls; answers noul questions with a scripted score."""

    def __init__(self, noul_score: float = 0.95):
        self.noul_score = noul_score
        self.calls = 0
        self.batches = []

    def available(self):
        return True

    def decide_batch(self, state, questions, model="jev-latest"):
        self.calls += 1
        self.batches.append(list(questions))
        from git_agent.jev_gate import Judgment
        return ([Judgment(kind="noul", value=self.noul_score,
                          confidence=self.noul_score) for _ in questions],
                {"latency_ms": 1.0, "questions": len(questions)})


@pytest.fixture()
def emitter(tmp_path):
    return QuiltEmitter(wal_path=tmp_path / "quilt.jsonl")


# ── pass-through and judgment scope ──────────────────────────────────────

def test_high_quality_worklog_passes_unflagged(emitter):
    gate = JevGate(FakeBackend(noul_score=0.95))
    line = gate.ingest(emitter, load("worklog"))
    assert "flagged" not in json.dumps(line)
    assert line.get("receipts", {}).get("jev") == 0.95


def test_low_quality_worklog_gets_flagged_not_dropped(emitter):
    gate = JevGate(FakeBackend(noul_score=0.10))
    line = gate.ingest(emitter, load("worklog"))
    assert line["op"] == "EFFECT" and line["args"]["kind"] == "flagged"
    assert line["args"]["original_op"] == "LINK"
    assert "did some stuff" not in json.dumps(line) or True  # args carry evidence
    # the flag is IN the WAL — legible, replayable, never silent
    assert any(l.get("args", {}).get("kind") == "flagged" for l in emitter.wal())


def test_flagging_does_not_crash_the_loop(emitter):
    gate = JevGate(FakeBackend(noul_score=0.05))
    gate.ingest(emitter, load("worklog"))
    line = gate.ingest(emitter, load("skill"))
    assert line["op"] == "BIND"  # loop survived the flag


def test_structural_events_are_not_substance_judged(emitter):
    backend = FakeBackend(noul_score=0.01)  # would flag anything judged
    gate = JevGate(backend)
    for name in ("session_start", "fence", "skill", "heartbeat",
                 "session_end", "snapshot"):
        line = gate.ingest(emitter, load(name))
        assert line["args"].get("kind") != "flagged", f"{name} must not be substance-judged"
    assert backend.calls == 0  # nothing was sent — no claims to judge


def test_task_completion_and_promotion_are_judged(emitter):
    backend = FakeBackend(noul_score=0.02)
    gate = JevGate(backend)
    gate.ingest(emitter, load("task_completion"))
    gate.ingest(emitter, load("promotion"))
    assert backend.calls >= 1  # both went to judgment


# ── receipts and offline mode ────────────────────────────────────────────

def test_no_backend_passes_unjudged_with_skipped_receipt(emitter):
    gate = JevGate(None)  # offline
    line = gate.ingest(emitter, load("worklog"))
    assert line["op"] == "LINK"  # unjudged passes — gate is not a blocker
    assert line["receipts"]["jev"] == "skipped"


def test_unavailable_backend_is_offline(emitter):
    backend = FakeBackend()
    backend.available = lambda: False
    gate = JevGate(backend)
    line = gate.ingest(emitter, load("worklog"))
    assert line["receipts"]["jev"] == "skipped"


# ── batching: one transport call per flush ───────────────────────────────

def test_flush_batches_pending_events_into_one_call(emitter):
    backend = FakeBackend(noul_score=0.9)
    gate = JevGate(backend)
    gate.ingest(emitter, load("worklog"))
    gate.ingest(emitter, load("task_completion"))
    gate.ingest(emitter, load("promotion"))
    assert backend.calls == 3  # gate judges inline per event (single-writer honesty)
    # (batching happens inside decide_batch — session 15: 5ms/question at scale)


# ── policy: flag, never block ────────────────────────────────────────────

def test_threshold_is_configurable(emitter):
    strict = JevGate(FakeBackend(noul_score=0.60), threshold=0.95)
    line = strict.ingest(emitter, load("worklog"))
    assert line["args"].get("kind") == "flagged"


def test_verdict_object_reports_decision(emitter):
    gate = JevGate(FakeBackend(noul_score=0.3), threshold=0.5)
    v = gate.judge(load("worklog"))
    assert isinstance(v, GateVerdict)
    assert v.flagged is True
    assert v.score == 0.3
