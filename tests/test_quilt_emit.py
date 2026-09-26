"""
Behavioral tests for the Vessel-Quilt emitter (git_agent.quilt_emit).

Fixtures in tests/fixtures/*.json are REAL lifecycle event payloads captured
from a live VesselManager by tests/_capture_fixtures.py — not invented shapes.

FAIL-first by construction: these tests were written before quilt_emit existed
and failed at import; the module was then built until green.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from git_agent.quilt_emit import (
    QuiltEmitter,
    QuiltValidationError,
    fnv1a,
    SCHEMA_PATH,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture()
def emitter(tmp_path):
    return QuiltEmitter(wal_path=tmp_path / "quilt.jsonl")


# ── opcode mapping (one fleet opcode per vessel event type) ──────────────

@pytest.mark.parametrize("fixture,opcode", [
    ("session_start", "BIND"),
    ("worklog", "LINK"),
    ("task_completion", "EFFECT"),
    ("promotion", "EFFECT"),
    ("fence", "EFFECT"),
    ("skill", "BIND"),
    ("snapshot", "VIEW"),
    ("heartbeat", "TICK"),
    ("session_end", "FORGET"),
])
def test_each_event_type_maps_to_its_quilt_opcode(emitter, fixture, opcode):
    line = emitter.ingest(load(fixture))
    assert line["op"] == opcode, f"{fixture} should map to {opcode}, got {line['op']}"


def test_worklog_link_carries_relation_args(emitter):
    line = emitter.ingest(load("worklog"))
    assert line["cell"] == "vessel/worklog"
    a = line["args"]
    assert a["action"] == "branched"
    assert a["target"] == "SuperInstance/git-agent"
    assert a["outcome"] == "success"


def test_promotion_effect_names_both_stages(emitter):
    line = emitter.ingest(load("promotion"))
    assert line["args"]["from_stage"] == "initiate"
    assert line["args"]["to_stage"] == "apprentice"
    assert line["args"]["kind"] == "promotion"


def test_session_start_binds_identity(emitter):
    line = emitter.ingest(load("session_start"))
    assert line["cell"] == "vessel/identity"
    assert line["args"]["name"] == "Super Z"
    assert line["args"]["designation"] == "Git-Native Agent"


def test_task_completion_effect_records_pass_fail(emitter):
    ok = emitter.ingest(load("task_completion"))
    assert ok["args"]["success"] is True
    bad_event = load("task_completion")
    bad_event.update(event_id="evt-fail-1", success=False)
    bad = emitter.ingest(bad_event)
    assert bad["args"]["success"] is False


# ── schema validation at the boundary ────────────────────────────────────

def test_missing_required_field_rejected_with_precise_error(emitter):
    ev = load("worklog")
    del ev["outcome"]
    with pytest.raises(QuiltValidationError) as exc:
        emitter.ingest(ev)
    assert "outcome" in str(exc.value)


def test_bad_outcome_enum_rejected(emitter):
    ev = load("worklog")
    ev["outcome"] = "exploded"
    with pytest.raises(QuiltValidationError):
        emitter.ingest(ev)


def test_unknown_event_type_rejected(emitter):
    ev = load("heartbeat")
    ev["type"] = "plasma"
    with pytest.raises(QuiltValidationError):
        emitter.ingest(ev)


def test_rejection_does_not_break_the_ingest_loop(emitter):
    bad = load("worklog")
    del bad["target"]
    with pytest.raises(QuiltValidationError):
        emitter.ingest(bad)
    good = emitter.ingest(load("worklog"))
    assert good["op"] == "LINK"  # loop survived the bad event


def test_schema_file_lives_with_the_producer():
    assert SCHEMA_PATH.exists()
    schema = json.loads(SCHEMA_PATH.read_text())
    assert "worklog" in json.dumps(schema)


# ── WAL integrity: fnv1a hash chain ──────────────────────────────────────

def test_hash_chain_links_every_line(emitter):
    for name in ("session_start", "worklog", "task_completion"):
        emitter.ingest(load(name))
    wal = emitter.wal()
    assert len(wal) == 3
    assert wal[0]["prev_hash"] == "0" * 16
    for prev, cur in zip(wal, wal[1:]):
        assert cur["prev_hash"] == prev["hash"]


def test_verify_ok_on_untampered_wal(emitter):
    for name in ("session_start", "worklog", "snapshot"):
        emitter.ingest(load(name))
    result = emitter.verify()
    assert result["ok"] is True
    assert result["divergences"] == []


def test_verify_detects_tampering(emitter, tmp_path):
    for name in ("session_start", "worklog"):
        emitter.ingest(load(name))
    lines = (tmp_path / "quilt.jsonl").read_text().splitlines()
    tampered = json.loads(lines[0])
    tampered["args"]["name"] = "Mallory"
    lines[0] = json.dumps(tampered)
    (tmp_path / "quilt.jsonl").write_text("\n".join(lines) + "\n")
    result = emitter.verify()
    assert result["ok"] is False
    assert result["divergences"]


def test_verify_detects_truncation(emitter, tmp_path):
    for name in ("session_start", "worklog", "snapshot"):
        emitter.ingest(load(name))
    lines = (tmp_path / "quilt.jsonl").read_text().splitlines()
    (tmp_path / "quilt.jsonl").write_text("\n".join(lines[:2]) + "\n")
    result = emitter.verify()
    assert result["ok"] is False


# ── replay equivalence: WAL → reducer state ──────────────────────────────

def test_replay_reproduces_ingested_state(emitter):
    for name in ("session_start", "worklog", "worklog", "promotion", "snapshot"):
        ev = load(name)
        ev["event_id"] = f"evt-replay-{name}-{emitter.wal().__len__()}"
        emitter.ingest(ev)
    live = emitter.state()
    replayed = emitter.replay()
    assert replayed == live


def test_at_least_once_duplicate_ingest_is_idempotent(emitter):
    ev = load("worklog")
    emitter.ingest(ev)
    emitter.ingest(copy.deepcopy(ev))  # same event_id, delivered twice
    emitter.ingest(copy.deepcopy(ev))
    assert len(emitter.wal()) == 1  # single WAL entry for one event_id


def test_fnv1a_is_stable_and_seedless():
    assert fnv1a("hello") == fnv1a("hello")
    assert fnv1a("hello") != fnv1a("hellp")
    assert len(fnv1a("anything")) == 16  # 64-bit → 16 hex chars


# ── regression: presence is not enough, strings must be non-empty ────────
# (found by JEV session 16 — a "target": "" worklog passed the validator
# while Jev scored its verifiability 0.04. Schema presence checks alone
# let empty claims through.)

def test_empty_string_field_rejected(emitter):
    ev = load("worklog")
    ev["target"] = ""
    with pytest.raises(QuiltValidationError) as exc:
        emitter.ingest(ev)
    assert "non-empty" in str(exc.value)


def test_whitespace_only_event_id_rejected(emitter):
    ev = load("heartbeat")
    ev["event_id"] = "   "
    with pytest.raises(QuiltValidationError):
        emitter.ingest(ev)
