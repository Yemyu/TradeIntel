"""Human-confirmed policy-to-statistics linkage, before any trade query.

This is an offline preparation gate, not a legal classifier or an amount
calculator.  A matching quotation proves provenance, not that the reviewer's
interpretation is correct.  The old whole-HTS8 report remains a separate route.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .announcement_statistics_report import (_CHINA, _resolve_range,
                                              prepare_announcement_statistics)
from .announcement_store import (announcement_lock, load_announcement_store,
                                 save_announcement_store)
from .policy_candidates import confirm_candidate, parse_code_precision
from .policy_documents import get_section

SCHEMA = "announcement-linkage-assessment-v1"
PREPARE_SCHEMA = "announcement-linkage-scope-v1"
RELATIONS = {"code_aligned", "parent_context", "country_context", "no_statistical_link"}
ORIGINS = {"mainland_only", "mainland_subset_of_china_hk", "other", "unknown"}
DIMENSIONS = {"shipping_method", "shipment_value", "firm_qualification", "approved_use",
              "entry_event", "exception_status", "other"}
_PROPOSAL_KEYS = {"relation", "origin_alignment", "context_code", "policy_scope_summary",
                  "unobserved_eligibility", "evidence"}
_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])\Z")


def _digest(value: dict[str, Any]) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _binding(store: dict[str, Any], policy_id: str, doc_version: str) -> tuple[dict, dict, dict]:
    document = next((doc for doc in store["documents"]
                     if doc["doc_version"] == doc_version), None)
    if not document or document.get("status") != "enabled" or document.get("policy_id") != policy_id:
        raise ValueError("关联判断只接受本政策已启用的公告版本")
    saved = (store.get("announcement_candidates") or {}).get(doc_version) or {}
    candidate, confirmation = saved.get("candidate"), saved.get("confirmation")
    if not isinstance(candidate, dict) or not isinstance(confirmation, dict):
        raise ValueError("公告没有已确认的候选字段")
    digest = candidate.get("candidate_digest")
    if (candidate.get("policy_id") != policy_id or not isinstance(digest, str)
            or confirmation.get("candidate_digest") != digest):
        raise ValueError("公告候选与确认记录不一致")
    confirm_candidate(candidate, store, confirmed_by="server-linkage-check", digest=digest)
    for field in candidate["fields"]:
        if any(item.get("doc_version") != doc_version for item in field.get("evidence", [])):
            raise ValueError("候选字段引用了另一公告版本")
    fields = {item["field"]: item for item in candidate["fields"]}
    return document, candidate, fields


def _validate_proposal(store: dict[str, Any], doc_version: str, fields: dict,
                       proposal: dict[str, Any]) -> None:
    if not isinstance(proposal, dict) or set(proposal) != _PROPOSAL_KEYS:
        raise ValueError("关联判断字段缺失或包含多余内容")
    relation, origin = proposal["relation"], proposal["origin_alignment"]
    if (not isinstance(relation, str) or relation not in RELATIONS
            or not isinstance(origin, str) or origin not in ORIGINS):
        raise ValueError("关联类型或原产地对应关系无效")
    summary = proposal["policy_scope_summary"]
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 1000:
        raise ValueError("必须填写简短的政策对象说明")
    eligibility = proposal["unobserved_eligibility"]
    if not isinstance(eligibility, list) or not eligibility:
        raise ValueError("必须逐项记录不能从贸易数据观察的适用条件；未知也须说明")
    for item in eligibility:
        if (not isinstance(item, dict) or set(item) != {"dimension", "defines_population", "description"}
                or not isinstance(item["dimension"], str) or item["dimension"] not in DIMENSIONS
                or type(item["defines_population"]) is not bool
                or not isinstance(item["description"], str) or not item["description"].strip()):
            raise ValueError("不可观察条件须有维度、是否界定对象及具体说明")
    evidence = proposal["evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("关联判断必须有本公告的逐字引文")
    seen: set[tuple[str, str]] = set()
    for item in evidence:
        if (not isinstance(item, dict) or set(item) != {"doc_version", "section_id", "quote"}
                or item["doc_version"] != doc_version or not isinstance(item["section_id"], str)
                or not isinstance(item["quote"], str) or not item["quote"].strip()):
            raise ValueError("关联判断引文的版本、段落或文字无效")
        found = get_section(store, doc_version, item["section_id"])
        if not found or item["quote"] not in found["section"]["text"]:
            raise ValueError("关联判断引文与保存的公告原文不一致")
        key = (item["section_id"], item["quote"])
        if key in seen:
            raise ValueError("关联判断引文重复")
        seen.add(key)

    origin_field = fields.get("origin") or {}
    if relation != "no_statistical_link":
        if origin not in {"mainland_only", "mainland_subset_of_china_hk"}:
            raise ValueError("没有确认中国大陆来源关系，不能连接中国大陆贸易数据")
        if origin_field.get("status") != "known" or not isinstance(origin_field.get("value"), str):
            raise ValueError("公告原产地字段未知，不能连接中国大陆贸易数据")
        source_origin = origin_field["value"]
        if origin == "mainland_only" and source_origin not in _CHINA:
            raise ValueError("公告原产地与中国大陆数据不符")
        if origin == "mainland_subset_of_china_hk":
            quote_text = " ".join(item["quote"] for item in evidence).casefold()
            if ("hong kong" not in quote_text and "香港" not in quote_text):
                raise ValueError("大陆只是中国及香港范围的子集；须引用涉及香港的原文")
            if not (source_origin in _CHINA or "china" in source_origin.casefold()
                    or "中国" in source_origin):
                raise ValueError("公告原产地不支持中国大陆子集")

    hts = fields.get("hts_codes") or {}
    entries = parse_code_precision(hts["value"]) if hts.get("status") == "known" else []
    code = proposal["context_code"]
    if relation == "code_aligned":
        if code is not None or not any(x["precision"] == "whole_hts8" for x in entries):
            raise ValueError("编码相符只能走已有的完整 HTS8 报告")
    elif relation == "parent_context":
        parents = {x["code"][:8] if x["precision"] == "hts10_partial" else x["code"]
                   for x in entries if x["precision"] != "whole_hts8"}
        if not isinstance(code, str) or code not in parents:
            raise ValueError("上层商品编码必须从已确认的部分范围推导，不可自由选择")
    elif relation == "country_context":
        if code is not None or hts.get("status") != "unknown":
            raise ValueError("国家背景只适用于未枚举完整商品编码的广泛货品公告")
        if any(item["defines_population"] for item in eligibility):
            raise ValueError("邮寄、价值、企业或用途等界定政策对象时，国家总量不能充当政策对象")
        if any((fields.get(name) or {}).get("status") != "known"
               for name in ("conditions", "exceptions")):
            raise ValueError("国家背景须先逐项确认公告条件和例外，未知不能默认为广泛货品")
        document = next(doc for doc in store["documents"] if doc["doc_version"] == doc_version)
        source_text = " ".join(section["text"] for section in document["sections"]).casefold()
        if origin == "mainland_only" and ("hong kong" in source_text or "香港" in source_text):
            raise ValueError("公告原文涉及香港；不能把中国大陆统计当作中国及香港总体")
    else:
        if code is not None:
            raise ValueError("暂无可连统计时不能提交商品范围")
        if (not any(item["defines_population"] for item in eligibility)
                and origin not in {"other", "unknown"}):
            raise ValueError("暂无统计关联需说明界定对象的缺失维度或不匹配的来源")


def confirm_linkage_assessment(root: Path, policy_id: str, doc_version: str,
                               proposal: dict[str, Any], *, confirmed_by: str,
                               expected_candidate_digest: str) -> dict[str, Any]:
    """Save a human decision bound to one source and candidate version."""
    if not isinstance(confirmed_by, str) or not confirmed_by.strip():
        raise ValueError("关联判断必须记录确认人")
    with announcement_lock(root, policy_id):
        store = load_announcement_store(root, policy_id)
        _, candidate, fields = _binding(store, policy_id, doc_version)
        if expected_candidate_digest != candidate["candidate_digest"]:
            raise ValueError("候选字段已变化；请重新确认关联判断")
        _validate_proposal(store, doc_version, fields, proposal)
        record = {"schema_version": SCHEMA, "policy_id": policy_id,
                  "doc_version": doc_version,
                  "candidate_digest": candidate["candidate_digest"],
                  **proposal, "confirmed_by": confirmed_by.strip()}
        record["assessment_digest"] = _digest(record)
        store.setdefault("linkage_assessments", {})[doc_version] = record
        save_announcement_store(root, policy_id, store)
        return record


def load_linkage_assessment(root: Path, policy_id: str, doc_version: str) -> dict[str, Any]:
    """Re-check the stored decision on every use; never trust a stale digest."""
    with announcement_lock(root, policy_id):
        store = load_announcement_store(root, policy_id)
        _, candidate, fields = _binding(store, policy_id, doc_version)
        record = (store.get("linkage_assessments") or {}).get(doc_version)
        if not isinstance(record, dict) or record.get("schema_version") != SCHEMA:
            raise ValueError("该公告还没有人工确认的关联判断")
        unsigned = {key: value for key, value in record.items() if key != "assessment_digest"}
        if record.get("assessment_digest") != _digest(unsigned):
            raise ValueError("关联判断摘要不一致；请重新确认")
        if (record.get("policy_id") != policy_id or record.get("doc_version") != doc_version
                or record.get("candidate_digest") != candidate["candidate_digest"]
                or not isinstance(record.get("confirmed_by"), str)
                or not record["confirmed_by"].strip()):
            raise ValueError("公告或候选已变化；请重新确认关联判断")
        proposal = {key: record.get(key) for key in _PROPOSAL_KEYS}
        if set(record) != _PROPOSAL_KEYS | {"schema_version", "policy_id", "doc_version",
                                            "candidate_digest", "confirmed_by", "assessment_digest"}:
            raise ValueError("关联判断字段结构无效")
        _validate_proposal(store, doc_version, fields, proposal)
        return record


def load_linkage_setup(root: Path, policy_id: str, doc_version: str) -> dict[str, Any]:
    """Read verified enabled fields and original sections for a refreshed page."""
    with announcement_lock(root, policy_id):
        store = load_announcement_store(root, policy_id)
        document, candidate, _ = _binding(store, policy_id, doc_version)
        result = {"policy_id": policy_id, "doc_version": doc_version,
                  "candidate_digest": candidate["candidate_digest"],
                  "fields": candidate["fields"],
                  "sections": [{"section_id": section["id"], "text": section["text"]}
                               for section in document["sections"]],
                  "source_url": document.get("url"),
                  "source_provenance": (store.get("announcement_imports") or {}).get(
                      doc_version, {}).get("source_provenance", "unknown")}
        return result


def prepare_linkage_scope(root: Path, policy_id: str, doc_version: str, *,
                          start_month: str | None = None, end_month: str | None = None,
                          trade_root: Path | None = None) -> dict[str, Any]:
    """Prepare an evidence-bound scope; does not query or create any amount."""
    record = load_linkage_assessment(root, policy_id, doc_version)
    relation = record["relation"]
    result: dict[str, Any] = {"schema_version": PREPARE_SCHEMA,
                              "policy_id": policy_id, "doc_version": doc_version,
                              "candidate_digest": record["candidate_digest"],
                              "assessment_digest": record["assessment_digest"],
                              "relation": relation, "policy_population": record["policy_scope_summary"],
                              "origin_alignment": record["origin_alignment"],
                              "unobserved_eligibility": record["unobserved_eligibility"],
                              "evidence": record["evidence"],
                              "policy_amount_status": "not_determined",
                              "hong_kong_included_in_statistics": False}
    if relation == "no_statistical_link":
        if start_month is not None or end_month is not None:
            raise ValueError("暂无可连统计时不能请求贸易数据月份")
        result.update({"route": "source_fact_card_only", "statistical_population": None,
                       "context_code": None, "months": [], "dataset_id": None,
                       "dataset_version": None, "classification_version": None})
    elif relation == "code_aligned":
        strict = prepare_announcement_statistics(
            root, policy_id, doc_version, start_month=start_month,
            end_month=end_month, trade_root=trade_root)
        result.update({"route": "announcement-statistics-report-v1",
                       "statistical_population": "已选完整 HTS8 的中国大陆来源美国消费进口观测；非实际征税额",
                       "context_code": None, "months": strict["months"],
                       "dataset_id": strict["dataset_id"],
                       "dataset_version": strict["dataset_version"],
                       "classification_version": strict["classification_version"],
                       "strict_scope": strict})
    else:
        data_root = trade_root or root
        start, end, months, trade, classes = _resolve_range(data_root, start_month, end_month)
        catalog = {item["month"]: item for item in trade["months"]}
        if any(catalog.get(month, {}).get("status") != "queryable_aggregate" for month in months):
            raise ValueError("所选月份有未发布的贸易数据；不能画连续背景趋势")
        if any(("import", month) not in classes.entries for month in months):
            raise ValueError("所选月份缺少已核验的商品目录")
        code = record["context_code"]
        if relation == "parent_context":
            if any(not any(item.startswith(code) for item in classes.month("import", month)["items"])
                   for month in months):
                raise ValueError("上层商品编码在所选月份的目录中不存在")
            population = f"整个 {code} 上层商品组的中国大陆来源消费进口，包含公告未覆盖货品"
            route = "announcement-context-report-v1:parent"
        else:
            population = ("本数据包已发布 HTS10 月包的中国大陆来源消费进口逐项合计；"
                          "不含香港单列来源，非公告适用金额或官方单列全国总量")
            route = "announcement-context-report-v1:country"
        result.update({"route": route, "statistical_population": population,
                       "context_code": code, "start_month": start, "end_month": end,
                       "months": months, "dataset_id": trade["dataset_id"],
                       "dataset_version": trade["dataset_version"],
                       "classification_version": classes.version,
                       "country_month_reconciliation": "pending" if relation == "country_context" else None,
                       "amount_semantics": "trade_context_not_policy_coverage"})
    result["prepare_digest"] = _digest(result)
    return result


def validate_prepared_linkage_scope(root: Path, prepared: dict[str, Any], *,
                                    trade_root: Path | None = None) -> dict[str, Any]:
    """Rebuild at the use boundary; a changed candidate/data/source fails closed."""
    if not isinstance(prepared, dict) or not isinstance(prepared.get("prepare_digest"), str):
        raise ValueError("缺少服务端准备的关联范围")
    unsigned = {key: val for key, val in prepared.items() if key != "prepare_digest"}
    if _digest(unsigned) != prepared["prepare_digest"]:
        raise ValueError("关联范围内容已变化；请重新确认")
    months = prepared.get("months")
    if not isinstance(months, list) or any(not isinstance(m, str) or not _MONTH.fullmatch(m)
                                            for m in months):
        raise ValueError("关联范围月份无效")
    fresh = prepare_linkage_scope(
        root, prepared.get("policy_id"), prepared.get("doc_version"),
        start_month=months[0] if months else None,
        end_month=months[-1] if months else None, trade_root=trade_root)
    if fresh != prepared:
        raise ValueError("公告、关联判断或贸易数据版本已变化；请重新确认")
    return fresh
