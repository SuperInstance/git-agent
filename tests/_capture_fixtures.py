"""One-shot fixture capture: emit the REAL lifecycle events a git-agent vessel
produces, save them as test fixtures. Run: python3 _capture_fixtures.py <dir>"""
import datetime
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from git_agent.vessel import VesselManager, WorklogEntry, check_promotion, GrowthStage


def ts():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def main(out_dir: str):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    n = [0]

    def eid():
        n[0] += 1
        return f"evt-{n[0]:04d}-captured"

    with tempfile.TemporaryDirectory() as td:
        vm = VesselManager(local_path=Path(td))
        ident = vm.state.identity

        fx = {}
        fx["session_start"] = {
            "event_id": eid(), "type": "session_start", "timestamp": ts(),
            "name": ident.name, "designation": ident.designation,
            "version": ident.version, "domains": [d.value for d in ident.domains],
        }

        entry = WorklogEntry(
            timestamp=ts(), action="branched", target="SuperInstance/git-agent",
            summary="Created feature branch quilt-emitter", outcome="success")
        vm.add_worklog_entry(entry)
        fx["worklog"] = {
            "event_id": eid(), "type": "worklog", "timestamp": entry.timestamp,
            "action": entry.action, "target": entry.target,
            "summary": entry.summary, "outcome": entry.outcome,
        }

        before = vm.state.career.total_tasks_completed
        vm.record_task_completion(success=True)
        promoted = vm.state.career.current_stage != GrowthStage.INITIATE or vm.state.career.total_tasks_completed > before
        fx["task_completion"] = {
            "event_id": eid(), "type": "task_completion", "timestamp": ts(),
            "success": True,
        }

        # a promotion event as recorded in the worklog by record_task_completion
        promo_entry = vm.state.worklog[-1] if vm.state.worklog[-1].action == "promoted" else None
        fx["promotion"] = {
            "event_id": eid(), "type": "promotion", "timestamp": promo_entry.timestamp if promo_entry else ts(),
            "from_stage": GrowthStage.INITIATE.value,
            "to_stage": (promo_entry.target if promo_entry else GrowthStage.APPRENTICE.value),
        }

        vm.complete_fence("first-pr")
        fx["fence"] = {"event_id": eid(), "type": "fence", "timestamp": ts(), "fence_name": "first-pr"}

        vm.acquire_skill("code-review")
        fx["skill"] = {"event_id": eid(), "type": "skill", "timestamp": ts(), "skill": "code-review"}

        fx["snapshot"] = {
            "event_id": eid(), "type": "snapshot", "timestamp": ts(),
            "stage": vm.state.career.current_stage.value,
            "total_tasks_completed": vm.state.career.total_tasks_completed,
            "total_tasks_failed": vm.state.career.total_tasks_failed,
            "worklog_len": len(vm.state.worklog),
        }

        fx["heartbeat"] = {"event_id": eid(), "type": "heartbeat", "timestamp": ts()}

        fx["session_end"] = {"event_id": eid(), "type": "session_end", "timestamp": ts(), "archived": True}

        for name, payload in fx.items():
            (out / f"{name}.json").write_text(json.dumps(payload, indent=2) + "\n")
        print(f"captured {len(fx)} fixtures -> {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "fixtures")
