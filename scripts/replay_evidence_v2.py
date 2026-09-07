"""Replay completed v1 Agent trajectories offline against v2 evidence rendering.

This is a development regression, never a new model evaluation: no provider
requests occur, and recorded model choices do not adapt to the enriched tools.
"""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_live_evaluation import digest
from src.tradeintel_ai.evidence_v2 import EvidenceAgentV2


class ReplayModel:
    def __init__(self, trace):
        self.responses = iter(deepcopy([t["response"] for t in trace if "response" in t]))

    def complete(self, **kwargs):
        return next(self.responses)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=ROOT / "tmp/ai-live-runs/20260907T060927114347Z-continued.json")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("输出已存在，不能覆盖")
    run = json.loads(args.run.read_text(encoding="utf-8"))
    entries = []
    for q in run["questions"]:
        old = q["systems"]["agent"]
        if not old.get("generation_complete"):
            entries.append({"id":q["id"], "repeat":q["repeat"], "status":"skipped_original_generation_failure"})
            continue
        result = EvidenceAgentV2(ReplayModel(old["trace"])).answer(q["question"])
        entries.append({"id":q["id"], "repeat":q["repeat"], "status":result["status"],
                        "legacy_replaced":old.get("safety_guard_triggered", False), "result":result})
    completed = [e for e in entries if e.get("result", {}).get("facts")]
    summary = {"mode":"offline_recorded_trajectory_regression", "api_requests":0,
        "source_run_sha256":digest(args.run), "v2_sha256":digest(ROOT / "src/tradeintel_ai/evidence_v2.py"),
        "agent_slots":len(entries), "evidence_reports_rendered":len(completed),
        "skipped_original_generation_failures":sum(e["status"].startswith("skipped") for e in entries),
        "previously_replaced_now_with_facts":sum(bool(e.get("legacy_replaced")) for e in completed),
        "unbound_facts":sum(not f["source_ids"] or any(s not in e["result"]["sources"] for s in f["source_ids"])
                            for e in completed for f in e["result"]["facts"]),
        "model_adopted":False, "semantic_accuracy":None,
        "limitation":"Recorded model choices replayed unchanged; not a new model run or evidence of task accuracy."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump({"summary":summary, "entries":entries}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
