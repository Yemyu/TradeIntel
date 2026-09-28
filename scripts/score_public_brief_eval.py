"""Aggregate reviewed public-brief runs without inventing model scores.

This is intentionally a post-run report.  It never calls a provider and it
never treats a structurally valid answer as semantically correct.  A question
counts as a full pass only when the saved run is structurally valid *and* the
ledger contains a matching human/AI-assisted semantic review with verdict
``pass``.  Unreviewed and unrun questions remain visible as such.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.tradeintel_ai.public_eval_ledger import (  # noqa: E402
    load as load_ledger, file_sha256, canonical_sha, validate_review_checks,
)
from src.tradeintel_ai.public_eval_protocols import (  # noqa: E402
    QUESTION_PROTOCOLS, UNIFIED_CANDIDATE_SCHEMA, UNIFIED_EXPERIMENT_ID,
    UNIFIED_RUN_SCHEMA, equivalent_messages,
)
from src.tradeintel_ai.public_brief_explanation import (  # noqa: E402
    messages as trade_messages, parse as parse_trade,
)
from src.tradeintel_ai.public_policy_explanation import (  # noqa: E402
    messages as policy_messages, parse as parse_policy,
)

QUESTION_IDS = ("q1", "q2", "q3", "q4")
STRUCTURAL_STATUS = "awaiting_semantic_review"
INTERFACE_STATUSES = {"unknown_outcome"}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("运行记录必须是JSON对象：" + str(path))
    return value


def _review_index(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for event in ledger.get("events", []):
        if event.get("event") == "semantic_review":
            result[event.get("run_id", "")] = event
    return result


def _question_result(run_path: Path, run: dict[str, Any],
                     reviews: dict[str, dict[str, Any]],
                     events: list[dict[str, Any]]) -> dict[str, Any]:
    run_id = run.get("run_id")
    raw_path = run_path.parent / "raw-response.txt"
    raw_saved = raw_path.is_file()
    review = reviews.get(run_id) if isinstance(run_id, str) else None
    actual_sha = file_sha256(raw_path) if raw_saved else None
    starts = [e for e in events if e.get("run_id") == run_id and e.get("event") == "started"]
    terminals = [e for e in events if e.get("run_id") == run_id
                 and e.get("event") == STRUCTURAL_STATUS]
    metadata = starts[0].get("metadata", {}) if len(starts) == 1 else {}
    unified = run.get("schema_version") == UNIFIED_RUN_SCHEMA
    expected_protocol = QUESTION_PROTOCOLS.get(run.get("question_id")) if unified else {
        "mode": "trade", "protocol": "public-brief-explanation-v1"}
    bound = bool(len(starts) == 1 and
                 metadata.get("question_id") == run.get("question_id") and
                 metadata.get("provider_id") == run.get("provider", {}).get("id") and
                 metadata.get("freeze_sha256") == run.get("freeze_sha256") and
                 metadata.get("request_sha256") == run.get("request_sha256") and
                 metadata.get("params") == run.get("params") and
                 metadata.get("execution_channel") == run.get("execution_channel") and
                 (not unified or (
                     metadata.get("experiment_id") == run.get("experiment_id") == UNIFIED_EXPERIMENT_ID and
                     metadata.get("mode") == run.get("mode") == (expected_protocol or {}).get("mode") and
                     metadata.get("protocol") == run.get("protocol") == (expected_protocol or {}).get("protocol") and
                     metadata.get("candidate_schema") == run.get("candidate_schema") == UNIFIED_CANDIDATE_SCHEMA and
                     metadata.get("package_manifest_sha256") == run.get("package_manifest_sha256") and
                     metadata.get("scoring_version") == run.get("scoring_version") == "public-brief-unified-scoring-v2")) and
                 Path(metadata.get("output_dir", "")).resolve() == run_path.parent.parent.resolve())
    validation_path = run_path.parent / "validation.json"
    validation = _read_json(validation_path) if validation_path.is_file() else {}
    run_validation = run.get("validation", {}) if isinstance(run.get("validation"), dict) else {}
    if unified:
        try:
            _verify_unified_record(run=run, raw_path=raw_path, validation=validation,
                                   expected=expected_protocol or {})
        except (ValueError, OSError, json.JSONDecodeError, KeyError, TypeError):
            bound = False
    valid_raw = bool(raw_saved and actual_sha == run.get("raw_sha256"))
    raw_matches = bool(review and valid_raw and bound and review.get("raw_sha256") == actual_sha)
    status = run.get("status")
    # v3 can have valid structure but fail cost/length. Keep this diagnostic
    # separate from the original eligibility flag used by semantic scoring.
    budget_events = [e for e in events if e.get("run_id") == run_id and
                     e.get("event") in {STRUCTURAL_STATUS, "blocked_output_budget", "needs_revision"}]
    budget_bound = bool(valid_raw and bound and len(budget_events) == 1 and
                        budget_events[0].get("raw_sha256") == actual_sha and
                        budget_events[0].get("output_budget") == run.get("output_budget"))
    budget = run.get("output_budget", {}) if budget_bound else {}
    structure_result = "not_checked"
    protocol_valid = bool(
        run_validation.get("mode", run.get("mode", "trade")) == (expected_protocol or {}).get("mode")
        and run_validation.get("protocol", run.get("protocol", "public-brief-explanation-v1"))
            == (expected_protocol or {}).get("protocol")
        and (not unified or expected_protocol is not None)
        and (not unified or run.get("experiment_id") == UNIFIED_EXPERIMENT_ID)
    )
    if budget_bound and validation.get("raw_sha256") == actual_sha and protocol_valid:
        structure_result = ("passed" if validation.get("status") == "manual_review_required"
                            and validation.get("interpretations")
                            and (not unified or run.get("mode") != "policy"
                                 or len(validation.get("policy_explanations", [])) == 3) else "needs_revision")
    structural_pass = bool(status == STRUCTURAL_STATUS and valid_raw and bound and
                           len(terminals) == 1 and terminals[0].get("raw_sha256") == actual_sha and
                           validation.get("raw_sha256") == actual_sha and
                           protocol_valid and
                           validation.get("status") == "manual_review_required" and
                           validation.get("interpretations") and
                           (not unified or run.get("mode") != "policy"
                            or (validation.get("policy_explanations")
                                and len(validation.get("policy_explanations", [])) == 3
                                and run_validation.get("policy_explanation_count") == 3)))
    verdict = review.get("verdict") if raw_matches else None
    if verdict is not None:
        try:
            validate_review_checks(review.get("checks"), verdict)
        except ValueError:
            verdict = None
    whole_pass = structural_pass and verdict == "pass"
    issues: list[str] = []
    if not raw_saved:
        issues.append("未保存原答")
    elif not valid_raw:
        issues.append("原答文件摘要不一致")
    if not bound:
        issues.append("运行记录与账本不一致")
    if status == STRUCTURAL_STATUS and not structural_pass:
        issues.append("结构验收证据不完整或为空答案")
    if status != STRUCTURAL_STATUS:
        issues.append(str(status or "缺少状态"))
    if review and not raw_matches:
        issues.append("审阅摘要与原答不一致")
    if review and verdict in {"minor_error", "major_error"}:
        issues.append((review.get("note") or verdict).strip())
    if not review:
        issues.append("尚未完成语义审阅")
    elif verdict is None:
        issues.append("语义审阅证据无效或缺少逐项理由")
    return {
        "question_id": run.get("question_id"),
        "mode": run.get("mode", "trade"),
        "protocol": run.get("protocol", "public-brief-explanation-v1"),
        "run_id": run_id,
        "status": status,
        "api_calls": run.get("api_calls", 0),
        "raw_saved": raw_saved,
        "structural_pass": structural_pass,
        "structure_result": structure_result,
        "budget_result": ("passed" if budget.get("within_gate") else "blocked") if budget else "unknown",
        "budget_reason": budget.get("reason"),
        "budget_protocol": budget.get("budget_protocol", "v2") if budget else None,
        "review_verdict": verdict if structural_pass else None,
        "reviewer": review.get("reviewer") if raw_matches else None,
        "ai_assisted_review": bool(review and raw_matches and review.get("ai_assisted")),
        "whole_pass": whole_pass,
        "interface_failure": status in INTERFACE_STATUSES,
        "issues": [item for item in issues if item],
        "run_file": str(run_path),
    }


def _verify_unified_record(*, run: dict[str, Any], raw_path: Path,
                           validation: dict[str, Any], expected: dict[str, str]) -> None:
    """Re-parse the saved raw answer against the exact frozen question input."""
    if (run.get("experiment_id") != UNIFIED_EXPERIMENT_ID
            or run.get("candidate_schema") != UNIFIED_CANDIDATE_SCHEMA
            or run.get("mode") != expected.get("mode")
            or run.get("protocol") != expected.get("protocol")):
        raise ValueError("运行题目协议身份不一致")
    package = Path(run["package_path"]).resolve()
    if not package.is_dir() or run.get("package_manifest_sha256") != file_sha256(package / "MANIFEST.json"):
        raise ValueError("统一评测题包清单摘要不一致")
    manifest = _read_json(package / "MANIFEST.json")
    if (manifest.get("schema_version") != UNIFIED_CANDIDATE_SCHEMA
            or manifest.get("experiment_id") != UNIFIED_EXPERIMENT_ID
            or manifest.get("question_protocols") != QUESTION_PROTOCOLS):
        raise ValueError("统一评测题包身份不一致")
    qid = run["question_id"]
    files = manifest.get("files_sha256", {})
    def read_bound(relative: str) -> Any:
        path = package / relative
        if path.is_symlink() or not path.is_file() or file_sha256(path) != files.get(relative):
            raise ValueError("统一评测题包文件摘要不一致")
        return json.loads(path.read_text(encoding="utf-8"))
    snapshot = read_bound(f"host_artifacts/{qid}/snapshot.json")
    response = read_bound(f"host_artifacts/{qid}/response.json")
    messages = read_bound(f"requests/{qid}/messages.json")
    scenario = manifest.get("scenarios", {}).get(qid, {})
    request_context = None
    context_relative = f"host_artifacts/{qid}/request_context.json"
    if qid == "q2":
        request_context = read_bound(context_relative)
    elif context_relative in files:
        raise ValueError("非Q2题包含追问上下文")
    if (scenario.get("mode") != expected.get("mode")
            or scenario.get("protocol") != expected.get("protocol")
            or not isinstance(snapshot.get("question"), str)
            or scenario.get("question") not in snapshot.get("question", "")
            or snapshot.get("identity") != {"session_id": scenario.get("session_id"),
                                               "task_id": scenario.get("task_id")}
            or snapshot.get("mode") != expected.get("mode")
            or snapshot.get("protocol") != expected.get("protocol")
            or not equivalent_messages(snapshot.get("messages"), messages)
            or snapshot.get("report") != response.get("report")
            or snapshot.get("report_sha256") != response.get("report_sha256")
            or snapshot.get("evidence_sha256") != response.get("evidence_sha256")
            or snapshot.get("policy_context") != response.get("policy_context")
            or snapshot.get("request_context") != request_context):
        raise ValueError("统一评测题包快照与解析协议不一致")
    if expected.get("mode") == "policy":
        rebuilt = policy_messages(snapshot["question"], snapshot["report"],
                                  policy_context=snapshot["policy_context"],
                                  request_context=request_context)
    else:
        rebuilt = trade_messages(snapshot["question"], snapshot["report"],
                                 policy_context=snapshot.get("policy_context"),
                                 request_context=request_context)
    if not equivalent_messages(rebuilt, messages):
        raise ValueError("统一评测送模消息不能从快照重建")
    raw = raw_path.read_text(encoding="utf-8")
    if expected.get("mode") == "policy":
        parsed = parse_policy(raw, snapshot["report"], question=snapshot["question"],
                              policy_context=snapshot.get("policy_context") or {},
                              request_context=snapshot.get("request_context"),
                              enforce_body_budget=False)
    else:
        parsed = parse_trade(raw, snapshot["report"])
    if parsed != validation:
        raise ValueError("保存的解析结果无法由原答和冻结输入复算")


def collect_results(*, results_root: Path, ledger_root: Path,
                    planned_questions: tuple[str, ...] = QUESTION_IDS) -> dict[str, Any]:
    if tuple(planned_questions) != QUESTION_IDS:
        raise ValueError("当前公共评测固定计划为q1、q2、q3、q4")
    ledger = load_ledger(ledger_root)
    reviews = _review_index(ledger)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    configurations: dict[tuple[str, str], dict[str, Any]] = {}
    for run_path in sorted(Path(results_root).rglob("q*/run.json")):
        run = _read_json(run_path)
        if run.get("schema_version") not in {"public-brief-provider-run-v1", UNIFIED_RUN_SCHEMA}:
            # In particular, the independent single-question policy runner is
            # not silently imported into the unified four-question comparison.
            continue
        qid = run.get("question_id")
        provider = run.get("provider") if isinstance(run.get("provider"), dict) else {}
        provider_id = provider.get("id")
        if qid not in QUESTION_IDS or not isinstance(provider_id, str) or not provider_id:
            continue
        unified = run.get("schema_version") == UNIFIED_RUN_SCHEMA
        config = {"provider": provider, "params": run.get("params"),
                  "freeze_sha256": run.get("freeze_sha256"),
                  "execution_channel": run.get("execution_channel", "legacy_unverified"),
                  "experiment_id": run.get("experiment_id", "public-brief-v1"),
                  "run_schema": run.get("schema_version"),
                  "candidate_schema": run.get("candidate_schema", "legacy"),
                  "package_manifest_sha256": run.get("package_manifest_sha256"),
                  "scoring_version": run.get("scoring_version", "public-brief-scoring-v1"),
                  "question_protocols": run.get("question_protocols", {}) if unified else {}}
        group_key = (provider_id, canonical_sha(config))
        configurations[group_key] = config
        grouped[group_key].append(_question_result(run_path, run, reviews, ledger.get("events", [])))

    rows: list[dict[str, Any]] = []
    for group_key in sorted(grouped):
        provider_id, config_sha = group_key
        config = configurations[group_key]
        by_question: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in grouped[group_key]:
            by_question[item["question_id"]].append(item)
        duplicate_qids = sorted(qid for qid, items in by_question.items() if len(items) > 1)
        # A duplicate is deliberately left unscored. The report exposes all
        # attempts below rather than selecting a convenient one.
        results = {qid: items[0] for qid, items in by_question.items()
                   if len(items) == 1}
        answered = sum(1 for item in results.values() if item["raw_saved"])
        structural = sum(1 for item in results.values() if item["structural_pass"])
        semantic = sum(1 for item in results.values() if item["review_verdict"] == "pass")
        whole = sum(1 for item in results.values() if item["whole_pass"])
        interface = sum(1 for item in results.values() if item["interface_failure"])
        issues = []
        for qid in QUESTION_IDS:
            item = results.get(qid)
            if item:
                issues.extend(f"{qid}: {issue}" for issue in item["issues"])
            elif qid in duplicate_qids:
                issues.append(f"{qid}: 多次运行记录，拒绝选择任何一次")
            else:
                issues.append(f"{qid}: 未运行")
        reviewed = sum(item["review_verdict"] is not None for item in results.values())
        resolved = sum(item["raw_saved"] and (item["review_verdict"] is not None or
                       item["status"] in {"invalid_response", "blocked_output_budget", "needs_revision"})
                       for item in results.values())
        rows.append({
            "experiment_id": config["experiment_id"],
            "candidate_schema": config["candidate_schema"],
            "scoring_version": config["scoring_version"],
            "question_protocols": config["question_protocols"],
            "provider_id": provider_id,
            "model_id": config["provider"].get("model_id"),
            "configuration_sha256": config_sha,
            "configuration": config,
            "execution_channel": config["execution_channel"],
            "planned_questions": len(QUESTION_IDS),
            "run_questions": len(results),
            "attempt_count": len(grouped[group_key]),
            "api_calls": sum(item.get("api_calls", 0) for item in grouped[group_key]),
            "duplicate_questions": duplicate_qids,
            "answered_questions": answered,
            "structural_pass": structural,
            "semantic_pass": semantic,
            "whole_pass": whole,
            "reviewed_questions": reviewed,
            "whole_pass_rate": (whole / answered if answered and resolved == answered else None),
            "interface_failures": interface,
            "main_issues": issues,
            "questions": [results[qid] for qid in QUESTION_IDS if qid in results],
            "attempts": grouped[group_key],
        })
    return {
        "schema_version": "public-brief-score-report-v2",
        "status": "reviewed_runs_only",
        "api_calls": 0,
        "planned_questions": list(QUESTION_IDS),
        "rows": rows,
        "boundary": "未运行或未完成语义审阅的题不计通过；这不是长期准确率。",
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# 公共四题模型评测汇总", "",
             "> 只有结构通过且完成语义审阅并判为 pass 的回答才计整题通过。未运行、接口失败和未审阅均保留，不补分。", "",
             "| 模型配置 | 已运行/计划 | 收到原答 | 达到语义审阅条件 | 语义通过 | 整题通过率 | 接口失败 | 主要问题 |",
             "|---|---:|---:|---:|---:|---:|---:|---|"]
    for row in report.get("rows", []):
        rate = (f"{row['whole_pass']}/{row['answered_questions']}（待审阅）" if row["whole_pass_rate"] is None
                else f"{row['whole_pass']}/{row['answered_questions']}（{row['whole_pass_rate']:.1%}）")
        issues = "；".join(row["main_issues"]) or "—"
        params = json.dumps(row['configuration']['params'], ensure_ascii=False, sort_keys=True)
        lines.append(f"| {row['provider_id']}（{row.get('model_id') or '未知'}；{row['execution_channel']}；{params}） | "
                     f"{row['run_questions']}/{row['planned_questions']} | {row['answered_questions']} | "
                     f"{row['structural_pass']} | {row['semantic_pass']} | {rate} | "
                     f"{row['interface_failures']} | {issues} |")
    if not report.get("rows"):
        lines.append("| 尚无已保存的运行 | 0/4 | 0 | 0 | 0 | — | 0 | 正式评测尚未开始 |")
    if report.get("rows"):
        lines.extend(["", "逐题状态（预算阻断不等于内容错误）：", "",
                      "| 配置 | 题目 | 执行结果 | 预算 | 结构 | 语义 |",
                      "|---|---|---|---|---|---|"])
        for row in report["rows"]:
            for item in row["questions"]:
                lines.append(f"| {row['provider_id']} | {item['question_id']} | {item['status']} | "
                             f"{item.get('budget_result', 'unknown')} / {item.get('budget_reason') or '—'} | "
                             f"{item.get('structure_result', 'not_checked')} | {item.get('review_verdict') or '待审阅'} |")
    lines.extend(["", report["boundary"], ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--ledger-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = collect_results(results_root=args.results_root,
                                 ledger_root=args.ledger_root)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8")
            args.output.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
