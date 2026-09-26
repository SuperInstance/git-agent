"""
Jev judgment gate — the attention layer of The Grand Quilt (P0.2).

Deterministic validators check shape; this gate checks substance. Events that
make *claims about work* (worklog entries, task completions, promotions) are
judged by a decision-model backend (TypeSafe Jev by default) before they earn
unflagged WAL space. Below threshold, the claim does not enter the WAL as
work — an EFFECT {kind: "flagged"} line referencing it does, so the rejection
is legible, replayable, and never silent. The gate flags; it never blocks,
never drops, never crashes the loop.

Policy (from JEV session 16): aim nouls at the specific claim; trust the
score; let confidence route. Structural events (identity, heartbeat, session
bookkeeping) are not claims and are never substance-judged.

Offline: no backend / no key -> events pass unjudged, receipt
{"jev": "skipped"}. The gate degrades to a no-op, not a wall.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

# Event types that make verifiable claims about work. Everything else is
# structural — presence-checked by the emitter, not substance-judged.
JUDGED_TYPES = ("worklog", "task_completion", "promotion")

DEFAULT_THRESHOLD = 0.5

_VERIFIABLE_WORK_Q = (
    "Does this vessel event describe concrete, verifiable engineering work "
    "(a named branch, commit, PR, repo, or artifact) — as opposed to vague "
    "activity claims that no one could check?"
)

_JUDGED_STATE_FIELDS = ("type", "action", "target", "summary",
                        "outcome", "success", "from_stage", "to_stage")


@dataclass
class Judgment:
    """One typed answer from a decision-model backend."""
    kind: str
    value: Any
    confidence: Optional[float] = None


@dataclass
class GateVerdict:
    event_type: str
    judged: bool
    flagged: bool
    score: Optional[float]
    question: Optional[str]


class JevGate:
    """Substance gate over a QuiltEmitter.

    Parameters
    ----------
    backend:
        Any object with ``available() -> bool`` and
        ``decide_batch(state, questions, model) -> (judgments, meta)`` where
        each judgment has ``.value``. The production backend is
        jev-quilt's TypeSafeBackend; pass None for offline mode.
    threshold:
        Scores below this are flagged (not blocked).
    question:
        The noul aimed at each judged event's specific claim (session 16:
        specific nouls move on quality; global scores don't).
    """

    def __init__(self, backend=None, threshold: float = DEFAULT_THRESHOLD,
                 question: str = _VERIFIABLE_WORK_Q):
        self.backend = backend
        self.threshold = threshold
        self.question = question

    def _online(self) -> bool:
        return self.backend is not None and bool(self.backend.available())

    def judge(self, event: Dict[str, Any]) -> GateVerdict:
        """Judge one event without writing anything."""
        etype = event.get("type", "")
        if etype not in JUDGED_TYPES or not self._online():
            return GateVerdict(etype, judged=False, flagged=False,
                               score=None, question=None)
        state = {"vessel_event": {k: event[k] for k in _JUDGED_STATE_FIELDS
                                  if k in event}}
        judgments, _ = self.backend.decide_batch(
            state, [{"name": "substance", "type": "noul",
                     "instructions": self.question}])
        score = float(judgments[0].value) if judgments else None
        flagged = score is not None and score < self.threshold
        return GateVerdict(etype, judged=True, flagged=flagged,
                           score=score, question=self.question)

    def ingest(self, emitter, event: Dict[str, Any]) -> Dict[str, Any]:
        """Judge + persist one event. Returns the WAL line written.

        Flagged claim  -> EFFECT vessel/flags line referencing the original
                          event (the claim does not earn unflagged WAL space;
                          its rejection is the record).
        Judged, passed -> normal emitter line + receipts.jev = score.
        Not judged     -> normal emitter line; receipts.jev = "skipped" if it
                          was a claim type judged offline, else no receipts.
        """
        verdict = self.judge(event)
        if verdict.flagged:
            from .quilt_emit import _map
            original_op = _map({**event, "event_id": "x", "timestamp": "t"})["op"]
            return emitter.append_line(
                "EFFECT", "vessel/flags",
                {"kind": "flagged",
                 "original_type": event["type"],
                 "original_op": original_op,
                 "original_event_id": event["event_id"],
                 "score": verdict.score,
                 "threshold": self.threshold},
                event["event_id"] + "/flagged",
                event["timestamp"],
                extra={"receipts": {"jev": verdict.score, "gate": "flagged"}})
        receipts = None
        if verdict.judged:
            receipts = {"jev": verdict.score}
        elif event.get("type") in JUDGED_TYPES:
            receipts = {"jev": "skipped"}
        return emitter.ingest(event, extra={"receipts": receipts} if receipts else None)
