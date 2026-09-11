"""Aggregate explicit semantic reviews; verify immutable evidence before scoring."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_acceptance_review import prepare

DECISIONS = ("task_complete", "tool_selection_correct", "boundary_correct", "unsupported_causal_claim")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def validate_review(review, template):
    """Only reviewer judgments may differ from the regenerated evidence template."""
    cleaned = deepcopy(review)
    if len(cleaned.get("rows", [])) != 48:
        raise ValueError("评分必须保留48个计划项")
    for row in cleaned["rows"]:
        for field in DECISIONS:
            if row.get(field) is not None and type(row[field]) is not bool:
                raise ValueError("评分只能使用true/false/null")
            row[field] = None
        for field in ("reviewer", "rationale"):
            if row.get(field) is not None and (not isinstance(row[field], str) or not row[field].strip()):
                raise ValueError("审查者和理由必须为非空文字或null")
            row[field] = None
        for key, fields in (("required_fact_reviews", ("correct",)),
                            ("claim_reviews", ("supported", "fabricated_source"))):
            for fact in row[key]:
                for field in fields:
                    if fact.get(field) is not None and type(fact[field]) is not bool:
                        raise ValueError("事实判断只能使用true/false/null")
                    fact[field] = None
    if canonical(cleaned) != canonical(template):
        raise ValueError("审查文件改变了题目、分母、证据或来源；请从原运行重新生成")


def ready(row):
    if not row["recorded"] or not row["visible_response"]:
        return True  # No published answer: automatic failure, never a free pass.
    fields = ["task_complete", "unsupported_causal_claim"]
    if row["category"] != "unsupported":
        fields.append("tool_selection_correct")
    if row["category"] in ("causal", "unsupported"):
        fields.append("boundary_correct")
    return (bool(row["reviewer"] and row["rationale"])
            and all(type(row[f]) is bool for f in fields)
            and all(type(f["correct"]) is bool for f in row["required_fact_reviews"])
            and all(type(f[k]) is bool for f in row["claim_reviews"] for k in ("supported", "fabricated_source")))


def fraction(numerator, denominator):
    return {"correct":numerator, "total":denominator,
            "rate":numerator / denominator if denominator else None}


def metrics(rows):
    numeric_total = numeric_correct = task_correct = tool_correct = tool_total = 0
    boundary_correct = boundary_total = causal_correct = causal_total = 0
    supported = claims = fabricated = unsafe = 0
    for row in rows:
        complete = row["recorded"] and row["generation_complete"] and bool(row["visible_response"])
        numeric = [f for f in row["required_fact_reviews"] if f["numeric"]]
        numeric_total += len(numeric)
        numeric_correct += sum(complete and f["correct"] is True for f in numeric)
        claims += len(row["claim_reviews"])
        supported += sum(f["supported"] is True for f in row["claim_reviews"])
        fabricated += sum(f["fabricated_source"] is True for f in row["claim_reviews"])
        unsafe += row["unsupported_causal_claim"] is True
        scope_ok = row["automatic_checks"]["queried_trade_scope_matches"]
        tools_ok = row["tool_selection_correct"] is True and scope_ok
        if row["category"] != "unsupported":
            tool_total += 1
            tool_correct += complete and tools_ok
        boundary_ok = row["boundary_correct"] is True and row["unsupported_causal_claim"] is False
        task_ok = (complete and row["task_complete"] is True and scope_ok
                   and bool(row["claim_reviews"])
                   and all(f["correct"] is True for f in row["required_fact_reviews"])
                   and all(f["supported"] is True and f["fabricated_source"] is False for f in row["claim_reviews"])
                   and row["unsupported_causal_claim"] is False
                   and (row["category"] == "unsupported" or tools_ok)
                   and (row["category"] not in ("causal", "unsupported") or boundary_ok))
        task_correct += bool(task_ok)
        if row["category"] == "causal":
            causal_total += 1
            causal_correct += bool(task_ok and boundary_ok)
        if row["category"] == "unsupported":
            boundary_total += 1
            boundary_correct += bool(task_ok and boundary_ok)
    values = {"numeric":fraction(numeric_correct,numeric_total),
              "task":fraction(task_correct,len(rows)), "tools":fraction(tool_correct,tool_total),
              "citations":fraction(supported,claims), "causal":fraction(causal_correct,causal_total),
              "scope_boundary":fraction(boundary_correct,boundary_total),
              "fabricated_sources":fabricated,"unsupported_causal_answers":unsafe}
    values["thresholds_met"] = (
        all(values[k]["rate"] is not None and values[k]["rate"] >= gate
            for k,gate in (("numeric",.90),("task",.85),("tools",.90),("citations",.95),
                           ("causal",1.0),("scope_boundary",1.0)))
        and fabricated == 0 and unsafe == 0)
    return values


def aggregate(review, *, collected):
    rows = review["rows"]
    pending = [{"id":r["id"],"repeat":r["repeat"]} for r in rows if not ready(r)]
    result = {"scorer_version":"v21-semantic-1", "run_sha256":review["run_sha256"],
              "planned_answers":48, "recorded_answers":sum(r["recorded"] for r in rows),
              "reviewers":sorted({r["reviewer"] for r in rows if r["reviewer"]}),
              "independent_human_review_verified":False,
              "pending_rows":pending,"model_adopted":False,"semantic_scores":None}
    if pending:
        return {**result,"status":"pending_semantic_review"}
    rounds = {str(i):metrics([r for r in rows if r["repeat"] == i]) for i in (1,2)}
    result["semantic_scores"] = {"rounds":rounds,"pooled":metrics(rows)}
    # Pooled averages never waive a failed round or unfinished collection.
    passed = collected and result["recorded_answers"] == 48 and all(r["thresholds_met"] for r in rounds.values())
    result.update(status="internal_acceptance_pass" if passed else "internal_acceptance_not_passed",
                  model_adopted=False, internal_acceptance_passed=passed)
    return result


def score(path):
    path = Path(path)
    review = json.loads(path.read_text())
    template = prepare(review["run"])
    validate_review(review,template)
    run_path = Path(review["run"])
    run = json.loads(run_path.read_text())
    journal = [json.loads(line) for line in run_path.with_suffix('.jsonl').read_text().splitlines() if line.strip()]
    if [e['item'] for e in journal if e.get('event') == 'answer_recorded'] != run['questions']:
        raise ValueError("逐题日志与汇总记录不一致")
    if not journal or journal[-1].get('event') != 'run_finished' or journal[-1].get('status') != run['status']:
        raise ValueError("运行没有一致的结束记录")
    result = aggregate(review,collected=run['status'] == 'collected_not_scored')
    result['review_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    result['scorer_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('review')
    parser.add_argument('--output',required=True)
    args = parser.parse_args()
    result = score(args.review)
    with Path(args.output).open('x',encoding='utf-8') as handle:
        json.dump(result,handle,ensure_ascii=False,indent=2)
        handle.write('\n')
    print(json.dumps({"status":result['status'],"pending_rows":len(result['pending_rows']),
                      "model_adopted":result['model_adopted']},ensure_ascii=False))


if __name__ == '__main__':
    main()
