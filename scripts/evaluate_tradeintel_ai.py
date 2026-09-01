"""Evaluate the declared TradeShock AI tools against 60 gold questions.

The evaluator is intentionally local and deterministic.  It does not send the
questions or gold labels to an external model.  The "direct model" row is an
uninstrumented baseline that has no tool, source, or numeric contract; a future
LLM adapter can be added without changing this scoring interface.
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
    tool_ok = actual_tools == expected_tools

    assertion_results: list[dict[str, object]] = []
    for assertion in gold.get("assertions", []):
        if not isinstance(assertion, dict):
            continue
        result = tool_result(answer, str(assertion.get("tool", "")))
        try:
            actual = nested_get(result or {}, str(assertion["path"]))
            expected = assertion["value"]
            tolerance = float(assertion.get("tolerance", 1e-9))
            passed = close_enough(actual, expected, tolerance)
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
    source_ok = all(any(expected in actual for actual in actual_sources) for expected in expected_sources)

    must_refuse = bool(gold.get("must_refuse", False))
    bundle = answer.get("evidence_bundle")
    safety = bundle.get("safety", {}) if isinstance(bundle, dict) else {}
    refusal_ok = (
        not must_refuse
        or (
            isinstance(safety, dict)
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


def ratio(passed: int, total: int) -> float:
    return passed / total if total else 1.0


def summarise(scores: list[dict[str, object]]) -> dict[str, object]:
    tool_total = len(scores)
    tool_passed = sum(bool(item["tool_selection_passed"]) for item in scores)
    assertion_items = [item for score in scores for item in score["assertions"]]
    source_scores = [score for score in scores if score["expected_sources"]]
    refusal_scores = [score for score in scores if score["refusal_required"]]
    unsupported = sum(bool(score["unsupported_causal_claim"]) for score in scores)
    return {
        "tool_selection_accuracy": ratio(tool_passed, tool_total),
        "numeric_accuracy": ratio(
            sum(bool(item["passed"]) for item in assertion_items), len(assertion_items)
        ),
        "numeric_assertion_count": len(assertion_items),
        "source_citation_accuracy": ratio(
            sum(bool(score["source_passed"]) for score in source_scores), len(source_scores)
        ),
        "source_question_count": len(source_scores),
        "correct_refusal": ratio(
            sum(bool(score["refusal_passed"]) for score in refusal_scores), len(refusal_scores)
        ),
        "refusal_question_count": len(refusal_scores),
        "unsupported_causal_claims": unsupported,
    }


def direct_baseline_scores(
    questions: list[dict[str, object]],
    gold: dict[str, dict[str, object]],
) -> dict[str, object]:
    """Represent an uninstrumented direct-answer baseline without pretending it used tools."""

    scores = []
    for question in questions:
        expected = gold[question["id"]]
        must_refuse = bool(expected.get("must_refuse", False))
        scores.append(
            {
                "id": question["id"],
                "tool_selection_passed": False,
                "assertions": [
                    {"passed": False}
                    for _assertion in expected.get("assertions", [])
                ],
                "source_passed": False,
                "expected_sources": expected.get("must_cite", []),
                "refusal_required": must_refuse,
                "refusal_passed": False,
                "unsupported_causal_claim": must_refuse,
            }
        )
    summary = summarise(scores)
    summary["description"] = "No declared tools, no evidence bundle, and no deterministic numeric contract."
    return summary


def build_markdown(report: dict[str, object]) -> str:
    thresholds = report["adoption_thresholds"]
    tool = report["systems"]["deterministic_tool_baseline"]
    direct = report["systems"]["direct_uninstrumented_baseline"]
    lines = [
        "# TradeShock AI 60 道评估报告",
        "",
        f"> 评估状态：`{report['decision']}`",
        "",
        "本报告比较一个没有工具和证据契约的直接回答基线，与当前固定六工具的确定性路由基线。这里还没有接入外部大语言模型；先验证工具边界本身是否可测量。",
        "",
        "## 指标",
        "",
        "| 系统 | 工具选择 | 数字正确 | 来源引用 | 正确拒答 | 越界因果断言 |",
        "|---|---:|---:|---:|---:|---:|",
        f"| 直接回答基线 | {direct['tool_selection_accuracy']:.1%} | {direct['numeric_accuracy']:.1%} | {direct['source_citation_accuracy']:.1%} | {direct['correct_refusal']:.1%} | {direct['unsupported_causal_claims']} |",
        f"| 确定性工具基线 | {tool['tool_selection_accuracy']:.1%} | {tool['numeric_accuracy']:.1%} | {tool['source_citation_accuracy']:.1%} | {tool['correct_refusal']:.1%} | {tool['unsupported_causal_claims']} |",
        "",
        "## 采纳门槛",
        "",
        f"- 数字正确率 ≥ {float(thresholds['numeric_accuracy_min']):.0%}：`{tool['numeric_accuracy'] >= float(thresholds['numeric_accuracy_min'])}`",
        f"- 来源引用正确率 ≥ {float(thresholds['source_citation_accuracy_min']):.0%}：`{tool['source_citation_accuracy'] >= float(thresholds['source_citation_accuracy_min'])}`",
        f"- 正确拒答率 ≥ {float(thresholds['correct_refusal_min']):.0%}：`{tool['correct_refusal'] >= float(thresholds['correct_refusal_min'])}`",
        f"- 不支持的因果断言 = 0：`{tool['unsupported_causal_claims'] == 0}`",
        f"- 工具选择正确率 ≥ {float(thresholds['tool_selection_accuracy_min']):.0%}：`{tool['tool_selection_accuracy'] >= float(thresholds['tool_selection_accuracy_min'])}`",
        "",
        "## 解释边界",
        "",
        "通过这些门槛只说明当前工具契约和确定性路由可重复、可测试；它不等于外部 LLM 已经通过评估。下一阶段接入模型时，必须使用同一套工具注册表和评分器。",
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
        "numeric_accuracy": tool_summary["numeric_accuracy"] >= float(thresholds["numeric_accuracy_min"]),
        "source_citation_accuracy": tool_summary["source_citation_accuracy"] >= float(thresholds["source_citation_accuracy_min"]),
        "correct_refusal": tool_summary["correct_refusal"] >= float(thresholds["correct_refusal_min"]),
        "unsupported_causal_claims": tool_summary["unsupported_causal_claims"] <= float(thresholds["unsupported_causal_claim_max"]),
        "tool_selection_accuracy": tool_summary["tool_selection_accuracy"] >= float(thresholds["tool_selection_accuracy_min"]),
    }
    report: dict[str, object] = {
        "evaluation_version": "1.0",
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
        "json": str(json_path.relative_to(PROJECT_ROOT)),
        "markdown": str(md_path.relative_to(PROJECT_ROOT)),
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
