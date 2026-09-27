"""One lossless JSON response parser shared by generation and review.

The provider may return either a JSON object or one complete Markdown JSON
fence. We keep the original bytes for audit and never repair, concatenate, or
silently drop fields.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any


CONTRACT_VERSION = "json-response-v1"
_FENCE = re.compile(r"\A```(?:json)?[ \t]*\r?\n(?P<body>.*)\r?\n```[ \t]*\Z", re.S | re.I)


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def parse_json_response(text: str) -> Any:
    """Parse exactly one provider response, accepting a complete JSON fence."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("empty JSON response")
    candidate = text.strip()
    match = _FENCE.fullmatch(candidate)
    if match:
        candidate = match.group("body").strip()
    elif "```" in candidate:
        raise ValueError("mixed or incomplete JSON fence")
    value = json.loads(candidate, object_pairs_hook=_unique)
    return value


def canonical_response(text: str, *, stage: str) -> dict[str, Any]:
    """Return the parsed response plus hashes; do not rewrite the raw text."""
    value = parse_json_response(text)
    raw_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {
        "contract_version": CONTRACT_VERSION,
        "stage": stage,
        "raw_sha256": raw_hash,
        "parsed": value,
    }
