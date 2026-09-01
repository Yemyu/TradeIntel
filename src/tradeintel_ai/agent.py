"""Provider-neutral model/tool loop with a deterministic causal safety guard.

No vendor SDK is imported here.  A real model adapter only needs to implement
``ChatModel.complete`` and use the schemas from :class:`ToolRegistry`.  The
tests use :class:`MockModel`, so the contract can be verified without an API
key or network access.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
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
REFUSAL_TERMS = (
    "不能",
    "无法",
    "不足",
    "不支持",
    "不能证明",
    "cannot",
    "can't",
    "not causal",
    "not prove",
)


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
    return ModelResponse(text=str(value.get("text", "")), tool_calls=tuple(calls))


def _looks_causal(question: str) -> bool:
    lowered = question.lower()
    return any(term in question or term in lowered for term in CAUSAL_QUESTION_TERMS)


def _has_causal_readiness(results: Sequence[dict[str, object]]) -> bool:
    return any(item.get("tool_name") == "get_causal_readiness" for item in results)


def _readiness_is_blocked(results: Sequence[dict[str, object]]) -> tuple[bool, str]:
    for item in results:
        if item.get("tool_name") != "get_causal_readiness":
            continue
        data = item.get("data", {})
        if isinstance(data, Mapping):
            status = str(data.get("status", "unknown"))
            return (not bool(data.get("causal_allowed", False))), status
    return False, "unknown"


def enforce_causal_safety(
    question: str,
    draft: str,
    tool_results: Sequence[dict[str, object]],
) -> tuple[str, bool]:
    """Replace an unsupported causal assertion when the readiness gate is blocked."""

    blocked, status = _readiness_is_blocked(tool_results)
    lowered_draft = draft.lower()
    assertion_present = any(term in draft or term in lowered_draft for term in CAUSAL_ASSERTION_TERMS)
    refusal_present = any(term in draft or term in lowered_draft for term in REFUSAL_TERMS)
    if blocked and _looks_causal(question) and assertion_present and not refusal_present:
        return (
            f"安全后卫已拦截越界因果表述：当前因果状态为 {status}，"
            "只能报告描述性变化，不能说关税导致了变化。",
            True,
        )
    return draft, False


class ToolCallingAgent:
    """Run a bounded model/tool loop and always attach the safety signal."""

    def __init__(self, model: ChatModel, registry: ToolRegistry | None = None, *, max_rounds: int = 4) -> None:
        if max_rounds < 1:
            raise ValueError("max_rounds must be positive")
        self.model = model
        self.registry = registry or ToolRegistry()
        self.max_rounds = max_rounds

    def answer(self, question: str) -> dict[str, object]:
        if not isinstance(question, str) or not question.strip():
            return {"status": "error", "error": "question 不能为空", "causal_claim": False}
        messages: list[dict[str, object]] = [{"role": "user", "content": question}]
        tool_results: list[dict[str, object]] = []
        draft = ""
        rounds = 0
        for rounds in range(1, self.max_rounds + 1):
            response = _normalise_response(
                self.model.complete(messages=messages, tools=self.registry.schemas())
            )
            if not response.tool_calls:
                draft = response.text.strip()
                break
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
                "causal_claim": False,
            }

        # If a causal question skipped the readiness tool, perform a read-only
        # preflight before allowing any final wording to leave the agent.
        if _looks_causal(question) and not _has_causal_readiness(tool_results):
            tool_results.append(self.registry.call("get_causal_readiness", {}))
        if not tool_results:
            return {
                "status": "error",
                "error": "模型没有调用任何已登记工具，不能生成无证据回答",
                "rounds": rounds,
                "causal_claim": False,
            }
        safe_text, guard_triggered = enforce_causal_safety(question, draft, tool_results)
        bundle = self.registry.call(
            "build_evidence_bundle",
            {"question": question, "tool_results": tool_results},
        )
        return {
            "status": "ok",
            "response": safe_text,
            "original_model_response": draft if guard_triggered else None,
            "safety_guard_triggered": guard_triggered,
            "rounds": rounds,
            "tool_results": tool_results,
            "evidence_bundle": bundle,
            "causal_claim": False,
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
