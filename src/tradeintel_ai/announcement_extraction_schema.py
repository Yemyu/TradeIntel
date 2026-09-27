"""Versioned transport contract for policy-announcement extraction.

This module is deliberately separate from the existing pilot runner.  A
provider tool call only gives us a predictable *transport shape*; it does not
prove that a value is true or that a quotation supports it.  Callers must
still pass the normalised answer through :func:`adapt_suggestion` and keep the
human review gate.

The transport representation avoids JSON ``null`` because the first strict
provider profile (DeepSeek beta) does not promise a nullable type.  A value is
therefore carried as ``{"present": true, "data": ...}``; an unknown or
conflicting value uses ``{"present": false, "data": ""}``.  Normalisation is
explicit and lossless for the existing review contract.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .announcement_extraction_pilot import MAX_REQUEST_BYTES, prepare_request
from .policy_candidates import REQUIRED_FIELDS

SCHEMA_VERSION = "policy-extraction-schema-v1"
FUNCTION_NAME = "submit_policy_fields"
SCHEMA_BODY_LIMIT = 28_000
SCHEMA_INPUT_TOKEN_LIMIT = 16_000
STRICT_ENDPOINT = "https://api.deepseek.com/beta/chat/completions"
COMPATIBLE_ENDPOINT = "https://api.deepseek.com/chat/completions"
STRUCTURED_TRANSPORT_PROMPT = """你只能调用 submit_policy_fields 一次，不能输出普通文本。
参数必须包含 doc_version 和 13 个 fields。每个 field 必须包含 field、status、value、reason、evidence。
value 必须是 {present:boolean,data:string}：known 时 present=true，data 是该值的 JSON 字符串；unknown 或 conflict 时 present=false、data 为空字符串。
reason 始终是字符串；known 没有理由时填空字符串。evidence 始终是对象数组，每项为 quote 和 occurrence；唯一出现的引文 occurrence 填0，重复引文填从1开始的序号。
只引用给出的公告原文，不补全税号、税率或政策含义；字段语义和引文仍会由程序复核。"""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def schema_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _transport_value_schema() -> dict[str, Any]:
    # DeepSeek strict mode only accepts a documented set of JSON Schema types;
    # an open ``{}`` schema is rejected by some providers.  Encode the
    # heterogeneous value as JSON text and decode it locally before the normal
    # semantic adapter runs.
    return {
        "type": "object",
        "properties": {"present": {"type": "boolean"}, "data": {"type": "string"}},
        "required": ["present", "data"],
        "additionalProperties": False,
    }


def function_definition(*, strict: bool = True) -> dict[str, Any]:
    """Return a stable OpenAI-compatible function-tool definition.

    The schema intentionally checks shape, not policy meaning.  DeepSeek's
    strict beta mode requires every object property to be listed in
    ``required`` and rejects additional properties; this definition follows
    that rule.  Providers that do not support ``strict`` may omit the flag and
    still use the same schema plus local validation.
    """
    evidence = {
        "type": "object",
        "properties": {"quote": {"type": "string"}, "occurrence": {"type": "integer"}},
        "required": ["quote", "occurrence"],
        "additionalProperties": False,
    }
    item = {
        "type": "object",
        "properties": {
            "field": {"type": "string", "enum": list(REQUIRED_FIELDS)},
            "status": {"type": "string", "enum": ["known", "unknown", "conflict"]},
            "value": _transport_value_schema(),
            # Empty string is the transport sentinel for the legacy null
            # reason used by known fields.
            "reason": {"type": "string"},
            "evidence": {"type": "array", "items": evidence},
        },
        "required": ["field", "status", "value", "reason", "evidence"],
        "additionalProperties": False,
    }
    function: dict[str, Any] = {
        "name": FUNCTION_NAME,
        "description": "Return review-only policy field suggestions with source quotes.",
        "parameters": {
            "type": "object",
            "properties": {
                "doc_version": {"type": "string"},
                "fields": {"type": "array", "items": item},
            },
            "required": ["doc_version", "fields"],
            "additionalProperties": False,
        },
    }
    if strict:
        function["strict"] = True
    return {"type": "function", "function": function}


def tool_choice() -> dict[str, Any]:
    """Force the single extraction function when the provider supports it."""
    return {"type": "function", "function": {"name": FUNCTION_NAME}}


def normalise_transport_answer(answer: Mapping[str, Any]) -> dict[str, Any]:
    """Convert the no-null transport shape into the existing pilot contract."""
    if not isinstance(answer, Mapping) or set(answer) != {"doc_version", "fields"}:
        raise ValueError("tool arguments must contain only doc_version and fields")
    fields = answer["fields"]
    if not isinstance(fields, list):
        raise ValueError("tool fields must be an array")
    normalised: list[dict[str, Any]] = []
    for item in fields:
        if not isinstance(item, Mapping) or set(item) != {"field", "status", "value", "reason", "evidence"}:
            raise ValueError("tool field has an invalid shape")
        value = item["value"]
        if not isinstance(value, Mapping) or set(value) != {"present", "data"} \
                or type(value["present"]) is not bool:
            raise ValueError("tool field value must be a present/data envelope")
        status = item["status"]
        if status in ("unknown", "conflict") and value["present"]:
            raise ValueError("unknown/conflict field cannot claim a value")
        if status == "known" and not value["present"]:
            raise ValueError("known field must carry a value")
        if not isinstance(value["data"], str):
            raise ValueError("tool field data must be JSON text")
        if not value["present"] and value["data"] != "":
            raise ValueError("unknown/conflict field data must be empty")
        decoded_value = None
        if value["present"]:
            try:
                decoded_value = json.loads(value["data"], object_pairs_hook=_RejectDuplicateKeys)
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError("known field data is not valid JSON text") from exc
        evidence = item["evidence"]
        if not isinstance(evidence, list):
            raise ValueError("tool field evidence must be an array")
        converted_evidence = []
        for cite in evidence:
            if not isinstance(cite, Mapping) or set(cite) != {"quote", "occurrence"}:
                raise ValueError("tool evidence must contain quote and occurrence")
            occurrence = cite["occurrence"]
            if type(occurrence) is not int or occurrence < 0:
                raise ValueError("tool evidence occurrence must be a non-negative integer")
            converted_evidence.append({"quote": cite["quote"],
                                       **({} if occurrence == 0 else {"occurrence": occurrence})})
        reason = item["reason"]
        if not isinstance(reason, str):
            raise ValueError("tool reason must be text")
        normalised.append({
            "field": item["field"],
            "status": status,
            "value": decoded_value,
            "reason": reason if reason else None,
            "evidence": converted_evidence,
        })
    return {"doc_version": answer["doc_version"], "fields": normalised}


class _RejectDuplicateKeys(dict):
    """JSON object hook that rejects duplicate keys instead of last-wins."""

    def __init__(self, pairs: list[tuple[str, Any]]) -> None:
        keys = [key for key, _ in pairs]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate JSON key")
        super().__init__(pairs)


def _loads_object(value: Any, *, label: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a JSON object")
    try:
        parsed = json.loads(value, object_pairs_hook=_RejectDuplicateKeys,
                            parse_constant=lambda token: (_ for _ in ()).throw(
                                ValueError(f"invalid JSON constant: {token}")))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{label} must be valid JSON without duplicate keys") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be a JSON object")
    return parsed


def parse_tool_response(raw: bytes | str, *, function_name: str = FUNCTION_NAME) -> dict[str, Any]:
    """Parse one provider response, requiring exactly one expected tool call.

    The raw bytes must be persisted by the caller before this function is
    invoked.  No retry or provider-specific recovery happens here.
    """
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("provider response is not UTF-8") from exc
    payload = _loads_object(raw, label="provider response")
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], Mapping):
        raise ValueError("provider response must contain exactly one choice")
    choice = choices[0]
    if choice.get("finish_reason") != "tool_calls":
        raise ValueError("provider response did not finish with tool_calls")
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise ValueError("provider response is missing message")
    if isinstance(message.get("content"), str) and message["content"].strip():
        raise ValueError("provider response mixed text with tool call")
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or len(calls) != 1 or not isinstance(calls[0], Mapping):
        raise ValueError("provider response must contain exactly one tool call")
    call = calls[0]
    if call.get("type") != "function" or not isinstance(call.get("function"), Mapping):
        raise ValueError("provider tool call is not a function")
    function = call["function"]
    if function.get("name") != function_name:
        raise ValueError("provider called an unexpected function")
    arguments = _loads_object(function.get("arguments"), label="tool arguments")
    return {
        "schema_version": SCHEMA_VERSION,
        "function_name": function_name,
        "arguments": arguments,
        "model": payload.get("model"),
        "usage": dict(payload.get("usage", {})) if isinstance(payload.get("usage"), Mapping) else {},
        "finish_reason": choice.get("finish_reason"),
    }


def prepare_schema_request(store: dict[str, Any], doc_version: str, *, model: str,
                           strict: bool = True) -> dict[str, Any]:
    """Build the isolated request and enforce its independent size gates."""
    if not isinstance(model, str) or not model.strip():
        raise ValueError("model must be a non-empty string")
    legacy = prepare_request(store, doc_version)
    messages = [dict(legacy["messages"][0]), dict(legacy["messages"][1])]
    messages[0]["content"] = STRUCTURED_TRANSPORT_PROMPT
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": [function_definition(strict=strict)],
        "tool_choice": tool_choice(),
        "parallel_tool_calls": False,
        "thinking": {"type": "disabled"},
        "max_tokens": 8192,
    }
    encoded = json.dumps(body, ensure_ascii=False, allow_nan=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    if len(encoded) > SCHEMA_BODY_LIMIT:
        raise ValueError(f"structured provider request {len(encoded)} bytes exceeds {SCHEMA_BODY_LIMIT}")
    # Keep the original input estimate as a separate gate; schema growth must
    # never be allowed to justify truncating the legal notice.
    if legacy["request_bytes"] > MAX_REQUEST_BYTES:
        raise ValueError("saved notice already exceeds the original input gate")
    from scripts.prepare_brief_v3_offline import estimate_input_tokens
    input_estimate = estimate_input_tokens(legacy["messages"])
    if input_estimate["tokens"] > SCHEMA_INPUT_TOKEN_LIMIT:
        raise ValueError(
            f"structured provider input estimate {input_estimate['tokens']} tokens "
            f"exceeds {SCHEMA_INPUT_TOKEN_LIMIT}"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "doc_version": doc_version,
        "model": model,
        "strict": strict,
        "endpoint_profile": "deepseek-beta-chat-tools-v1" if strict else "openai-compatible-chat-tools-v1",
        "endpoint": STRICT_ENDPOINT if strict else COMPATIBLE_ENDPOINT,
        "body": body,
        "body_bytes": len(encoded),
        "body_sha256": hashlib.sha256(encoded).hexdigest(),
        "input_request_sha256": legacy["request_sha256"],
        "input_request_bytes": legacy["request_bytes"],
        "input_token_estimate": input_estimate,
        "input_token_limit": SCHEMA_INPUT_TOKEN_LIMIT,
        "body_limit": SCHEMA_BODY_LIMIT,
    }


__all__ = [
    "FUNCTION_NAME", "SCHEMA_VERSION", "SCHEMA_BODY_LIMIT",
    "SCHEMA_INPUT_TOKEN_LIMIT", "STRICT_ENDPOINT", "COMPATIBLE_ENDPOINT",
    "function_definition", "tool_choice",
    "schema_hash", "normalise_transport_answer", "parse_tool_response",
    "prepare_schema_request",
]
