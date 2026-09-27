"""Version-bound, descriptive trade reports for manually confirmed notices."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .announcement_store import announcement_lock, load_announcement_store
from .announcement_trade_bridge import inspect_published_import_coverage
from .policy_candidates import confirm_candidate, parse_code_precision
from .trade_classification_catalog import ClassificationCatalog
from .trade_data_repository import TradeDataError, TradeDataRepository
from .trade_report_store import create_record

_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])\Z")
_HTS8 = re.compile(r"\d{8}\Z")
_CHINA = {"China", "中国", "China origin", "中国原产"}
REPORT_KIND = "announcement-statistics-report-v1"
MAX_MONTHS = 24
MAX_CODES = 100


def _digest(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _month_index(value: str) -> int:
    year, month = map(int, value.split("-"))
    return year * 12 + month - 1


def _month_at(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _binding(root: Path, policy_id: str, doc_version: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not isinstance(policy_id, str) or not policy_id.strip() or not isinstance(doc_version, str) or not doc_version.strip():
        raise ValueError("公告编号和公告版本必填")
    with announcement_lock(root, policy_id):
        store = load_announcement_store(root, policy_id)
        doc = next((row for row in store.get("documents", [])
                    if row.get("doc_version") == doc_version), None)
        if not isinstance(doc, dict) or doc.get("status") != "enabled":
            raise ValueError("只有已启用的公告可以生成贸易报告")
        saved = (store.get("announcement_candidates") or {}).get(doc_version)
        candidate = saved.get("candidate") if isinstance(saved, dict) else None
        confirmation = saved.get("confirmation") if isinstance(saved, dict) else None
        if not isinstance(candidate, dict) or not isinstance(confirmation, dict):
            raise ValueError("公告没有已确认的字段")
        digest = candidate.get("candidate_digest")
        if (candidate.get("policy_id") != policy_id or not isinstance(digest, str)
                or confirmation.get("candidate_digest") != digest):
            raise ValueError("公告候选与确认记录不一致")
        confirm_candidate(candidate, store, confirmed_by="server-statistical-report", digest=digest)
        fields = {item.get("field"): item for item in candidate.get("fields", [])
                  if isinstance(item, dict)}
        origin = fields.get("origin") or {}
        hts = fields.get("hts_codes") or {}
        if origin.get("status") != "known" or origin.get("value") not in _CHINA:
            raise ValueError("目前报告只支持已确认的中国原产地公告")
        if hts.get("status") != "known":
            raise ValueError("商品范围尚未确认")
        entries = parse_code_precision(hts.get("value"))
        codes = sorted(item["code"] for item in entries if item["precision"] == "whole_hts8")
        if not codes or len(codes) > MAX_CODES or len(codes) != len(set(codes)):
            raise ValueError("公告没有可查询的完整 HTS8 范围，或范围超过单次上限")
        return store, doc, {"candidate": candidate, "fields": fields,
                            "codes": codes, "candidate_digest": digest}


def _versions(root: Path) -> tuple[dict[str, Any], ClassificationCatalog]:
    trade = TradeDataRepository(root).catalog()
    classes = ClassificationCatalog(root)
    return trade, classes


def _resolve_range(root: Path, start_month: str | None, end_month: str | None) -> tuple[str, str, list[str], dict[str, Any], ClassificationCatalog]:
    trade, classes = _versions(root)
    queryable = sorted(item["month"] for item in trade["months"]
                       if item.get("status") == "queryable_aggregate")
    if not queryable:
        raise TradeDataError("目前没有已发布的可查询进口月份")
    end = end_month or queryable[-1]
    if not isinstance(end, str) or not _MONTH.fullmatch(end):
        raise ValueError("结束月份格式必须为 YYYY-MM")
    start = start_month or _month_at(_month_index(end) - 11)
    if not isinstance(start, str) or not _MONTH.fullmatch(start) or _month_index(start) > _month_index(end):
        raise ValueError("起止月份无效")
    months = [_month_at(i) for i in range(_month_index(start), _month_index(end) + 1)]
    if len(months) > MAX_MONTHS:
        raise ValueError(f"单次最多查询{MAX_MONTHS}个月，请缩小月份范围")
    return start, end, months, trade, classes


def prepare_announcement_statistics(root: Path, policy_id: str, doc_version: str, *,
                                    selected_codes: list[str] | None = None,
                                    start_month: str | None = None,
                                    end_month: str | None = None,
                                    trade_root: Path | None = None) -> dict[str, Any]:
    """Return a server-derived scope for the user to confirm."""
    _, _, binding = _binding(root, policy_id, doc_version)
    codes = binding["codes"]
    if selected_codes is not None:
        if (not isinstance(selected_codes, list) or not selected_codes
                or any(not isinstance(code, str) or not _HTS8.fullmatch(code) for code in selected_codes)
                or len(selected_codes) != len(set(selected_codes))
                or not set(selected_codes).issubset(codes)):
            raise ValueError("所选商品必须是公告已确认的完整 HTS8 子集")
        codes = sorted(selected_codes)
    start, end, months, trade, classes = _resolve_range(trade_root or root, start_month, end_month)
    partial = [item for item in parse_code_precision(binding["fields"]["hts_codes"].get("value"))
               if item["precision"] != "whole_hts8"]
    payload = {"schema_version": "announcement-statistics-scope-v1",
               "policy_id": policy_id, "doc_version": doc_version,
               "candidate_digest": binding["candidate_digest"],
               "dataset_id": trade["dataset_id"], "dataset_version": trade["dataset_version"],
               "classification_version": classes.version, "flow": "import", "reporter": "US",
               "partner": "CHINA", "metric": "import_value_consumption_usd",
               "selected_codes": codes, "excluded_partial_entries": partial,
               "unselected_whole_codes": sorted(set(binding["codes"]) - set(codes)),
               "start_month": start, "end_month": end, "months": months,
               "scope_status": "selected_whole_hts8_only",
               "latest_available_month": max((m for m in months if any(
                   item["month"] == m and item.get("status") == "queryable_aggregate"
                   for item in trade["months"])), default=None)}
    payload["prepare_digest"] = _digest(payload)
    return payload


def _field_citations(candidate: dict[str, Any], doc_version: str) -> list[dict[str, Any]]:
    citations = []
    for field in candidate.get("fields", []):
        if not isinstance(field, dict):
            continue
        for evidence in field.get("evidence", []):
            if isinstance(evidence, dict):
                citations.append({"field": field.get("field"),
                                  "section_id": evidence.get("section_id"),
                                  "quote": evidence.get("quote"),
                                  "doc_version": doc_version})
    return citations


def _published_sets(root: Path, trade_catalog: dict[str, Any], classes: ClassificationCatalog,
                    month: str, codes: list[str]) -> dict[str, dict[str, Any]]:
    source = next((item for item in trade_catalog["months"] if item["month"] == month), None)
    expected_by_code: dict[str, set[str] | None] = {code: None for code in codes}
    try:
        classified = classes.month("import", month)["items"]
        for code in codes:
            expected_by_code[code] = {subcode for subcode in classified
                                      if subcode.startswith(code)}
    except TradeDataError:
        pass
    matched = {code: set() for code in codes}
    observed = {code: set() for code in codes}
    source_digest = None
    if source and source.get("status") == "queryable_aggregate":
        path = root / str(source["processed_file"])
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        if before != source.get("processed_sha256"):
            raise TradeDataError("贸易明细与发布目录摘要不一致")
        source_digest = source.get("source_sha256")
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                hts10, hts8 = row.get("hts10", ""), row.get("hts8", "")
                if hts8 not in matched:
                    continue
                if (not re.fullmatch(r"\d{10}", hts10) or not hts10.startswith(hts8)
                        or row.get("source_sha256") != source_digest
                        or row.get("china_observed") not in {"0", "1"}):
                    raise TradeDataError("公告贸易明细中的商品编码、来源或观察状态无效")
                matched[hts8].add(hts10)
                if row["china_observed"] == "1":
                    observed[hts8].add(hts10)
        if hashlib.sha256(path.read_bytes()).hexdigest() != before:
            raise TradeDataError("读取贸易明细期间文件发生变化")
    output = {}
    classification_items = None
    if any(value is not None for value in expected_by_code.values()):
        classification_items = classes.month("import", month)["items"]
    for code in codes:
        expected = expected_by_code[code]
        got, seen = matched[code], observed[code]
        if expected is not None and not got.issubset(expected):
            raise TradeDataError(f"{month} 的 {code} 数据包含官方目录之外的子编码")
        output[code] = {"expected_codes": sorted(expected) if expected is not None else None,
                        "matched_codes": sorted(got), "observed_codes": sorted(seen),
                        "expected_count": len(expected) if expected is not None else None,
                        "matched_count": len(got), "observed_count": len(seen),
                        "absent_codes": sorted(expected - got) if expected is not None else None,
                        "unobserved_codes": sorted(got - seen),
                        "complete": bool(expected) and expected == got == seen,
                        "classification_available": expected is not None}
        if expected is not None:
            output[code]["names"] = [classification_items.get(item, "") for item in sorted(expected)]
    return output


def build_announcement_statistics_report(root: Path, prepared: dict[str, Any], *,
                                          trade_root: Path | None = None) -> dict[str, Any]:
    expected_keys = {"schema_version", "policy_id", "doc_version", "candidate_digest",
                     "dataset_id", "dataset_version", "classification_version", "flow", "reporter",
                     "partner", "metric", "selected_codes", "excluded_partial_entries", "start_month",
                     "unselected_whole_codes", "end_month", "months", "scope_status",
                     "latest_available_month", "prepare_digest"}
    if not isinstance(prepared, dict) or set(prepared) != expected_keys:
        raise ValueError("确认范围字段缺失或包含多余内容")
    unsigned = {key: value for key, value in prepared.items() if key != "prepare_digest"}
    if prepared.get("prepare_digest") != _digest(unsigned):
        raise ValueError("确认范围摘要无效，请重新确认")
    data_root = trade_root or root
    fresh = prepare_announcement_statistics(
        root, prepared["policy_id"], prepared["doc_version"],
        selected_codes=prepared["selected_codes"], start_month=prepared["start_month"],
        end_month=prepared["end_month"], trade_root=data_root)
    if fresh != prepared:
        raise ValueError("公告、贸易数据或商品目录版本已变化，请重新确认")
    store, doc, binding = _binding(root, prepared["policy_id"], prepared["doc_version"])
    trade_catalog, classes = _versions(data_root)
    month_catalog = {item["month"]: item for item in trade_catalog["months"]}
    monthly = []
    previous_by_code: dict[str, dict[str, Any]] | None = None
    for month in prepared["months"]:
        bridges = [inspect_published_import_coverage(
            root, prepared["policy_id"], prepared["doc_version"], month=month,
            dataset_version=prepared["dataset_version"], requested_codes=[code],
            trade_root=data_root)
            for code in prepared["selected_codes"]]
        by_code = _published_sets(data_root, trade_catalog, classes, month, prepared["selected_codes"])
        rows = []
        for bridge in bridges:
            code = bridge["selected_codes"][0]
            row = bridge["rows"][0]
            detail = by_code[code]
            if (row["matched_hts10"] != detail["matched_count"]
                    or row["observed_hts10"] != detail["observed_count"]):
                raise TradeDataError(f"{month} {code} 的统计查询与细分目录核对不一致")
            detail["month"] = month
            previous = (previous_by_code or {}).get(code)
            same_scope = bool(previous and detail["complete"] and previous["complete"]
                              and _month_index(month) - _month_index(previous["month"]) == 1
                              and month[:4] == previous["month"][:4]
                              and detail["expected_codes"] == previous["expected_codes"]
                              and detail["names"] == previous["names"])
            value = row["observed_import_value_consumption_usd"]
            rows.append({"hts8": code, "status": row["status"], "observed_value_usd": value,
                         **detail,
                         "month_change_usd": value - previous["value_usd"] if same_scope else None,
                         "month_change_status": "comparable" if same_scope else "not_comparable"})
        observed = [item["observed_value_usd"] for item in rows if item["observed_value_usd"] is not None]
        all_complete = bool(rows) and all(item["complete"] for item in rows)
        source = month_catalog.get(month) or {}
        monthly.append({"month": month, "status": source.get("status", "unavailable"),
                        "observed_value_usd": sum(observed) if observed else None,
                        "complete_value_usd": sum(observed) if all_complete else None,
                        "complete_codes": sum(item["complete"] for item in rows),
                        "selected_codes": len(rows), "rows": rows,
                        "source_url": source.get("source_url"),
                        "source_sha256": source.get("source_sha256"),
                        "processed_sha256": source.get("processed_sha256")})
        previous_by_code = {item["hts8"]: {"month": month, "complete": item["complete"],
                               "expected_codes": item["expected_codes"], "names": item.get("names", []),
                               "value_usd": item["observed_value_usd"]} for item in rows}
    final_trade, final_classes = _versions(data_root)
    if (final_trade["dataset_version"] != prepared["dataset_version"]
            or final_classes.version != prepared["classification_version"]):
        raise TradeDataError("生成报告期间数据版本或商品目录发生变化，请重新确认")
    _, final_doc, final_binding = _binding(root, prepared["policy_id"], prepared["doc_version"])
    if final_doc.get("status") != "enabled" or final_binding["candidate_digest"] != prepared["candidate_digest"]:
        raise ValueError("生成报告期间公告确认内容发生变化，请重新确认")
    document = next((row for row in store.get("documents", [])
                     if row.get("doc_version") == prepared["doc_version"]), {})
    metadata = (store.get("announcement_imports") or {}).get(prepared["doc_version"], {})
    fields = [{"field": item.get("field"), "status": item.get("status"),
               "value": item.get("value"), "reason": item.get("reason")}
              for item in binding["candidate"].get("fields", []) if isinstance(item, dict)]
    return {"kind": REPORT_KIND, "question": binding["fields"].get("title", {}).get("value") or "公告相关商品贸易情况",
            "policy": {"policy_id": prepared["policy_id"], "doc_version": prepared["doc_version"],
                       "candidate_digest": prepared["candidate_digest"], "title": document.get("title"),
                       "fields": fields, "citations": _field_citations(binding["candidate"], prepared["doc_version"]),
                       "source_url": metadata.get("source_url") or next(
                           (item.get("url") for item in document.get("sources", [])
                            if isinstance(item, dict) and item.get("url")), None),
                       "source_provenance": metadata.get("source_provenance", "unknown"),
                       "source_url_verification": metadata.get("source_url_verification", "unknown")},
            "scope": {key: prepared[key] for key in ("dataset_id", "dataset_version", "classification_version",
                      "flow", "reporter", "partner", "metric", "selected_codes", "excluded_partial_entries",
                      "unselected_whole_codes",
                      "start_month", "end_month", "latest_available_month")},
            "monthly": monthly, "policy_amount_status": "not_determined",
            "sources": [{"type": "us_trade_month", "months": [item["month"] for item in monthly
                          if item.get("source_url") == url], "url": url}
                        for url in dict.fromkeys(item["source_url"] for item in monthly
                                                 if item.get("source_url"))],
            "notes": ["图表金额为该月已观测的中国来源消费进口额；缺失细分行不补零。",
                      "它不是逐笔适用税额、政策造成的贸易变化或因果效果。",
                      "跨年商品编码可比性尚未核验；报告不计算跨年增幅。"]}


def generate_announcement_statistics_record(root: Path, prepared: dict[str, Any], *,
                                            trade_root: Path | None = None) -> dict[str, Any]:
    from .trade_report_store import NO_EXPLANATION_PROTOCOL
    report = build_announcement_statistics_report(root, prepared, trade_root=trade_root)
    return create_record(root, report, explanation_protocol=NO_EXPLANATION_PROTOCOL)


__all__ = ["REPORT_KIND", "prepare_announcement_statistics",
           "build_announcement_statistics_report", "generate_announcement_statistics_record"]
