"""Equivalence seed: the rule cog must match the oracle on every corpus row.

Ladder position (docs/COG-LADDER.md): this is the fleet's first L3 test --
"is the repo (its deterministic cog) as good as the iterator it stands in
for, ON THE RECORDED CORPUS?" The corpus witness is corpus/corpus.jsonl;
every row pins its input to a real chain position via wal_ref, so a row is
re-derivable, not asserted.

FAIL-first by construction, matching tests/test_quilt_provenance.py:
the RED run is recorded in pins/failfirst.log on the branch.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from git_agent.cogs.verifiable_work import judge_verifiable_work

ROOT = Path(__file__).parent.parent
CORPUS = ROOT / "corpus" / "corpus.jsonl"


def _rows():
    assert CORPUS.exists(), (
        "corpus/corpus.jsonl absent -- run tools/harvest_corpus.py first; "
        "the equivalence test judges the cog against the harvested witness, "
        "never against thin air."
    )
    return [json.loads(line) for line in
            CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_corpus_rows_exist_and_are_labeled():
    rows = _rows()
    assert len(rows) >= 10, f"corpus too thin: {len(rows)} rows"
    for row in rows:
        assert row.get("oracle_source"), f"{row['id']}: missing oracle_source"
        assert row.get("wal_ref", {}).get("wal_hash"), f"{row['id']}: no wal_ref"


def test_rule_cog_matches_oracle_on_every_row():
    rows = _rows()
    mismatches = []
    for row in rows:
        got = judge_verifiable_work(row["input"])["value"]
        want = row["output"]["value"]
        if got != want:
            mismatches.append(
                f"{row['id']} ({row['input']['event_id']}): "
                f"cog={got} oracle={want} [{row['oracle_source']}]")
    assert not mismatches, (
        "rule cog diverged from oracle on "
        f"{len(mismatches)}/{len(rows)} rows:\n  " + "\n  ".join(mismatches))


def test_corpus_prompt_is_the_gate_noul():
    from git_agent.jev_gate import _VERIFIABLE_WORK_Q
    rows = _rows()
    bad = [r["id"] for r in rows if r["prompt"] != _VERIFIABLE_WORK_Q]
    assert not bad, f"rows not aimed at the production noul: {bad}"
