"""The captain's view — end-to-end demo of The Grand Quilt P0 stack.

Plays the real captured vessel stream (same fixtures as PR #1's tests)
through the emitter + Jev gate (stubbed backend so it runs offline), then
renders STATE.md — the one page a human reads in thirty seconds.

Run:  python3 examples/captains_view.py
Needs: the fixture stream at ../git-agent/tests/fixtures or /tmp/git-agent/...
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from git_agent.jev_gate import JevGate, Judgment
from git_agent.projection import render_state_md
from git_agent.quilt_emit import QuiltEmitter

FIXTURE_CANDIDATES = [
    Path(__file__).parent.parent / "tests" / "fixtures",
    Path("/tmp/git-agent/tests/fixtures"),
]
EVENT_ORDER = ["session_start", "worklog", "task_completion", "promotion",
               "fence", "skill", "snapshot", "heartbeat", "session_end"]


class DemoBackend:
    """Pretends to be Jev: scores worklog-style events high, vague ones low."""

    def available(self):
        return True

    def decide_batch(self, state, questions, model="jev-latest"):
        ev = json.loads(state)["vessel_event"] if isinstance(state, str) else state["vessel_event"]
        etype = ev.get("type", "")
        if etype == "worklog":
            summary, target = str(ev.get("summary", "")), str(ev.get("target", ""))
            concrete = any(k in summary for k in ("branch", "PR", "commit", "merge")) and bool(target.strip())
            score = 0.93 if concrete else 0.08
        elif etype == "promotion":
            score = 0.9 if ev.get("from_stage") and ev.get("to_stage") else 0.2
        else:  # task_completion
            score = 0.85 if "success" in ev else 0.3
        return ([Judgment(kind="noul", value=score, confidence=score) for _ in questions],
                {"latency_ms": 0.0, "questions": len(questions)})


def main():
    fixtures = next((c for c in FIXTURE_CANDIDATES if c.exists()), None)
    if fixtures is None:
        print("fixtures not found — run tests/_capture_fixtures.py first")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as td:
        emitter = QuiltEmitter(wal_path=Path(td) / "quilt.jsonl")
        gate = JevGate(DemoBackend(), threshold=0.5)

        # a normal session, then a vague one that deserves flagging
        for i, name in enumerate(EVENT_ORDER):
            ev = json.loads((fixtures / f"{name}.json").read_text())
            ev["event_id"] = f"evt-demo-{i:02d}"
            gate.ingest(emitter, ev)
        vague = json.loads((fixtures / "worklog.json").read_text())
        vague.update(event_id="evt-demo-vague",
                     summary="did some stuff", target="")
        gate.ingest(emitter, vague)

        print(render_state_md(emitter))
        print(f"WAL: {emitter.wal_path}")
        print(f"verify: {emitter.verify()}")


if __name__ == "__main__":
    main()
