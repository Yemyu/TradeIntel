"""Provider-neutral model/tool loop with a deterministic causal safety guard.

No vendor SDK is imported here.  A real model adapter only needs to implement
``ChatModel.complete`` and use the schemas from :class:`ToolRegistry`.  The
tests use :class:`MockModel`, so the contract can be verified without an API
key or network access.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol
from collections.abc import Mapping, Sequence

from .tools import ToolRegistry


CAUSAL_QUESTION_TERMS = (
    "因果",
    "导致",
    "造成",
    "影响",
    "effect",
    "impact",
    "causal",
    "caused",
)
CAUSAL_ASSERTION_TERMS = (
    "关税导致",
    "关税造成",
    "政策导致",
    "政策造成",
    "tariff caused",
    "caused by tariff",
    "causal effect is",
    "the effect of the tariff is",
)

# Only the host may aggregate evidence from its own execution records.
MODEL_TOOL_NAMES = frozenset({
    "get_policy_event", "get_trade_series", "get_descriptive_change",
    "get_data_quality_status", "get_causal_readiness",
})


@dataclass(frozen=True)
class ModelToolCall:
    """The provider-neutral shape of one model-requested tool call."""

    call_id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class ModelResponse:
    """A model turn containing text, tool calls, or both."""

    text: str = ""
    tool_calls: tuple[ModelToolCall, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


class ChatModel(Protocol):
    """Minimal interface required by :class:`ToolCallingAgent`."""

    def complete(
        self,
        *,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]],
    ) -> ModelResponse:
        ...


def _normalise_response(value: ModelResponse | Mapping[str, object]) -> ModelResponse:
    if isinstance(value, ModelResponse):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("model.complete must return ModelResponse or a mapping")
    calls: list[ModelToolCall] = []
    raw_calls = value.get("tool_calls", [])
    if not isinstance(raw_calls, Sequence) or isinstance(raw_calls, (str, bytes)):
        raise TypeError("model tool_calls must be a list")
    for index, raw_call in enumerate(raw_calls):
        if not isinstance(raw_call, Mapping):
            raise TypeError("each model tool call must be an object")
        arguments = raw_call.get("arguments", {})
        if not isinstance(arguments, Mapping):
            raise TypeError("tool call arguments must be an object")
        calls.append(
            ModelToolCall(
                call_id=str(raw_call.get("call_id", f"call_{index + 1}")),
                name=str(raw_call.get("name", "")),
                arguments=dict(arguments),
            )
        )
    metadata = value.get("metadata", {})
    return ModelResponse(
        text=str(value.get("text", "")),
        tool_calls=tuple(calls),
        metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
    )


def _summarise_model_run(turns: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Keep provider metadata without exposing request headers or secrets."""

    names = sorted({str(turn["model"]) for turn in turns if turn.get("model")})
    usage_totals: dict[str, int] = {}
    for turn in turns:
        usage = turn.get("usage", {})
        if not isinstance(usage, Mapping):
            continue
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens"):
            value = usage.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                usage_totals[key] = usage_totals.get(key, 0) + int(value)
    return {
        "turn_count": len(turns),
        "model_names": names,
        "usage_totals": usage_totals,
        "turns": [dict(turn) for turn in turns],
    }


def _looks_causal(question: str) -> bool:
    lowered = question.lower()
    return any(term in question or term in lowered for term in CAUSAL_QUESTION_TERMS)


def _readiness_is_blocked(results: Sequence[dict[str, object]]) -> tuple[bool, str]:
    for item in results:
        if item.get("tool_name") != "get_causal_readiness" or item.get("status") != "ok":
            continue
        data = item.get("data", {})
        if isinstance(data, Mapping):
            status = str(data.get("status", "unknown"))
            return data.get("causal_allowed") is not True, status
    return True, "unknown"


def enforce_causal_safety(
    question: str,
    draft: str,
    tool_results: Sequence[dict[str, object]],
) -> tuple[str, bool]:
    """Conservative lexical screen, NOT a semantic correctness verifier.

    A disclaimer elsewhere in the draft cannot waive a detected assertion.
    Unflagged drafts still require final-answer review.
    """

    blocked, status = _readiness_is_blocked(tool_results)
    lowered_draft = draft.lower()
    assertion_present = any(term in draft or term in lowered_draft for term in CAUSAL_ASSERTION_TERMS)
    if blocked and assertion_present:
        return (
            f"安全后卫已拦截越界因果表述：当前因果状态为 {status}，"
            "只能报告描述性变化，不能说关税导致了变化。",
            True,
        )
    return draft, False


class ToolCallingAgent:
    """Run a bounded model/tool loop and always attach the safety signal."""

    def __init__(self, model: ChatModel, registry: ToolRegistry | None = None, *, max_rounds: int = 4, max_tool_calls: int = 16) -> None:
        if max_rounds < 1 or max_tool_calls < 1:
            raise ValueError("max_rounds and max_tool_calls must be positive")
        self.model = model
        self.registry = registry or ToolRegistry()
        self.max_rounds = max_rounds
        self.max_tool_calls = max_tool_calls

    def answer(self, question: str) -> dict[str, object]:
        if not isinstance(question, str) or not question.strip():
            return {"status": "error", "error": "question 不能为空", "causal_claim": False}
        messages: list[dict[str, object]] = [{"role": "user", "content": question}]
        tool_results: list[dict[str, object]] = []
        model_selected_tools: list[str] = []
        seen_call_ids: set[str] = set()
        model_turns: list[dict[str, object]] = []
        draft = ""
        rounds = 0
        for rounds in range(1, self.max_rounds + 1):
            response = _normalise_response(
                self.model.complete(messages=messages, tools=[
                    schema for schema in self.registry.schemas()
                    if schema["name"] in MODEL_TOOL_NAMES
                ])
            )
            model_turns.append(dict(response.metadata))
            if not response.tool_calls:
                draft = response.text.strip()
                break
            if len(model_selected_tools) + len(response.tool_calls) > self.max_tool_calls:
                return {"status": "error", "error": "模型请求超过工具调用次数上限",
                        "tool_results": tool_results, "causal_claim": False}
            call_ids = [call.call_id for call in response.tool_calls]
            if any(not call_id or call_id in seen_call_ids for call_id in call_ids) or len(set(call_ids)) != len(call_ids):
                return {"status": "error", "error": "工具调用ID为空或重复",
                        "tool_results": tool_results, "causal_claim": False}
            seen_call_ids.update(call_ids)
            messages.append(
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "call_id": call.call_id,
                            "name": call.name,
                            "arguments": call.arguments,
                        }
                        for call in response.tool_calls
                    ],
                }
            )
            for call in response.tool_calls:
                model_selected_tools.append(call.name)
                if call.name not in MODEL_TOOL_NAMES:
                    result = {"tool_name": call.name, "status": "error",
                              "error": "模型无权调用该工具；证据包只能由程序生成"}
                else:
                    result = self.registry.call(call.name, call.arguments)
                tool_results.append(result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.call_id,
                        "name": call.name,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
        else:  # pragma: no cover - the loop exits through a bounded failure below
            rounds = self.max_rounds

        if not draft:
            return {
                "status": "error",
                "error": "模型在最大轮数内没有生成最终文本",
                "rounds": rounds,
                "tool_results": tool_results,
                "model_run": _summarise_model_run(model_turns),
                "causal_claim": False,
            }

        successful_results = [item for item in tool_results
                              if item.get("status") == "ok" and item.get("tool_name") in MODEL_TOOL_NAMES]
        if not successful_results:
            return {
                "status": "error",
                "error": "模型没有调用任何已登记工具并取得成功结果，不能生成无证据回答",
                "rounds": rounds,
                "tool_results": tool_results,
                "model_run": _summarise_model_run(model_turns),
                "causal_claim": False,
            }
        # Check authoritative readiness on every answer, regardless of the
        # user's wording. Do not count this host call as a model selection.
        readiness = self.registry.call("get_causal_readiness", {})
        readiness_data = readiness.get("data")
        if (
            readiness.get("status") != "ok"
            or not isinstance(readiness_data, Mapping)
            or not isinstance(readiness_data.get("causal_allowed"), bool)
            or readiness_data.get("status") in (None, "", "unknown")
        ):
            return {"status": "error", "error": "无法核验因果状态，停止输出模型答案",
                    "tool_results": tool_results, "model_run": _summarise_model_run(model_turns),
                    "causal_claim": False}
        successful_results = [item for item in successful_results if item["tool_name"] != "get_causal_readiness"] + [readiness]
        safe_text, guard_triggered = enforce_causal_safety(question, draft, successful_results)
        bundle = self.registry.call(
            "build_evidence_bundle",
            {"question": question, "tool_results": successful_results},
        )
        if bundle.get("status") == "error":
            return {"status": "error", "error": "证据打包失败",
                    "model_run": _summarise_model_run(model_turns), "causal_claim": False}
        return {
            "status": "ok" if guard_triggered else "needs_review",
            "answer_kind": "fixed_safety_refusal" if guard_triggered else "unverified_model_draft",
            "final_answer_verified": guard_triggered,
            "task_success_verified": False,
            "review_required": not guard_triggered,
            "response": safe_text,
            "original_model_response": draft if guard_triggered else None,
            "safety_guard_triggered": guard_triggered,
            "rounds": rounds,
            "tool_results": successful_results,
            "model_tool_results": tool_results,
            "model_selected_tools": model_selected_tools,
            "host_selected_tools": ["get_causal_readiness", "build_evidence_bundle"],
            "model_run": _summarise_model_run(model_turns),
            "evidence_bundle": bundle,
            "causal_claim": False if guard_triggered else None,
        }


class MockModel:
    """A tiny offline model used to test the protocol and safety guard."""

    def complete(
        self,
        *,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]],
    ) -> ModelResponse:
        question = str(messages[0].get("content", "")) if messages else ""
        lowered = question.lower()
        if not any(message.get("role") == "tool" for message in messages):
            if _looks_causal(question):
                return ModelResponse(
                    tool_calls=(
                        ModelToolCall("call_change", "get_descriptive_change", {}),
                        ModelToolCall("call_readiness", "get_causal_readiness", {}),
                    )
                )
            if "质量" in question or "quality" in lowered:
                return ModelResponse(
                    tool_calls=(ModelToolCall("call_quality", "get_data_quality_status", {}),)
                )
            if (
                "政策" in question
                or "关税" in question
                or "policy" in lowered
                or "section 301" in lowered
                or "list 1" in lowered
            ):
                return ModelResponse(
                    tool_calls=(ModelToolCall("call_policy", "get_policy_event", {}),)
                )
            return ModelResponse(
                tool_calls=(ModelToolCall("call_change", "get_descriptive_change", {}),)
            )
        if _looks_causal(question):
            # Deliberately unsafe text: the safety guard must intercept it.
            return ModelResponse(text="关税导致中国进口下降了。")
        return ModelResponse(text="这是基于已登记工具和来源的回答。")
