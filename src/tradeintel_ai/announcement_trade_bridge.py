"""Read-only bridge from a confirmed notice to published US import statistics.

This is intentionally separate from the older case-bound ``trade_coverage``
record and its A3 report gate.  An observed HTS line is a statistical fact,
not a determination that each entry was legally subject to the notice.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .announcement_store import announcement_lock, load_announcement_store
from .policy_candidates import confirm_candidate, parse_code_precision
from .trade_data_repository import TradeDataError, TradeDataRepository, TradeQuery

_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])\Z")
_HTS8 = re.compile(r"\d{8}\Z")
_CHINA_ORIGINS = {"China", "中国", "China origin", "中国原产"}
_MAX_CODES = 100


def _digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def inspect_published_import_coverage(
    announcement_root: Path,
    policy_id: str,
    doc_version: str,
    *,
    month: str,
    dataset_version: str,
    requested_codes: list[str] | None = None,
    trade_root: Path | None = None,
) -> dict[str, Any]:
    """Inspect one month's Chinese-origin import rows for a confirmed notice.

    ``trade_root`` is an internal test/rehearsal injection point; product code
    should omit it so the registered announcement and published data share a
    root.  This function does not write coverage, enable a policy, or make an
    A3 report eligible for generation.
    """
    if not isinstance(month, str) or not _MONTH.fullmatch(month):
        raise ValueError("覆盖月份必须是 YYYY-MM")
    if not isinstance(dataset_version, str) or not re.fullmatch(r"[0-9a-f]{64}", dataset_version):
        raise ValueError("必须明确指定已发布进口数据版本")
    with announcement_lock(announcement_root, policy_id):
        store = load_announcement_store(announcement_root, policy_id)
        document = next((item for item in store.get("documents", [])
                         if item.get("doc_version") == doc_version), None)
        if not isinstance(document, dict) or document.get("status") != "enabled":
            raise ValueError("只允许核对已启用且版本明确的公告")
        record = (store.get("announcement_candidates") or {}).get(doc_version)
        candidate = (record or {}).get("candidate") if isinstance(record, dict) else None
        confirmation = (record or {}).get("confirmation") if isinstance(record, dict) else None
        if not isinstance(candidate, dict) or not isinstance(confirmation, dict):
            raise ValueError("公告缺少已确认的字段候选")
        digest = candidate.get("candidate_digest")
        if (candidate.get("policy_id") != policy_id
                or not isinstance(digest, str)
                or confirmation.get("candidate_digest") != digest):
            raise ValueError("公告候选与人工确认摘要不一致")
        confirm_candidate(candidate, store, confirmed_by="server-statistical-check",
                          digest=digest)
        fields = {item.get("field"): item for item in candidate.get("fields", [])}
        origin = fields.get("origin") or {}
        if origin.get("status") != "known" or origin.get("value") not in _CHINA_ORIGINS:
            raise ValueError("当前只核对已确认的中国原产地公告；不能代用全部来源")
        hts = fields.get("hts_codes") or {}
        if hts.get("status") != "known":
            raise ValueError("公告税号尚未确认；不能查贸易统计")
        entries = parse_code_precision(hts.get("value"))
        all_codes = [item["code"] for item in entries]
        if len(all_codes) != len(set(all_codes)):
            raise ValueError("公告税号重复；需先修正候选")
        whole_codes = sorted(item["code"] for item in entries
                             if item["precision"] == "whole_hts8")
        partial_entries = [item for item in entries if item["precision"] != "whole_hts8"]

    if requested_codes is None:
        selected = whole_codes
    else:
        if (not isinstance(requested_codes, list) or not requested_codes
                or any(not isinstance(code, str) or not _HTS8.fullmatch(code)
                       for code in requested_codes)
                or len(requested_codes) != len(set(requested_codes))
                or not set(requested_codes).issubset(set(whole_codes))):
            raise ValueError("所选税号必须是公告已确认 whole HTS8 的唯一子集")
        selected = sorted(requested_codes)
    if len(selected) > _MAX_CODES:
        raise ValueError(f"单次最多核对 {_MAX_CODES} 个 HTS8；请明确选择子集")

    repository = TradeDataRepository(trade_root or announcement_root)
    catalog = repository.catalog()
    if catalog["dataset_version"] != dataset_version:
        raise TradeDataError("进口数据版本已变化；请重新确认")
    month_source = next((item for item in catalog["months"]
                         if item["month"] == month), None)
    rows: list[dict[str, Any]] = []
    for code in selected:
        query = TradeQuery("US", "import", code, month, month, "CHINA", dataset_version)
        result = repository.query(query)
        if result.get("dataset_version") != dataset_version or len(result["months"]) != 1:
            raise TradeDataError("进口查询返回版本或月份不一致")
        item = result["months"][0]
        if item["month"] != month or item["status"] not in {
            "observed", "not_observed", "no_record", "not_processed"
        }:
            raise TradeDataError("进口查询返回无效观察状态")
        matched = item.get("matched_hts10", 0)
        observed_subcodes = item.get("observed_hts10", 0)
        if (type(matched) is not int or type(observed_subcodes) is not int
                or matched < 0 or not 0 <= observed_subcodes <= matched):
            raise TradeDataError("进口查询返回无效的细分行观察数量")
        rows.append({
            "hts8": code,
            "status": item["status"],
            "observed_import_value_consumption_usd": item.get("value_usd"),
            "matched_hts10": matched,
            "observed_hts10": observed_subcodes,
            "not_observed_hts10": matched - observed_subcodes,
            "classification_year": item["classification_year"],
        })
    observed = sum(item["status"] == "observed" for item in rows)
    if not selected:
        statistical_status = "no_whole_hts8_selected"
    elif observed == len(selected):
        statistical_status = "all_selected_observed"
    elif observed:
        statistical_status = "partly_observed"
    else:
        statistical_status = "none_observed"
    status_counts = {status: sum(item["status"] == status for item in rows)
                     for status in ("observed", "not_observed", "no_record", "not_processed")}
    matched_subcodes = sum(item["matched_hts10"] for item in rows)
    observed_subcodes = sum(item["observed_hts10"] for item in rows)
    if not matched_subcodes:
        subcode_status = "no_matched_hts10"
    elif matched_subcodes == observed_subcodes:
        subcode_status = "all_matched_hts10_observed"
    else:
        subcode_status = "some_matched_hts10_not_observed"
    result = {
        "schema_version": "announcement-import-statistics-v1",
        "policy_id": policy_id,
        "doc_version": doc_version,
        "candidate_digest": digest,
        "dataset_id": catalog["dataset_id"],
        "dataset_version": dataset_version,
        "month": month,
        "reporter": "US",
        "flow": "import",
        "partner": "CHINA",
        "metric": "import_value_consumption_usd",
        "source_url": month_source.get("source_url") if month_source else None,
        "source_sha256": month_source.get("source_sha256") if month_source else None,
        "processed_sha256": month_source.get("processed_sha256") if month_source else None,
        "selected_codes": selected,
        "unselected_whole_codes": sorted(set(whole_codes) - set(selected)),
        "partial_policy_entries": partial_entries,
        "scope_status": "contains_partial_policy_codes" if partial_entries else "whole_hts8_candidates_only",
        "statistical_status": statistical_status,
        "status_counts": status_counts,
        "subcode_observation_status": subcode_status,
        "matched_hts10": matched_subcodes,
        "observed_hts10": observed_subcodes,
        "observed_codes": observed,
        "requested_codes": len(selected),
        "rows": rows,
        "policy_amount_status": "not_determined",
        "boundary": "这些是所选HTS8的中国来源美国消费进口统计；金额只合计已观测细分行，"
                    "未观测行不补零。它不是逐笔政策适用额、税款、损失或因果效果；"
                    "原文条件、商品限定和跨年分类需另行审阅。此结果不放行旧A3报告。",
    }
    result["result_sha256"] = _digest(result)
    return result


__all__ = ["inspect_published_import_coverage"]
