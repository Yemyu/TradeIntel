"""Deterministic multi-period evidence for ``analysis-request-v1``.

The builder consumes an already version-pinned trade-series result.  It never
downloads data, fills missing months, or upgrades an unreviewed comparability
record.  Percentages are calculated with Decimal before display rounding.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import math
from typing import Any, Mapping

from .analysis_request import (request_digest, resolve_query_plan,
                                validate_analysis_request)


SCHEMA_VERSION = "temporal-evidence-v1"
_PERCENT = Decimal("0.0001")


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _sha(value: Any) -> str:
    return hashlib.sha256(_stable(value).encode("utf-8")).hexdigest()


def _month_key(value: str) -> tuple[int, int]:
    if not isinstance(value, str) or len(value) != 7 or value[4] != "-":
        raise ValueError("月份必须是 YYYY-MM")
    year, month = (int(item) for item in value.split("-", 1))
    if not 1 <= month <= 12:
        raise ValueError("月份无效")
    return year, month


def _month_range(start: str, end: str) -> list[str]:
    year, month = _month_key(start)
    last = _month_key(end)
    result = []
    while (year, month) <= last:
        result.append(f"{year:04d}-{month:02d}")
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return result


def _previous_month(month: str, count: int = 1) -> str:
    year, number = _month_key(month)
    for _ in range(count):
        if number == 1:
            year, number = year - 1, 12
        else:
            number -= 1
    return f"{year:04d}-{number:02d}"


def _number(value: Any, *, name: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} 必须是非负整数或 null")
    return value


def _is_number(value: Any) -> bool:
    return value is None or (type(value) is int and value >= 0)


def _percent(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value.quantize(_PERCENT, rounding=ROUND_HALF_UP))


def _change(current: int | None, base: int | None) -> tuple[int | None, str | None]:
    if current is None or base is None:
        return None, "比较所需月份缺失"
    return current - base, None


def _growth(current: int | None, base: int | None) -> tuple[float | None, str | None]:
    if current is None or base is None:
        return None, "比较所需月份缺失"
    if base == 0:
        return None, "基期为零，增速未定义"
    return _percent(Decimal(current - base) * Decimal(100) / Decimal(base)), None


def _share(china: int | None, world: int | None) -> tuple[float | None, str | None]:
    if china is None or world is None:
        return None, "中国金额或全部来源金额缺失"
    if world == 0:
        return None, "全部来源金额为零，份额未定义"
    if china > world:
        raise ValueError("中国金额不能大于全部来源金额")
    return _percent(Decimal(china) * Decimal(100) / Decimal(world)), None


def _source_records(trade: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    sources = ((trade.get("evidence") or {}).get("sources")
               if isinstance(trade.get("evidence"), Mapping) else [])
    result, ids = [], []
    fingerprints: dict[str, str] = {}
    for source in sources or []:
        if not isinstance(source, Mapping):
            continue
        item = deepcopy(dict(source))
        source_id = item.get("id") or item.get("path") or item.get("url")
        if not source_id:
            source_id = "derived:" + _sha(item)
        item["source_id"] = str(source_id)
        fingerprint = str(item.get("sha256") or item.get("path") or item.get("url") or _sha(item))
        old = fingerprints.get(item["source_id"])
        if old is not None and old != fingerprint:
            raise ValueError("同一 source_id 对应了不同来源内容")
        if old is not None:
            continue
        fingerprints[item["source_id"]] = fingerprint
        result.append(item)
        ids.append(item["source_id"])
    return result, ids


def _comparability_source(comparability: Any, source_id: str | None) -> dict[str, Any] | None:
    if not source_id or comparability is None:
        return None
    candidates = comparability.get("records", comparability) if isinstance(comparability, Mapping) else comparability
    if isinstance(candidates, Mapping):
        candidates = list(candidates.values())
    for record in candidates or []:
        if isinstance(record, Mapping) and record.get("source_id") == source_id:
            source = record.get("source")
            if isinstance(source, Mapping):
                item = deepcopy(dict(source))
                item["source_id"] = source_id
                return item
            return {"source_id": source_id, "kind": "comparability_review",
                    "description": "服务端登记的口径核查记录"}
    return None


def _comparability_status(comparability: Any, *, product: str, metric: str,
                          kind: str, base: str, current: str) -> tuple[str, str | None]:
    """Find an exact host-supplied comparability record, never a broad default."""
    if isinstance(comparability, Mapping):
        candidates = comparability.get("records", comparability)
    else:
        candidates = comparability
    if isinstance(candidates, Mapping):
        candidates = list(candidates.values())
    if isinstance(candidates, list):
        for record in candidates:
            if not isinstance(record, Mapping):
                continue
            if (record.get("product") == product and record.get("metric") == metric
                    and record.get("kind") == kind and record.get("base_period") == base
                    and record.get("period") == current):
                status = record.get("status")
                if status in {"reviewed", "unverified", "incompatible"}:
                    return status, record.get("source_id")
    return "unverified", None


def _metric(metric_id: str, *, value: Any, unit: str, product: str,
            period: str, source_ids: list[str], denominator: str | None = None,
            base_period: str | None = None, status: str = "known",
            reason: str | None = None, **extra: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": metric_id, "value": value, "unit": unit,
        "product_scope": product, "period": period,
        "base_period": base_period, "denominator_definition": denominator,
        "status": status, "source_ids": list(source_ids),
    }
    if reason:
        result["reason"] = reason
    result.update(extra)
    return result


def build_temporal_evidence(trade: Mapping[str, Any], request: Mapping[str, Any], *,
                            comparability: Any = None,
                            query_plan: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build a version-bound evidence object from a pinned trade series."""
    canonical = validate_analysis_request(request)
    if not isinstance(trade, Mapping) or not isinstance(trade.get("data"), Mapping):
        raise ValueError("贸易序列结果缺少 data")
    data = trade["data"]
    if trade.get("status") != "ok" or trade.get("causal_claim") is not False:
        raise ValueError("贸易序列不是已确认的描述性结果")
    if data.get("policy_id") != canonical["policy_id"]:
        raise ValueError("贸易序列政策与分析请求不一致")
    data_version = trade.get("data_version")
    if data_version != canonical["data_version"]:
        raise ValueError("贸易序列版本与分析请求不一致")
    if data.get("measure") != "import_value_consumption_usd" or data.get("origin") != "all_origins":
        raise ValueError("多期证据必须使用全部来源的美国消费进口金额")
    if not isinstance(data.get("series"), list):
        raise ValueError("贸易序列缺少 series")
    coverage_complete = data.get("coverage_complete")
    if not isinstance(coverage_complete, bool):
        raise ValueError("贸易序列 coverage_complete 必须是布尔值")
    missing_months = data.get("missing_months") or []
    if not isinstance(missing_months, list) or any(
            not isinstance(month, str) for month in missing_months):
        raise ValueError("贸易序列 missing_months 无效")
    plan = dict(query_plan or resolve_query_plan(canonical))
    required_months = plan.get("required_months")
    if not isinstance(required_months, list) or not required_months:
        raise ValueError("query_plan 缺少 required_months")
    rows: dict[str, Mapping[str, Any]] = {}
    for row in data["series"]:
        if not isinstance(row, Mapping) or not isinstance(row.get("month"), str):
            raise ValueError("贸易序列含无效月份行")
        month = str(row["month"])
        if month in rows:
            raise ValueError(f"贸易序列含重复月份：{month}")
        rows[month] = row
    missing_plan_months = set(required_months) - set(rows)
    if missing_plan_months:
        # A missing comparison base must not prevent the report from showing
        # the requested display window.  Materialise an empty row so coverage
        # and the corresponding comparison metric become explicit unknowns.
        for month in sorted(missing_plan_months):
            rows[month] = {"month": month, "product_breakdown": []}
    tool_missing_comparison = False
    if data.get("requested_months") is not None:
        if not isinstance(data["requested_months"], list):
            raise ValueError("贸易工具 requested_months 必须是列表")
        requested = list(data["requested_months"])
        if set(plan.get("display_months") or []) - set(requested):
            raise ValueError("贸易工具登记的展示月份少于请求计划")
        if set(required_months) - set(requested):
            tool_missing_comparison = True
    months = list(plan.get("display_months") or [])
    if not months:
        raise ValueError("query_plan 缺少 display_months")
    source_records, source_ids = _source_records(trade)
    requested_products = canonical["products"]
    breakdowns: dict[str, dict[str, Mapping[str, Any]]] = {}
    coverage: list[dict[str, Any]] = []
    limitations = list(trade.get("limitations") or [])
    if missing_plan_months:
        limitations.append("请求计划中的月份未返回数据行，相关覆盖或比较保留为未知："
                           + "、".join(sorted(missing_plan_months)))
    if tool_missing_comparison:
        limitations.append("比较基月未被贸易工具请求，相关比较保留为未知。")
    if not coverage_complete and missing_months:
        limitations.append("绑定发布版本缺少月份：" + "、".join(sorted(set(missing_months))))
    metrics: list[dict[str, Any]] = []
    metric_lookup: dict[tuple[str, str, str], str] = {}
    observations: list[dict[str, Any]] = []
    origin_observation_ids: dict[str, str] = {}

    for month in required_months:
        row = rows.get(month)
        available: dict[str, Mapping[str, Any]] = {}
        raw_breakdown = (row or {}).get("product_breakdown", [])
        if not isinstance(raw_breakdown, list):
            raise ValueError(f"{month} product_breakdown 不是列表")
        for item in raw_breakdown:
            if not isinstance(item, Mapping) or not isinstance(item.get("hts8"), str):
                raise ValueError(f"{month} 含无效商品明细")
            code = str(item["hts8"])
            if code in available:
                raise ValueError(f"{month} 含重复商品：{code}")
            available[code] = item
        breakdowns[month] = available
        for code in requested_products:
            item = available.get(code)
            world_value = item.get("all_origins_value_usd") if item else None
            china_value = item.get("china_value_usd") if item else None
            if item is not None and (not _is_number(world_value) or not _is_number(china_value)):
                raise ValueError(f"{month}/{code} 金额字段不是非负整数或 null")
            status = "observed" if item is not None and world_value is not None and china_value is not None else "missing"
            coverage.append({"month": month, "product": code, "status": status,
                             "data_version": data_version,
                             "reason": None if status == "observed" else ("该月份金额字段缺失" if item is not None else "该月份没有该商品的受信任行")})
            world = _number(world_value,
                            name="all_origins_value_usd")
            china = _number(china_value,
                            name="china_value_usd")
            share, share_reason = _share(china, world)
            values = {
                "world": (world, None if world is not None else "该月份缺少全部来源金额"),
                "china": (china, None if china is not None else "该月份缺少中国原产金额"),
                "other": ((world - china) if world is not None and china is not None else None,
                          None if world is not None and china is not None else "无法由完整两项金额分解其他来源"),
                "share": (share, share_reason),
            }
            for name, (value, reason) in values.items():
                unit = "percent" if name == "share" else "usd"
                metric_id = f"metric:{code}:{month}:{name}"
                metric_lookup[(code, month, name)] = metric_id
                metrics.append(_metric(
                    metric_id, value=value, unit=unit, product=code, period=month,
                    source_ids=source_ids,
                    denominator=("美国全部来源消费进口额" if name == "share" else None),
                    status="known" if value is not None else "unknown", reason=reason,
                ))
            observations.append({
                "id": f"observation:{canonical['policy_id']}:{code}:{month}:level",
                "kind": "level", "metric_ids": [metric_lookup[(code, month, name)]
                                                    for name in ("world", "china", "other", "share")],
                "source_ids": list(source_ids), "scope": {"product": code, "period": month},
                "comparability": "not_applicable",
                "fact_sentence": f"{month} 的 {code} 贸易金额和中国来源份额由程序计算。",
            })

    # Add selected-scope totals only when every requested product is present.
    for month in months:
        product_items = [breakdowns[month].get(code) for code in requested_products]
        if any(item is None for item in product_items):
            continue
        world_values = [_number(item.get("all_origins_value_usd"), name="all_origins_value_usd")
                        for item in product_items]
        china_values = [_number(item.get("china_value_usd"), name="china_value_usd")
                        for item in product_items]
        if any(value is None for value in world_values + china_values):
            continue
        world = sum(value for value in world_values if value is not None)
        china = sum(value for value in china_values if value is not None)
        share, share_reason = _share(china, world)
        for name, value, reason in (("world", world, None), ("china", china, None),
                                    ("other", world - china, None), ("share", share, share_reason)):
            metric_id = f"metric:selected_total:{month}:{name}"
            metrics.append(_metric(metric_id, value=value, unit="percent" if name == "share" else "usd",
                                   product="selected_total", period=month,
                                   source_ids=source_ids,
                                   denominator=("美国全部来源消费进口额" if name == "share" else None),
                                   status="known" if value is not None else "unknown", reason=reason))

    if "origins" in canonical["comparisons"]:
        anchor = canonical["window"]["anchor_month"]
        for code in requested_products:
            item = breakdowns.get(anchor, {}).get(code)
            origin_rows = (item or {}).get("origin_breakdown") if item else None
            if not isinstance(origin_rows, list):
                continue
            checked: list[dict[str, Any]] = []
            seen_origins: set[str] = set()
            for origin in origin_rows:
                if not isinstance(origin, Mapping) or not isinstance(origin.get("origin_code"), str):
                    raise ValueError(f"{anchor}/{code} 来源明细无效")
                origin_code = str(origin["origin_code"])
                if origin_code in seen_origins or not _is_number(origin.get("value_usd")):
                    raise ValueError(f"{anchor}/{code} 来源明细重复或金额无效")
                seen_origins.add(origin_code)
                checked.append({"origin_code": origin_code,
                                "origin_name": str(origin.get("origin_name") or ""),
                                "value_usd": _number(origin.get("value_usd"), name="origin.value_usd")})
            world = _number((item or {}).get("all_origins_value_usd"), name="all_origins_value_usd")
            if world is None or sum(int(row["value_usd"]) for row in checked) != world:
                raise ValueError(f"{anchor}/{code} 来源明细与全部来源金额不守恒")
            top = checked[:5]
            rest_value = sum(int(row["value_usd"]) for row in checked[5:])
            origin_metric_ids: list[str] = []
            for row in top:
                metric_id = f"metric:{code}:{anchor}:origin:{row['origin_code']}"
                metrics.append(_metric(metric_id, value=row["value_usd"], unit="usd",
                                       product=code, period=anchor, source_ids=source_ids,
                                       origin_code=row["origin_code"], origin_name=row["origin_name"]))
                origin_metric_ids.append(metric_id)
            if len(checked) > 5:
                metric_id = f"metric:{code}:{anchor}:origin:other"
                metrics.append(_metric(metric_id, value=rest_value, unit="usd",
                                       product=code, period=anchor, source_ids=source_ids,
                                       origin_code="other", origin_name="其余来源合计"))
                origin_metric_ids.append(metric_id)
            observation_id = f"observation:{canonical['policy_id']}:{code}:{anchor}:origins"
            observations.append({
                "id": observation_id, "kind": "composition", "metric_ids": origin_metric_ids,
                "source_ids": list(source_ids), "scope": {"product": code, "period": anchor,
                                                            "top_n": 5, "rest_included": len(checked) > 5},
                "comparability": "not_applicable",
                "fact_sentence": f"{anchor} 的 {code} 来源地按代码汇总，列出金额前五及其余合计。",
            })
            origin_observation_ids[code] = observation_id

    anchor = canonical["window"]["anchor_month"]
    for kind in canonical["comparisons"]:
        if kind == "origins":
            missing_origins = [code for code in requested_products if code not in origin_observation_ids]
            if missing_origins:
                limitations.append("来源地结构只对已提供逐来源明细的商品展示；缺失商品不补零。")
                observations.append({
                    "id": f"observation:{canonical['policy_id']}:origins:{anchor}:coverage",
                    "kind": "coverage", "metric_ids": [], "source_ids": list(source_ids),
                    "scope": {"period": anchor, "products": missing_origins},
                    "comparability": "unavailable",
                    "fact_sentence": "部分商品没有完整来源地明细，无法列出来源排名。",
                })
            continue
        if kind == "series":
            observations.append({
                "id": f"observation:{canonical['policy_id']}:series:{anchor}",
                "kind": "level", "metric_ids": [metric_lookup[(code, anchor, "world")]
                                                    for code in requested_products
                                                    if (code, anchor, "world") in metric_lookup],
                "source_ids": list(source_ids), "scope": {"periods": months, "products": requested_products},
                "comparability": "not_applicable",
                "fact_sentence": "逐月金额序列按原始统计口径列示；不自动把首末月差异称为政策效果。",
            })
            continue
        base = _previous_month(anchor, 1 if kind == "mom" else 12)
        for code in requested_products:
            status, comparison_source = _comparability_status(
                comparability, product=code, metric="trade_exposure", kind=kind,
                base=base, current=anchor)
            if comparison_source and comparison_source not in source_ids:
                extra_source = _comparability_source(comparability, comparison_source)
                if extra_source is None:
                    raise ValueError("可比性记录引用了未登记来源")
                source_records.append(extra_source)
                source_ids.append(comparison_source)
            current_world = (breakdowns.get(anchor, {}).get(code) or {}).get("all_origins_value_usd")
            base_world = (breakdowns.get(base, {}).get(code) or {}).get("all_origins_value_usd")
            current_china = (breakdowns.get(anchor, {}).get(code) or {}).get("china_value_usd")
            base_china = (breakdowns.get(base, {}).get(code) or {}).get("china_value_usd")
            current_world = _number(current_world, name="all_origins_value_usd")
            base_world = _number(base_world, name="all_origins_value_usd")
            current_china = _number(current_china, name="china_value_usd")
            base_china = _number(base_china, name="china_value_usd")
            change_world, world_reason = _change(current_world, base_world)
            growth_world, growth_reason = _growth(current_world, base_world)
            change_china, china_reason = _change(current_china, base_china)
            growth_china, china_growth_reason = _growth(current_china, base_china)
            current_share, current_share_reason = _share(current_china, current_world)
            base_share, base_share_reason = _share(base_china, base_world)
            # Recompute the percentage-point difference from the raw integer
            # amounts.  Subtracting display-rounded floats can introduce a
            # one-basis-point error in a report even though the source values
            # are exact.
            if (current_china is not None and current_world not in (None, 0)
                    and base_china is not None and base_world not in (None, 0)):
                share_delta = _percent(
                    (Decimal(current_china) * Decimal(100) / Decimal(current_world))
                    - (Decimal(base_china) * Decimal(100) / Decimal(base_world)))
            else:
                share_delta = None
            # Numeric comparison values are released only by an exact
            # reviewed record.  A mathematically computable difference is
            # still unknown to the report when the classification/HTS bridge
            # has not been reviewed.
            comparable = status == "reviewed"
            gate_reason = None if comparable else f"比较口径状态为 {status}，未授权输出跨期数值"
            for name, value, unit, reason in (
                ("world_change", change_world if comparable else None, "usd", gate_reason or world_reason),
                ("world_growth", growth_world if comparable else None, "percent", gate_reason or growth_reason),
                ("china_change", change_china if comparable else None, "usd", gate_reason or china_reason),
                ("china_growth", growth_china if comparable else None, "percent", gate_reason or china_growth_reason),
                ("share_change", share_delta if comparable else None, "percentage_points",
                 gate_reason or current_share_reason or base_share_reason),
            ):
                metric_id = f"metric:{code}:{kind}:{base}:{anchor}:{name}"
                metrics.append(_metric(metric_id, value=value, unit=unit, product=code,
                                       period=anchor, base_period=base, source_ids=source_ids,
                                       status="known" if value is not None else "unknown", reason=reason,
                                       comparability=status))
            observations.append({
                "id": f"observation:{canonical['policy_id']}:{code}:{kind}:{base}:{anchor}",
                "kind": "comparison", "metric_ids": [
                    f"metric:{code}:{kind}:{base}:{anchor}:world_change",
                    f"metric:{code}:{kind}:{base}:{anchor}:world_growth",
                    f"metric:{code}:{kind}:{base}:{anchor}:china_change",
                    f"metric:{code}:{kind}:{base}:{anchor}:china_growth",
                    f"metric:{code}:{kind}:{base}:{anchor}:share_change",
                ],
                # comparison_source has already been appended to source_ids
                # above (and is shared by all metrics in this observation).
                # Do not duplicate it in the observation reference list.
                "source_ids": list(source_ids),
                "scope": {"product": code, "period": anchor, "base_period": base},
                "comparability": status,
                "fact_sentence": (f"{anchor} 与 {base} 的 {code} 变化已按程序计算；"
                                   f"可比性状态为 {status}，不代表政策因果。"),
            })
            if status != "reviewed":
                limitations.append(f"{code} 的 {kind} 比较区间 {base}→{anchor} 尚未完成专项口径核查，保留为 {status}。")

    if not source_records:
        limitations.append("本次证据没有可登记来源记录；不能把数值标为可追溯。")
    result = {
        "schema_version": SCHEMA_VERSION,
        "request_digest": request_digest(canonical),
        "request": deepcopy(canonical),
        "query_plan": deepcopy(plan),
        "policy_binding": deepcopy(canonical["policy_binding"]),
        "data_version": data_version,
        "coverage_by_month_product": coverage,
        "comparability": [item for item in _comparability_records(canonical, anchor, comparability)],
        "metrics": metrics,
        "observations": observations,
        "sources": source_records,
        "limitations": list(dict.fromkeys(str(item) for item in limitations if item)),
    }
    return result


def validate_temporal_evidence(evidence: Mapping[str, Any],
                               request: Mapping[str, Any]) -> dict[str, Any]:
    """Validate IDs and references before a temporal result is persisted.

    This is deliberately a structural validator.  It does not upgrade an
    ``unverified`` comparison, infer missing months, or treat a rendered
    sentence as evidence.  Those decisions belong to the host's data review.
    """
    canonical = validate_analysis_request(request)
    if not isinstance(evidence, Mapping) or evidence.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("temporal-evidence-v1 版本不受支持")
    if evidence.get("request_digest") != request_digest(canonical):
        raise ValueError("证据与分析请求摘要不一致")
    if evidence.get("data_version") != canonical["data_version"]:
        raise ValueError("证据与分析请求数据版本不一致")
    metrics = evidence.get("metrics")
    observations = evidence.get("observations")
    sources = evidence.get("sources")
    if not isinstance(metrics, list) or not isinstance(observations, list) or not isinstance(sources, list):
        raise ValueError("证据 metrics/observations/sources 必须是列表")
    metric_ids = [item.get("id") for item in metrics if isinstance(item, Mapping)]
    observation_ids = [item.get("id") for item in observations if isinstance(item, Mapping)]
    if len(metric_ids) != len(metrics) or any(not isinstance(item, str) or not item for item in metric_ids):
        raise ValueError("证据含无效 metric id")
    if len(metric_ids) != len(set(metric_ids)):
        raise ValueError("证据含重复 metric id")
    if len(observation_ids) != len(observations) or any(not isinstance(item, str) or not item for item in observation_ids):
        raise ValueError("证据含无效 observation id")
    if len(observation_ids) != len(set(observation_ids)):
        raise ValueError("证据含重复 observation id")
    source_ids = set()
    for source in sources:
        if not isinstance(source, Mapping) or not isinstance(source.get("source_id"), str) or not source["source_id"]:
            raise ValueError("证据含无效 source_id")
        if source["source_id"] in source_ids:
            raise ValueError("证据含重复 source_id")
        source_ids.add(source["source_id"])
    metric_set = set(metric_ids)
    valid_products = set(canonical["products"]) | {"selected_total"}
    allowed_units = {"usd", "percent", "percentage_points"}
    for metric in metrics:
        required_fields = {"id", "value", "unit", "product_scope", "period",
                           "base_period", "denominator_definition", "status", "source_ids"}
        if not required_fields <= set(metric):
            raise ValueError("metric 缺少必需字段")
        if metric.get("product_scope") not in valid_products:
            raise ValueError("metric 商品范围超出请求")
        if metric.get("unit") not in allowed_units:
            raise ValueError("metric 单位无效")
        if not isinstance(metric.get("period"), str):
            raise ValueError("metric period 无效")
        _month_key(metric["period"])
        if metric.get("base_period") is not None:
            if not isinstance(metric["base_period"], str):
                raise ValueError("metric base_period 无效")
            _month_key(metric["base_period"])
        value = metric.get("value")
        if isinstance(value, bool) or (not isinstance(value, (int, float, type(None)))):
            raise ValueError("metric value 类型无效")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("metric value 不能是 NaN 或 Infinity")
        if metric.get("status") not in {"known", "unknown"}:
            raise ValueError("metric status 无效")
        if metric.get("status") == "known" and value is None:
            raise ValueError("known metric 的 value 不能为 null")
        if metric.get("status") == "unknown" and (value is not None or not isinstance(metric.get("reason"), str)):
            raise ValueError("未知 metric 必须是 null 并说明 reason")
        if not isinstance(metric.get("source_ids"), list):
            raise ValueError("metric source_ids 必须是列表")
        metric_sources = metric.get("source_ids") or []
        if any(not isinstance(source, str) or not source for source in metric_sources):
            raise ValueError("metric source_ids 含无效来源")
        if len(metric_sources) != len(set(metric_sources)):
            raise ValueError("metric source_ids 不能重复")
        if any(source not in source_ids for source in metric_sources):
            raise ValueError("metric 引用了不存在的来源")
        if metric.get("comparability") is not None and metric["comparability"] not in {
                "reviewed", "unverified", "incompatible"}:
            raise ValueError("metric comparability 状态无效")
        if metric.get("comparability") in {"unverified", "incompatible"} and value is not None:
            raise ValueError("未核验或不可比 metric 不能携带跨期数值")
    for observation in observations:
        refs = observation.get("metric_ids")
        if not isinstance(refs, list) or any(ref not in metric_set for ref in refs):
            raise ValueError("observation 引用了不存在的 metric")
        if not isinstance(observation.get("source_ids"), list):
            raise ValueError("observation source_ids 必须是列表")
        observation_sources = observation.get("source_ids") or []
        if any(not isinstance(source, str) or not source for source in observation_sources):
            raise ValueError("observation source_ids 含无效来源")
        if len(observation_sources) != len(set(observation_sources)):
            raise ValueError("observation source_ids 不能重复")
        if any(source not in source_ids for source in observation_sources):
            raise ValueError("observation 引用了不存在的来源")
        if observation.get("kind") not in {"level", "comparison", "composition", "coverage"}:
            raise ValueError("observation kind 无效")
        if not isinstance(observation.get("fact_sentence"), str) or not observation["fact_sentence"].strip():
            raise ValueError("observation 缺少程序事实句")
        if observation.get("comparability") not in {
                "not_applicable", "reviewed", "unverified", "incompatible", "unavailable"}:
            raise ValueError("observation comparability 状态无效")
    coverage = evidence.get("coverage_by_month_product")
    if not isinstance(coverage, list):
        raise ValueError("coverage_by_month_product 必须是列表")
    plan = evidence.get("query_plan")
    if (not isinstance(plan, Mapping)
            or not isinstance(plan.get("required_months"), list)
            or not isinstance(plan.get("display_months"), list)):
        raise ValueError("证据缺少 query_plan.required_months/display_months")
    required_plan_months = plan["required_months"]
    display_plan_months = plan["display_months"]
    if (any(not isinstance(month, str) for month in required_plan_months)
            or any(not isinstance(month, str) for month in display_plan_months)
            or not set(display_plan_months).issubset(set(required_plan_months))):
        raise ValueError("query_plan 月份范围无效")
    for month in required_plan_months:
        _month_key(month)
    unavailable_plan = plan.get("unavailable", [])
    if not isinstance(unavailable_plan, list) or any(not isinstance(item, Mapping)
                                                      for item in unavailable_plan):
        raise ValueError("query_plan.unavailable 无效")
    expected = {(month, code) for month in required_plan_months
                for code in canonical["products"]}
    seen = set()
    for item in coverage:
        if not isinstance(item, Mapping) or item.get("data_version") != canonical["data_version"]:
            raise ValueError("coverage 记录未绑定数据版本")
        key = (item.get("month"), item.get("product"))
        if key in seen or key not in expected or item.get("status") not in {"observed", "missing"}:
            raise ValueError("coverage 记录重复、越界或状态无效")
        if item.get("status") == "missing" and not isinstance(item.get("reason"), str):
            raise ValueError("missing coverage 必须说明 reason")
        seen.add(key)
    if seen != expected:
        raise ValueError("coverage 未覆盖请求窗口中的全部商品月份")
    return deepcopy(dict(evidence))


def _reader_status(status: str) -> str:
    return {
        "not_applicable": "—",
        "reviewed": "已核对",
        "unverified": "尚未核实",
        "incompatible": "口径不一致，不宜直接比较",
        "unavailable": "数据暂缺",
    }.get(status, "状态待核对")


def _reader_source_label(source: Mapping[str, Any]) -> str:
    kind = source.get("kind")
    month = source.get("month")
    if kind == "official_census_archive" and isinstance(month, str):
        return f"美国人口普查局 {month} 月官方进口数据"
    url = str(source.get("url") or "").lower()
    if "federalregister.gov" in url:
        return "美国《联邦公报》政策文件"
    if "govdelivery.com/accounts/usdhscbp" in url:
        return "美国海关与边境保护局公告"
    if "usitc.gov" in url:
        return "美国国际贸易委员会税则文件"
    return "官方来源"


def render_temporal_evidence(evidence: Mapping[str, Any], request: Mapping[str, Any]) -> str:
    """Render a reader-facing deterministic multi-period brief.

    The output is intentionally a report, not a chat answer: every number is
    tied to a metric ID and the text explicitly separates observation from
    comparability and policy causality.
    """
    canonical = validate_analysis_request(request)
    validated = validate_temporal_evidence(evidence, canonical)
    metrics = {item["id"]: item for item in validated["metrics"]}
    product_name = lambda code: str(code)
    lines = ["## 贸易数据与变化", "",
             f"- 统计期：{canonical['window']['start']} 至 {canonical['window']['end']}；最新月份：{canonical['window']['anchor_month']}",
             f"- 涉及商品税号：{', '.join(canonical['products'])}", "",
             "## 阅读说明", "",
             "以下整理的是官方贸易金额与来源份额，说明数据中观察到的变化；"
             "这不是投资建议，月度或同比变化本身也不能证明是某项政策造成的。", "",
             "### 月度进口金额与来源份额", "",
             "| 月份 | 商品税号（商品名称见政策范围） | 全部来源金额（美元） | 中国来源金额（美元） | 中国来源份额 |"]
    lines.append("|---|---|---:|---:|---:|")
    display_months = set(validated["query_plan"]["display_months"])
    for item in validated["coverage_by_month_product"]:
        if item["month"] not in display_months:
            continue
        code, month = item["product"], item["month"]
        world = metrics.get(f"metric:{code}:{month}:world")
        china = metrics.get(f"metric:{code}:{month}:china")
        share = metrics.get(f"metric:{code}:{month}:share")
        def fmt(metric: Mapping[str, Any] | None) -> str:
            if not metric or metric.get("value") is None:
                return "未知（" + str((metric or {}).get("reason") or "缺少数据") + "）"
            return f"{metric['value']:,}" if metric.get("unit") == "usd" else f"{metric['value']:.4f}%"
        lines.append(f"| {month} | {product_name(code)} | {fmt(world)} | {fmt(china)} | {fmt(share)} |")
    comparison_obs = [item for item in validated["observations"] if item.get("kind") == "comparison"]
    if comparison_obs:
        lines.extend(["", "### 环比与同比", "",
                      "| 商品 | 比较 | 金额变化 | 金额增速 | 中国份额变化 | 可比性 |"])
        lines.append("|---|---|---:|---:|---:|---|")
        for obs in comparison_obs:
            refs = [metrics[item] for item in obs["metric_ids"]]
            by_name = {item["id"].rsplit(":", 1)[-1]: item for item in refs}
            def cfmt(name: str) -> str:
                item = by_name[name]
                if item.get("value") is None:
                    return "尚未核实" if item.get("reason") else "暂无可计算结果"
                suffix = "%" if item.get("unit") == "percent" else (
                    " 个百分点" if item.get("unit") == "percentage_points" else "")
                value = item["value"]
                rendered = f"{value:,}" if item.get("unit") == "usd" else str(value)
                return rendered + suffix
            scope = obs["scope"]
            lines.append(f"| {product_name(scope['product'])} | {scope['base_period']} → {scope['period']} | "
                         f"{cfmt('world_change')} | {cfmt('world_growth')} | {cfmt('share_change')} | "
                         f"{_reader_status(obs['comparability'])} |")
    lines.extend(["", "### 数据覆盖与限制", ""])
    display_coverage = [item for item in validated["coverage_by_month_product"]
                        if item["month"] in display_months]
    missing = [item for item in display_coverage if item["status"] == "missing"]
    lines.append(f"- 本表包含 {len(display_coverage)} 个商品—月份记录；缺少数据的记录：{len(missing)}。")
    unavailable = (validated.get("query_plan") or {}).get("unavailable") or []
    if unavailable:
        labels = [f"{item.get('month')}/{item.get('product')}"
                  for item in unavailable[:12]]
        suffix = "等" if len(unavailable) > 12 else ""
        lines.append("- 暂无数据的商品与月份：" + "、".join(labels) + suffix + "。")
    limitations = list(validated.get("limitations") or [])
    has_unverified_detail = any("比较区间" in item and "尚未完成专项口径核查" in item
                               for item in limitations)
    visible_limitations = []
    for limitation in limitations:
        if "比较区间" in limitation and "尚未完成专项口径核查" in limitation:
            continue
        plain = (limitation.replace("unverified", "尚未核实")
                 .replace("mom", "环比").replace("yoy", "同比"))
        if plain not in visible_limitations:
            visible_limitations.append(plain)
    for limitation in visible_limitations:
        lines.append(f"- {limitation}")
    if has_unverified_detail:
        lines.append("- 表中标为“尚未核实”的跨期比较尚未完成口径核对；这不代表变化为零或变化不存在。")
    lines = [line.replace(
        "CONCORD 编码存在性已检查；跨期编码定义连续性仍待审阅，不能据此保证同比可比。",
        "相关商品税号可在官方分类中找到，但跨年分类定义是否连续仍待核对，因此暂不报告同比结论。",
    ).replace(
        "统计期按月发布；缺失月份保留为未知，不能补零。",
        "统计数据按月发布；缺项会明确标示，不会按零处理。",
    ) for line in lines]
    lines.extend(["", "### 数据来源", ""])
    seen_urls: set[str] = set()
    public_sources = []
    for source in validated["sources"]:
        url = source.get("url")
        if not isinstance(url, str) or not url.startswith("https://") or url in seen_urls:
            continue
        seen_urls.add(url)
        public_sources.append(f"[{_reader_source_label(source)}]({url})")
    if public_sources:
        lines.extend(f"- {source}" for source in public_sources)
    else:
        lines.append("本次所用来源已在项目资料中登记。")
    return "\n".join(lines) + "\n"


def _comparability_records(request: Mapping[str, Any], anchor: str, supplied: Any) -> list[dict[str, Any]]:
    records = []
    for kind in request["comparisons"]:
        if kind in {"series", "origins"}:
            continue
        base = _previous_month(anchor, 1 if kind == "mom" else 12)
        for product in request["products"]:
            status, source_id = _comparability_status(supplied, product=product,
                                                      metric="trade_exposure", kind=kind,
                                                      base=base, current=anchor)
            record = {"id": f"comparability:{product}:{kind}:{base}:{anchor}",
                      "product": product, "metric": "trade_exposure", "kind": kind,
                      "base_period": base, "period": anchor, "status": status}
            if source_id:
                record["source_id"] = source_id
            records.append(record)
    return records


__all__ = ["SCHEMA_VERSION", "build_temporal_evidence", "validate_temporal_evidence",
           "render_temporal_evidence"]
