"""Versioned protocol mapping for the unified public four-question eval."""

import json

UNIFIED_EXPERIMENT_ID = "public-brief-unified-v2"
UNIFIED_CANDIDATE_SCHEMA = "public-service-candidate-v2"
UNIFIED_FREEZE_SCHEMA = "public-brief-unified-freeze-v2"
UNIFIED_RUN_SCHEMA = "public-brief-unified-provider-run-v2"

QUESTION_PROTOCOLS = {
    "q1": {"mode": "trade", "protocol": "public-brief-explanation-v1"},
    "q2": {"mode": "trade", "protocol": "public-brief-explanation-v1"},
    "q3": {"mode": "policy", "protocol": "public-policy-explanation-prototype-v2"},
    "q4": {"mode": "trade", "protocol": "public-brief-explanation-v1"},
}


def equivalent_messages(left, right) -> bool:
    """Compare messages while ignoring only JSON-object key ordering."""
    if not isinstance(left, list) or not isinstance(right, list) or len(left) != len(right):
        return False
    for first, second in zip(left, right):
        if not isinstance(first, dict) or not isinstance(second, dict):
            return False
        if first.keys() != second.keys() or first.get("role") != second.get("role"):
            return False
        a, b = first.get("content"), second.get("content")
        if a == b:
            continue
        try:
            if json.loads(a) != json.loads(b):
                return False
        except (TypeError, json.JSONDecodeError):
            return False
    return True

__all__ = [
    "QUESTION_PROTOCOLS", "UNIFIED_CANDIDATE_SCHEMA", "UNIFIED_EXPERIMENT_ID",
    "UNIFIED_FREEZE_SCHEMA", "UNIFIED_RUN_SCHEMA", "equivalent_messages",
]
