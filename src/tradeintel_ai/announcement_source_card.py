"""Source-only card for notices without a defensible trade-statistics join.

The card preserves human-confirmed policy fields and their original quotes.  It
does not query trade data, infer missing fields or allocate an amount to policy.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .announcement_linkage import validate_prepared_linkage_scope
from .announcement_store import load_announcement_store
from .trade_report_store import NO_EXPLANATION_PROTOCOL, create_record


REPORT_KIND = "announcement-context-report-v1"
_ROUTE = "source_fact_card_only"


def build_source_fact_card(root: Path, prepared: dict[str, Any]) -> dict[str, Any]:
    """Revalidate the confirmed source and return an explicitly chartless card."""
    if not isinstance(prepared, dict) or prepared.get("route") != _ROUTE:
        raise ValueError("这里只能生成暂无可连统计的公告原文事实卡")
    validate_prepared_linkage_scope(root, prepared)
    store = load_announcement_store(root, prepared["policy_id"])
    document = next((item for item in store["documents"]
                     if item["doc_version"] == prepared["doc_version"]), None)
    saved = (store.get("announcement_candidates") or {}).get(prepared["doc_version"]) or {}
    candidate = saved.get("candidate") or {}
    if (document is None or candidate.get("candidate_digest") != prepared["candidate_digest"]
            or not isinstance(candidate.get("fields"), list)):
        raise ValueError("公告或已确认字段已变化，请重新确认")
    fields = [{"field": row["field"], "status": row["status"],
               "value": deepcopy(row["value"]),
               "reason": row.get("reason"),
               "evidence": deepcopy(row["evidence"])}
              for row in candidate["fields"]]
    validate_prepared_linkage_scope(root, prepared)
    return {"kind": REPORT_KIND, "context_type": "source_only",
            "policy": {"policy_id": prepared["policy_id"],
                       "doc_version": prepared["doc_version"],
                       "candidate_digest": prepared["candidate_digest"],
                       "assessment_digest": prepared["assessment_digest"],
                       "policy_population": prepared["policy_population"],
                       "evidence": deepcopy(prepared["evidence"]),
                       "confirmed_fields": fields,
                       "source_url": document.get("url"),
                       "source_provenance": (store.get("announcement_imports") or {}).get(
                           prepared["doc_version"], {}).get("source_provenance", "unknown"),
                       "rate_evidence_scope": "source_document_only",
                       "current_applicability_status": "not_verified"},
            "scope": {"statistical_population": None,
                      "origin_alignment": prepared["origin_alignment"],
                      "unobserved_eligibility": deepcopy(prepared["unobserved_eligibility"]),
                      "dataset_id": None, "dataset_version": None,
                      "classification_version": None,
                      "prepare_digest": prepared["prepare_digest"]},
            "statistical_link": {"status": "not_available",
                                 "reason": "现有月度商品表不能识别公告所限定的人、货或入境事件；不附贸易图表。"},
            "chart_status": "not_available",
            "monthly": [], "policy_amount_status": "not_determined",
            "sources": [{"url": document.get("url"),
                         "doc_version": prepared["doc_version"],
                         "evidence": deepcopy(prepared["evidence"])}],
            "notes": ["这是一张公告原文事实卡，不是贸易金额报告。",
                      "已确认字段只反映原公告文字，不代表现行税率或当前适用状态。",
                      "未知字段及无法从贸易表观察的资格条件保留原样，不补零也不推断政策效果。"]}


def generate_source_fact_record(root: Path, prepared: dict[str, Any]) -> dict[str, Any]:
    report = build_source_fact_card(root, prepared)
    return create_record(root, report, explanation_protocol=NO_EXPLANATION_PROTOCOL)


__all__ = ["REPORT_KIND", "build_source_fact_card", "generate_source_fact_record"]
