"""
The captain's VIEW — P0.3 of The Grand Quilt.

Given a vessel's quilt WAL, render the one page a human actually reads:
identity, career trajectory, worklog digest, judgment receipts, quality flags.
The last mile is rendering, not archaeology — thirty seconds of reading
instead of a diff nobody opened.

Two renderers:
  render_state_json(emitter) -> dict (machine view; feeds tidepool/gauge)
  render_state_md(emitter)   -> str  (human view; STATE.md)

Everything is derived from the WAL alone — replay it, render it, and the view
is exactly as trustworthy as the chain underneath it.
"""

from __future__ import annotations

from typing import Any, Dict, List

FLAG_CELL = "vessel/flags"


def _collect(emitter) -> Dict[str, Any]:
    lines = emitter.wal()
    identity = None
    promotions: List = []
    fences: List = []
    skills: List = []
    worklog_actions: List[str] = []
    receipts = {"judged": 0, "scores": [], "skipped": 0}
    flags = 0
    stage = None

    for line in lines:
        op, cell, args = line.get("op"), line.get("cell"), line.get("args", {})
        if op == "BIND" and cell == "vessel/identity":
            identity = args
        elif op == "BIND" and cell == "vessel/skills":
            if args.get("skill") not in skills:
                skills.append(args.get("skill"))
        elif op == "LINK" and cell == "vessel/worklog":
            worklog_actions.append(args.get("action", "?"))
        elif op == "EFFECT":
            kind = args.get("kind")
            if kind == "promotion":
                promotions.append([args.get("from_stage"), args.get("to_stage")])
                stage = args.get("to_stage")
            elif kind == "fence":
                if args.get("fence_name") not in fences:
                    fences.append(args.get("fence_name"))
            elif kind == "flagged":
                flags += 1
        elif op == "VIEW" and cell == "vessel/state":
            stage = args.get("stage") or stage
        rec = line.get("receipts", {}).get("jev")
        if rec == "skipped":
            receipts["skipped"] += 1
        elif isinstance(rec, (int, float)):
            receipts["judged"] += 1
            receipts["scores"].append(rec)

    return {"identity": identity, "stage": stage, "promotions": promotions,
            "fences": fences, "skills": skills,
            "worklog_count": len(worklog_actions),
            "worklog_actions": worklog_actions,
            "flags": flags, "receipts": receipts,
            "lines": len(lines)}


def render_state_json(emitter) -> Dict[str, Any]:
    c = _collect(emitter)
    return {"identity": c["identity"], "stage": c["stage"],
            "career": {"promotions": c["promotions"], "fences": c["fences"],
                       "skills": c["skills"]},
            "worklog_count": c["worklog_count"],
            "worklog_actions": c["worklog_actions"],
            "flags": c["flags"], "receipts": c["receipts"],
            "wal_lines": c["lines"]}


def render_state_md(emitter) -> str:
    c = _collect(emitter)
    if c["lines"] == 0:
        return "# Vessel\n\n_no events recorded — this vessel has not spoken._\n"

    ident = c["identity"] or {}
    out = ["# Vessel — the captain's view", ""]
    out.append("## Identity")
    out.append(f"- **{ident.get('name', 'unnamed')}** — {ident.get('designation', 'unknown designation')}")
    out.append(f"- version {ident.get('version', '?')} · domains: {', '.join(ident.get('domains', []) or ['?'])}")
    out.append("")
    out.append("## Career")
    out.append(f"- stage: **{c['stage'] or 'unknown'}**")
    if c["promotions"]:
        trail = " → ".join(f"{a}->{b}" for a, b in c["promotions"])
        out.append(f"- promotions: {trail}")
    if c["fences"]:
        out.append(f"- fences: {', '.join(c['fences'])}")
    if c["skills"]:
        out.append(f"- skills: {', '.join(c['skills'])}")
    out.append("")
    out.append("## Worklog")
    if c["worklog_actions"]:
        counts: Dict[str, int] = {}
        for a in c["worklog_actions"]:
            counts[a] = counts.get(a, 0) + 1
        out.append(", ".join(f"{a} ×{n}" for a, n in counts.items()))
    else:
        out.append("_no work recorded yet._")
    out.append("")
    out.append("## Receipts")
    r = c["receipts"]
    if r["scores"]:
        mean_s = sum(r["scores"]) / len(r["scores"])
        out.append(f"- judged: {r['judged']} (mean {mean_s:.2f})")
    else:
        out.append(f"- judged: {r['judged']}")
    out.append(f"- skipped (offline): {r['skipped']}")
    out.append(f"- **FLAGGED: {c['flags']}**" if c["flags"] else "- flagged: 0")
    out.append("")
    out.append(f"_rendered from {c['lines']} WAL lines — as trustworthy as the chain._")
    return "\n".join(out) + "\n"
