"""The verifiable-work cog -- a rule-based stand-in for the Jev substance call.

This is the cog ladder's reference implementation of L3-in-progress: a
deterministic pure function that answers jev_gate's verifiable-work noul
without a decision-model backend. It exists to be tested AGAINST recorded
oracle outputs (corpus/corpus.jsonl) by tests/test_equivalence_seed.py.

Graduation criterion (docs/COG-LADDER.md): this cog earns the right to
judge offline work claims *in place of* an LLM call only while its verdicts
match the oracle on every corpus row. When the corpus upgrades from
operator-labels to backend transcripts, this file is where the equivalence
claim lives or dies.

Deliberately boring: no imports beyond stdlib, no state, one function in,
one Judgment-shaped dict out -- mirroring the shape jev_gate expects from
a decision-model backend.
"""

from __future__ import annotations

import re
from typing import Any

# Strong markers: a single one is sufficient evidence of checkable work.
_STRONG = (
    re.compile(r"\b[0-9a-f]{7,40}\b"),                 # commit sha
    re.compile(r"\bPR\s*#\d+\b", re.I),                # PR #4
    re.compile(r"\bSuperInstance/[\w.-]+\b"),          # named repo
)

# Weak markers: engineering vocabulary; need two-or-more to pass.
_WEAK = tuple(re.compile(p, re.I) for p in (
    r"\bbranch\b", r"\bpin(?:ned)?\b", r"\bmerge[sd]?\b", r"\btest",
    r"\bcommit(?:ted)?\b", r"\bwitness\b", r"\breceipt", r"\bCI\b",
    r"\bfixture", r"\bopened\b",
))


def _haystack(event: dict[str, Any]) -> str:
    fields = ("action", "target", "summary", "outcome", "from_stage", "to_stage")
    return " ".join(str(event.get(k, "")) for k in fields)


def judge_verifiable_work(event: dict[str, Any]) -> dict[str, Any]:
    """Rule verdict: does this event describe concrete, checkable work?

    Mirrors jev_gate._VERIFIABLE_WORK_Q's distinction: named artifacts
    (sha / PR / repo) are checkable; activity words are not. task_completion
    and promotion events are structural outcomes -- even with success:true
    they name no artifact, so they are not verifiable work *claims* (the
    captured fixture evt-0003-captured is the reference negative case).
    """
    etype = event.get("type", "")
    if etype not in ("worklog",):
        return {"kind": "substance", "value": False,
                "why": "not a worklog claim"}

    text = _haystack(event)
    if any(p.search(text) for p in _STRONG):
        return {"kind": "substance", "value": True, "why": "named artifact"}

    weak_hits = sum(1 for p in _WEAK if p.search(text))
    if weak_hits >= 2:
        return {"kind": "substance", "value": True,
                "why": f"{weak_hits} weak engineering markers"}

    return {"kind": "substance", "value": False, "why": "vague activity claim"}
