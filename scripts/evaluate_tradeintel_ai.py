"""Evaluate the declared TradeShock AI tools against 60 gold questions.

This development regression checks tool fields and permission signals only.
It does not evaluate natural-language answers or run any language model.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.tradeintel_ai.router import answer_question
from src.tradeintel_ai.tools import ToolRegistry


DEFAULT_QUESTIONS = PROJECT_ROOT / "evals/questions.jsonl"
DEFAULT_GOLD = PROJECT_ROOT / "evals/gold_answers.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data/processed/ai"
DEFAULT_CONFIG = PROJECT_ROOT / "config/causal_control_design.json"


def load_questions(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as handle:
        questions = [json.loads(line) for line in handle if line.strip()]
    if len(questions) != 60 or len({item["id"] for item in questions}) != 60:
        raise ValueError("The frozen evaluation set must contain 60 unique questions")
    return questions


def load_gold(path: Path) -> dict[str, dict[str, object]]:
    with path.open(encoding="utf-8") as handle:
        gold = json.load(handle)
    if not isinstance(gold, dict) or len(gold) != 60:
        raise ValueError("The frozen gold-answer set must contain 60 records")
    return gold


def nested_get(value: object, path: str) -> object:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(path)
        current = current[part]
    return current


def tool_result(answer: dict[str, object], name: str) -> dict[str, object] | None:
    return next(
        (item for item in answer.get("tool_results", []) if item.get("tool_name") == name),
        None,
    )


def source_strings(answer: dict[str, object]) -> list[str]:
    values: list[str] = []
    bundle = answer.get("evidence_bundle")
    if isinstance(bundle, dict):
        values.extend(repr(item) for item in bundle.get("sources", []))
    for result in answer.get("tool_results", []):
        if not isinstance(result, dict):
            continue
        evidence = result.get("evidence")
        if isinstance(evidence, dict):
            values.extend(repr(item) for item in evidence.get("sources", []))
    return values


def close_enough(actual: object, expected: object, tolerance: float) -> bool:
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=tolerance)
        except (TypeError, ValueError):
            return False
    return actual == expected


def score_question(
    question: dict[str, object],
    gold: dict[str, object],
    answer: dict[str, object],
) -> dict[str, object]:
    expected_tools = list(gold.get("tools", []))
    actual_tools = list(answer.get("selected_tools", []))
    successful = answer.get("status") == "ok"
    tool_ok = successful and actual_tools == expected_tools

    assertion_results: list[dict[str, object]] = []
    for assertion in gold.get("assertions", []):
        if not isinstance(assertion, dict):
            continue
        result = tool_result(answer, str(assertion.get("tool", "")))
        try:
            actual = nested_get(result or {}, str(assertion["path"]))
            expected = assertion["value"]
            tolerance = float(assertion.get("tolerance", 1e-9))
            passed = successful and result.get("status") == "ok" and close_enough(actual, expected, tolerance)
        except (KeyError, TypeError, ValueError):
            actual = None
            expected = assertion.get("value")
            passed = False
        assertion_results.append(
            {
                "tool": assertion.get("tool"),
                "path": assertion.get("path"),
                "expected": expected,
                "actual": actual,
                "passed": passed,
            }
        )
    numeric_ok = all(bool(item["passed"]) for item in assertion_results)

    expected_sources = [str(item) for item in gold.get("must_cite", [])]
    actual_sources = source_strings(answer)
    source_ok = successful and all(any(expected in actual for actual in actual_sources) for expected in expected_sources)

    must_refuse = bool(gold.get("must_refuse", False))
    bundle = answer.get("evidence_bundle")
    safety = bundle.get("safety", {}) if isinstance(bundle, dict) else {}
    refusal_ok = (
        not must_refuse
        or (
            successful
            and isinstance(safety, dict)
            and safety.get("causal_claim") is False
            and safety.get("causal_language_allowed") is False
            and safety.get("causal_blocked") is True
        )
    )
    unsupported_claim = bool(
        must_refuse
        and isinstance(safety, dict)
        and (safety.get("causal_claim") is True or safety.get("causal_language_allowed") is True)
    )
    return {
        "id": question["id"],
        "category": question["category"],
        "intent": answer.get("intent"),
        "expected_intent": gold.get("intent"),
        "selected_tools": actual_tools,
        "expected_tools": expected_tools,
        "tool_selection_passed": tool_ok,
        "assertions": assertion_results,
        "numeric_passed": numeric_ok,
        "source_passed": source_ok,
        "expected_sources": expected_sources,
        "refusal_required": must_refuse,
        "refusal_passed": refusal_ok,
        "unsupported_causal_claim": unsupported_claim,
    }


def ratio(passed: int, total: int) -> float | None:
    return passed / total if total else None


def summarise(scores: list[dict[str, object]]) -> dict[str, object]:
    tool_total = len(scores)
    tool_passed = sum(bool(item["tool_selection_passed"]) for item in scores)
    assertion_items = [item for score in scores for item in score["assertions"]]
    source_scores = [score for score in scores if score["expected_sources"]]
    refusal_scores = [score for score in scores if score["refusal_required"]]
    unsupported = sum(bool(score["unsupported_causal_claim"]) for score in scores)
    return {
        "tool_selection_accuracy": ratio(tool_passed, tool_total),
        "tool_data_assertion_accuracy": ratio(
            sum(bool(item["passed"]) for item in assertion_items), len(assertion_items)
        ),
        "tool_data_assertion_count": len(assertion_items),
        "source_presence_rate": ratio(
            sum(bool(score["source_passed"]) for score in source_scores), len(source_scores)
        ),
        "source_question_count": len(source_scores),
        "refusal_signal_accuracy": ratio(
            sum(bool(score["refusal_passed"]) for score in refusal_scores), len(refusal_scores)
        ),
        "refusal_question_count": len(refusal_scores),
        "unsafe_permission_signal_count": unsupported,
    }


def direct_baseline_scores(
    questions: list[dict[str, object]],
    gold: dict[str, dict[str, object]],
) -> dict[str, object]:
    """No run means no score, not an assumed failure."""
    return {"status": "not_run", "metrics": None,
            "description": "没有真实模型调用记录；旧版预设失败分数已撤回。"}


def build_markdown(report: dict[str, object]) -> str:
    thresholds = report["adoption_thresholds"]
    tool = report["systems"]["deterministic_tool_baseline"]
    lines = [
        "# TradeShock AI 60 道评估报告",
        "",
        f"> 评估状态：`{report['decision']}`",
        "",
        "本报告仅检查60道已用于开发的工具契约回归题。没有运行真实模型，也没有评价最终自然语言答案。",
        "旧版直接回答对照的0%和13次越界是程序预设，不是实验观测；现已撤回，改为未运行。",
        "",
        "## 指标",
        "",
        "| 系统 | 工具选择 | 工具字段断言 | 来源记录存在 | 拒答状态信号 | 不安全权限信号数 |",
        "|---|---:|---:|---:|---:|---:|",
        "| 真实模型直接回答 | 未运行 | 未测 | 未测 | 未测 | 未测 |",
        f"| 确定性工具回归 | {tool['tool_selection_accuracy']:.1%} | {tool['tool_data_assertion_accuracy']:.1%} | {tool['source_presence_rate']:.1%} | {tool['refusal_signal_accuracy']:.1%} | {tool['unsafe_permission_signal_count']} |",
        "",
        "## 工具层门槛（不代表模型采纳）",
        "",
        f"- 工具字段断言（含数值、日期和状态） ≥ {float(thresholds['numeric_accuracy_min']):.0%}：`{report['adoption']['numeric_accuracy']}`",
        f"- 来源记录存在率 ≥ {float(thresholds['source_citation_accuracy_min']):.0%}：`{report['adoption']['source_citation_accuracy']}`",
        f"- 拒答状态信号符合率 ≥ {float(thresholds['correct_refusal_min']):.0%}：`{report['adoption']['correct_refusal']}`",
        f"- 不安全权限信号 = 0：`{tool['unsafe_permission_signal_count'] == 0}`",
        f"- 工具选择正确率 ≥ {float(thresholds['tool_selection_accuracy_min']):.0%}：`{tool['tool_selection_accuracy'] >= float(thresholds['tool_selection_accuracy_min'])}`",
        "",
        "## 解释边界",
        "",
        "通过只说明开发题上的工具字段符合断言。最终文字的数字、引用支持关系、拒答语义均未测，不能用本评分器直接宣称真实模型通过。",
        f"分母：工具选择{report['question_count']}题；字段断言{tool['tool_data_assertion_count']}项；来源{tool['source_question_count']}题；需拒因果{tool['refusal_question_count']}题。",
        "",
        "详细逐题结果见同目录的 `ai_evaluation_report.json`；问题和 gold 标签分别保存在 `evals/questions.jsonl` 与 `evals/gold_answers.json`，路由过程不会读取 gold 标签。",
    ]
    return "\n".join(lines) + "\n"


def evaluate(
    *,
    questions_path: Path = DEFAULT_QUESTIONS,
    gold_path: Path = DEFAULT_GOLD,
    config_path: Path = DEFAULT_CONFIG,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, object]:
    questions = load_questions(questions_path)
    gold = load_gold(gold_path)
    if set(item["id"] for item in questions) != set(gold):
        raise ValueError("Questions and gold labels have different IDs")
    registry = ToolRegistry()
    scores = [
        score_question(question, gold[question["id"]], answer_question(question["question"], registry=registry))
        for question in questions
    ]
    tool_summary = summarise(scores)
    with config_path.open(encoding="utf-8") as handle:
        config = json.load(handle)
    thresholds = config["ai_application"]["evaluation"]["adoption_thresholds"]
    adoption = {
        "numeric_accuracy": tool_summary["tool_data_assertion_accuracy"] is not None and tool_summary["tool_data_assertion_accuracy"] >= float(thresholds["numeric_accuracy_min"]),
        "source_citation_accuracy": tool_summary["source_presence_rate"] is not None and tool_summary["source_presence_rate"] >= float(thresholds["source_citation_accuracy_min"]),
        "correct_refusal": tool_summary["refusal_signal_accuracy"] is not None and tool_summary["refusal_signal_accuracy"] >= float(thresholds["correct_refusal_min"]),
        "unsupported_causal_claims": tool_summary["unsafe_permission_signal_count"] <= float(thresholds["unsupported_causal_claim_max"]),
        "tool_selection_accuracy": tool_summary["tool_selection_accuracy"] >= float(thresholds["tool_selection_accuracy_min"]),
    }
    report: dict[str, object] = {
        "evaluation_version": "2.0",
        "evaluation_scope": "development_tool_contracts_only",
        "final_answer_evaluation": {"status": "not_run", "metrics": None},
        "model_adopted": False,
        "question_count": len(questions),
        "categories": {
            category: sum(item["category"] == category for item in questions)
            for category in sorted({str(item["category"]) for item in questions})
        },
        "adoption_thresholds": thresholds,
        "systems": {
            "direct_uninstrumented_baseline": direct_baseline_scores(questions, gold),
            "deterministic_tool_baseline": tool_summary,
        },
        "adoption": adoption,
        "decision": "tool_contracts_passed_ready_for_llm_adapter" if all(adoption.values()) else "blocked_before_llm_adapter",
        "question_file": str(questions_path.relative_to(PROJECT_ROOT)),
        "gold_file": str(gold_path.relative_to(PROJECT_ROOT)),
        "scores": scores,
        "leakage_controls": {
            "gold_labels_sent_to_router": False,
            "post_policy_activity_used_for_matching": False,
            "arbitrary_sql_allowed": False,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "ai_evaluation_report.json"
    md_path = output_dir / "ai_evaluation_report.md"
    report["outputs"] = {
        "json": str(json_path.relative_to(PROJECT_ROOT)) if json_path.is_relative_to(PROJECT_ROOT) else str(json_path),
        "markdown": str(md_path.relative_to(PROJECT_ROOT)) if md_path.is_relative_to(PROJECT_ROOT) else str(md_path),
    }
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(build_markdown(report), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    report = evaluate(
        questions_path=args.questions,
        gold_path=args.gold,
        config_path=args.config,
        output_dir=args.output_dir,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["decision"] == "tool_contracts_passed_ready_for_llm_adapter" else 1


if __name__ == "__main__":
    raise SystemExit(main())
