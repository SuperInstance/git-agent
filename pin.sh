#!/usr/bin/env bash
# Equivalence-seed pins. FAIL-first discipline: each pin exits non-zero
# with a concrete message. Evidence lives in pins/failfirst.log and
# pins/final.log on the branch.
set -u
cd "$(dirname "$0")"
export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"
FAIL=0

say()  { printf '%s\n' "$*"; }
ok()   { say "ok - $*"; }
bad()  { say "FAIL - $*"; FAIL=1; }

# E1: corpus exists; every wal_ref resolves to a real chain position when
# the harvester is re-run (fnv1a is deterministic -> re-harvest must
# reproduce identical hashes; drift = the witness is not replayable).
if [ -f corpus/corpus.jsonl ]; then
  ok "E1a corpus/corpus.jsonl exists"
  python3 - <<'PY' || bad "E1b wal_ref resolution"
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, "src")
from git_agent.quilt_emit import QuiltEmitter
rows = [json.loads(l) for l in Path("corpus/corpus.jsonl").read_text().splitlines() if l.strip()]
# ONE emitter for ALL rows, in corpus order: seq is cumulative over the
# harvest run, so re-ingesting per-row into fresh emitters would drift.
em = QuiltEmitter(wal_path=Path(tempfile.mkdtemp()) / "q.jsonl")
for r in rows:
    line = em.ingest(r["input"])
    assert line["seq"] == r["wal_ref"]["wal_seq"], f"{r['id']}: seq drift"
    assert line["hash"] == r["wal_ref"]["wal_hash"], f"{r['id']}: hash drift"
print("ok - E1b all wal_refs re-derive from real ingest")
PY
else
  bad "E1a corpus/corpus.jsonl missing"
fi

# E2: corpus has >= 10 triples.
n=$(grep -c . corpus/corpus.jsonl 2>/dev/null || echo 0)
if [ "$n" -ge 10 ]; then ok "E2 corpus has $n rows (>=10)"; else bad "E2 corpus thin: $n rows"; fi

# E3: equivalence test passes clean-tree.
if python3 -m pytest tests/test_equivalence_seed.py -q >/tmp/eqseed.out 2>&1; then
  ok "E3 equivalence test GREEN"
else
  bad "E3 equivalence test not green: $(tail -1 /tmp/eqseed.out)"
fi

# E4: every row carries oracle_source + wal_ref + event identity.
python3 - <<'PY' || bad "E4 row completeness"
import json
from pathlib import Path
rows = [json.loads(l) for l in Path("corpus/corpus.jsonl").read_text().splitlines() if l.strip()]
for r in rows:
    assert r.get("oracle_source") and r.get("wal_ref"), r["id"]
    assert r["wal_ref"].get("event_id") == r["input"]["event_id"], r["id"]
print("ok - E4 every row complete (oracle_source, wal_ref, identity)")
PY

say ""
if [ "$FAIL" -eq 0 ]; then say "ALL PINS PASS"; else say "PINS FAILED"; fi
exit "$FAIL"
