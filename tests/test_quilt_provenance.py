"""
Provenance pin: the opcode doctrine in docs/GRAND-QUILT.md must carry an
in-repo citation of its canonical source (AI-Writings/algebra.md).

Why this exists: the referral edge aw-quint-opcode -> ga-quilt-emit was booked
PENDING (never VERIFIED) because the merged quilt_emit PR cited the five-opcode
doctrine without naming the source repo. Weight law: VERIFIED requires a merged
PR in the TARGET repo citing the source. This pin keeps the citation from
drifting back out.

FAIL-first by construction: on main, GRAND-QUILT.md names no algebra.md
source, so this test fails there.
"""

from __future__ import annotations

from pathlib import Path

DOCS = Path(__file__).parent.parent / "docs"


def test_grand_quilt_cites_canonical_opcode_source():
    text = (DOCS / "GRAND-QUILT.md").read_text(encoding="utf-8")
    assert "AI-Writings/blob/main/algebra.md" in text, (
        "GRAND-QUILT.md describes the opcode doctrine without citing its "
        "canonical source (AI-Writings/algebra.md); the referral edge "
        "aw-quint-opcode -> ga-quilt-emit would decay back to PENDING."
    )


def test_grand_quilt_citation_names_the_edge():
    text = (DOCS / "GRAND-QUILT.md").read_text(encoding="utf-8")
    assert "aw-quint-opcode" in text and "ga-quilt-emit" in text, (
        "citation must name the referral edge it serves, per the "
        "quilt-tools weight law"
    )
