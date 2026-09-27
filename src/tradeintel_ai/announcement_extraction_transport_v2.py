"""Versioned compatibility contract for the second structured probe.

The first structured transport asked the model to put every known value into
JSON text.  The provider accepted the tool call, but naturally emitted scalar
text for title/date/origin fields while using JSON text for arrays and objects.
This module makes that distinction explicit without changing the v1 parser or
invalidating its frozen profiles.

The transport still uses the same strict ``present/data`` shape.  ``data`` is
raw text for scalar fields and JSON text for list/object fields.  The existing
normaliser is reused after scalar text is encoded locally, so all the original
duplicate-key, evidence, and review-only checks remain in force.
"""
from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
from typing import Any

from .announcement_extraction_pilot import MAX_REQUEST_BYTES, _PROMPT, _has_code, prepare_request
from .announcement_extraction_schema import (
    SCHEMA_BODY_LIMIT,
    SCHEMA_INPUT_TOKEN_LIMIT,
    STRICT_ENDPOINT,
    function_definition,
    normalise_transport_answer,
    tool_choice,
)
from .policy_candidates import REQUIRED_FIELDS


CONTRACT_VERSION = "policy-extraction-transport-v2"
SCALAR_FIELDS = frozenset({
    "title", "publication_date", "effective_date", "clock_24h",
    "timezone", "origin", "rate_meaning",
})
JSON_FIELDS = frozenset(REQUIRED_FIELDS) - SCALAR_FIELDS

_SEMANTIC_PROMPT_V2 = _PROMPT.replace(
    "{names}", ", ".join(REQUIRED_FIELDS)
).replace(
    "reason is text or null",
    "reason is always a string; known uses an empty string when there is no extra reason, "
    "unknown and conflict use a nonempty reason",
)

STRUCTURED_TRANSPORT_PROMPT_V2 = _SEMANTIC_PROMPT_V2 + """

Transport rules for this function call:
- Call submit_policy_fields exactly once and return no ordinary text.
- Every value uses {present:boolean,data:string}. For unknown or conflict use
  present=false and data="".
- For known scalar fields title, publication_date, effective_date, clock_24h,
  timezone, origin and rate_meaning, data is the raw text value. Do not add
  JSON quotation marks. Dates remain YYYY-MM-DD and clock remains HH:MM.
- The status value is always exactly one of known, unknown or conflict. The
  rates value may contain kind=conditional_rates_v1, but that belongs inside
  value.data and is never a status.
- For known entry_events, hts_codes, rates, conditions, exceptions and
  revisions, data is a JSON string. For example hts_codes data must be the
  JSON text [{"code":"28046100","precision":"whole_hts8"}], not a list
  of bare strings. The local checker will parse this text and apply the field
  rules above.
- Evidence occurrence is 0 only when the exact quote occurs once in the whole
  notice. If the exact quote occurs more than once, use its 1-based occurrence
  number; never use 0 for an ambiguous quote.
"""


def prepare_schema_request_v2(store: dict[str, Any], doc_version: str, *,
                              model: str, strict: bool = True) -> dict[str, Any]:
    """Build the v2 body while leaving the frozen v1 builder untouched."""
    legacy = prepare_request(store, doc_version)
    messages = [dict(legacy["messages"][0]), dict(legacy["messages"][1])]
    messages[0]["content"] = STRUCTURED_TRANSPORT_PROMPT_V2
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": [function_definition(strict=strict)],
        "tool_choice": tool_choice(),
        "parallel_tool_calls": False,
        "thinking": {"type": "disabled"},
        "max_tokens": 8192,
    }
    encoded = json.dumps(body, ensure_ascii=False, allow_nan=False,
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > SCHEMA_BODY_LIMIT:
        raise ValueError(f"structured provider request {len(encoded)} bytes exceeds {SCHEMA_BODY_LIMIT}")
    if legacy["request_bytes"] > MAX_REQUEST_BYTES:
        raise ValueError("saved notice already exceeds the original input gate")
    from scripts.prepare_brief_v3_offline import estimate_input_tokens
    input_estimate = estimate_input_tokens(legacy["messages"])
    if input_estimate["tokens"] > SCHEMA_INPUT_TOKEN_LIMIT:
        raise ValueError(
            f"structured provider input estimate {input_estimate['tokens']} tokens "
            f"exceeds {SCHEMA_INPUT_TOKEN_LIMIT}"
        )
    import hashlib
    return {
        "schema_version": CONTRACT_VERSION,
        "doc_version": doc_version,
        "model": model,
        "strict": strict,
        "endpoint_profile": "deepseek-beta-chat-tools-v2" if strict
        else "openai-compatible-chat-tools-v2",
        "endpoint": STRICT_ENDPOINT if strict else "https://api.deepseek.com/chat/completions",
        "body": body,
        "body_bytes": len(encoded),
        "body_sha256": hashlib.sha256(encoded).hexdigest(),
        "input_request_sha256": legacy["request_sha256"],
        "input_request_bytes": legacy["request_bytes"],
        "input_token_estimate": input_estimate,
        "input_token_limit": SCHEMA_INPUT_TOKEN_LIMIT,
        "body_limit": SCHEMA_BODY_LIMIT,
    }


def _validate_shape(answer: Mapping[str, Any]) -> None:
    if not isinstance(answer, Mapping) or set(answer) != {"doc_version", "fields"}:
        raise ValueError("tool arguments must contain only doc_version and fields")
    fields = answer["fields"]
    if not isinstance(fields, list):
        raise ValueError("tool fields must be an array")
    seen: set[str] = set()
    for item in fields:
        if not isinstance(item, Mapping):
            raise ValueError("tool field has an invalid shape")
        if set(item) != {"field", "status", "value", "reason", "evidence"}:
            raise ValueError("tool field has an invalid shape")
        name = item["field"]
        if name not in REQUIRED_FIELDS or name in seen:
            raise ValueError("tool field is unknown or duplicated")
        seen.add(name)


def normalise_transport_answer_v2(answer: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise the v2 scalar/raw-text contract into the v1 review contract.

    Scalar fields are deliberately not parsed as JSON.  Arrays and objects
    must still be JSON text, so a malformed or duplicate-key payload remains a
    hard failure instead of being silently accepted.
    """
    _validate_shape(answer)
    converted = copy.deepcopy(dict(answer))
    for item in converted["fields"]:
        # A provider may follow the legacy semantic wording and return null for
        # a known reason.  This is a safe lossless conversion because the
        # downstream review contract ignores known-field reasons. Unknown and
        # conflict reasons remain mandatory and are never filled in here.
        if item["status"] == "known" and item["reason"] is None:
            item["reason"] = ""
        # One prior response put the rates value kind in the status slot while
        # leaving value absent. Treat that explicit absence as unknown; do not
        # manufacture a rate or silently accept a present value under an
        # invalid status.
        if item["status"] == "conditional_rates_v1":
            value = item["value"]
            if (isinstance(value, Mapping) and value.get("present") is False
                    and isinstance(item["reason"], str) and item["reason"].strip()):
                item["status"] = "unknown"
            else:
                raise ValueError("rates kind must be inside value.data, not field status")
        value = item["value"]
        if not isinstance(value, Mapping) or set(value) != {"present", "data"} \
                or type(value["present"]) is not bool:
            raise ValueError("tool field value must be a present/data envelope")
        if not isinstance(value["data"], str):
            raise ValueError("tool field data must be text")
        if not value["present"]:
            if value["data"] != "":
                raise ValueError("unknown/conflict field data must be empty")
            continue
        name = item["field"]
        if name in SCALAR_FIELDS:
            if not value["data"].strip():
                raise ValueError(f"known scalar field {name} must be nonempty text")
            # The v1 normaliser expects JSON text.  Encode only after the
            # field-specific contract has established that this is raw text.
            value["data"] = json.dumps(value["data"], ensure_ascii=False)
        elif name not in JSON_FIELDS:
            raise ValueError(f"field {name} has no transport type")
    return normalise_transport_answer(converted)


def complete_hts_code_evidence_v2(answer: Mapping[str, Any], store: Mapping[str, Any]) -> dict[str, Any]:
    """Add deterministic source-row evidence for listed HTS codes.

    The model proposes the codes; the saved official notice verifies and
    supplies the row quote.  A code absent from the notice is rejected. This
    avoids requiring a long table to be copied into the tool response while
    keeping the final candidate evidence source-backed.
    """
    completed = copy.deepcopy(dict(answer))
    documents = store.get("documents") if isinstance(store, Mapping) else None
    if not isinstance(documents, list):
        raise ValueError("document store is missing documents")
    doc = next((item for item in documents
                if isinstance(item, Mapping) and item.get("doc_version") == completed.get("doc_version")), None)
    if not isinstance(doc, Mapping):
        raise ValueError("answer document version is absent from the store")
    sections = doc.get("sections")
    if not isinstance(sections, list):
        raise ValueError("document sections are missing")
    source = "".join(item.get("text", "") for item in sections
                     if isinstance(item, Mapping) and isinstance(item.get("text"), str))
    fields = completed.get("fields")
    if not isinstance(fields, list):
        raise ValueError("answer fields are missing")
    hts = next((item for item in fields
                if isinstance(item, Mapping) and item.get("field") == "hts_codes"), None)
    if not isinstance(hts, Mapping) or hts.get("status") != "known":
        return completed
    value = hts.get("value")
    if not isinstance(value, list):
        raise ValueError("hts_codes value must be a list before evidence completion")
    evidence = hts.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError("hts_codes evidence must be a list")
    for entry in value:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("code"), str):
            raise ValueError("hts_codes entry is malformed")
        code = entry["code"]
        if any(isinstance(cite, Mapping) and _has_code(cite.get("quote", ""), code)
               for cite in evidence):
            continue
        row = next((line for line in source.splitlines()
                    if re.match(rf"^\s*{re.escape(code)}(?:\.+|\s)", line)), None)
        if row is None:
            raise ValueError(f"HTS code {code} is absent from the saved notice")
        occurrences = [m.start() for m in re.finditer(re.escape(row), source)]
        if not occurrences:
            raise ValueError(f"source row for HTS code {code} cannot be located")
        cite: dict[str, Any] = {"quote": row}
        if len(occurrences) > 1:
            cite["occurrence"] = 1
        evidence.append(cite)
    return completed


__all__ = ["CONTRACT_VERSION", "SCALAR_FIELDS", "JSON_FIELDS",
           "STRUCTURED_TRANSPORT_PROMPT_V2", "prepare_schema_request_v2",
           "normalise_transport_answer_v2", "complete_hts_code_evidence_v2"]
