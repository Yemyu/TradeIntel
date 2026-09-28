"""Read-only, version-bound trade background for a confirmed parent code.

The amount is for the WHOLE statistical parent group, never for the policy's
partial legal scope.  Country-wide context and source-only cards deliberately
do not enter this builder; they need separate verification/presentation gates.
"""
from __future__ import annotations

import csv
from copy import deepcopy
from pathlib import Path
import re
from typing import Any

from .announcement_linkage import validate_prepared_linkage_scope
from .announcement_store import load_announcement_store
from .trade_classification_catalog import ClassificationCatalog
from .trade_data_repository import (TradeDataError, TradeDataRepository, TradeQuery,
                                    _sha256)
from .trade_report_store import NO_EXPLANATION_PROTOCOL, create_record

REPORT_KIND = "announcement-context-report-v1"
_PARENT_ROUTE = REPORT_KIND + ":parent"


def _parent_month_coverage(root: Path, month: str, code: str,
                           catalog: dict, classes: ClassificationCatalog,
                           queried: dict) -> dict[str, Any]:
    """Independently reconcile matching HTS10 rows against the official list."""
    source = next((item for item in catalog["months"] if item["month"] == month), None)
    if not source or source.get("status") != "queryable_aggregate":
        raise TradeDataError("上层商品背景只接受已发布的连续月份")
    classified = classes.month("import", month)
    expected = {item: name for item, name in classified["items"].items()
                if item.startswith(code)}
    if not expected:
        raise TradeDataError(f"{month} 的上层编码 {code} 不在商品目录中")
    path = root / source["processed_file"]
    original_hash = _sha256(path)
    if original_hash != source["processed_sha256"]:
        raise TradeDataError("贸易明细与发布目录摘要不一致")
    matched: set[str] = set()
    observed: set[str] = set()
    observed_total = 0
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        required = {"year", "month", "hts10", "hts8", "source_sha256",
                    "china_observed", "china_import_value_consumption_usd"}
        if not required.issubset(reader.fieldnames or []):
            raise TradeDataError("上层商品明细缺少必要字段")
        for row in reader:
            hts10 = row.get("hts10", "")
            if not hts10.startswith(code):
                continue
            if (not re.fullmatch(r"\d{10}", hts10) or hts10 in matched
                    or row.get("hts8") != hts10[:8]
                    or row.get("source_sha256") != source["source_sha256"]
                    or row.get("year") != month[:4]
                    or row.get("month") not in {month[5:], str(int(month[5:]))}
                    or row.get("china_observed") not in {"0", "1"}):
                raise TradeDataError("上层商品明细编码、月份、来源或观察状态无效")
            matched.add(hts10)
            if row["china_observed"] == "1":
                observed.add(hts10)
                try:
                    value = int(row["china_import_value_consumption_usd"])
                except (ValueError, TypeError) as exc:
                    raise TradeDataError("上层商品进口额无效") from exc
                if value < 0:
                    raise TradeDataError("上层商品进口额不能为负")
                observed_total += value
    if _sha256(path) != original_hash:
        raise TradeDataError("读取上层商品明细期间文件发生变化")
    row = queried["months"][0]
    if (row["month"] != month or row["matched_hts10"] != len(matched)
            or row["observed_hts10"] != len(observed)
            or row["value_usd"] != (observed_total if observed else None)
            or queried["product_code"] != code or queried["partner"] != "CHINA"
            or queried["dataset_version"] != catalog["dataset_version"]):
        raise TradeDataError("上层商品独立核对与受信任查询不一致")
    unexpected = matched - expected.keys()
    if unexpected:
        raise TradeDataError("已发布贸易明细包含商品目录之外的子编码")
    complete = set(expected) == matched == observed
    return {"month": month,
            "status": "complete_observed" if complete else "incomplete_observation",
            "whole_parent_value_usd": observed_total if complete else None,
            "expected_hts10_count": len(expected), "matched_hts10_count": len(matched),
            "observed_hts10_count": len(observed),
            "missing_hts10": sorted(set(expected) - matched),
            "unobserved_hts10": sorted(matched - observed),
            "classification_year": int(month[:4]),
            "source_url": source.get("source_url"),
            "source_sha256": source["source_sha256"],
            "processed_sha256": source["processed_sha256"],
            "classification_names": [expected[item] for item in sorted(expected)],
            "_expected_codes": sorted(expected)}


def build_parent_context_report(root: Path, prepared: dict[str, Any], *,
                                trade_root: Path | None = None) -> dict[str, Any]:
    """Build a descriptive background snapshot; never produce policy amounts."""
    if not isinstance(prepared, dict) or prepared.get("route") != _PARENT_ROUTE:
        raise ValueError("这里只能生成已确认的上层商品背景")
    data_root = trade_root or root
    validate_prepared_linkage_scope(root, prepared, trade_root=data_root)
    code = prepared["context_code"]
    trade = TradeDataRepository(data_root)
    catalog = trade.catalog()
    classes = ClassificationCatalog(data_root)
    if (catalog["dataset_version"] != prepared["dataset_version"]
            or classes.version != prepared["classification_version"]):
        raise TradeDataError("贸易数据或商品目录版本已变化，请重新确认")
    monthly = []
    prior: dict[str, Any] | None = None
    for month in prepared["months"]:
        queried = trade.query(TradeQuery(
            reporter="US", flow="import", product_code=code,
            start_month=month, end_month=month, partner="CHINA",
            dataset_version=prepared["dataset_version"]))
        item = _parent_month_coverage(data_root, month, code, catalog, classes, queried)
        comparable = bool(prior and prior["status"] == item["status"] == "complete_observed"
                          and prior["month"][:4] == month[:4]
                          and prior["_expected_codes"] == item["_expected_codes"]
                          and prior["classification_names"] == item["classification_names"]
                          and (int(month[:4]) * 12 + int(month[5:])
                               - int(prior["month"][:4]) * 12 - int(prior["month"][5:]) == 1))
        item["month_change_status"] = "comparable" if comparable else "not_comparable"
        item["month_change_usd"] = (
            item["whole_parent_value_usd"] - prior["whole_parent_value_usd"] if comparable else None)
        prior = item
        monthly.append({key: value for key, value in item.items() if key != "_expected_codes"})
    validate_prepared_linkage_scope(root, prepared, trade_root=data_root)
    store = load_announcement_store(root, prepared["policy_id"])
    document = next(item for item in store["documents"]
                    if item["doc_version"] == prepared["doc_version"])
    candidate = store["announcement_candidates"][prepared["doc_version"]]["candidate"]
    source_url = document.get("url")
    report = {"kind": REPORT_KIND, "context_type": "parent",
              "policy": {"policy_id": prepared["policy_id"],
                         "doc_version": prepared["doc_version"],
                         "candidate_digest": prepared["candidate_digest"],
                         "assessment_digest": prepared["assessment_digest"],
                         "policy_population": prepared["policy_population"],
                         "evidence": deepcopy(prepared["evidence"]),
                         "confirmed_fields": deepcopy(candidate["fields"]),
                         "source_url": source_url,
                         "source_provenance": (store.get("announcement_imports") or {}).get(
                             prepared["doc_version"], {}).get("source_provenance", "unknown"),
                         "rate_evidence_scope": "source_document_only",
                         "current_applicability_status": "not_verified"},
              "scope": {"statistical_population": prepared["statistical_population"],
                        "context_code": code,
                        "origin_alignment": prepared["origin_alignment"],
                        "unobserved_eligibility": prepared["unobserved_eligibility"],
                        "reporter": "US", "flow": "import", "partner": "CHINA",
                        "metric": "import_value_consumption_usd",
                        "start_month": prepared["start_month"],
                        "end_month": prepared["end_month"],
                        "dataset_id": prepared["dataset_id"],
                        "dataset_version": prepared["dataset_version"],
                        "classification_version": prepared["classification_version"],
                        "prepare_digest": prepared["prepare_digest"],
                        "amount_semantics": "whole_parent_trade_context_not_policy_coverage"},
              "monthly": monthly, "policy_amount_status": "not_determined",
              "sources": [{"month": item["month"], "url": item["source_url"],
                           "source_sha256": item["source_sha256"],
                           "processed_sha256": item["processed_sha256"]}
                          for item in monthly],
              "notes": ["金额只代表整个上层商品组，包含公告未覆盖的货品。",
                        "若目录子码缺失或未观测，不展示该月金额，也不补零。",
                        "相邻月份只有在完整观测、同年且子码与名称一致时才计算变化。",
                        "原公告税率不代表报告月份或现在实际适用税率。",
                        "这不是政策受影响金额、应缴税额或政策效果。"]}
    return report


def generate_parent_context_record(root: Path, prepared: dict[str, Any], *,
                                   trade_root: Path | None = None) -> dict[str, Any]:
    report = build_parent_context_report(root, prepared, trade_root=trade_root)
    return create_record(root, report, explanation_protocol=NO_EXPLANATION_PROTOCOL)


__all__ = ["REPORT_KIND", "build_parent_context_report", "generate_parent_context_record"]
