"""Freeze and independently check the 0111 prospective research-plan set.

This command is deliberately offline.  It validates the new questions, the
human reference envelope, and the frozen local data without importing a model
adapter or asking for a credential.  The reference values are for the future
reviewer only; they are never sent to a tested model.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from math import isclose
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "evals/research_plan_prospective_0111_questions.jsonl"
REFERENCE = ROOT / "evals/research_plan_prospective_0111_reference.json"
MONTHLY = ROOT / "data/processed/analysis/policy_case_monthly.csv"
HS6_PANEL = ROOT / "data/processed/causal/causal_trade_hs6_monthly.csv"
POLICY_EVENT = ROOT / "data/processed/policy/section301_list1_event.csv"
POLICY_EXPOSURE = ROOT / "data/processed/causal/policy_exposure_hs6.csv"
REGISTERED_WINDOWS = ROOT / "data/processed/analysis/registered_comparison_windows.json"
STATISTICAL_BASELINE = ROOT / "data/processed/analysis/statistical_baseline_summary.json"
PROMPT = ROOT / "src/tradeintel_ai/unified_research.py"
CORPUS = ROOT / "docs/experiments/phase13a-policy-retrieval/corpus.json"
OLD_QUESTIONS = ROOT / "evals/research_plan_acceptance_questions.jsonl"

EXPECTED_IDS = {
    *(f"P{i}" for i in range(11, 15)),
    *(f"T{i}" for i in range(11, 15)),
    *(f"C{i}" for i in range(11, 15)),
    *(f"X{i}" for i in range(11, 17)),
    *(f"B{i}" for i in range(11, 17)),
}
MONTHLY_FIELDS = {
    "China": "target_import_value_consumption_usd",
    "other_origins": "other_origins_import_value_consumption_usd",
    "all_origins": "all_origins_import_value_consumption_usd",
}
REGISTERED_IDS = {
    "recent_clean_pre_same_months",
    "pre_policy_placebo_same_months",
    "immediate_post_same_months",
    "persistence_monitoring_same_months",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_questions() -> list[dict]:
    rows = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    if len(rows) != 24 or {row.get("id") for row in rows} != EXPECTED_IDS:
        raise ValueError("0111 question set must contain the fixed 24 unique IDs")
    if any(set(row) != {"id", "category", "question"} for row in rows):
        raise ValueError("question schema changed")
    if any(not isinstance(row["question"], str) or not row["question"].strip()
           for row in rows):
        raise ValueError("questions must be non-empty strings")
    counts = {category: sum(row["category"] == category for row in rows)
              for category in ("support", "clarification", "boundary")}
    if counts != {"support": 12, "clarification": 6, "boundary": 6}:
        raise ValueError(f"category counts changed: {counts}")
    if OLD_QUESTIONS.exists():
        old = {json.loads(line)["question"] for line in OLD_QUESTIONS.read_text(encoding="utf-8").splitlines()
               if line.strip()}
        overlap = [row["id"] for row in rows if row["question"] in old]
        if overlap:
            raise ValueError(f"retired question reused: {overlap}")
    return rows


def _load_monthly() -> dict[str, dict[str, str]]:
    with MONTHLY.open(newline="", encoding="utf-8") as handle:
        rows = {row["month_label"]: row for row in csv.DictReader(handle)}
    if len(rows) != 48 or min(rows) != "2016-01" or max(rows) != "2019-12":
        raise ValueError("monthly panel coverage changed")
    return rows


def _load_hs6() -> dict[tuple[str, str], dict[str, str]]:
    with HS6_PANEL.open(newline="", encoding="utf-8") as handle:
        return {(row["hs6_2017"], f"{int(row['year']):04d}-{int(row['month']):02d}"): row
                for row in csv.DictReader(handle)}


def _load_policy() -> dict[str, str]:
    with POLICY_EVENT.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    row = next((row for row in rows if row.get("policy_id") == "us_301_list1_2018"), None)
    if row is None:
        raise ValueError("Section 301 List 1 event is missing")
    return row


def _load_exposure() -> set[str]:
    with POLICY_EXPOSURE.open(newline="", encoding="utf-8") as handle:
        return {row["hs6_2017"] for row in csv.DictReader(handle)
                if row.get("policy_id") == "us_301_list1_2018"}


def _load_windows() -> dict[str, dict]:
    obj = json.loads(REGISTERED_WINDOWS.read_text(encoding="utf-8"))
    comparisons = obj.get("comparisons")
    if set(comparisons or {}) != REGISTERED_IDS:
        raise ValueError("registered comparison IDs changed")
    return comparisons


def _amounts(ref: dict, monthly: dict, hs6_rows: dict) -> list[int]:
    scope = ref["trade"]
    origin = scope["origin"]
    field = ("china_import_value_consumption_usd" if origin == "China"
             else "all_origin_import_value_consumption_usd")
    values = []
    for month in scope["months"]:
        if scope["granularity"] == "policy_aggregate":
            row = monthly.get(month)
            if row is None:
                raise ValueError(f"missing aggregate month {month}")
            values.append(int(row[MONTHLY_FIELDS[origin]]))
        else:
            row = hs6_rows.get((scope["hs6"], month))
            if row is None:
                raise ValueError(f"missing HS6 {scope['hs6']} month {month}")
            values.append(int(row[field]))
    return values


def _check_support(q: dict, ref: dict, monthly: dict, hs6_rows: dict,
                   exposure: set[str], windows: dict[str, dict], policy: dict) -> dict:
    question = q["question"]
    if ref.get("expected_terminal") != "plan":
        raise ValueError(f"support reference is not plan: {q['id']}")
    if not set(ref["tasks"]).issubset({"policy", "trade"}) or not ref["tasks"]:
        raise ValueError(f"invalid tasks: {q['id']}")
    if "policy" in ref["tasks"]:
        if ref["policy_question"] not in question or ref["policy_as_of"] not in question:
            raise ValueError(f"policy quote/cutoff not contained: {q['id']}")
        for key, expected in ref.get("policy_facts", {}).items():
            if key == "additional_rate_percent":
                actual = float(policy["additional_rate"]) * 100
            elif key == "target_origin":
                actual = policy["target_origin"]
            else:
                actual = policy[key]
            if actual != expected:
                raise ValueError(f"policy reference mismatch {q['id']} {key}")
    if "trade" not in ref["tasks"]:
        return {"id": q["id"], "kind": "policy", "validated": True}
    scope = ref["trade"]
    if scope["origin"] not in MONTHLY_FIELDS:
        raise ValueError(f"invalid origin: {q['id']}")
    if scope["granularity"] not in {"policy_aggregate", "hs6_2017"}:
        raise ValueError(f"invalid granularity: {q['id']}")
    if scope["granularity"] == "policy_aggregate" and scope["hs6"] is not None:
        raise ValueError(f"aggregate reference cannot have hs6: {q['id']}")
    if scope["granularity"] == "hs6_2017" and scope["hs6"] not in exposure:
        raise ValueError(f"HS6 not in exposure: {q['id']}")
    comparison = scope["comparison"]
    kind = comparison["kind"]
    if kind not in {"sequence", "endpoint", "registered"}:
        raise ValueError(f"invalid comparison: {q['id']}")
    if kind == "registered":
        cid = comparison["comparison_id"]
        if cid not in windows or scope["months"] is not None:
            raise ValueError(f"registered comparison must derive months: {q['id']}")
        window = windows[cid]
        months = list(window["reference_months"]) + list(window["current_months"])
        values = []
        for month in months:
            if scope["granularity"] != "policy_aggregate":
                raise ValueError(f"registered HS6 comparison not frozen: {q['id']}")
            values.append(int(monthly[month][MONTHLY_FIELDS[scope["origin"]]]))
        half = len(window["reference_months"])
        actual = {
            "reference_months": window["reference_months"],
            "current_months": window["current_months"],
            "reference_value_usd": sum(values[:half]),
            "current_value_usd": sum(values[half:]),
        }
        expected = ref["answer"]
        if any(actual[key] != expected[key] for key in actual):
            raise ValueError(f"registered reference mismatch: {q['id']}")
        denominator = expected["reference_value_usd"]
        pct = (expected["current_value_usd"] - denominator) / denominator
        if not isclose(pct, expected["change_pct"], rel_tol=0, abs_tol=1e-15):
            raise ValueError(f"registered percentage mismatch: {q['id']}")
        return {"id": q["id"], "kind": "registered", "validated": True}
    months = scope["months"]
    if not isinstance(months, list) or len(months) < 1:
        raise ValueError(f"explicit months required: {q['id']}")
    values = _amounts(ref, monthly, hs6_rows)
    expected_values = ref["answer"].get("values")
    if expected_values is not None:
        if [item["month"] for item in expected_values] != months:
            raise ValueError(f"series months mismatch: {q['id']}")
        if [item["value_usd"] for item in expected_values] != values:
            raise ValueError(f"series values mismatch: {q['id']}")
    if kind == "endpoint":
        if len(months) != 2:
            raise ValueError(f"endpoint must have two months: {q['id']}")
        expected = ref["answer"]
        change = values[1] - values[0]
        pct = change / values[0]
        if (expected["reference_value_usd"], expected["current_value_usd"], expected["change_usd"]) != (values[0], values[1], change):
            raise ValueError(f"endpoint values mismatch: {q['id']}")
        if not isclose(pct, expected["change_pct"], rel_tol=0, abs_tol=1e-15):
            raise ValueError(f"endpoint percentage mismatch: {q['id']}")
    return {"id": q["id"], "kind": kind, "validated": True}


def preflight() -> dict:
    questions = load_questions()
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    if set(reference) - {"purpose"} != {row["id"] for row in questions}:
        raise ValueError("reference IDs do not match questions")
    monthly = _load_monthly()
    hs6_rows = _load_hs6()
    policy = _load_policy()
    exposure = _load_exposure()
    windows = _load_windows()
    results = []
    for question in questions:
        ref = reference[question["id"]]
        if question["category"] == "support":
            results.append(_check_support(question, ref, monthly, hs6_rows, exposure, windows, policy))
        elif ref.get("expected_terminal") != "clarify":
            if question["category"] != "boundary" or ref.get("expected_terminal") != "boundary_stop":
                raise ValueError(f"terminal/category mismatch: {question['id']}")
            if not ref.get("reason"):
                raise ValueError(f"boundary reason missing: {question['id']}")
            results.append({"id": question["id"], "kind": "boundary", "validated": True})
        else:
            if question["category"] != "clarification" or not isinstance(ref.get("expected_missing"), list):
                raise ValueError(f"clarification reference mismatch: {question['id']}")
            results.append({"id": question["id"], "kind": "clarification", "validated": True})
    hash_paths = [QUESTIONS, REFERENCE, MONTHLY, HS6_PANEL, POLICY_EVENT,
                  POLICY_EXPOSURE, REGISTERED_WINDOWS, STATISTICAL_BASELINE,
                  PROMPT, CORPUS]
    return {
        "version": "research-plan-prospective-0111-preflight-1",
        "status": "preflight_passed",
        "online_run": False,
        "new_api_calls": 0,
        "question_count": 24,
        "counts": {"support": 12, "clarification": 6, "boundary": 6},
        "support_ids": [row["id"] for row in questions if row["category"] == "support"],
        "clarification_ids": [row["id"] for row in questions if row["category"] == "clarification"],
        "boundary_ids": [row["id"] for row in questions if row["category"] == "boundary"],
        "validated_references": results,
        "semantic_scores": None,
        "purpose": "Freeze the 0111 set and independent references before any model sees a question.",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "sha256": {str(path.relative_to(ROOT)): digest(path) for path in hash_paths},
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "docs/experiments/research-plan-prospective-0111/preflight.json")
    args = parser.parse_args(argv)
    report = preflight()
    if args.output.exists():
        raise ValueError("refusing to overwrite an existing frozen preflight report")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
