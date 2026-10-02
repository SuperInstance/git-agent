#!/usr/bin/env python3
"""Harvest the fleet's first L1 mock corpus: (input, prompt, output) triples.

Every triple is replayable from real artifacts:
  input   <- a vessel event (a tests/fixtures/*.json capture, or a synthetic
             event generated here and pushed through the REAL QuiltEmitter
             ingest path -- never a parallel writer)
  prompt  <- jev_gate._VERIFIABLE_WORK_Q (the exact noul the production gate
             aims at judged events)
  output  <- an oracle verdict. PROVENANCE IS DECLARED PER ROW: today the
             oracle is hand-labeled by the operator (lane G), because no
             decision-model transcript exists in-repo. oracle_source ranks:
               "operator-label"  (hand-labeled; weakest)
               "mock-seam"       (recorded through llm/base.py MockProvider)
               "backend-transcript" (real Jev backend score, replayed)
             The ladder upgrade is: record real backend scores through the
             mock seam, re-harvest, and the corpus self-promotes.

wal_ref pins each row to the chain: seq + fnv1a hash of the WAL line the
input event earned when ingested through the real emitter. Re-running this
script is deterministic (fnv1a is order-stable), so wal_ref is checkable
forever -- rerun and diff.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from git_agent.jev_gate import _VERIFIABLE_WORK_Q, JUDGED_TYPES
from git_agent.quilt_emit import QuiltEmitter

ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
OUT = ROOT / "corpus" / "corpus.jsonl"

# Synthetic judged events, pushed through the real ingest path.
# Concrete ones carry named artifacts (branch / commit / PR / repo);
# vague ones carry activity words only. Labels are operator-assigned.
SYNTHETIC_JUDGED = [
    # concrete, verifiable engineering work
    {"event_id": "syn-wl-commit", "type": "worklog",
     "timestamp": "2026-10-02T04:00:00+00:00", "action": "committed",
     "target": "SuperInstance/git-agent",
     "summary": "Landed commit 8d6c31a on main", "outcome": "success"},
    {"event_id": "syn-wl-pr", "type": "worklog",
     "timestamp": "2026-10-02T04:00:01+00:00", "action": "opened",
     "target": "SuperInstance/git-agent",
     "summary": "Opened PR #4 with the emitter changes", "outcome": "success"},
    {"event_id": "syn-wl-branch", "type": "worklog",
     "timestamp": "2026-10-02T04:00:02+00:00", "action": "branched",
     "target": "SuperInstance/git-agent",
     "summary": "Created branch equivalence-seed", "outcome": "success"},
    {"event_id": "syn-wl-pin", "type": "worklog",
     "timestamp": "2026-10-02T04:00:03+00:00", "action": "pinned",
     "target": "SuperInstance/git-agent",
     "summary": "pin.sh GREEN: 3/3 pins pass clean-tree", "outcome": "success"},
    {"event_id": "syn-wl-merge", "type": "worklog",
     "timestamp": "2026-10-02T04:00:04+00:00", "action": "merged",
     "target": "SuperInstance/git-agent",
     "summary": "Merged PR #4 into main after CI", "outcome": "success"},
    {"event_id": "syn-wl-test", "type": "worklog",
     "timestamp": "2026-10-02T04:00:05+00:00", "action": "tested",
     "target": "SuperInstance/git-agent",
     "summary": "tests/test_quilt_emit.py 12/12 green", "outcome": "success"},
    {"event_id": "syn-tc-pass", "type": "task_completion",
     "timestamp": "2026-10-02T04:00:06+00:00", "success": True},
    {"event_id": "syn-pr-promote", "type": "promotion",
     "timestamp": "2026-10-02T04:00:07+00:00",
     "from_stage": "greenhorn", "to_stage": "able-bodied"},
    # vague activity claims -- no one could check these
    {"event_id": "syn-wl-vague1", "type": "worklog",
     "timestamp": "2026-10-02T04:00:08+00:00", "action": "worked on",
     "target": "stuff",
     "summary": "made some progress on things", "outcome": "partial"},
    {"event_id": "syn-wl-vague2", "type": "worklog",
     "timestamp": "2026-10-02T04:00:09+00:00", "action": "thought about",
     "target": "the project",
     "summary": "considered various approaches", "outcome": "success"},
    {"event_id": "syn-wl-vague3", "type": "worklog",
     "timestamp": "2026-10-02T04:00:10+00:00", "action": "improved",
     "target": "general quality",
     "summary": "cleaned up and made it better", "outcome": "success"},
    {"event_id": "syn-wl-vague4", "type": "worklog",
     "timestamp": "2026-10-02T04:00:11+00:00", "action": "handled",
     "target": "misc tasks",
     "summary": "took care of some loose ends", "outcome": "partial"},
    {"event_id": "syn-wl-vague5", "type": "worklog",
     "timestamp": "2026-10-02T04:00:12+00:00", "action": "synced",
     "target": "the team",
     "summary": "aligned on next steps", "outcome": "success"},
]

# Synthetic events of STRUCTURAL types are never substance-judged; they are
# corpus negative-controls (cog must agree: not a claim -> not verifiable work).
SYNTHETIC_STRUCTURAL = [
    {"event_id": "syn-ss", "type": "session_start",
     "timestamp": "2026-10-02T04:00:13+00:00", "name": "vessel-7",
     "designation": "scout", "version": "0.1"},
    {"event_id": "syn-hb", "type": "heartbeat",
     "timestamp": "2026-10-02T04:00:14+00:00"},
    {"event_id": "syn-se", "type": "session_end",
     "timestamp": "2026-10-02T04:00:15+00:00"},
    {"event_id": "syn-snap", "type": "snapshot",
     "timestamp": "2026-10-02T04:00:16+00:00", "stage": "greenhorn"},
]

# Operator labels: (event_id -> expected verifiable_work value).
# task_completion fixtures/events are labeled by their success field plus
# the presence of an artifact reference -- the captured fixture carries
# none, so its label is False (a bare "success": true asserts nothing
# checkable). This is the needle the rule cog must learn to thread.
LABELS = {
    "evt-0002-captured": True,    # "Created feature branch quilt-emitter"
    "evt-0003-captured": False,   # bare success:true, no artifact named
    "syn-wl-commit": True, "syn-wl-pr": True, "syn-wl-branch": True,
    "syn-wl-pin": True, "syn-wl-merge": True, "syn-wl-test": True,
    "syn-tc-pass": False,       # same needle: success without an artifact
    "syn-pr-promote": False,    # promotion names stages, not artifacts
    "syn-wl-vague1": False, "syn-wl-vague2": False, "syn-wl-vague3": False,
    "syn-wl-vague4": False, "syn-wl-vague5": False,
    "syn-ss": False, "syn-hb": False, "syn-se": False, "syn-snap": False,
}


def _fixture_events():
    for path in sorted(FIXTURES.glob("*.json")):
        yield path, json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    emitter = QuiltEmitter(wal_path=tmp / "quilt.jsonl")

    rows = []
    n = 0
    for path, event in _fixture_events():
        label = LABELS.get(event["event_id"])
        if label is None:
            continue  # unlabeled fixture rows are not harvested (honesty:
                      # an unlabeled row has no oracle, so it is not a triple)
        line = emitter.ingest(event)
        n += 1
        rows.append({
            "id": f"c{n:03d}", "input": event,
            "prompt": _VERIFIABLE_WORK_Q,
            "output": {"kind": "substance", "value": label},
            "oracle_source": "operator-label",
            "wal_ref": {"fixture": f"tests/fixtures/{path.name}",
                        "event_id": event["event_id"],
                        "wal_seq": line["seq"], "wal_hash": line["hash"]},
            "synthetic": False,
        })
    for event in SYNTHETIC_JUDGED + SYNTHETIC_STRUCTURAL:
        label = LABELS[event["event_id"]]
        line = emitter.ingest(event)
        n += 1
        rows.append({
            "id": f"c{n:03d}", "input": event,
            "prompt": _VERIFIABLE_WORK_Q,
            "output": {"kind": "substance", "value": label},
            "oracle_source": "operator-label",
            "wal_ref": {"fixture": None, "event_id": event["event_id"],
                        "wal_seq": line["seq"], "wal_hash": line["hash"]},
            "synthetic": True,
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    judged = [r for r in rows if r["input"]["type"] in JUDGED_TYPES]
    print(f"harvested {len(rows)} triples "
          f"({len(judged)} judged-type, {len(rows) - len(judged)} structural "
          f"negative-controls) -> {OUT.relative_to(ROOT)}")
    print(f"prompt pinned to jev_gate._VERIFIABLE_WORK_Q "
          f"({len(_VERIFIABLE_WORK_Q)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
