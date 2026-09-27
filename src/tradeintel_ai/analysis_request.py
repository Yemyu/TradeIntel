"""Validated multi-period analysis requests.

This contract is intentionally separate from ``research-request-v2``.  The
older contract remains single-month compatible; this module refuses to infer a
window or comparison when the caller has not supplied one.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import json
import re
from typing import Any, Mapping


SCHEMA_VERSION = "analysis-request-v1"
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
VERSION_RE = re.compile(r"^[0-9a-f]{64}$")
HTS8_RE = re.compile(r"^\d{8}$")
POLICY_VIEWS = {"archived_event", "verified_as_of"}
COMPARISONS = {"mom", "yoy", "series", "origins"}
REQUEST_FIELDS = {
    "schema_version", "original_question", "policy_id", "policy_binding",
    "products", "window", "comparisons", "data_version", "policy_view",
    "policy_verified_at", "requested_as_of",
}
WINDOW_FIELDS = {"start", "end", "anchor_month", "mode", "selection_reason"}


def _month(value: Any) -> tuple[int, int]:
    if not isinstance(value, str) or not MONTH_RE.fullmatch(value):
        raise ValueError("月份必须是 YYYY-MM")
    year, month = (int(part) for part in value.split("-", 1))
    if year < 1:
        raise ValueError("年份无效")
    return year, month


def _month_leq(left: str, right: str) -> bool:
    return _month(left) <= _month(right)


def _month_add(value: str, offset: int) -> str:
    year, month = _month(value)
    absolute = year * 12 + month - 1 + offset
    if absolute < 0:
        raise ValueError("月份计算超出支持范围")
    return f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"


def _month_list(start: str, end: str) -> list[str]:
    _month(start)
    _month(end)
    if not _month_leq(start, end):
        raise ValueError("月份窗口无效")
    result: list[str] = []
    cursor = start
    while _month_leq(cursor, end):
        result.append(cursor)
        cursor = _month_add(cursor, 1)
    return result


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _normalise_binding(binding: Any, policy_id: str) -> dict[str, Any] | None:
    if binding is None:
        return None
    if not isinstance(binding, dict) or not binding:
        raise ValueError("policy_binding 必须是已确认的对象")
    result = deepcopy(binding)
    if result.get("policy_id") != policy_id:
        raise ValueError("policy_binding 与 policy_id 不一致")
    for key in ("doc_version", "candidate_digest"):
        if key in result and (not isinstance(result[key], str) or not result[key].strip()):
            raise ValueError(f"policy_binding.{key} 无效")
    return result


def _normalise_window(window: Any) -> dict[str, Any]:
    if not isinstance(window, dict) or set(window) != WINDOW_FIELDS:
        raise ValueError("window 字段不完整")
    result = deepcopy(window)
    start, end, anchor = result["start"], result["end"], result["anchor_month"]
    _month(start)
    _month(end)
    _month(anchor)
    if not _month_leq(start, end):
        raise ValueError("window.start 不能晚于 window.end")
    if not _month_leq(start, anchor) or not _month_leq(anchor, end):
        raise ValueError("anchor_month 必须位于请求窗口内")
    if result["mode"] not in {"latest", "explicit"}:
        raise ValueError("window.mode 只能是 latest 或 explicit")
    if not isinstance(result["selection_reason"], str) or not result["selection_reason"].strip():
        raise ValueError("window.selection_reason 不能为空")
    return result


def validate_analysis_request(request: Mapping[str, Any], *,
                              available_products: set[str] | None = None) -> dict[str, Any]:
    """Validate and return a canonical copy of an ``analysis-request-v1``."""
    if not isinstance(request, Mapping) or set(request) != REQUEST_FIELDS:
        raise ValueError("analysis-request-v1 字段不完整或包含未知字段")
    result = deepcopy(dict(request))
    if result["schema_version"] != SCHEMA_VERSION:
        raise ValueError("不支持的分析请求版本")
    if not isinstance(result["original_question"], str) or not 1 <= len(result["original_question"].strip()) <= 2000:
        raise ValueError("original_question 必须是1至2000字")
    if not isinstance(result["policy_id"], str) or not result["policy_id"].strip():
        raise ValueError("policy_id 不能为空")
    result["policy_binding"] = _normalise_binding(result["policy_binding"], result["policy_id"])
    products = result["products"]
    if not isinstance(products, list) or not products:
        raise ValueError("products 必须是非空 HTS8 列表")
    if any(not isinstance(code, str) or not HTS8_RE.fullmatch(code) for code in products):
        raise ValueError("products 只能包含八位 HTS8")
    if len(set(products)) != len(products):
        raise ValueError("products 不能重复")
    if available_products is not None and not set(products).issubset(available_products):
        raise ValueError("products 含未登记商品")
    result["products"] = sorted(products)
    result["window"] = _normalise_window(result["window"])
    comparisons = result["comparisons"]
    if (not isinstance(comparisons, list) or not comparisons
            or any(item not in COMPARISONS for item in comparisons)
            or len(set(comparisons)) != len(comparisons)):
        raise ValueError("comparisons 必须是不重复的 mom/yoy/series/origins 列表")
    if "series" not in comparisons:
        raise ValueError("多期请求必须显式包含 series")
    result["comparisons"] = [item for item in ("series", "mom", "yoy", "origins")
                              if item in comparisons]
    if not isinstance(result["data_version"], str) or not VERSION_RE.fullmatch(result["data_version"]):
        raise ValueError("data_version 必须是已核验版本摘要")
    if result["policy_view"] not in POLICY_VIEWS:
        raise ValueError("policy_view 不受支持")
    for key in ("policy_verified_at", "requested_as_of"):
        value = result[key]
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"{key} 为空时必须使用 null")
        if value is not None:
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"{key} 必须是 YYYY-MM-DD") from exc
    if result["policy_view"] == "verified_as_of" and result["policy_verified_at"] is None:
        raise ValueError("verified_as_of 必须绑定 policy_verified_at")
    if result["requested_as_of"] is not None:
        try:
            date.fromisoformat(result["requested_as_of"])
        except ValueError as exc:
            raise ValueError("requested_as_of 必须是 YYYY-MM-DD") from exc
    result["policy_binding"] = (dict(sorted(result["policy_binding"].items()))
                                 if result["policy_binding"] else None)
    return result


def request_digest(request: Mapping[str, Any]) -> str:
    """Return the identity digest after validation."""
    canonical = validate_analysis_request(request)
    return _digest(canonical)


def default_window(snapshot: Mapping[str, Any], *, lookback: int = 6,
                   products: list[str] | None = None) -> dict[str, Any]:
    """Resolve the latest common complete window from a published snapshot.

    ``lookback=6`` means the anchor month plus five preceding months.  The
    result never reaches beyond the registered snapshot and never uses the
    machine's current calendar month.
    """
    if not isinstance(snapshot, Mapping):
        raise ValueError("发布快照缺失")
    start, end = str(snapshot.get("start") or ""), str(snapshot.get("end") or "")
    _month(start)
    _month(end)
    if lookback < 1 or lookback > 48:
        raise ValueError("lookback 必须在1至48之间")
    candidate_end = end
    selected = list(products or [])
    months = snapshot.get("months")
    if selected and isinstance(months, Mapping):
        common: list[str] = []
        for month in months:
            if not isinstance(month, str) or not MONTH_RE.fullmatch(month):
                continue
            metrics = months[month].get("metrics") if isinstance(months[month], Mapping) else None
            breakdown = metrics.get("product_breakdown") if isinstance(metrics, Mapping) else None
            rows = {str(item.get("hts8")): item for item in breakdown or []
                    if isinstance(item, Mapping) and item.get("hts8")}
            if all(code in rows and _is_complete_amount_row(rows[code]) for code in selected):
                common.append(month)
        if not common:
            raise ValueError("所选商品没有共同完整月份")
        candidate_end = max(common)
    candidate = _month_add(candidate_end, -(lookback - 1))
    if candidate < start:
        candidate = start
    actual_length = len(_month_list(candidate, candidate_end))
    return {"start": candidate, "end": candidate_end, "anchor_month": candidate_end,
            "mode": "latest",
            "selection_reason": f"采用所选商品共同完整的最新发布月份 {candidate_end}，向前取最多六个月（实际 {actual_length} 个月）。"}


def _is_complete_amount_row(row: Any) -> bool:
    return (isinstance(row, Mapping)
            and type(row.get("all_origins_value_usd")) is int
            and row.get("all_origins_value_usd") >= 0
            and type(row.get("china_value_usd")) is int
            and row.get("china_value_usd") >= 0)


def resolve_query_plan(request: Mapping[str, Any], *,
                       available: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Derive display and comparison months without changing the request.

    ``available`` is an optional host-owned month/product coverage map.  It is
    used only to annotate gaps; it never fills a gap or silently drops a
    requested product.  The plan makes a comparison base month explicit so a
    six-month display can still calculate the requested year-over-year pair.
    """
    canonical = validate_analysis_request(request)
    display_months = _month_list(canonical["window"]["start"], canonical["window"]["end"])
    anchor = canonical["window"]["anchor_month"]
    comparison_pairs: list[dict[str, Any]] = []
    required = set(display_months)
    for kind, offset in (("mom", -1), ("yoy", -12)):
        if kind not in canonical["comparisons"]:
            continue
        base = _month_add(anchor, offset)
        required.add(base)
        comparison_pairs.append({"kind": kind, "base_period": base,
                                 "period": anchor, "products": list(canonical["products"])})
    available_months = sorted(required)
    unavailable: list[dict[str, Any]] = []
    if available is not None:
        for month in available_months:
            month_value = available.get(month, {}) if isinstance(available, Mapping) else {}
            for product in canonical["products"]:
                present = False
                if isinstance(month_value, Mapping):
                    if isinstance(month_value.get("products"), (list, tuple, set)):
                        present = product in month_value["products"]
                    elif isinstance(month_value.get(product), bool):
                        present = month_value[product]
                if not present:
                    unavailable.append({"month": month, "product": product,
                                        "reason": "绑定发布版本没有经过完整性核验的该商品月份"})
    return {
        "display_months": display_months,
        "required_months": available_months,
        "anchor_month": anchor,
        "comparison_pairs": comparison_pairs,
        "unavailable": unavailable,
        "selection_reason": canonical["window"]["selection_reason"],
    }


__all__ = ["SCHEMA_VERSION", "COMPARISONS", "validate_analysis_request",
           "request_digest", "default_window", "resolve_query_plan"]
