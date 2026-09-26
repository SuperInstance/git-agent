"""
Vessel-Quilt emitter — git-agent's lifecycle events as quilt 5-opcode WAL records.

The fleet's quilt kernel speaks five opcodes (BIND / LINK / EFFECT / VIEW / TICK,
plus FORGET). git-agent's vessel already produces structured lifecycle events
(session start, worklog entries, task outcomes, career promotions, fences,
skills, snapshots, heartbeats, session end) — this module is the translation
and validation layer that makes git-agent the first quilt-native fleet agent.

Every ingested event is:
  1. validated against the event schema (enforced here in stdlib code; the
     canonical JSON Schema lives beside the producer at
     ``git_agent/schemas/event.schema.json`` for external consumers),
  2. mapped to exactly one quilt opcode line,
  3. appended to a fnv1a hash-chained JSONL WAL (default ``~/.git-agent/quilt.jsonl``),
  4. folded into a reducer state that ``replay()`` can reconstruct from the WAL alone.

Guarantees: invalid events raise ``QuiltValidationError`` (never silently
dropped, never crash the ingest loop); duplicate ``event_id`` deliveries are
idempotent (at-least-once ingest → exactly-once WAL).
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_PATH = Path(__file__).parent / "schemas" / "event.schema.json"

DEFAULT_WAL = Path.home() / ".git-agent" / "quilt.jsonl"

EVENT_TYPES = (
    "session_start", "worklog", "task_completion", "promotion",
    "fence", "skill", "snapshot", "heartbeat", "session_end",
)

# per-type required fields beyond the universal (event_id, type, timestamp)
REQUIRED: Dict[str, tuple] = {
    "session_start": ("name", "designation", "version"),
    "worklog": ("action", "target", "summary", "outcome"),
    "task_completion": ("success",),
    "promotion": ("from_stage", "to_stage"),
    "fence": ("fence_name",),
    "skill": ("skill",),
    "snapshot": ("stage",),
    "heartbeat": (),
    "session_end": (),
}

OUTCOMES = ("success", "failure", "partial")
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


class QuiltValidationError(ValueError):
    """Raised when an event fails schema validation. Precise about the why."""


def fnv1a(s: str) -> str:
    """64-bit FNV-1a, hex-encoded (16 chars). Same integrity family the fleet's
    rate limiter and quilt WAL use — fast, deterministic, non-cryptographic."""
    h = 0xCBF29CE484222325
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


def _canonical(obj: Dict[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _validate(event: Dict[str, Any]) -> None:
    if not isinstance(event, dict):
        raise QuiltValidationError("event must be a JSON object")
    for field in ("event_id", "type", "timestamp"):
        if field not in event:
            raise QuiltValidationError(f"missing required field: {field!r}")
        if field != "type" and (not isinstance(event[field], str) or not event[field].strip()):
            raise QuiltValidationError(f"{field!r} must be a non-empty string")
    if not isinstance(event["event_id"], str) or not event["event_id"]:
        raise QuiltValidationError("event_id must be a non-empty string")
    if event["type"] not in EVENT_TYPES:
        raise QuiltValidationError(
            f"unknown event type: {event['type']!r} (expected one of {', '.join(EVENT_TYPES)})")
    if not (isinstance(event["timestamp"], str) and _TS_RE.match(event["timestamp"])):
        raise QuiltValidationError(
            f"timestamp must be ISO-8601 (YYYY-MM-DDTHH:MM:SS...), got {event['timestamp']!r}")
    for field in REQUIRED[event["type"]]:
        if field not in event:
            raise QuiltValidationError(
                f"{event['type']} event missing required field: {field!r}")
        if isinstance(event[field], str) and not event[field].strip():
            raise QuiltValidationError(
                f"{event['type']} field {field!r} must be non-empty if present as a string")
    if event["type"] == "worklog":
        if event["outcome"] not in OUTCOMES:
            raise QuiltValidationError(
                f"worklog outcome must be one of {OUTCOMES}, got {event['outcome']!r}")


def _map(event: Dict[str, Any]) -> Dict[str, Any]:
    """One vessel event → one quilt opcode line (minus chain fields)."""
    t = event["type"]
    if t == "session_start":
        return {"op": "BIND", "cell": "vessel/identity",
                "args": {"name": event["name"], "designation": event["designation"],
                         "version": event["version"], "domains": event.get("domains", [])}}
    if t == "worklog":
        return {"op": "LINK", "cell": "vessel/worklog",
                "args": {"action": event["action"], "target": event["target"],
                         "summary": event["summary"], "outcome": event["outcome"]}}
    if t == "task_completion":
        return {"op": "EFFECT", "cell": "vessel/career",
                "args": {"kind": "task", "success": bool(event["success"])}}
    if t == "promotion":
        return {"op": "EFFECT", "cell": "vessel/career",
                "args": {"kind": "promotion", "from_stage": event["from_stage"],
                         "to_stage": event["to_stage"]}}
    if t == "fence":
        return {"op": "EFFECT", "cell": "vessel/career",
                "args": {"kind": "fence", "fence_name": event["fence_name"]}}
    if t == "skill":
        return {"op": "BIND", "cell": "vessel/skills", "args": {"skill": event["skill"]}}
    if t == "snapshot":
        return {"op": "VIEW", "cell": "vessel/state",
                "args": {"stage": event["stage"],
                         "total_tasks_completed": event.get("total_tasks_completed"),
                         "total_tasks_failed": event.get("total_tasks_failed"),
                         "worklog_len": event.get("worklog_len")}}
    if t == "heartbeat":
        return {"op": "TICK", "cell": "vessel/heartbeat", "args": {}}
    if t == "session_end":
        return {"op": "FORGET", "cell": "vessel/session",
                "args": {"archived": bool(event.get("archived", True))}}
    raise QuiltValidationError(f"unmapped event type: {t}")  # pragma: no cover


class QuiltEmitter:
    """Ingest vessel lifecycle events → append hash-chained quilt WAL lines."""

    def __init__(self, wal_path: Optional[Path] = None):
        self.wal_path = Path(wal_path) if wal_path else DEFAULT_WAL
        self._seen: set = set()
        self._state: Dict[str, Any] = self._empty_state()
        if self.wal_path.exists():
            for line in self._read_lines():
                self._seen.add(line["event_id"])
                self._fold(line, self._state)

    @staticmethod
    def _empty_state() -> Dict[str, Any]:
        return {"identity": None, "tasks_completed": 0, "tasks_failed": 0,
                "promotions": [], "fences": [], "skills": [], "worklog": 0,
                "last_tick": None, "archived": False, "lines": 0}

    def _read_lines(self) -> List[Dict[str, Any]]:
        if not self.wal_path.exists():
            return []
        out = []
        for raw in self.wal_path.read_text().splitlines():
            if raw.strip():
                out.append(json.loads(raw))
        return out

    def wal(self) -> List[Dict[str, Any]]:
        return self._read_lines()

    def ingest(self, event: Dict[str, Any]) -> Dict[str, Any]:
        _validate(event)
        if event["event_id"] in self._seen:
            for line in self._read_lines():  # idempotent no-op: return the existing line
                if line["event_id"] == event["event_id"]:
                    return line
            raise QuiltValidationError(  # pragma: no cover
                f"event_id {event['event_id']!r} seen but absent from WAL")
        line = _map(event)
        line["event_id"] = event["event_id"]
        line["timestamp"] = event["timestamp"]
        prev = self._read_lines()
        line["seq"] = len(prev)
        line["prev_hash"] = prev[-1]["hash"] if prev else "0" * 16
        line["hash"] = fnv1a(_canonical({k: v for k, v in line.items() if k != "hash"}))
        self.wal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.wal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, sort_keys=True) + "\n")
        self._seen.add(event["event_id"])
        self._fold(line, self._state)
        return line

    @staticmethod
    def _fold(line: Dict[str, Any], st: Dict[str, Any]) -> None:
        st["lines"] += 1
        op, args = line["op"], line.get("args", {})
        if op == "BIND" and line["cell"] == "vessel/identity":
            st["identity"] = args
        elif op == "BIND" and line["cell"] == "vessel/skills":
            if args.get("skill") not in st["skills"]:
                st["skills"].append(args.get("skill"))
        elif op == "LINK":
            st["worklog"] += 1
        elif op == "EFFECT":
            k = args.get("kind")
            if k == "task":
                st["tasks_completed" if args.get("success") else "tasks_failed"] += 1
            elif k == "promotion":
                st["promotions"].append((args.get("from_stage"), args.get("to_stage")))
            elif k == "fence":
                if args.get("fence_name") not in st["fences"]:
                    st["fences"].append(args.get("fence_name"))
        elif op == "TICK":
            st["last_tick"] = line.get("timestamp")
        elif op == "FORGET":
            st["archived"] = bool(args.get("archived"))

    def state(self) -> Dict[str, Any]:
        return self._state

    def replay(self) -> Dict[str, Any]:
        st = self._empty_state()
        for line in self._read_lines():
            self._fold(line, st)
        return st

    def verify(self) -> Dict[str, Any]:
        """Replay the WAL from disk and diff against expectations.

        Checks: (a) per-line hash recomputation, (b) chain linkage, (c) seq
        continuity, (d) replay equivalence with the live reducer state.
        """
        divergences: List[str] = []
        lines = self._read_lines()
        for i, line in enumerate(lines):
            want = fnv1a(_canonical({k: v for k, v in line.items() if k != "hash"}))
            if line.get("hash") != want:
                divergences.append(f"line {i}: hash mismatch (tampered)")
            if i == 0:
                if line.get("prev_hash") != "0" * 16:
                    divergences.append("line 0: genesis prev_hash must be 16 zeros")
            else:
                if line.get("prev_hash") != lines[i - 1].get("hash"):
                    divergences.append(f"line {i}: chain link broken (truncation or reorder)")
            if line.get("seq") != i:
                divergences.append(f"line {i}: seq gap (expected {i}, got {line.get('seq')})")
        replayed = self.replay()
        if replayed != self._state:
            divergences.append("replay state diverges from live reducer state")
        return {"ok": not divergences, "divergences": divergences}
