"""Deterministic trade coverage and A3 report helpers for a bound notice.

This module is deliberately small and conservative.  An announcement is a
policy document, not a trade dataset, so the report binds it to a separately
registered trade case and records that source case explicitly.  It never
turns an HTS6/ex/partial match into a whole-HTS8 exposure and never calls a
model.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .brief_fact_catalog import build_fact_catalog, render_fact_catalog, validate_fact_catalog
from .evidence_bundle import build_evidence_bundle
from .exposure_version_store import ExposureVersionStore, VersionStoreError
from .policy_candidates import parse_code_precision
from .policy_documents import citation_id, get_section
from .repository import DataPaths, EvidenceRepository

_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_HTS8 = re.compile(r"^\d{8}$")


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def coverage_digest(value: dict[str, Any]) -> str:
    """Digest the server-created query record, excluding its own digest."""
    unsigned = {key: item for key, item in value.items() if key != "coverage_digest"}
    return hashlib.sha256(_stable(unsigned).encode("utf-8")).hexdigest()


def _field_map(candidate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["field"]: item for item in candidate.get("fields", [])
            if isinstance(item, dict) and isinstance(item.get("field"), str)}


def candidate_hts_entries(candidate: dict[str, Any]) -> list[dict[str, str]]:
    fields = _field_map(candidate)
    field = fields.get("hts_codes")
    if not field or field.get("status") != "known":
        return []
    try:
        return parse_code_precision(field.get("value"))
    except ValueError:
        return []


def _candidate_codes(candidate: dict[str, Any]) -> list[str]:
    return [item["code"] for item in candidate_hts_entries(candidate)]


def requested_announcement_codes(candidate: dict[str, Any], request: dict[str, Any]) -> list[str]:
    """Resolve a full policy scope or an explicitly selected HTS8 subset."""
    entries = candidate_hts_entries(candidate)
    whole = [item["code"] for item in entries if item.get("precision") == "whole_hts8"]
    selected = request.get("products")
    if selected is not None:
        if (not isinstance(selected, list) or not selected
                or any(not _HTS8.fullmatch(str(code)) for code in selected)
                or len(selected) != len(set(str(code) for code in selected))):
            raise ValueError("公告所选商品必须是唯一的 HTS8 列表")
        codes = sorted(str(code) for code in selected)
    elif request.get("product") in (None, "", "all"):
        codes = sorted(whole)
    else:
        code = str(request.get("product"))
        if not _HTS8.fullmatch(code):
            raise ValueError("公告所选商品必须是 HTS8 或 all")
        codes = [code]
    if not codes or not set(codes).issubset(set(whole)):
        raise ValueError("请求商品不在公告已确认的 whole HTS8 范围内")
    return codes


def _whole_hts8_codes(candidate: dict[str, Any]) -> list[str]:
    return [item["code"] for item in candidate_hts_entries(candidate)
            if item.get("precision") == "whole_hts8"]


def _field_value(fields: dict[str, dict[str, Any]], name: str, default: Any = None) -> Any:
    field = fields.get(name) or {}
    return field.get("value") if field.get("status") == "known" else default


def _field_reason(fields: dict[str, dict[str, Any]], name: str) -> str | None:
    field = fields.get(name) or {}
    reason = field.get("reason")
    return str(reason) if isinstance(reason, str) and reason.strip() else None


def _source_for_section(store: dict[str, Any], doc_version: str,
                        section_id: str) -> dict[str, Any]:
    found = get_section(store, doc_version, section_id)
    if found is None:
        raise ValueError(f"公告引文位置不存在：{doc_version}:{section_id}")
    document, section = found["document"], found["section"]
    source_record = next((item for item in document.get("sources", [])
                          if item.get("source_id") == section.get("source_id")), {})
    source = {
        "id": citation_id(doc_version, section_id),
        "url": document.get("url") or source_record.get("url"),
        "text": section["text"],
        "text_sha256": hashlib.sha256(section["text"].encode("utf-8")).hexdigest(),
        "document_sha256": source_record.get("document_sha256"),
        "doc_version": doc_version,
        "section_id": section_id,
    }
    # A missing document hash is an explicit limitation of a pasted local
    # notice, not a reason to invent one.
    if source["document_sha256"] is None:
        source.pop("document_sha256")
    return source


def _field_sources(store: dict[str, Any], doc_version: str,
                   field: dict[str, Any] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for evidence in (field or {}).get("evidence", []):
        item = _source_for_section(store, doc_version, evidence["section_id"])
        if item["id"] not in {source["id"] for source in result}:
            result.append(item)
    return result


def build_announcement_policy_facts(store: dict[str, Any], doc_version: str,
                                    candidate: dict[str, Any], data_version: str,
                                    requested_codes: list[str]) -> dict[str, Any]:
    """Project reviewed candidate fields into the generic A3 policy contract.

    The generic contract intentionally has no hard-coded tax rates or product
    list.  Every value still points to a saved announcement section, while
    unknown fields remain explicit and are copied into the report limitations.
    """
    if store.get("policy_id") != candidate.get("policy_id"):
        raise ValueError("公告候选与公告存储的 policy_id 不一致")
    document = next((item for item in store.get("documents", [])
                     if item.get("doc_version") == doc_version), None)
    if document is None or document.get("status") != "enabled":
        raise ValueError("公告必须是已启用版本才能生成报告")
    fields = _field_map(candidate)
    all_sources: dict[str, dict[str, Any]] = {}
    by_field: dict[str, list[dict[str, Any]]] = {}
    for name, field in fields.items():
        sources = _field_sources(store, doc_version, field)
        by_field[name] = sources
        for source in sources:
            all_sources.setdefault(source["id"], source)
    first_section = (document.get("sections") or [])[0]
    fallback = _source_for_section(store, doc_version, first_section["id"])
    all_sources.setdefault(fallback["id"], fallback)

    scope_source = (by_field.get("hts_codes")
                    or [fallback])[0]["id"]
    origin_source = (by_field.get("origin") or by_field.get("effective_date")
                     or [fallback])[0]["id"]
    rates_value = _field_value(fields, "rates", {})
    if not isinstance(rates_value, dict):
        rates_value = {}
    rate_meaning = _field_value(fields, "rate_meaning")
    additional_meanings = {"additional duty", "additional rate of duty",
                           "additional ad valorem duty", "额外从价税率", "额外税率"}
    is_additional = isinstance(rate_meaning, str) and rate_meaning.strip().lower() in additional_meanings
    conditions_value = _field_value(fields, "conditions")
    exceptions_value = _field_value(fields, "exceptions")
    title = _field_value(fields, "title")
    limitations = [
        "这是新公告与独立贸易数据集的绑定报告；source_case_id 和数据版本必须同时核对。",
        "贸易金额是统计范围内的美国消费进口金额，不是逐笔法律适用税基、税款或损失。",
        "公告字段来自人工确认候选；quote 可回溯不等于法律语义已由系统判断。",
    ]
    all_whole_codes = _whole_hts8_codes(candidate)
    if set(requested_codes) != set(all_whole_codes):
        omitted = sorted(set(all_whole_codes) - set(requested_codes))
        limitations.append(
            f"公告登记的政策范围包含 {len(all_whole_codes)} 个 whole HTS8；"
            f"本次贸易统计只核对其中 {len(requested_codes)} 个，"
            f"另有 {len(omitted)} 个没有纳入本次统计：{'、'.join(omitted)}。"
        )
    for name in ("clock_24h", "timezone", "entry_events", "origin", "conditions", "exceptions", "revisions"):
        reason = _field_reason(fields, name)
        if reason:
            limitations.append(f"公告字段 {name} 仍未知：{reason}")
    rows: list[dict[str, Any]] = []
    for code in requested_codes:
        raw_rate = rates_value.get(code)
        rate = None
        if raw_rate is not None and type(raw_rate) in (int, float, str):
            try:
                number = Decimal(str(raw_rate))
                if number.is_finite() and 0 <= number <= 1000:
                    rate = int(number) if number == number.to_integral_value() else float(number)
            except InvalidOperation:
                pass
        rate_sources = by_field.get("rates") or [fallback]
        origin_sources = by_field.get("origin") or [fallback]
        row: dict[str, Any] = {
            "hts8": code,
            "source_id": rate_sources[0]["id"],
            "origin_source_id": origin_sources[0]["id"],
        }
        row["reported_rate"] = {"value": raw_rate, "meaning": rate_meaning,
                                "additional_rate_verified": is_additional and rate is not None}
        if rate is not None and is_additional:
            row["additional_duty_percent"] = rate
        elif raw_rate is not None:
            limitations.append(f"HTS {code} 的税率值或税率含义未适配为额外从价税率；保留确认值，不据此计算税额。")
        details: dict[str, Any] = {}
        if isinstance(title, str) and title.strip():
            details["registered_name"] = title
        for name, value in (("conditions", conditions_value), ("exceptions", exceptions_value)):
            field = fields.get(name) or {}
            if field.get("status") == "known":
                details[name] = {"status": "known", "text": value}
            else:
                details[name] = {"status": field.get("status", "unknown"),
                                 "reason": field.get("reason") or "该字段未完成确认。"}
        scope_text = "".join(source["text"] for source in by_field.get("hts_codes", [])) or fallback["text"]
        details["original_scope_clause"] = scope_text
        row["details"] = details
        rows.append(row)

    effective = _field_value(fields, "effective_date", "未知（未确认）")
    clock = _field_value(fields, "clock_24h", "未知（未确认）")
    timezone = _field_value(fields, "timezone", "未知（未确认）")
    origin = _field_value(fields, "origin", "未知（未确认）")
    entry_events = _field_value(fields, "entry_events", "未知（未确认）")
    facts = {
        "policy_view": "archived_event",
        "policy_id": candidate["policy_id"],
        "data_version": data_version,
        "model_generated": False,
        "legal_approval": False,
        "title": title or "未知（未确认）",
        "effective_date": effective,
        "clock_24h": clock,
        "timezone": timezone,
        "origin": origin,
        "entry_events": entry_events,
        "product_rates": rows,
        "requested_products": list(requested_codes),
        "scope_source_id": scope_source,
        "origin_source_id": origin_source,
        "sources": list(all_sources.values()),
        "limitations": limitations,
    }
    return facts


def _repository_for_version(root: Path, source_case_id: str,
                            data_version: str | None) -> tuple[EvidenceRepository, str, str | None]:
    from .policy_cases import resolve_case
    case = resolve_case(source_case_id)
    store = ExposureVersionStore(root, root / case.versions)
    active = store.active_version()
    version = data_version or active
    if version is None:
        raise VersionStoreError("贸易来源没有已发布活动版本")
    try:
        release = store.release_root(version)
    except VersionStoreError as exc:
        raise VersionStoreError("指定贸易版本没有已核验发布副本") from exc
    repository = EvidenceRepository(DataPaths(release))
    repository.exposure_version = version
    repository.exposure_store = store
    return repository, version, active


def _filter_trade_result(raw: dict[str, Any], *, announcement_policy_id: str,
                         source_case_id: str, requested_codes: list[str],
                         month: str, data_version: str) -> dict[str, Any]:
    data = raw.get("data") or {}
    if data.get("policy_id") != source_case_id or raw.get("data_version") != data_version:
        raise ValueError("贸易查询返回的来源政策或数据版本不一致")
    filtered_series: list[dict[str, Any]] = []
    for item in data.get("series") or []:
        if item.get("month") != month:
            continue
        products = [row for row in item.get("product_breakdown") or []
                    if row.get("hts8") in requested_codes]
        if len(products) != len(requested_codes):
            raise ValueError("贸易查询未覆盖公告要求的全部 HTS8")
        all_value = sum(int(row["all_origins_value_usd"]) for row in products)
        china_value = sum(int(row["china_value_usd"]) for row in products)
        filtered_series.append({
            "month": month,
            "value_usd": china_value,
            "all_origins_value_usd": all_value,
            "china_value_usd": china_value,
            "target_share_percent": round(china_value / all_value * 100, 4) if all_value else None,
            "product_breakdown": products,
        })
    if len(filtered_series) != 1:
        raise ValueError("贸易查询未返回恰好一个请求月份")
    result = deepcopy(raw)
    result["source_case_id"] = source_case_id
    result["source_data_policy_id"] = source_case_id
    result["data"] = deepcopy(data)
    result["data"].update({
        "policy_id": announcement_policy_id,
        "hts8": requested_codes[0] if len(requested_codes) == 1 else None,
        "requested_months": [month],
        "months": 1,
        "series": filtered_series,
        "total_usd": filtered_series[0]["value_usd"],
        "observed_total_usd": filtered_series[0]["value_usd"],
        "coverage_complete": True,
        "missing_months": [],
    })
    result["limitations"] = list(result.get("limitations") or []) + [
        f"贸易数字来自已登记来源案例 {source_case_id}，仅在公告 HTS8 与该来源统计范围一致时复用。",
        "政策公告与贸易统计的绑定是统计覆盖，不证明每笔进口在法律上实际适用该政策。",
    ]
    result["data_version"] = data_version
    return result


def query_bound_trade(root: Path, *, announcement_policy_id: str,
                      source_case_id: str, requested_codes: list[str],
                      month: str, data_version: str | None = None) -> dict[str, Any]:
    """Query one trusted registered source case and alias only its covered rows."""
    if not _MONTH.fullmatch(month):
        raise ValueError("覆盖月份必须是 YYYY-MM")
    if not requested_codes or any(not _HTS8.fullmatch(code) for code in requested_codes):
        raise ValueError("覆盖查询只接受完整 HTS8")
    repository, version, _active = _repository_for_version(root, source_case_id, data_version)
    from .policy_exposure_tools import get_policy_exposure_series
    raw = get_policy_exposure_series(origin="China", policy_id=source_case_id,
                                     start=month, end=month, repository=repository)
    available = {row.get("hts8") for row in (raw.get("data") or {}).get("series", [{}])[0].get("product_breakdown", [])}
    missing = sorted(set(requested_codes) - available)
    if missing:
        raise ValueError("贸易来源缺少公告要求的 HTS8：" + "、".join(missing))
    return _filter_trade_result(raw, announcement_policy_id=announcement_policy_id,
                                source_case_id=source_case_id,
                                requested_codes=sorted(requested_codes),
                                month=month, data_version=version)


def query_bound_trade_partial(root: Path, *, announcement_policy_id: str,
                              source_case_id: str, requested_codes: list[str],
                              month: str, data_version: str | None = None) -> tuple[dict[str, Any] | None, list[str], list[str], str]:
    """Read the available subset without hiding missing HTS8 codes.

    The regular query is intentionally strict and remains the report gate.  A
    coverage check, however, must be able to say “2 of 18 available” instead
    of collapsing the whole query to an uninformative error.  This helper uses
    the same pinned release and filtering logic, returns the filtered result
    for the available subset, and leaves report generation to the exact gate.
    """
    if not _MONTH.fullmatch(month):
        raise ValueError("覆盖月份必须是 YYYY-MM")
    if not requested_codes or any(not _HTS8.fullmatch(code) for code in requested_codes):
        raise ValueError("覆盖查询只接受完整 HTS8")
    repository, version, _active = _repository_for_version(root, source_case_id, data_version)
    from .policy_exposure_tools import get_policy_exposure_series
    raw = get_policy_exposure_series(origin="China", policy_id=source_case_id,
                                     start=month, end=month, repository=repository)
    series = (raw.get("data") or {}).get("series") or []
    if len(series) != 1 or series[0].get("month") != month:
        raise ValueError("贸易查询未返回恰好一个请求月份")
    available = {str(row.get("hts8")) for row in series[0].get("product_breakdown") or []}
    requested = sorted(set(requested_codes))
    covered = sorted(set(requested) & available)
    missing = sorted(set(requested) - set(covered))
    result = None
    if covered:
        result = _filter_trade_result(raw, announcement_policy_id=announcement_policy_id,
                                      source_case_id=source_case_id,
                                      requested_codes=covered,
                                      month=month, data_version=version)
    return result, covered, missing, version


def build_announcement_session_brief(root: Path, request: dict[str, Any],
                                     policy_binding: dict[str, Any],
                                     *, store: dict[str, Any],
                                     candidate: dict[str, Any],
                                     coverage: dict[str, Any]) -> dict[str, Any]:
    """Build the same A3 contract for an announcement with exact coverage."""
    from .policy_candidates import confirm_candidate
    policy_id = policy_binding.get("policy_id")
    doc_version = policy_binding.get("doc_version")
    if request.get("policy_id") != policy_id or store.get("policy_id") != policy_id:
        raise ValueError("请求与公告绑定身份不一致")
    confirm_candidate(candidate, store, confirmed_by="server-report",
                      digest=policy_binding.get("candidate_digest"))
    if (coverage.get("coverage_digest") != coverage_digest(coverage)
            or coverage.get("policy_id") != policy_id
            or coverage.get("doc_version") != doc_version
            or coverage.get("candidate_digest") != policy_binding.get("candidate_digest")
            or coverage.get("data_version") != policy_binding.get("data_version")):
        raise ValueError("公告覆盖内容或绑定摘要不一致；请重新核对覆盖")
    month = str(request.get("month") or "")
    if coverage.get("availability") != "exact" or coverage.get("month") != month:
        raise ValueError("公告贸易覆盖不是当前月份的 exact；不能生成金额报告")
    covered_codes = list(coverage.get("requested_codes") or [])
    if not covered_codes or any(not _HTS8.fullmatch(code) for code in covered_codes):
        raise ValueError("公告覆盖不是完整 HTS8 范围；不能生成金额报告")
    codes = requested_announcement_codes(candidate, request)
    if not set(codes).issubset(set(covered_codes)):
        raise ValueError("请求商品不在已核验的公告贸易覆盖范围内")
    if policy_binding.get("trade_coverage_digest") != coverage.get("coverage_digest"):
        raise ValueError("公告覆盖版本已变化；请重新确认范围")
    data_version = coverage.get("data_version")
    trade = query_bound_trade(
        root, announcement_policy_id=policy_binding["policy_id"],
        source_case_id=coverage["source_case_id"], requested_codes=codes,
        month=month, data_version=data_version)
    sheet = build_announcement_policy_facts(
        store, policy_binding["doc_version"], candidate, data_version, codes)
    bundle = build_evidence_bundle(trade, sheet, focus=str(request.get("focus") or "contrast"))
    catalog = build_fact_catalog(bundle)
    validate_fact_catalog(catalog)
    return {
        "kind": "program-report-a3",
        "policy_id": policy_binding["policy_id"],
        "policy_binding": deepcopy(policy_binding),
        "month": month,
        "product": request.get("product") or "all",
        "products": list(codes),
        "focus": request.get("focus") or "contrast",
        "data_version": data_version,
        "active_version": data_version,
        "source_case_id": coverage["source_case_id"],
        "catalog_sha256": catalog["catalog_sha256"],
        # Keep the complete host-owned catalog available for the same
        # explanation/review path as the registered primary case.
        "catalog": catalog,
        "fact_count": len(catalog["facts"]),
        "observation_count": len(catalog["observations"]),
        "question": f"政策 {policy_binding['policy_id']} 在 {month} 的商品贸易范围解读",
        "evidence_rows": [
            {"hts8": profile["hts8"],
             "world_import_usd": profile["world_import_usd"],
             "china_import_usd": profile["china_import_usd"],
             "china_share_percent": profile["china_share_of_product_percent"],
             "share_status": "unknown" if profile["china_share_of_product_percent"] is None else "known"}
            for profile in bundle.get("profiles", [])
        ],
        "a3_markdown": render_fact_catalog(catalog),
        "boundary": "本响应是绑定政策公告与已核验贸易来源后的确定性程序报告，不含模型生成内容；"
                    "金额是统计覆盖，不是逐笔法律适用额、税款或因果结论。",
    }


__all__ = ["build_announcement_policy_facts", "build_announcement_session_brief",
           "candidate_hts_entries", "coverage_digest", "query_bound_trade",
           "query_bound_trade_partial", "requested_announcement_codes"]
