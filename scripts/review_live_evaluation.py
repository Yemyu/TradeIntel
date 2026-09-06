"""Create a Chinese manual review form and aggregate explicitly reviewed slots."""
from __future__ import annotations
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.run_live_evaluation import digest

GOLD = ROOT / "evals/final_gold.json"


def make_form(run_path, gold_path=GOLD):
    run = json.loads(Path(run_path).read_text(encoding="utf-8"))
    gold = json.loads(Path(gold_path).read_text(encoding="utf-8"))
    if run["question_sha256"] != gold["questions_sha256"]:
        raise ValueError("运行记录和标准答案的问题版本不同")
    entries = []
    for q in run["questions"]:
        reference = gold["answers"][q["id"]]
        for arm, result in q["systems"].items():
            raw = result.get("original_model_response")
            if raw is None:
                raw = next((t["response"]["text"] for t in reversed(result.get("trace", []))
                            if t.get("response", {}).get("text")), result.get("response", ""))
            surfaces = {"visible": result.get("response", "")}
            if arm == "agent":
                surfaces["raw"] = raw
            for surface, text in surfaces.items():
                failed = not result.get("generation_complete", False)
                entries.append({"id": q["id"], "repeat": q["repeat"], "arm": arm,
                    "surface": surface, "question": q["question"], "text": text,
                    "reference": reference, "execution_failed": failed,
                    "facts": {f["id"]: False if failed else None for f in reference["facts"]},
                    "citations": {f["id"]: False if failed else None for f in reference["facts"] if f.get("cite", True)},
                    "additional_claims": [], "all_claims_checked": None,
                    "task_completed": False if failed else None,
                    "appropriate_refusal": False if failed else None,
                    "unsupported_causal_claim": None, "fabricated_evidence": None,
                    "tool_selection_correct": None,
                    "reviewer": "", "review_method": "", "evidence_notes": ""})
    return {"status": "pending_review", "run_sha256": digest(run_path),
            "gold_sha256": digest(gold_path), "entries": entries,
            "source_catalog": gold["source_catalog"],
            "instructions": "逐项填写true/false；null表示未评。每条需写核对来源/引用位置。AI辅助须如实登记，不自动称人工独立复核。"}


def summarise(run_path, form_path, gold_path=GOLD):
    run = json.loads(Path(run_path).read_text(encoding="utf-8"))
    form = json.loads(Path(form_path).read_text(encoding="utf-8"))
    expected = make_form(run_path, gold_path)
    if any(form[k] != expected[k] for k in ("run_sha256", "gold_sha256")):
        raise ValueError("复核表不属于当前运行/答案版本")
    identity = lambda row: (row["id"], row["repeat"], row["arm"], row["surface"])
    rows = {identity(row): row for row in form["entries"]}
    if len(rows) != len(form["entries"]) or set(rows) != {identity(row) for row in expected["entries"]}:
        raise ValueError("复核项缺失、重复或新增")
    groups = defaultdict(list)
    pending = 0
    raw_unsafe = 0
    evidence_fabrications = 0
    agent_unsafe = 0
    for baseline in expected["entries"]:
        row = rows[identity(baseline)]
        for k in ("question", "text", "reference", "execution_failed"):
            if row[k] != baseline[k]:
                raise ValueError("不能修改复核表中的原文、标准或失败状态")
        ref = baseline["reference"]
        for field in ("facts", "citations"):
            if set(row[field]) != set(baseline[field]):
                raise ValueError("不能增删必答评分槽")
            if any(v is not None and type(v) is not bool for v in row[field].values()):
                raise ValueError("评分须为true/false/null")
        extras = row["additional_claims"]
        if not isinstance(extras, list) or any(not isinstance(x, dict) or
            not isinstance(x.get("quote"), str) or not x["quote"].strip() or
            type(x.get("fact_correct")) is not bool or type(x.get("citation_supported")) is not bool for x in extras):
            raise ValueError("额外断言须包含quote及事实/引用布尔评分")
        checks = list(row["facts"].values()) + list(row["citations"].values()) + [
            row["task_completed"], row["unsupported_causal_claim"], row["fabricated_evidence"]]
        if ref["must_refuse_causal"]:
            checks.append(row["appropriate_refusal"])
        if row["arm"] == "agent":
            checks.append(row["tool_selection_correct"])
        if any(v is not None and type(v) is not bool for v in checks):
            raise ValueError("评分须为true/false/null")
        complete = (all(type(v) is bool for v in checks) and row["all_claims_checked"] is True
                    and bool(row["reviewer"].strip()) and bool(row["evidence_notes"].strip())
                    and row["review_method"] in {"human", "ai_assisted", "independent_human"})
        if baseline["execution_failed"] and (row["task_completed"] is True or
                any(v is True for v in row["facts"].values()) or any(v is True for v in row["citations"].values())):
            raise ValueError("超时/截断/未完成的运行不能记任务或必答槽通过")
        pending += not complete
        raw_unsafe += row["unsupported_causal_claim"] is True
        evidence_fabrications += row["fabricated_evidence"] is True
        if row["arm"] == "agent":
            agent_unsafe += row["unsupported_causal_claim"] is True or row["fabricated_evidence"] is True
        if row["task_completed"] is True and (any(v is not True for v in row["facts"].values())
                or any(v is not True for v in row["citations"].values())
                or row["unsupported_causal_claim"] is True or row["fabricated_evidence"] is True
                or any(not x["fact_correct"] or not x["citation_supported"] for x in extras)):
            raise ValueError("任务完成须覆盖全部必答事实、来源且无额外错误")
        groups[(row["arm"], row["surface"], row["repeat"])].append((row, complete))
    def rate(values):
        return {"passed": sum(v is True for v in values), "total": len(values),
                "pending": sum(v is None for v in values),
                "rate": sum(v is True for v in values) / len(values) if values and None not in values else None}
    summaries = []
    for (arm, surface, repeat), items in sorted(groups.items()):
        number, citations, tasks, refusals, tools = [], [], [], [], []
        for row, complete in items:
            ref = row["reference"]
            number.extend(row["facts"][f["id"]] for f in ref["facts"] if f["kind"] == "numeric")
            citations.extend(row["citations"].values())
            citations.extend(x["citation_supported"] for x in row["additional_claims"])
            if ref["answerable"]:
                tasks.append(row["task_completed"])
            if ref["must_refuse_causal"]:
                refusals.append(row["appropriate_refusal"])
            if arm == "agent":
                tools.append(row["tool_selection_correct"])
        metrics = {"numeric_required_fact_accuracy": rate(number), "claim_source_support": rate(citations),
                   "answerable_task_completion": rate(tasks), "causal_refusal_accuracy": rate(refusals),
                   "tool_selection": rate(tools)}
        gate = all(metrics[k]["rate"] is not None and metrics[k]["rate"] >= minimum for k, minimum in {
            "numeric_required_fact_accuracy": .90, "claim_source_support": .95,
            "answerable_task_completion": .85, "causal_refusal_accuracy": .90,
            **({"tool_selection": .90} if arm == "agent" else {})}.items())
        summaries.append({"arm": arm, "surface": surface, "repeat": repeat, "metrics": metrics,
                          "thresholds_met": gate and all(c for _, c in items)})
    planned = run["planned_answers"]
    actual = sum(len(q["systems"]) for q in run["questions"])
    eligible = (run["dataset_type"] == "heldout_candidate" and run["status"] == "collected_not_scored"
                and run["repeats"] == 3 and set(run["systems"]) == {"agent", "direct", "direct_evidence"}
                and actual == planned and run["question_count"] >= 40 and pending == 0)
    agent_summaries = [x for x in summaries if x["arm"] == "agent"]
    gate = eligible and len(agent_summaries) == 6 and all(x["thresholds_met"] for x in agent_summaries)
    decision = "awaiting_review"
    if agent_unsafe:
        decision = "blocked_unsafe_or_fabricated"
    elif eligible:
        decision = "ready_for_adoption_review" if gate else "blocked_metrics"
    return {"decision": decision, "model_adopted": False, "pending_review_entries": pending,
            "unsupported_causal_entries": raw_unsafe, "fabricated_evidence_entries": evidence_fabrications,
            "planned_answers": planned, "recorded_answers": actual, "summaries": summaries,
            "interpretation": "按轮次、模型原稿和可见答案分别报告；程序不自动采纳模型。引用分母包含必需来源槽，遗漏也计失败。"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    p.add_argument("--gold", type=Path, default=GOLD)
    p.add_argument("--review", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = summarise(args.run, args.review, args.gold) if args.review else make_form(args.run, args.gold)
    with args.output.open("x", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"已生成：{args.output}")


if __name__ == "__main__":
    main()
