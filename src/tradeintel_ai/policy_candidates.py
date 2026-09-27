"""Candidate policy fields with per-field original-text evidence and gated
confirmation.  Auto-detected documents always stay candidates; adopting a
field into the product requires a human confirmation bound to the candidate
digest, and any change to the document or the field invalidates it.

Field evidence stores {doc_version, section_id, quote}; the quote must appear
verbatim in the saved section text, so ``quote matched`` never means ``semantics
verified``.  Unknown and conflicting fields are first-class values -- a missing
field must never silently become ``known``.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from datetime import datetime, timezone
import re
from typing import Any

from .policy_documents import get_section, validate_document_store

SCHEMA = "policy-candidates-v1"
FIELD_STATUSES = ("known", "unknown", "conflict")
REQUIRED_FIELDS = ("title", "publication_date", "effective_date", "clock_24h", "timezone",
                   "entry_events", "origin", "hts_codes", "rates", "rate_meaning",
                   "conditions", "exceptions", "revisions")
CODE_PRECISIONS = ("whole_hts8", "partial_ex", "text_limited", "hs6_only", "hts10_partial")
_CODE_LENGTH = {"whole_hts8": 8, "partial_ex": 8, "text_limited": 8, "hs6_only": 6,
                "hts10_partial": 10}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def candidate_digest(candidate: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(candidate).encode("utf-8")).hexdigest()


def build_candidates(fields: list[dict[str, Any]], store: dict[str, Any], *,
                     allowed_statuses: tuple[str, ...] = ("enabled",)) -> dict[str, Any]:
    """Assemble and verify one candidate record against a document store.

    ``allowed_statuses`` extends the document statuses a quote may cite: the
    default only accepts enabled documents, while the announcement flow cites
    a disabled CANDIDATE document that is being confirmed for the first time.
    """
    validate_document_store(store)
    seen: set[str] = set()
    verified: list[dict[str, Any]] = []
    for field in fields:
        if not isinstance(field, dict) or field.get("field") not in REQUIRED_FIELDS:
            raise ValueError(f"candidate fields must be one of {REQUIRED_FIELDS}")
        name = field["field"]
        if name in seen:
            raise ValueError(f"duplicate candidate field: {name}")
        seen.add(name)
        status = field.get("status")
        if status not in FIELD_STATUSES:
            raise ValueError(f"field {name} status must be one of {FIELD_STATUSES}")
        value = field.get("value")
        evidence = field.get("evidence", [])
        if not isinstance(evidence, list):
            raise ValueError(f"field {name} evidence must be a list")
        if status == "known":
            if value is None:
                raise ValueError(f"known field {name} needs a value")
            if not evidence:
                raise ValueError(f"known field {name} needs at least one verbatim quote")
            if name == "hts_codes":
                parse_code_precision(value)
        if status == "conflict" and len(evidence) < 2:
            raise ValueError(f"conflict field {name} needs at least two evidence entries")
        checked = []
        for item in evidence:
            if not isinstance(item, dict) or set(item) != {"doc_version", "section_id", "quote"}:
                raise ValueError(f"field {name} evidence must be doc_version/section_id/quote")
            quote = item["quote"]
            if not isinstance(quote, str) or not quote.strip():
                raise ValueError(f"field {name} quote must be a non-empty string")
            if not isinstance(item["section_id"], str) or not item["section_id"] \
                    or not isinstance(item["doc_version"], str) or not item["doc_version"]:
                raise ValueError(f"field {name} evidence location is malformed")
            found = get_section(store, item["doc_version"], item["section_id"])
            if found is None:
                raise ValueError(f"field {name} cites an unknown section: {item['section_id']}")
            if found["document"].get("status") not in allowed_statuses:
                raise ValueError(f"field {name} cites a non-enabled document")
            if quote not in found["section"]["text"]:
                raise ValueError(f"field {name} quote does not match saved original text")
            checked.append({"doc_version": item["doc_version"],
                            "section_id": item["section_id"],
                            "quote": quote})
        if status == "unknown":
            reason = field.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(f"unknown field {name} needs an explicit reason")
            checked = []
        verified.append({"field": name, "value": deepcopy(value), "status": status,
                         "evidence": checked,
                         "reason": field.get("reason") if status == "unknown" else None})
    missing = [name for name in REQUIRED_FIELDS if name not in seen]
    candidate = {"schema_version": SCHEMA, "policy_id": store.get("policy_id"),
                 "data_version": store.get("data_version"),
                 "fields": verified, "missing_required_fields": missing}
    candidate["candidate_digest"] = candidate_digest(
        {key: value for key, value in candidate.items()})
    return candidate


def confirm_candidate(candidate: dict[str, Any], store: dict[str, Any], *,
                      confirmed_by: str, digest: str | None = None,
                      allowed_statuses: tuple[str, ...] = ("enabled",)) -> dict[str, Any]:
    """Bind a human confirmation to the candidate digest; re-verify everything.

    Before confirming, the candidate schema, its recorded digest, the policy
    identity against the current store, every field status, and the missing
    required fields are re-checked from scratch -- a self-consistent hash
    alone never proves anything.  The confirmation fails if the candidate
    content no longer matches its recorded digest, if the supplied digest
    differs, or if any cited quote no longer matches the current store.
    ``allowed_statuses`` mirrors :func:`build_candidates` for the announcement
    flow, whose document is still a disabled candidate at confirmation time.
    """
    validate_document_store(store)
    if candidate.get("schema_version") != SCHEMA:
        raise ValueError("candidate schema mismatch; re-confirm is required")
    recorded = candidate.get("candidate_digest")
    recomputed = candidate_digest({key: value for key, value in candidate.items()
                                   if key != "candidate_digest"})
    if recorded != recomputed:
        raise ValueError("candidate content changed after its digest was recorded; re-confirm is required")
    if digest is not None and digest != recorded:
        raise ValueError("confirmation digest does not match the candidate; re-confirm is required")
    if candidate.get("policy_id") != store.get("policy_id") \
            or candidate.get("data_version") != store.get("data_version"):
        raise ValueError("candidate policy identity does not match the store; re-confirm is required")
    field_names = set()
    for field in candidate.get("fields", []):
        if not isinstance(field, dict) or field.get("field") not in REQUIRED_FIELDS \
                or field.get("field") in field_names:
            raise ValueError("candidate field list is malformed; re-confirm is required")
        field_names.add(field["field"])
        if field.get("status") not in FIELD_STATUSES:
            raise ValueError(f"field {field['field']} status is invalid; re-confirm is required")
        if field.get("status") == "unknown" and not (field.get("reason") or "").strip():
            raise ValueError(f"unknown field {field['field']} lost its reason; re-confirm is required")
        if field["field"] == "hts_codes" and field.get("status") == "known":
            parse_code_precision(field.get("value"))
    missing = [name for name in REQUIRED_FIELDS if name not in field_names]
    if missing != candidate.get("missing_required_fields"):
        raise ValueError("candidate missing-field list is stale; re-confirm is required")
    for field in candidate.get("fields", []):
        for item in field.get("evidence", []):
            found = get_section(store, item["doc_version"], item["section_id"])
            if found is None or found["document"].get("status") not in allowed_statuses:
                raise ValueError(f"field {field['field']} cites a changed or disabled section; re-confirm is required")
            if item["quote"] not in found["section"]["text"]:
                raise ValueError(f"field {field['field']} quote no longer matches; re-confirm is required")
    return {"schema_version": "policy-candidate-confirmation-v1",
            "candidate_digest": recorded,
            "confirmed_by": confirmed_by,
            "confirmed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "evidence_reverified": True,
            "policy_identity_verified": True,
            "boundary": "确认只绑定摘要与引文复核；quote匹配不代表语义正确，语义判断仍在人工审阅。"}


def parse_code_precision(value: Any) -> list[dict[str, Any]]:
    """Normalize the hts_codes field value into code/precision entries.

    Precision and code length must match: ``whole_hts8``/``partial_ex``/
    ``text_limited`` carry 8-digit codes, ``hs6_only`` carries a real 6-digit
    code (and must never be extended to HTS8), ``hts10_partial`` carries a
    10-digit partial line.
    """
    if not isinstance(value, list) or not value:
        raise ValueError("hts_codes value must be a non-empty list of code entries")
    entries = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("hts_codes entries must be objects")
        code = item.get("code")
        precision = item.get("precision")
        if precision not in CODE_PRECISIONS:
            raise ValueError(f"code {code!r} precision must be one of {CODE_PRECISIONS}")
        if not isinstance(code, str) or not re.fullmatch(rf"\d{{{_CODE_LENGTH[precision]}}}", code):
            raise ValueError(f"code {code!r} does not match precision {precision} "
                             f"(needs {_CODE_LENGTH[precision]} digits)")
        if code[:2] in {"98", "99"}:
            raise ValueError(f"code {code!r} is a Chapter 98/99 reporting heading, not a merchandise code")
        entries.append({"code": code, "precision": precision})
    return entries


def build_coverage(candidate: dict[str, Any], *,
                   trade_evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """Layered coverage: code precision, policy scope match, trade coverage.

    The trade layer stays ``not_checked`` unless a trusted trade-query result
    is supplied with ``trade_evidence`` = {"codes": [...], "month": "YYYY-MM",
    "data_version": ..., "availability": "exact"|"partial"|"none"} -- the
    codes and month must match the candidate's HTS entries.  Without such
    evidence no trade amount may ever be called an exact policy exposure.
    """
    fields = {field["field"]: field for field in candidate.get("fields", [])}
    hts = fields.get("hts_codes")
    if hts is None or hts.get("status") != "known":
        return {"code_precision": "unknown", "policy_scope_match": "unknown",
                "trade_coverage": "not_checked",
                "boundary": "税号字段未知或缺失时，不能把任何贸易金额称为对应政策范围的精确金额。"}
    entries = parse_code_precision(hts.get("value"))
    exact = all(item["precision"] == "whole_hts8" for item in entries)
    code_precision = "exact_hts8" if exact else "partial"
    # ex / 文字限定 / 部分HTS10 / HS6 只能给上层统计参考，不能称精确受影响金额。
    policy_scope_match = "whole_hts8" if exact else "partial"
    candidate_codes = sorted(item["code"] for item in entries if len(item["code"]) == 8)
    if trade_evidence is None:
        trade_coverage = "not_checked"
        covered_codes = []
        requested_codes = candidate_codes
    else:
        if not isinstance(trade_evidence, dict) or \
                trade_evidence.get("availability") not in ("exact", "partial", "none"):
            raise ValueError("trade_evidence must carry availability: exact/partial/none")
        codes = trade_evidence.get("codes")
        requested = trade_evidence.get("requested_codes", codes)
        if (not isinstance(codes, list) or len(codes) != len(set(str(c) for c in codes))
                or not set(str(c) for c in codes).issubset(candidate_codes)):
            raise ValueError("trade_evidence codes must be a unique subset of candidate HTS8 entries")
        if (not isinstance(requested, list)
                or len(requested) != len(set(str(c) for c in requested))
                or not set(str(c) for c in requested).issubset(candidate_codes)
                or not set(str(c) for c in codes).issubset(set(str(c) for c in requested))):
            raise ValueError("trade_evidence requested_codes must contain the covered HTS8 subset")
        if not trade_evidence.get("month") or not trade_evidence.get("data_version"):
            raise ValueError("trade_evidence must carry the queried month and data version")
        trade_coverage = trade_evidence["availability"]
        covered_codes = sorted(str(c) for c in codes)
        requested_codes = sorted(str(c) for c in requested)
    if policy_scope_match != "whole_hts8" and trade_coverage == "exact":
        raise ValueError("partial policy scope must never be reported as exact exposure")
    if trade_evidence is None:
        requested_codes = candidate_codes
    elif not requested_codes:
        raise ValueError("trade_evidence requested_codes cannot be empty")
    return {"code_precision": code_precision, "policy_scope_match": policy_scope_match,
            "trade_coverage": trade_coverage,
            "codes": entries,
            "candidate_codes": candidate_codes,
            "requested_codes": requested_codes,
            "covered_codes": covered_codes,
            "coverage_scope": "full" if requested_codes == candidate_codes else "selected",
            "missing_codes": sorted(set(requested_codes) - set(covered_codes)),
            "boundary": "仅 whole_hts8 且有受信任贸易查询结果时才可称精确政策敞口；"
                        "ex/文字限定/部分HTS10只作上层参考并标partial；HS6不可扩成HTS8；"
                        "未查询贸易数据时保持not_checked。"}


__all__ = ["SCHEMA", "REQUIRED_FIELDS", "build_candidates", "build_coverage",
           "candidate_digest", "confirm_candidate", "parse_code_precision"]
