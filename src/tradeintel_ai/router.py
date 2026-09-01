"""A deliberately small baseline router for the evidence tools.

This is not presented as a production language model.  It is a deterministic
baseline that makes the tool contracts runnable and measurable before an LLM
is connected.  The eventual model adapter must use the same registry and
cannot bypass the causal refusal signal.
"""

from __future__ import annotations

from collections.abc import Sequence

from .tools import (
    DEFAULT_POLICY_ID,
    ToolRegistry,
)


CAUSAL_TERMS = (
    "因果",
    "导致",
    "造成",
    "引起",
    "影响",
    "由政策",
    "政策效果",
    "关税效果",
    "causal",
    "cause",
    "caused",
    "effect",
    "impact",
)
CHANGE_TERMS = (
    "变化",
    "下降",
    "上升",
    "同比",
    "进口",
    "share",
    "change",
    "decline",
    "increase",
)
QUALITY_TERMS = (
    "质量",
    "覆盖率",
    "数据是否可靠",
    "数据覆盖",
    "quality",
    "coverage",
    "pass_with_review",
)
POLICY_TERMS = ("政策", "关税", "section 301", "list 1", "tariff", "policy")


def classify_question(question: str) -> str:
    """Classify a question into one of the small, auditable intents."""

    if not isinstance(question, str) or not question.strip():
        return "invalid"
    lowered = question.strip().lower()
    if any(term in lowered for term in QUALITY_TERMS):
        return "data_quality"
    if any(term in lowered for term in CAUSAL_TERMS):
        return "causal_readiness"
    if any(term in lowered for term in CHANGE_TERMS):
        return "descriptive_change"
    if any(term in lowered for term in POLICY_TERMS):
        return "policy_event"
    return "needs_clarification"


def _first_result(results: Sequence[dict[str, object]], tool_name: str) -> dict[str, object] | None:
    return next((result for result in results if result.get("tool_name") == tool_name), None)


def infer_comparison_id(question: str, default: str = "immediate_post_same_months") -> str:
    """Map a few declared natural-language aliases to registered comparisons."""

    lowered = question.strip().lower()
    if "安慰剂" in question or "placebo" in lowered or "2017年8" in question or "2017 年 8" in question:
        return "pre_policy_placebo_same_months"
    if "持续性" in question or "monitoring" in lowered or "2019年8" in question or "2019 年 8" in question:
        return "persistence_monitoring_same_months"
    if "最近政策前" in question or "recent pre" in lowered or "2018年1" in question or "2018 年 1" in question:
        return "recent_clean_pre_same_months"
    return default


def _format_percent(value: object) -> str:
    if value is None:
        return "未知"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "未知"


def _make_response(intent: str, results: Sequence[dict[str, object]]) -> str:
    if intent == "causal_readiness":
        readiness = _first_result(results, "get_causal_readiness")
        data = readiness.get("data", {}) if readiness else {}
        status = data.get("status", "unknown") if isinstance(data, dict) else "unknown"
        descriptive = _first_result(results, "get_descriptive_change")
        descriptive_data = descriptive.get("data", {}) if descriptive else {}
        change = descriptive_data.get("target_change_pct") if isinstance(descriptive_data, dict) else None
        return (
            f"当前因果状态为 {status}。"
            f"已登记描述性比较中，中国相关商品进口变化为 {_format_percent(change)}；"
            "这只能说明观察到的变化，不能据此说关税导致了变化。"
        )
    if intent == "descriptive_change":
        descriptive = _first_result(results, "get_descriptive_change")
        data = descriptive.get("data", {}) if descriptive else {}
        if not isinstance(data, dict):
            return "描述性工具没有返回可读结果。"
        return (
            f"已登记比较 {data.get('comparison_id', '')} 显示："
            f"中国相关商品进口变化 {_format_percent(data.get('target_change_pct'))}，"
            f"其他原产地变化 {_format_percent(data.get('other_origins_change_pct'))}。"
            "这是描述性证据，不是关税因果估计。"
        )
    if intent == "policy_event":
        event = _first_result(results, "get_policy_event")
        data = event.get("data", {}) if event else {}
        if not isinstance(data, dict):
            return "政策工具没有返回可读结果。"
        return (
            f"登记政策为 {data.get('policy_name', '')}，生效日 {data.get('effective_date', '')}，"
            f"附加税率 {data.get('additional_rate_percent', '未知')}%。这是政策事实，不是效果估计。"
        )
    if intent == "data_quality":
        quality = _first_result(results, "get_data_quality_status")
        data = quality.get("data", {}) if quality else {}
        if not isinstance(data, dict):
            return "质量工具没有返回可读结果。"
        summary = data.get("summary", {})
        if not isinstance(summary, dict):
            summary = {}
        return (
            f"数据质量总状态为 {data.get('overall_status', 'unknown')}；"
            f"失败规则 {summary.get('failed_rule_count', '未知')} 条，"
            f"需要复核 {summary.get('review_rule_count', '未知')} 条。"
        )
    if intent == "needs_clarification":
        return "我可以回答已登记的政策事实、描述性变化、数据质量和因果可行性问题；请指定其中一个。"
    return "问题格式无效，请提供自然语言问题。"


def answer_question(
    question: str,
    *,
    registry: ToolRegistry | None = None,
    comparison_id: str = "immediate_post_same_months",
) -> dict[str, object]:
    """Run the deterministic baseline and attach an evidence bundle."""

    registry = registry or ToolRegistry()
    intent = classify_question(question)
    selected_comparison_id = (
        infer_comparison_id(question, comparison_id)
        if comparison_id == "immediate_post_same_months"
        else comparison_id
    )
    if intent in {"invalid", "needs_clarification"}:
        return {
            "status": "needs_clarification" if intent == "needs_clarification" else "error",
            "router": "deterministic_baseline_v1",
            "question": question,
            "intent": intent,
            "selected_tools": [],
            "tool_results": [],
            "response": _make_response(intent, []),
        }

    calls: list[tuple[str, dict[str, object]]] = []
    if intent == "policy_event":
        calls.append(("get_policy_event", {"policy_id": DEFAULT_POLICY_ID}))
    elif intent == "descriptive_change":
        calls.append(
            (
                "get_descriptive_change",
                {"policy_id": DEFAULT_POLICY_ID, "comparison_id": selected_comparison_id},
            )
        )
    elif intent == "data_quality":
        calls.append(("get_data_quality_status", {}))
    elif intent == "causal_readiness":
        calls.extend(
            [
                (
                    "get_descriptive_change",
                    {"policy_id": DEFAULT_POLICY_ID, "comparison_id": selected_comparison_id},
                ),
                ("get_causal_readiness", {}),
            ]
        )
    results = [registry.call(name, arguments) for name, arguments in calls]
    bundle = registry.call(
        "build_evidence_bundle",
        {"question": question, "tool_results": results},
    )
    return {
        "status": "ok",
        "router": "deterministic_baseline_v1",
        "question": question,
        "intent": intent,
        "selected_tools": [name for name, _arguments in calls],
        "tool_results": results,
        "evidence_bundle": bundle,
        "response": _make_response(intent, results),
    }
