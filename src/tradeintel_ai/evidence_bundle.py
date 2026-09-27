"""Deterministic, version-bound observations for the v2 research brief."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from copy import deepcopy
from typing import Any


def _percent(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    value = (Decimal(numerator) * Decimal("100") / Decimal(denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return float(value)


def _check_trade(trade: dict[str, Any], sheet: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if 'schema_version' in sheet:
        from .policy_facts_contract import validate_policy_facts
        validate_policy_facts(sheet)
    if trade.get("status") != "ok" or trade.get("data_version") != sheet.get("data_version"):
        raise ValueError("trade evidence is not bound to the policy fact sheet")
    data = trade.get("data") or {}
    if data.get("policy_id") != sheet.get("policy_id") or data.get("coverage_complete") is not True:
        raise ValueError("incomplete or cross-case trade evidence")
    if data.get("measure") != "import_value_consumption_usd" or data.get("origin") != "China":
        raise ValueError("v2 requires China consumption-import evidence")
    series = data.get("series")
    months = data.get("requested_months")
    if not isinstance(series, list) or not series or [row.get("month") for row in series] != months:
        raise ValueError("trade months are not ordered or bound")
    known = {row.get("hts8") for row in sheet.get("product_rates", [])}
    if not known:
        if sheet.get('policy_id') != 'us_301_solar2024':
            raise ValueError('policy product mapping missing')
        known = {"85414200", "85414300"}
    rows: list[dict[str, Any]] = []
    for month in series:
        products = month.get("product_breakdown")
        if not isinstance(products, list) or not products or len({p.get("hts8") for p in products}) != len(products):
            raise ValueError("duplicate or missing product rows")
        expected = {data['hts8']} if data.get('hts8') else known
        if {p.get('hts8') for p in products} != expected:
            raise ValueError('trade product coverage does not match requested scope')
        for row in products:
            if row.get("hts8") not in known:
                raise ValueError("trade product is outside policy facts")
            world = row.get("all_origins_value_usd")
            china = row.get("china_value_usd")
            if type(world) is not int or type(china) is not int or world < 0 or china < 0 or china > world:
                raise ValueError("invalid trade amount")
            rows.append({"month": month["month"], **row})
    return data, rows


def build_evidence_bundle(
    trade: dict[str, Any], sheet: dict[str, Any], *, focus: str = "contrast"
) -> dict[str, Any]:
    """Compute metric identities and observations; no model or network calls."""
    if focus not in {"china_amount", "china_share", "contrast"}:
        raise ValueError("unknown v2 focus")
    data, rows = _check_trade(trade, sheet)
    if len({row["month"] for row in rows}) != 1:
        raise ValueError("monthly v2 brief requires one month")
    month = rows[0]["month"]
    scope_world = sum(row["all_origins_value_usd"] for row in rows)
    scope_china = sum(row["china_value_usd"] for row in rows)
    metrics: list[dict[str, Any]] = []
    profiles: list[dict[str, Any]] = []
    trade_sources = []
    for source in trade.get('evidence', {}).get('sources', []):
        item = deepcopy(source)
        item.setdefault('id', 'trade:' + hashlib.sha256(json.dumps(source,sort_keys=True).encode()).hexdigest())
        trade_sources.append(item)
    source_refs = [s['id'] for s in trade_sources]
    for row in rows:
        code = row["hts8"]
        metric_prefix = f"metric.{month}.{code}"
        profile = {
            "hts8": code,
            "world_import_usd": row["all_origins_value_usd"],
            "china_import_usd": row["china_value_usd"],
            # Recompute from bound monetary evidence; cached percentages are
            # never authoritative for this derived observation.
            "china_share_of_product_percent": _percent(row["china_value_usd"], row["all_origins_value_usd"]),
            "product_share_of_scope_world_percent": _percent(row["all_origins_value_usd"], scope_world),
            "product_share_of_scope_china_percent": _percent(row["china_value_usd"], scope_china),
        }
        profiles.append(profile)
        for suffix, value, numerator_id, denominator_id in (
            ("world_import_usd", row["all_origins_value_usd"], None, None),
            ("china_import_usd", row["china_value_usd"], None, None),
            ("china_share_of_product_percent", profile["china_share_of_product_percent"],
             f"{metric_prefix}.china_import_usd", f"{metric_prefix}.world_import_usd"),
            ("product_share_of_scope_world_percent", profile["product_share_of_scope_world_percent"],
             f"{metric_prefix}.world_import_usd", "metric.scope.world_import_usd"),
            ("product_share_of_scope_china_percent", profile["product_share_of_scope_china_percent"],
             f"{metric_prefix}.china_import_usd", "metric.scope.china_import_usd"),
        ):
            metrics.append({
                "id": f"{metric_prefix}.{suffix}",
                "metric_type": suffix,
                "product_scope": code,
                "period": month,
                "measure": "import_value_consumption_usd" if suffix.endswith("usd") else "share",
                "unit": "USD" if suffix.endswith("usd") else "percent",
                "value": value,
                "status": "known" if value is not None else "unknown",
                "numerator_id": numerator_id,
                "denominator_id": denominator_id,
                "derived_from": "trade-evidence.json",
                "source_refs": list(dict.fromkeys(source_refs)),
            })
    metrics.extend([
        {"id": "metric.scope.world_import_usd", "metric_type": "scope_world_import_usd", "product_scope": "all", "period": month,
         "measure": "import_value_consumption_usd", "unit": "USD", "value": scope_world, "status": "known", "derived_from": "trade-evidence.json",
         "source_refs": list(dict.fromkeys(source_refs))},
        {"id": "metric.scope.china_import_usd", "metric_type": "scope_china_import_usd", "product_scope": "all", "period": month,
         "measure": "import_value_consumption_usd", "unit": "USD", "value": scope_china, "status": "known", "derived_from": "trade-evidence.json",
         "source_refs": list(dict.fromkeys(source_refs))},
    ])
    max_amount = max((p["china_import_usd"] for p in profiles), default=None)
    max_share = max((p["china_share_of_product_percent"] for p in profiles
                     if p["china_share_of_product_percent"] is not None), default=None)
    amount_leaders = sorted(p["hts8"] for p in profiles if p["china_import_usd"] == max_amount) if max_amount is not None else []
    share_leaders = sorted(p["hts8"] for p in profiles if p["china_share_of_product_percent"] == max_share) if max_share is not None else []
    observations: list[dict[str, Any]] = []
    if amount_leaders and len(profiles) > 1:
        observations.append({"id": "observation.amount_leader", "type": "amount_leader", "period": month,
                             "product_scope": "all", "metric_ids": [f"metric.{month}.{code}.china_import_usd" for code in amount_leaders],
                             "value": amount_leaders, "meaning": "中国原产金额最高的登记商品（并列保留）"})
    if share_leaders and len(profiles) > 1:
        observations.append({"id": "observation.share_leader", "type": "share_leader", "period": month,
                             "product_scope": "all", "metric_ids": [f"metric.{month}.{code}.china_share_of_product_percent" for code in share_leaders],
                             "value": share_leaders, "meaning": "中国来源占该商品美国进口比例最高的登记商品（并列保留）"})
    if amount_leaders and share_leaders and set(amount_leaders) != set(share_leaders):
        observations.append({"id": "observation.rank_contrast", "type": "rank_contrast", "period": month,
                             "product_scope": "all", "metric_ids": [m['id'] for m in metrics if m['metric_type'] in ('china_import_usd','china_share_of_product_percent')],
                             "value": {"amount_leader": amount_leaders, "share_leader": share_leaders},
                             "meaning": "金额排序与中国来源占比排序的关注对象不同"})
    if len(profiles) == 1:
        observations.append({"id": "observation.single_product_profile", "type": "single_product_profile", "period": month,
                             "product_scope": profiles[0]["hts8"], "metric_ids": [m["id"] for m in metrics if m.get("product_scope") == profiles[0]["hts8"]],
                             "value": profiles[0]["hts8"], "meaning": "单个商品的金额与来源份额概况"})
    limitations = list(trade.get("limitations") or [])
    limitations.extend(sheet.get("limitations") or [])
    limitations.extend([
        "观察描述统计关系，不证明关税造成贸易变化。",
        "中国来源占比不等于中国出口对美国的依赖，也不等于替代供应能力。",
        "金额不是逐笔实际税基、企业税款或损失。",
    ])
    seen: set[str] = set()
    limitations = [item for item in limitations if isinstance(item, str) and not (item in seen or seen.add(item))]
    from .policy_product_details import project
    current_facts = project(sheet, [p['hts8'] for p in profiles])
    return {
        "schema_version": "evidence-bundle-v2",
        "policy_id": sheet["policy_id"], "data_version": sheet["data_version"],
        "request": {"month": month, "product": data.get("hts8") or "all", "focus": focus},
        "tool_result_sha256": hashlib.sha256(json.dumps(trade, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        "policy_facts_sha256": hashlib.sha256(json.dumps(sheet, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        "policy_facts": current_facts,
        "metrics": metrics, "profiles": profiles, "observations": observations,
        "limitations": [{"id": f"limitation.{index+1}", "text": text} for index, text in enumerate(limitations)],
        "sources": trade_sources + deepcopy(current_facts.get('sources', [])),
        "boundaries": {"causal_claim": False, "model_generated": False, "legal_approval": False},
    }


def render_observations(bundle: dict[str, Any]) -> list[str]:
    """Human-readable deterministic facts; values are not generated by the model."""
    profiles = {p["hts8"]: p for p in bundle["profiles"]}
    lines = ["## 数据观察（程序计算）", "", f"统计期：{bundle['request']['month']}；数据版本：`{bundle['data_version']}`。", ""]
    for observation in bundle["observations"]:
        if observation["type"] == "amount_leader":
            codes = observation["value"]
            amount = profiles[codes[0]]["china_import_usd"]
            lines.append(f"- 中国原产金额最高：{'、'.join(codes)}，金额 {amount:,} 美元。")
        elif observation["type"] == "share_leader":
            codes = observation["value"]
            share = profiles[codes[0]]["china_share_of_product_percent"]
            lines.append(f"- 中国来源占该商品美国进口比例最高：{'、'.join(codes)}，占比 {share:.2f}%。")
        elif observation["type"] == "rank_contrast":
            value = observation["value"]
            lines.append(f"- 关注角度不同会得到不同对象：金额最高是 {'、'.join(value['amount_leader'])}，来源占比最高是 {'、'.join(value['share_leader'])}。")
        elif observation["type"] == "single_product_profile":
            p = profiles[observation["value"]]
            share = '未知（全部来源金额为零）' if p['china_share_of_product_percent'] is None else f"{p['china_share_of_product_percent']:.2f}%"
            lines.append(f"- {p['hts8']}：全部来源金额 {p['world_import_usd']:,} 美元，中国原产金额 {p['china_import_usd']:,} 美元，中国来源占比 {share}。")
    lines += ["", "这些是描述性观察，不是政策因果、税款或损失结论。"]
    return lines
