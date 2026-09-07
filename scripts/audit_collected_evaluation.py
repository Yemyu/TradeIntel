"""Audit collection integrity and proven blockers; does not fabricate semantic scores."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.continue_live_evaluation import prepare
from scripts.review_live_evaluation import make_form
from scripts.run_live_evaluation import digest

DEFAULT_RUN = ROOT / "tmp/ai-live-runs/20260907T060927114347Z-continued.json"


def build_audit(run_path):
    run, slots, records = prepare(run_path)
    if len(records) != len(slots) or run["status"] != "collected_not_scored":
        raise ValueError("须先完成整批采集")
    parent_path = Path(run["continuation"]["parent"])
    if digest(parent_path) != run["continuation"]["parent_sha256"]:
        raise ValueError("原批次指纹变化")
    _, _, parent_records = prepare(parent_path)
    if any(records[key] != value for key, value in parent_records.items()):
        raise ValueError("续跑覆盖了原批次记录")
    form = make_form(run_path)
    # These are confirmed visible-output omissions, not a lexical truth scorer.
    # The host substituted one source-free sentence for the entire response.
    guarded = []
    for key, result in records.items():
        if result.get("safety_guard_triggered"):
            text = result.get("response", "")
            if not text.startswith("安全后卫已拦截越界因果表述：") or "http" in text or "data/" in text:
                raise ValueError("替代回答结构变化，须重新人工核对")
            guarded.append(key)
    guarded = set(guarded)
    for entry in form["entries"]:
        key = (entry["repeat"], entry["id"], entry["arm"])
        if key in guarded and entry["surface"] == "visible":
            entry["citations"] = dict.fromkeys(entry["citations"], False)
            entry["task_completed"] = False
            entry["reviewer"] = "Codex collection audit"
            entry["review_method"] = "ai_assisted"
            entry["evidence_notes"] = "完整可见回答已核对：固定替代句没有任何具体来源，必需来源槽均缺失；事实和其他语义项仍待评。"
    gold = {entry["id"]: entry["reference"] for entry in form["entries"]}
    groups = []
    for repeat in range(1, 4):
        for arm in ("agent", "direct", "direct_evidence"):
            selected = {key: value for key, value in records.items() if key[0] == repeat and key[2] == arm}
            answerable = {key for key in selected if gold[key[1]]["answerable"]}
            failed = {key for key, value in selected.items() if not value.get("generation_complete")}
            guard_failures = (set(selected) & guarded)
            known_task_failures = (failed | guard_failures) & answerable
            groups.append({"repeat": repeat, "arm": arm, "recorded": len(selected),
                "generation_complete": len(selected)-len(failed), "generation_failed": len(failed),
                "host_replaced": len(guard_failures), "answerable_tasks": len(answerable),
                "proven_task_failure_ids": sorted(k[1] for k in known_task_failures),
                "task_completion_upper_bound": (len(answerable)-len(known_task_failures))/len(answerable),
                "actual_task_completion_rate": None})
    errors = Counter(value.get("error", value.get("status", "unknown")) for value in records.values()
                     if not value.get("generation_complete"))
    blocked = any(row["arm"] == "agent" and row["task_completion_upper_bound"] < .85 for row in groups)
    result = {"status": "blocking_diagnostic_complete", "run_sha256": digest(run_path),
        "original_records_preserved": len(parent_records), "recorded_answers": len(records),
        "generation_complete": sum(bool(v.get("generation_complete")) for v in records.values()),
        "request_count": run["request_count"], "guarded_visible_answers": len(guarded),
        "failures": dict(errors), "groups": groups, "adoption_blocked_by_upper_bound": blocked,
        "model_adopted": False, "semantic_scoring_complete": False,
        "review_entries": len(form["entries"]),
        "interpretation": "完成率上限只扣除已证明失败的任务；不是实际正确率。21次拦截不等于21次误报；具体误报须逐条语义核对。"}
    return result, form


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    audit, form = build_audit(args.run)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    paths = [args.output_dir / name for name in ("collection-audit.json", "partial-review.json")]
    if any(p.exists() for p in paths):
        raise ValueError("审查产物已存在，不能覆盖")
    for path, value in zip(paths, (audit, form)):
        with path.open("x", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write("\n")
    print(json.dumps({k:v for k,v in audit.items() if k not in {"groups", "failures"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
