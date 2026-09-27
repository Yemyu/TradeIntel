"""Versioned, bounded input view for the public multi-period explanation.

The deterministic program report remains the source of truth.  This module
creates a readable provider view that contains every observation and metric,
but removes repeated labels and audit-only hashes.  The provider can decode
the business meaning from ``view`` alone; the packed sidecar is only a local
audit copy and is never required to understand the request.
"""
from __future__ import annotations

from copy import deepcopy
import csv
import hashlib
import io
import json
from typing import Any, Mapping

from .analysis_request import validate_analysis_request
from .evidence_transport import pack, unpack
from .policy_facts_contract import validate_policy_facts
from .temporal_evidence import validate_temporal_evidence


VIEW_SCHEMA = "public-brief-input-view-v2"
SIDECAR_SCHEMA = "public-brief-input-sidecar-v2"

_LEVEL_MEASURES = ("world", "china", "other", "share")
_COMPARISON_MEASURES = (
    "world_change", "world_growth", "china_change", "china_growth", "share_change"
)
_COMPARISON_SUFFIXES = set(_COMPARISON_MEASURES)
_LEVEL_SUFFIXES = set(_LEVEL_MEASURES)
_META_KEYS = ("unit", "denominator_definition", "status", "comparability", "reason")
_FACT_TEMPLATES = {
    "l": "{period} 的 {product} 贸易金额和中国来源份额由程序计算。",
    "o": "{period} 的 {product} 来源地按代码汇总，列出金额前五及其余合计。",
    "s": "逐月金额序列按原始统计口径列示；不自动把首末月差异称为政策效果。",
    "c": "{period} 与 {base} 的 {product} 变化已按程序计算；可比性状态为 {comparability}，不代表政策因果。",
}
# Repeated official/local prefixes are encoded as ``[prefix_index, suffix]``
# in the wire source table.  Decoding them recovers the exact source ID/URL.
_SOURCE_PREFIXES = (
    "data/processed/policy_exposure/monthly/us_301_review2025_tungsten_solar_",
    "data/processed/policy_exposure/",
    "data/processed/policy/",
    "https://www.census.gov/trade/downloads/",
    "https://www.federalregister.gov/documents/",
    "https://content.govdelivery.com/accounts/USDHSCBP/bulletins/",
)


def _encode_source_ref(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    for index, prefix in sorted(enumerate(_SOURCE_PREFIXES), key=lambda item: len(item[1]), reverse=True):
        if value.startswith(prefix) and len(value) - len(prefix) < len(value):
            return [index, value[len(prefix):]]
    return value


def _decode_source_ref(value: Any) -> Any:
    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], int):
        index, suffix = value
        if 0 <= index < len(_SOURCE_PREFIXES) and isinstance(suffix, str):
            return _SOURCE_PREFIXES[index] + suffix
        raise ValueError("压缩来源引用前缀无效")
    return value


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _sha(value: Any) -> str:
    return hashlib.sha256(_stable(value).encode("utf-8")).hexdigest()


def _required_str(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} 无效")
    return value


def _source_aliases(evidence: Mapping[str, Any]) -> tuple[dict[str, str], list[list[Any]]]:
    sources = evidence.get("sources")
    if not isinstance(sources, list):
        raise ValueError("证据来源目录无效")
    aliases: dict[str, str] = {}
    url_aliases: dict[str, str] = {}
    rows: list[list[Any]] = []
    for index, source in enumerate(sources, 1):
        if not isinstance(source, Mapping):
            raise ValueError("证据来源含无效记录")
        source_id = _required_str(source.get("source_id"), "证据 source_id")
        if source_id in aliases:
            raise ValueError("证据来源 source_id 重复")
        alias = f"s{index}"
        aliases[source_id] = alias
        # The provider needs citable source ID/URL and source type.  Local
        # paths are already the source IDs; month/file/hash fields stay in
        # the host-side audit record.
        url = source.get("url")
        rows.append([alias, source.get("kind"), _encode_source_ref(source_id),
                     None if url == source_id else _encode_source_ref(url)])
    return aliases, rows


def _source_set_aliases(source_ids: list[Any], aliases: Mapping[str, str],
                        sets: dict[tuple[str, ...], str], rows: list[list[Any]]) -> str:
    if not isinstance(source_ids, list) or any(not isinstance(value, str) for value in source_ids):
        raise ValueError("证据引用来源列表无效")
    try:
        key = tuple(aliases[value] for value in source_ids)
    except KeyError as exc:
        raise ValueError("证据引用了来源目录之外的 source_id") from exc
    if key not in sets:
        sets[key] = f"ss{len(sets) + 1}"
        rows.append([sets[key], list(key)])
    return sets[key]


def _source_set_value(group: Mapping[str, Any], index: int, count: int) -> str:
    value = group.get("source_set")
    if isinstance(value, str):
        return value
    if isinstance(value, list) and len(value) == count and isinstance(value[index], str):
        return value[index]
    raise ValueError("指标来源集合缺失或长度不一致")


def _metric_defaults(family: str, measure: str) -> dict[str, Any]:
    if family == "level":
        if measure == "share":
            return {"unit": "percent", "denominator_definition": "美国全部来源消费进口额",
                    "status": "known", "comparability": None, "reason": None}
        return {"unit": "usd", "denominator_definition": None, "status": "known",
                "comparability": None, "reason": None}
    if family == "comparison":
        units = {"world_change": "usd", "world_growth": "percent",
                 "china_change": "usd", "china_growth": "percent",
                 "share_change": "percentage_points"}
        return {"unit": units[measure], "denominator_definition": None,
                "status": None, "comparability": None, "reason": None}
    if family == "origin":
        return {"unit": "usd", "denominator_definition": None, "status": "known",
                "comparability": None, "reason": None}
    raise ValueError("指标 family 不受支持")


def _metric_meta(metric: Mapping[str, Any]) -> dict[str, Any]:
    return {key: metric.get(key) for key in _META_KEYS}


def _parse_metric_id(metric_id: str) -> tuple[str, tuple[Any, ...]]:
    parts = metric_id.split(":")
    if len(parts) == 4 and parts[0] == "metric" and parts[-1] in _LEVEL_SUFFIXES:
        return "level", (parts[1], parts[2], parts[3])
    if len(parts) == 6 and parts[0] == "metric" and parts[-1] in _COMPARISON_SUFFIXES:
        return "comparison", (parts[1], parts[2], parts[3], parts[4], parts[5])
    if len(parts) == 5 and parts[0] == "metric" and parts[3] == "origin":
        return "origin", (parts[1], parts[2], parts[4])
    raise ValueError(f"无法编码指标 ID：{metric_id}")


def _metric_id(family: str, key: tuple[Any, ...], measure: str | None = None) -> str:
    if family == "level":
        product, period, default_measure = key
        return f"metric:{product}:{period}:{measure or default_measure}"
    if family == "comparison":
        product, kind, base_period, period, default_measure = key
        return f"metric:{product}:{kind}:{base_period}:{period}:{measure or default_measure}"
    if family == "origin":
        product, period, origin_code = key
        return f"metric:{product}:{period}:origin:{origin_code}"
    raise ValueError("无法重建指标 ID")


def _observation_key(observation: Mapping[str, Any], products: list[str],
                     periods: list[str]) -> list[Any]:
    """Encode scope and ID components without repeating the policy prefix."""
    observation_id = _required_str(observation.get("id"), "观察 ID")
    parts = observation_id.split(":")
    kind = observation.get("kind")
    scope = observation.get("scope") if isinstance(observation.get("scope"), Mapping) else {}
    if kind == "comparison" and len(parts) == 6:
        product, comparison_kind, base, period = parts[2], parts[3], parts[4], parts[5]
        if product not in products or base not in periods or period not in periods:
            raise ValueError("比较观察范围不在目录中")
        return ["c", products.index(product), comparison_kind, periods.index(base), periods.index(period)]
    if kind == "composition" and len(parts) == 5:
        product, period = parts[2], parts[3]
        if product not in products or period not in periods:
            raise ValueError("来源构成观察范围不在目录中")
        return ["o", products.index(product), periods.index(period),
                scope.get("top_n"), scope.get("rest_included")]
    if kind == "level" and len(parts) == 5 and parts[2] != "series":
        product, period = parts[2], parts[3]
        if product not in products or period not in periods:
            raise ValueError("水平观察范围不在目录中")
        return ["l", products.index(product), periods.index(period)]
    if kind == "level" and len(parts) == 4 and parts[2] == "series":
        scope_periods = scope.get("periods")
        scope_products = scope.get("products")
        if (not isinstance(scope_periods, list) or not isinstance(scope_products, list)
                or any(value not in periods for value in scope_periods)
                or any(value not in products for value in scope_products)):
            raise ValueError("序列观察范围无效")
        return ["s", [periods.index(value) for value in scope_periods],
                [products.index(value) for value in scope_products]]
    raise ValueError(f"无法编码观察 ID：{observation_id}")


def _observation_id(policy_id: str, key: list[Any], products: list[str],
                    periods: list[str]) -> tuple[str, dict[str, Any]]:
    if not isinstance(key, list) or not key or not isinstance(key[0], str):
        raise ValueError("观察 key 无效")
    tag = key[0]
    if tag == "l" and len(key) == 3:
        product, period = products[key[1]], periods[key[2]]
        return (f"observation:{policy_id}:{product}:{period}:level",
                {"product": product, "period": period})
    if tag == "o" and len(key) == 5:
        product, period = products[key[1]], periods[key[2]]
        return (f"observation:{policy_id}:{product}:{period}:origins",
                {"product": product, "period": period, "top_n": key[3],
                 "rest_included": key[4]})
    if tag == "s" and len(key) == 3:
        scope_periods = [periods[index] for index in key[1]]
        scope_products = [products[index] for index in key[2]]
        return (f"observation:{policy_id}:series:{scope_periods[-1]}",
                {"periods": scope_periods, "products": scope_products})
    if tag == "c" and len(key) == 5:
        product, comparison_kind = products[key[1]], key[2]
        base, period = periods[key[3]], periods[key[4]]
        return (f"observation:{policy_id}:{product}:{comparison_kind}:{base}:{period}",
                {"product": product, "period": period, "base_period": base})
    raise ValueError("观察 key 结构无效")


def _fact_sentence(key: list[Any], comparability: Any, products: list[str],
                   periods: list[str]) -> str:
    tag = key[0]
    if tag == "l":
        return _FACT_TEMPLATES[tag].format(product=products[key[1]], period=periods[key[2]])
    if tag == "o":
        return _FACT_TEMPLATES[tag].format(product=products[key[1]], period=periods[key[2]])
    if tag == "s":
        return _FACT_TEMPLATES[tag]
    if tag == "c":
        return _FACT_TEMPLATES[tag].format(product=products[key[1]], base=periods[key[3]],
                                           period=periods[key[4]], comparability=comparability)
    raise ValueError("无法生成观察事实句")


def select_observation_ids(evidence: Mapping[str, Any]) -> set[str]:
    """Return every validated observation ID in the confirmed evidence."""
    observations = evidence.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ValueError("确认范围没有 observations")
    result: set[str] = set()
    for item in observations:
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
            raise ValueError("观察目录含无效项目")
        if item["id"] in result:
            raise ValueError("观察 ID 重复")
        result.add(item["id"])
    return result


def _normal_source(source: Mapping[str, Any]) -> dict[str, Any]:
    if set(source) - {"source_id", "kind", "url", "path", "sha256", "month", "file_name"}:
        raise ValueError("证据来源包含未声明的投影字段")
    kind = source.get("kind")
    result = {"source_id": source.get("source_id"), "kind": kind,
              "url": source.get("url")}
    if kind == "local_evidence_file":
        result["path"] = source.get("path") or source.get("source_id")
    return result


def _normal_metric(metric: Mapping[str, Any]) -> dict[str, Any]:
    if set(metric) - {"id", "value", "unit", "product_scope", "period", "base_period",
                      "denominator_definition", "status", "source_ids", "comparability",
                      "reason", "origin_code", "origin_name"}:
        raise ValueError("指标包含未声明的投影字段")
    return {"id": metric.get("id"), "value": metric.get("value"),
            "unit": metric.get("unit"), "product_scope": metric.get("product_scope"),
            "period": metric.get("period"), "base_period": metric.get("base_period"),
            "denominator_definition": metric.get("denominator_definition"),
            "status": metric.get("status"), "source_ids": list(metric.get("source_ids") or []),
            "comparability": metric.get("comparability"), "reason": metric.get("reason"),
            "origin_code": metric.get("origin_code"), "origin_name": metric.get("origin_name")}


def _normal_coverage(item: Mapping[str, Any], data_version: str) -> dict[str, Any]:
    if set(item) - {"month", "product", "status", "data_version", "reason"}:
        raise ValueError("覆盖记录包含未声明的投影字段")
    return {"month": item.get("month"), "product": item.get("product"),
            "status": item.get("status"), "data_version": item.get("data_version", data_version),
            "reason": item.get("reason")}


def _normal_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    """Keep business/legal fields; drop only audit-only field references."""
    result = deepcopy(dict(policy))
    for row in result.get("product_rates") or []:
        details = row.get("details") if isinstance(row, dict) else None
        if isinstance(details, dict):
            details.pop("field_refs", None)
    registration = result.get("registration")
    if isinstance(registration, Mapping):
        raw_csv = registration.get("csv_text")
        columns = ["raw_hts", "canonical_hts8", "source_annex", "source_location",
                   "source_url", "implementation_source_url"]
        rows: list[list[Any]] = []
        if isinstance(raw_csv, str) and raw_csv.strip():
            reader = csv.DictReader(io.StringIO(raw_csv))
            redundant = {"policy_id", "product_description", "product_description_zh",
                         "additional_rate_percent", "effective_date"}
            if (not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames)
                    or set(reader.fieldnames) != set(columns) | redundant):
                raise ValueError("政策登记列变化，需要更新输入投影合同")
            rates = {row["hts8"]: row for row in result.get("product_rates") or []}
            for item in reader:
                rate = rates.get(item.get("canonical_hts8"))
                if not rate or None in item:
                    raise ValueError("政策登记行与税号表不一致")
                details = rate.get("details") or {}
                expected = {"policy_id": result.get("policy_id"),
                            "product_description": details.get("registered_name"),
                            "product_description_zh": details.get("registered_name_zh"),
                            "additional_rate_percent": str(rate.get("additional_duty_percent")),
                            "effective_date": details.get("effective_date")}
                if any(item.get(k) != value for k, value in expected.items()):
                    raise ValueError("政策登记被去重字段与发送的政策事实不一致")
                rows.append([item.get(column) for column in columns])
        result["registration"] = {"path": registration.get("path"),
                                   "sha256": registration.get("sha256"),
                                   "encoding": registration.get("encoding"),
                                   "columns": columns, "rows": rows}
    return result


def _project_original(report: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    evidence = report["evidence"]
    normalized_evidence = {
        "schema_version": evidence.get("schema_version"),
        "request_digest": evidence.get("request_digest"),
        "request": deepcopy(evidence.get("request")),
        "query_plan": deepcopy(evidence.get("query_plan")),
        "policy_binding": deepcopy(evidence.get("policy_binding")),
        "data_version": evidence.get("data_version"),
        "coverage_by_month_product": [
            _normal_coverage(item, evidence.get("data_version"))
            for item in evidence.get("coverage_by_month_product") or []
        ],
        "comparability": deepcopy(evidence.get("comparability") or []),
        "metrics": [_normal_metric(item) for item in evidence.get("metrics") or []],
        "observations": deepcopy(evidence.get("observations") or []),
        "sources": [_normal_source(item) for item in evidence.get("sources") or []],
        "limitations": deepcopy(evidence.get("limitations") or []),
    }
    return {"request": deepcopy(report.get("request")), "evidence": normalized_evidence,
            "policy_context": _normal_policy(policy),
            "watchlist": deepcopy(report.get("watchlist") or [])}


def _compact_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if not policy:
        return {}
    validate_policy_facts(policy)
    policy_sources = policy.get("sources") or []
    aliases: dict[str, str] = {}
    url_aliases: dict[str, str] = {}
    source_rows: list[list[Any]] = []
    for index, source in enumerate(policy_sources, 1):
        source_id = _required_str(source.get("id"), "政策来源 ID")
        if source_id in aliases:
            raise ValueError("政策来源 ID 重复")
        alias = f"p{index}"
        aliases[source_id] = alias
        if isinstance(source.get("url"), str):
            url_aliases[source["url"]] = alias
        source_rows.append([alias, source_id, source.get("url"), source.get("text"),
                            source.get("document_sha256"), source.get("text_sha256")])
    clauses: list[str] = []
    clause_alias: dict[str, int] = {}

    def clause_index(value: Any) -> int | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("政策范围条款必须是文字")
        if value not in clause_alias:
            clause_alias[value] = len(clauses)
            clauses.append(value)
        return clause_alias[value]

    rate_rows: list[list[Any]] = []
    for row in policy.get("product_rates") or []:
        if not isinstance(row, Mapping):
            raise ValueError("政策税号记录无效")
        details = row.get("details") if isinstance(row.get("details"), Mapping) else {}
        conditions = details.get("conditions") if isinstance(details.get("conditions"), Mapping) else {}
        exceptions = details.get("exceptions") if isinstance(details.get("exceptions"), Mapping) else {}
        source_id, origin_source_id = row.get("source_id"), row.get("origin_source_id")
        if source_id not in aliases or origin_source_id not in aliases:
            raise ValueError("政策税号记录未绑定政策来源")
        rate_rows.append([
            row.get("hts8"), row.get("additional_duty_percent"), aliases[source_id],
            aliases[origin_source_id], details.get("registered_name"),
            details.get("registered_name_zh"), details.get("registered_name_zh_status"),
            details.get("registered_name_zh_reason"), clause_index(details.get("original_scope_clause")),
            details.get("clause_role"), conditions.get("status"), conditions.get("reason"),
            exceptions.get("status"), exceptions.get("reason"), details.get("origin"),
            details.get("effective_date"), details.get("clock_24h"), details.get("timezone"),
            details.get("entry_events"),
        ])
    registration = policy.get("registration") if isinstance(policy.get("registration"), Mapping) else {}
    registration_columns = ["raw_hts", "canonical_hts8", "source_annex", "source_location",
                            "source_url", "implementation_source_url"]
    registration_rows: list[list[Any]] = []
    raw_csv = registration.get("csv_text")
    if isinstance(raw_csv, str) and raw_csv.strip():
        for item in csv.DictReader(io.StringIO(raw_csv)):
            registration_rows.append([
                item.get("raw_hts"), item.get("canonical_hts8"), item.get("source_annex"),
                item.get("source_location"),
                url_aliases.get(item.get("source_url"), _encode_source_ref(item.get("source_url"))),
                url_aliases.get(item.get("implementation_source_url"),
                                _encode_source_ref(item.get("implementation_source_url"))),
            ])
    return {
        "view": policy.get("policy_view"), "policy_id": policy.get("policy_id"),
        "data_version": policy.get("data_version"), "model_generated": policy.get("model_generated"),
        "legal_approval": policy.get("legal_approval"), "effective_date": policy.get("effective_date"),
        "clock_24h": policy.get("clock_24h"), "timezone": policy.get("timezone"),
        "origin": policy.get("origin"), "entry_events": policy.get("entry_events"),
        "scope_source_id": aliases.get(policy.get("scope_source_id"), policy.get("scope_source_id")),
        "origin_source_id": aliases.get(policy.get("origin_source_id"), policy.get("origin_source_id")),
        "schema_version": policy.get("schema_version"),
        "rate_columns": ["hts8", "additional_rate_percent", "rate_source", "origin_source",
                         "registered_name", "registered_name_zh", "name_status", "name_reason",
                         "scope_clause_index", "clause_role", "condition_status", "condition_reason",
                         "exception_status", "exception_reason", "origin", "effective_date",
                         "clock_24h", "timezone", "entry_events"],
        "rates": rate_rows, "scope_clauses": clauses,
        "sources": {"columns": ["id", "source_id", "url", "text", "document_sha256", "text_sha256"],
                    "rows": source_rows},
        "limitations": deepcopy(policy.get("limitations") or []),
        "registration": {"path": registration.get("path"), "sha256": registration.get("sha256"),
                         "encoding": registration.get("encoding"), "columns": registration_columns,
                         "rows": registration_rows},
    }


def _build_metric_tables(evidence: Mapping[str, Any], products: list[str], periods: list[str],
                         source_aliases: Mapping[str, str], source_sets: dict[tuple[str, ...], str],
                         source_set_rows: list[list[Any]]) -> tuple[dict[str, Any], dict[str, str]]:
    metrics = evidence.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        raise ValueError("证据缺少指标")
    metric_alias: dict[str, str] = {}
    levels: dict[tuple[str, str], dict[str, Any]] = {}
    comparisons: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    origins: list[dict[str, Any]] = []
    origin_names: list[str | None] = []
    origin_name_index: dict[str | None, int] = {}
    semantics: dict[str, Any] = {"level": {}, "comparison": {}, "origin": _metric_defaults("origin", "origin")}
    for measure in _LEVEL_MEASURES:
        semantics["level"][measure] = _metric_defaults("level", measure)
    for measure in _COMPARISON_MEASURES:
        semantics["comparison"][measure] = _metric_defaults("comparison", measure)
    for index, metric in enumerate(metrics, 1):
        if not isinstance(metric, Mapping):
            raise ValueError("指标记录无效")
        metric_id = _required_str(metric.get("id"), "指标 ID")
        if metric_id in metric_alias:
            raise ValueError("指标 ID 重复")
        family, key = _parse_metric_id(metric_id)
        metric_alias[metric_id] = f"m{index}"
        source_set = _source_set_aliases(list(metric.get("source_ids") or []), source_aliases,
                                          source_sets, source_set_rows)
        meta = _metric_meta(metric)
        if family == "level":
            product, period, measure = key
            if product not in products or period not in periods:
                raise ValueError("指标范围不在请求目录中")
            group = levels.setdefault((product, period), {
                "product": products.index(product), "period": periods.index(period),
                "source_sets": {}, "ids": {}, "values": {}, "overrides": {},
            })
            group["source_sets"][measure] = source_set
            group["ids"][measure] = metric_alias[metric_id]
            group["values"][measure] = metric.get("value")
            override = {k: meta[k] for k in _META_KEYS
                        if meta[k] != semantics["level"][measure].get(k)}
            if override:
                group["overrides"][measure] = override
        elif family == "comparison":
            product, kind, base_period, period, measure = key
            if product not in products or base_period not in periods or period not in periods:
                raise ValueError("比较指标范围不在请求目录中")
            group = comparisons.setdefault((product, kind, base_period, period), {
                "product": products.index(product), "kind": kind,
                "base": periods.index(base_period), "period": periods.index(period),
                "source_sets": {}, "ids": {}, "values": {}, "metadata": None,
                "overrides": {},
            })
            group["source_sets"][measure] = source_set
            group["ids"][measure] = metric_alias[metric_id]
            group["values"][measure] = metric.get("value")
            comparison_meta = {key: meta[key] for key in ("status", "comparability", "reason")}
            if group["metadata"] is None:
                group["metadata"] = comparison_meta
            elif group["metadata"] != comparison_meta:
                group["overrides"][measure] = comparison_meta
        else:
            product, period, origin_code = key
            if product not in products or period not in periods:
                raise ValueError("来源指标范围不在请求目录中")
            origin_name = metric.get("origin_name")
            if origin_name not in origin_name_index:
                origin_name_index[origin_name] = len(origin_names)
                origin_names.append(origin_name)
            row = {"id": metric_alias[metric_id], "product": products.index(product),
                   "period": periods.index(period), "origin_code": origin_code,
                   "origin_name_index": origin_name_index[origin_name], "value": metric.get("value"),
                   "source_set": source_set}
            override = {k: meta[k] for k in _META_KEYS
                        if meta[k] != semantics["origin"].get(k)}
            if override:
                row["overrides"] = override
            origins.append(row)

    def finalize(group: dict[str, Any], measures: tuple[str, ...]) -> dict[str, Any]:
        aliases = [group["ids"].get(measure) for measure in measures]
        values = [group["values"].get(measure) for measure in measures]
        source_values = [group["source_sets"].get(measure) for measure in measures]
        source_set: str | list[str] = source_values[0] if len(set(source_values)) == 1 else source_values
        return {"product": group["product"], "period": group["period"],
                "source_set": source_set, "ids": aliases, "values": values,
                "overrides": deepcopy(group.get("overrides") or {})}

    level_columns = ["product", "period", "source_set", "ids", "values", "overrides"]
    level_rows = []
    for group in levels.values():
        row = finalize(group, _LEVEL_MEASURES)
        level_rows.append([row[column] for column in level_columns])
    comparison_rows = []
    for group in comparisons.values():
        row = finalize(group, _COMPARISON_MEASURES)
        row.update({"kind": group["kind"], "base": group["base"],
                    "metadata": deepcopy(group.get("metadata") or {})})
        row = {"product": row["product"], "kind": row["kind"], "base": row["base"],
               "period": row["period"], "source_set": row["source_set"],
               "ids": row["ids"], "values": row["values"], "metadata": row["metadata"],
               "overrides": row["overrides"]}
        comparison_columns = ["product", "kind", "base", "period", "source_set", "ids",
                              "values", "metadata", "overrides"]
        comparison_rows.append([row[column] for column in comparison_columns])
    return ({"semantics": semantics,
             "levels": {"columns": ["product", "period", "source_set", "ids", "values", "overrides"],
                        "measures": list(_LEVEL_MEASURES),
                        "rows": level_rows},
             "comparisons": {"columns": ["product", "kind", "base", "period", "source_set", "ids",
                                           "values", "metadata", "overrides"],
                             "measures": list(_COMPARISON_MEASURES), "rows": comparison_rows},
             "origins": {"columns": ["id", "product", "period", "origin_code", "origin_name_index",
                                      "value", "source_set", "overrides"],
                         "origin_names": origin_names, "rows": [
                             [row.get(column) for column in
                              ["id", "product", "period", "origin_code", "origin_name_index",
                               "value", "source_set", "overrides"]]
                             for row in origins]}}, metric_alias)


def _build_wire_evidence(report: Mapping[str, Any], source_aliases: Mapping[str, str],
                         source_rows: list[list[Any]]) -> tuple[dict[str, Any], dict[str, str]]:
    evidence = report["evidence"]
    request = report["request"]
    products = list(request.get("products") or [])
    for product in [item.get("product_scope") for item in evidence.get("metrics") or []]:
        if product and product not in products:
            products.append(product)
    periods = sorted({item.get("period") for item in evidence.get("metrics") or [] if item.get("period")}
                     | {item.get("base_period") for item in evidence.get("comparability") or []
                        if item.get("base_period")}
                     | {item.get("period") for item in evidence.get("comparability") or []
                        if item.get("period")})
    source_sets: dict[tuple[str, ...], str] = {}
    source_set_rows: list[list[Any]] = []
    metric_view, metric_alias = _build_metric_tables(evidence, products, periods, source_aliases,
                                                     source_sets, source_set_rows)
    observation_rows: list[list[Any]] = []
    observation_alias: dict[str, str] = {}
    for index, item in enumerate(evidence.get("observations") or [], 1):
        observation_id = _required_str(item.get("id"), "观察 ID")
        observation_alias[observation_id] = f"o{index}"
        scope_key = _observation_key(item, products, periods)
        fact = _fact_sentence(scope_key, item.get("comparability"), products, periods)
        if item.get("fact_sentence") != fact:
            raise ValueError("观察事实句与其范围/可比性状态不一致")
        observation_rows.append([
            f"o{index}", item.get("kind"), scope_key,
            item.get("comparability"), [metric_alias.get(value) for value in item.get("metric_ids") or []],
            _source_set_aliases(list(item.get("source_ids") or []), source_aliases, source_sets,
                                source_set_rows),
        ])
    coverage_rows = []
    for item in evidence.get("coverage_by_month_product") or []:
        if item.get("product") not in products or item.get("month") not in periods:
            raise ValueError("覆盖范围不在请求目录中")
        coverage_rows.append([products.index(item["product"]), periods.index(item["month"]),
                              item.get("status"), item.get("reason")])
    comparability_rows = []
    for item in evidence.get("comparability") or []:
        source = item.get("source_id")
        source_alias = source_aliases.get(source) if source else None
        if source and source_alias is None:
            raise ValueError("可比性记录引用了来源目录之外的 source_id")
        comparability_rows.append([
            item.get("id"), products.index(item["product"]), item.get("metric"), item.get("kind"),
            periods.index(item["base_period"]) if item.get("base_period") else None,
            periods.index(item["period"]) if item.get("period") else None,
            item.get("status"), source_alias,
        ])
    wire_evidence = {
        "schema_version": evidence.get("schema_version"), "request_digest": evidence.get("request_digest"),
        "policy_binding": deepcopy(evidence.get("policy_binding")), "data_version": evidence.get("data_version"),
        "query_plan": deepcopy(evidence.get("query_plan")), "products": products, "periods": periods,
        "coverage": {"columns": ["product", "period", "status", "reason"], "rows": coverage_rows},
        "comparability": {"columns": ["id", "product", "metric", "kind", "base", "period", "status", "source"],
                           "rows": comparability_rows},
        "sources": {"columns": ["id", "kind", "source", "url"],
                    "prefixes": list(_SOURCE_PREFIXES), "rows": source_rows},
        "source_sets": {"columns": ["id", "source_ids"], "rows": source_set_rows},
        "metrics": metric_view,
        "observations": {"columns": ["id", "kind", "scope", "comparability", "metric_ids", "source_set"],
                          "rows": observation_rows, "fact_templates": _FACT_TEMPLATES},
        "limitations": deepcopy(evidence.get("limitations") or []),
    }
    return wire_evidence, observation_alias


def build_view(report: Mapping[str, Any], policy_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build a complete v2 provider view and a host-only audit sidecar."""
    if not isinstance(report, Mapping) or report.get("schema_version") != "public-report-v1":
        raise ValueError("公开输入必须来自 public-report-v1")
    request = validate_analysis_request(report.get("request") or {})
    evidence = report.get("evidence")
    validate_temporal_evidence(evidence, request)
    policy = deepcopy(dict(policy_context or {}))
    if policy:
        validate_policy_facts(policy)
    source_aliases, source_rows = _source_aliases(evidence)
    wire_evidence, observation_aliases = _build_wire_evidence(report, source_aliases, source_rows)
    compact_policy = _compact_policy(policy) if policy else {}
    view = {"schema_version": VIEW_SCHEMA,
            "binding": {"policy_id": request["policy_id"], "data_version": evidence.get("data_version"),
                        "request_digest": evidence.get("request_digest"), "policy_context_present": bool(policy)},
            "request": deepcopy(dict(request)), "evidence": wire_evidence,
            "policy": compact_policy, "watchlist": deepcopy(report.get("watchlist") or [])}
    original = {"report": deepcopy(dict(report)), "policy_context": policy}
    semantic = _project_original(report, policy)
    decoded = decode_view(view)
    if decoded != semantic:
        raise ValueError("公开输入 v2 视图无法从 wire 完整解码")
    sidecar = {"schema_version": SIDECAR_SCHEMA, "original": pack(original),
               "original_sha256": _sha(original), "view_sha256": _sha(view),
               "semantic_sha256": _sha(semantic), "observation_aliases": observation_aliases}
    packet = {"view": view, "sidecar": sidecar}
    if restore_view(packet) != original:
        raise ValueError("公开输入视图 sidecar 还原失败")
    return packet


def _decode_policy(view_policy: Mapping[str, Any]) -> dict[str, Any]:
    if not view_policy:
        return {}
    required = ("rate_columns", "rates", "sources", "scope_clauses", "registration")
    if any(key not in view_policy for key in required):
        raise ValueError("政策视图字段不完整")
    source_block = view_policy["sources"]
    expected_columns = ["id", "source_id", "url", "text", "document_sha256", "text_sha256"]
    if not isinstance(source_block, Mapping) or source_block.get("columns") != expected_columns:
        raise ValueError("政策来源表结构无效")
    source_aliases: dict[str, str] = {}
    source_urls: dict[str, str | None] = {}
    sources: list[dict[str, Any]] = []
    for row in source_block.get("rows") or []:
        if not isinstance(row, list) or len(row) != 6:
            raise ValueError("政策来源表行无效")
        alias, source_id, url, text, document_sha, text_sha = row
        if not isinstance(alias, str) or alias in source_aliases:
            raise ValueError("政策来源别名重复")
        source_aliases[alias] = source_id
        source_urls[alias] = url
        sources.append({"id": source_id, "url": url, "text": text,
                        "document_sha256": document_sha, "text_sha256": text_sha})
    rates: list[dict[str, Any]] = []
    columns = view_policy["rate_columns"]
    for row in view_policy.get("rates") or []:
        if not isinstance(row, list) or len(row) != len(columns):
            raise ValueError("政策税号表行无效")
        item = dict(zip(columns, row))
        source = source_aliases.get(item.pop("rate_source"))
        origin_source = source_aliases.get(item.pop("origin_source"))
        if source is None or origin_source is None:
            raise ValueError("政策税号表引用未知来源")
        clause_index = item.pop("scope_clause_index")
        clauses = view_policy["scope_clauses"]
        if clause_index is not None and (not isinstance(clause_index, int)
                                         or not 0 <= clause_index < len(clauses)):
            raise ValueError("政策范围条款索引无效")
        details = {"registered_name": item.pop("registered_name"),
                   "registered_name_zh": item.pop("registered_name_zh"),
                   "registered_name_zh_status": item.pop("name_status"),
                   "registered_name_zh_reason": item.pop("name_reason"),
                   "original_scope_clause": clauses[clause_index] if clause_index is not None else None,
                   "clause_role": item.pop("clause_role"),
                   "conditions": {"status": item.pop("condition_status"), "reason": item.pop("condition_reason")},
                   "exceptions": {"status": item.pop("exception_status"), "reason": item.pop("exception_reason")},
                   "origin": item.pop("origin"), "effective_date": item.pop("effective_date"),
                   "clock_24h": item.pop("clock_24h"), "timezone": item.pop("timezone"),
                   "entry_events": item.pop("entry_events")}
        rates.append({"hts8": item.pop("hts8"),
                      "additional_duty_percent": item.pop("additional_rate_percent"),
                      "source_id": source, "origin_source_id": origin_source, "details": details})
        if item:
            raise ValueError("政策税号表存在未解码字段")
    registration = view_policy.get("registration") or {}
    registration_decoded = deepcopy(registration)
    if isinstance(registration_decoded, dict):
        def resolve_registration_source(value: Any) -> Any:
            if isinstance(value, str) and value in source_urls:
                return source_urls[value]
            return _decode_source_ref(value)
        rows = []
        for row in registration_decoded.get("rows") or []:
            if not isinstance(row, list) or len(row) != 6:
                raise ValueError("政策登记表行无效")
            item = list(row)
            item[4] = resolve_registration_source(item[4])
            item[5] = resolve_registration_source(item[5])
            rows.append(item)
        registration_decoded["rows"] = rows
    return {"schema_version": view_policy.get("schema_version"), "policy_view": view_policy.get("view"),
            "policy_id": view_policy.get("policy_id"), "data_version": view_policy.get("data_version"),
            "model_generated": view_policy.get("model_generated"), "legal_approval": view_policy.get("legal_approval"),
            "effective_date": view_policy.get("effective_date"), "clock_24h": view_policy.get("clock_24h"),
            "timezone": view_policy.get("timezone"), "origin": view_policy.get("origin"),
            "entry_events": deepcopy(view_policy.get("entry_events") or []), "product_rates": rates,
            "scope_source_id": source_aliases.get(view_policy.get("scope_source_id"), view_policy.get("scope_source_id")),
            "origin_source_id": source_aliases.get(view_policy.get("origin_source_id"), view_policy.get("origin_source_id")),
            "sources": sources, "limitations": deepcopy(view_policy.get("limitations") or []),
            "registration": registration_decoded}


def _decode_evidence(view: Mapping[str, Any]) -> dict[str, Any]:
    evidence = view.get("evidence")
    if not isinstance(evidence, Mapping):
        raise ValueError("v2 view 缺少 evidence")
    products, periods = evidence.get("products"), evidence.get("periods")
    if (not isinstance(products, list) or any(not isinstance(x, str) for x in products)
            or not isinstance(periods, list) or any(not isinstance(x, str) for x in periods)):
        raise ValueError("v2 目录 products/periods 无效")
    source_block = evidence.get("sources")
    expected_source_columns = ["id", "kind", "source", "url"]
    if (not isinstance(source_block, Mapping)
            or source_block.get("columns") != expected_source_columns
            or source_block.get("prefixes") != list(_SOURCE_PREFIXES)):
        raise ValueError("证据来源表结构无效")
    source_alias: dict[str, str] = {}
    sources: list[dict[str, Any]] = []
    for row in source_block.get("rows") or []:
        if not isinstance(row, list) or len(row) != 4:
            raise ValueError("证据来源表行无效")
        alias, kind, source_ref, url_ref = row
        source_id = _decode_source_ref(source_ref)
        url = _decode_source_ref(url_ref)
        if not isinstance(alias, str) or alias in source_alias or not isinstance(source_id, str):
            raise ValueError("证据来源别名无效")
        source_alias[alias] = source_id
        if url is None and source_id.startswith("http"):
            url = source_id
        source = {"source_id": source_id, "kind": kind, "url": url}
        if kind == "local_evidence_file":
            source["path"] = source_id
        sources.append(source)
    set_block = evidence.get("source_sets")
    if not isinstance(set_block, Mapping) or set_block.get("columns") != ["id", "source_ids"]:
        raise ValueError("证据来源集合表结构无效")
    source_sets: dict[str, list[str]] = {}
    for row in set_block.get("rows") or []:
        if not isinstance(row, list) or len(row) != 2 or row[0] in source_sets:
            raise ValueError("证据来源集合别名重复")
        aliases = row[1]
        if not isinstance(aliases, list) or any(alias not in source_alias for alias in aliases):
            raise ValueError("证据来源集合引用未知来源")
        source_sets[row[0]] = [source_alias[alias] for alias in aliases]

    metrics_block = evidence.get("metrics")
    if not isinstance(metrics_block, Mapping) or not isinstance(metrics_block.get("semantics"), Mapping):
        raise ValueError("指标表结构无效")
    expected_semantics = {
        "level": {m: _metric_defaults("level", m) for m in _LEVEL_MEASURES},
        "comparison": {m: _metric_defaults("comparison", m) for m in _COMPARISON_MEASURES},
        "origin": _metric_defaults("origin", "origin"),
    }
    if metrics_block["semantics"] != expected_semantics:
        raise ValueError("指标语义字典与版本合同不一致")
    metric_by_alias: dict[str, dict[str, Any]] = {}

    def decode_meta(family: str, measure: str, override: Mapping[str, Any] | None = None,
                    group_meta: Mapping[str, Any] | None = None) -> dict[str, Any]:
        meta = _metric_defaults(family, measure)
        if group_meta:
            meta.update(group_meta)
        if override:
            meta.update(override)
        return meta

    level_table = metrics_block.get("levels") or {}
    if level_table.get("measures") != list(_LEVEL_MEASURES):
        raise ValueError("水平指标顺序与版本合同不一致")
    if level_table.get("columns") != ["product", "period", "source_set", "ids", "values", "overrides"]:
        raise ValueError("水平指标列定义无效")
    for raw_row in level_table.get("rows") or []:
        if not isinstance(raw_row, list) or len(raw_row) != 6:
            raise ValueError("水平指标行结构无效")
        row = dict(zip(level_table["columns"], raw_row))
        if not isinstance(row, Mapping) or not isinstance(row.get("ids"), list) or len(row["ids"]) != 4:
            raise ValueError("水平指标分组无效")
        p_index, period_index = row.get("product"), row.get("period")
        if not isinstance(p_index, int) or not 0 <= p_index < len(products) or not isinstance(period_index, int) or not 0 <= period_index < len(periods):
            raise ValueError("水平指标范围无效")
        values = row.get("values")
        if not isinstance(values, list) or len(values) != 4:
            raise ValueError("水平指标值表无效")
        for index, measure in enumerate(_LEVEL_MEASURES):
            alias = row["ids"][index]
            if not isinstance(alias, str) or alias in metric_by_alias:
                raise ValueError("指标别名无效或重复")
            source_set = _source_set_value(row, index, 4)
            if source_set not in source_sets:
                raise ValueError("指标引用未知来源集合")
            metric_id = _metric_id("level", (products[p_index], periods[period_index], measure))
            meta = decode_meta("level", measure, (row.get("overrides") or {}).get(measure))
            metric_by_alias[alias] = {"id": metric_id, "value": values[index],
                                      "product_scope": products[p_index], "period": periods[period_index],
                                      "base_period": None, **meta, "source_ids": source_sets[source_set],
                                      "origin_code": None, "origin_name": None}
    comparison_table = metrics_block.get("comparisons") or {}
    if comparison_table.get("measures") != list(_COMPARISON_MEASURES):
        raise ValueError("比较指标顺序与版本合同不一致")
    if comparison_table.get("columns") != ["product", "kind", "base", "period", "source_set", "ids",
                                             "values", "metadata", "overrides"]:
        raise ValueError("比较指标列定义无效")
    for raw_row in comparison_table.get("rows") or []:
        if not isinstance(raw_row, list) or len(raw_row) != 9:
            raise ValueError("比较指标行结构无效")
        row = dict(zip(comparison_table["columns"], raw_row))
        if not isinstance(row, Mapping) or not isinstance(row.get("ids"), list) or len(row["ids"]) != 5:
            raise ValueError("比较指标分组无效")
        p_index, base_index, period_index = row.get("product"), row.get("base"), row.get("period")
        if (not isinstance(p_index, int) or not 0 <= p_index < len(products)
                or not isinstance(base_index, int) or not 0 <= base_index < len(periods)
                or not isinstance(period_index, int) or not 0 <= period_index < len(periods)
                or not isinstance(row.get("kind"), str)):
            raise ValueError("比较指标范围无效")
        values = row.get("values")
        if not isinstance(values, list) or len(values) != 5:
            raise ValueError("比较指标值表无效")
        for index, measure in enumerate(_COMPARISON_MEASURES):
            alias = row["ids"][index]
            if not isinstance(alias, str) or alias in metric_by_alias:
                raise ValueError("指标别名无效或重复")
            source_set = _source_set_value(row, index, 5)
            if source_set not in source_sets:
                raise ValueError("比较指标引用未知来源集合")
            metric_id = _metric_id("comparison", (products[p_index], row["kind"], periods[base_index], periods[period_index], measure))
            meta = decode_meta("comparison", measure,
                               (row.get("overrides") or {}).get(measure), row.get("metadata") or {})
            metric_by_alias[alias] = {"id": metric_id, "value": values[index],
                                      "product_scope": products[p_index], "period": periods[period_index],
                                      "base_period": periods[base_index], **meta, "source_ids": source_sets[source_set],
                                      "origin_code": None, "origin_name": None}
    origin_table = metrics_block.get("origins") or {}
    if origin_table.get("columns") != ["id", "product", "period", "origin_code", "origin_name_index",
                                        "value", "source_set", "overrides"]:
        raise ValueError("来源指标列定义无效")
    origin_names = origin_table.get("origin_names")
    if not isinstance(origin_names, list):
        raise ValueError("来源指标名称表缺失")
    for raw_row in origin_table.get("rows") or []:
        if not isinstance(raw_row, list) or len(raw_row) != 8:
            raise ValueError("来源指标行结构无效")
        row = dict(zip(origin_table["columns"], raw_row))
        if not isinstance(row, Mapping) or not isinstance(row.get("id"), str):
            raise ValueError("来源指标行无效")
        p_index, period_index, source_set, alias = row.get("product"), row.get("period"), row.get("source_set"), row["id"]
        if not isinstance(p_index, int) or not 0 <= p_index < len(products) or not isinstance(period_index, int) or not 0 <= period_index < len(periods) or source_set not in source_sets or alias in metric_by_alias:
            raise ValueError("来源指标范围或别名无效")
        origin_name_index = row.get("origin_name_index")
        if (not isinstance(origin_names, list) or not isinstance(origin_name_index, int)
                or not 0 <= origin_name_index < len(origin_names)):
            raise ValueError("来源指标名称索引无效")
        metric_id = _metric_id("origin", (products[p_index], periods[period_index], row.get("origin_code")))
        meta = decode_meta("origin", "origin", row.get("overrides"))
        metric_by_alias[alias] = {"id": metric_id, "value": row.get("value"),
                                  "product_scope": products[p_index], "period": periods[period_index],
                                  "base_period": None, **meta, "source_ids": source_sets[source_set],
                                  "origin_code": row.get("origin_code"), "origin_name": origin_names[origin_name_index]}
    metrics = [metric_by_alias[alias] for alias in sorted(metric_by_alias, key=lambda value: int(value[1:]))]

    observations_block = evidence.get("observations")
    if (not isinstance(observations_block, Mapping)
            or observations_block.get("fact_templates") != _FACT_TEMPLATES):
        raise ValueError("观察表结构无效")
    observations: list[dict[str, Any]] = []
    seen_observations: set[str] = set()
    policy_id = view["binding"].get("policy_id")
    for row in observations_block.get("rows") or []:
        if not isinstance(row, list) or len(row) != 6:
            raise ValueError("观察表行无效")
        alias, kind, scope_key, comparability, metric_aliases, source_set = row
        if not isinstance(alias, str) or not isinstance(metric_aliases, list) or source_set not in source_sets:
            raise ValueError("观察引用无效")
        canonical_id, scope = _observation_id(policy_id, scope_key, products, periods)
        if canonical_id in seen_observations:
            raise ValueError("观察 ID 重复")
        seen_observations.add(canonical_id)
        if any(value not in metric_by_alias for value in metric_aliases):
            raise ValueError("观察引用未知指标")
        fact = _fact_sentence(scope_key, comparability, products, periods)
        observations.append({"id": canonical_id, "kind": kind,
                             "metric_ids": [metric_by_alias[value]["id"] for value in metric_aliases],
                             "source_ids": source_sets[source_set], "scope": scope,
                             "comparability": comparability, "fact_sentence": fact})
    coverage_block = evidence.get("coverage")
    if not isinstance(coverage_block, Mapping):
        raise ValueError("覆盖表结构无效")
    data_version = evidence.get("data_version") or view["binding"].get("data_version")
    coverage = []
    for row in coverage_block.get("rows") or []:
        if not isinstance(row, list) or len(row) != 4:
            raise ValueError("覆盖表行无效")
        p_index, period_index, status, reason = row
        if not isinstance(p_index, int) or not 0 <= p_index < len(products) or not isinstance(period_index, int) or not 0 <= period_index < len(periods):
            raise ValueError("覆盖表索引无效")
        coverage.append({"month": periods[period_index], "product": products[p_index],
                         "status": status, "data_version": data_version, "reason": reason})
    comp_block = evidence.get("comparability")
    if not isinstance(comp_block, Mapping):
        raise ValueError("可比性表结构无效")
    comparability = []
    for row in comp_block.get("rows") or []:
        if not isinstance(row, list) or len(row) != 8:
            raise ValueError("可比性表行无效")
        item_id, p_index, metric, kind, base_index, period_index, status, source = row
        if source is not None and source not in source_alias:
            raise ValueError("可比性引用未知来源")
        item = {"id": item_id, "product": products[p_index], "metric": metric, "kind": kind,
                "base_period": periods[base_index] if base_index is not None else None,
                "period": periods[period_index] if period_index is not None else None, "status": status}
        if source is not None:
            item["source_id"] = source_alias[source]
        comparability.append(item)
    return {"schema_version": evidence.get("schema_version"), "request_digest": evidence.get("request_digest"),
            "request": deepcopy(view.get("request")), "query_plan": deepcopy(evidence.get("query_plan")),
            "policy_binding": deepcopy(evidence.get("policy_binding")), "data_version": data_version,
            "coverage_by_month_product": coverage, "comparability": comparability, "metrics": metrics,
            "observations": observations, "sources": sources,
            "limitations": deepcopy(evidence.get("limitations") or [])}


def decode_view(view: Mapping[str, Any]) -> dict[str, Any]:
    """Decode all business fields using only the provider wire view."""
    if not isinstance(view, Mapping) or view.get("schema_version") != VIEW_SCHEMA:
        raise ValueError("公开输入视图版本无效")
    binding = view.get("binding")
    if not isinstance(binding, Mapping):
        raise ValueError("公开输入视图缺少绑定")
    evidence = _decode_evidence(view)
    policy = _decode_policy(view.get("policy") or {})
    if policy and (policy.get("policy_id") != binding.get("policy_id")
                   or policy.get("data_version") != binding.get("data_version")):
        raise ValueError("政策视图绑定不一致")
    return {"request": deepcopy(view.get("request")), "evidence": evidence,
            "policy_context": policy, "watchlist": deepcopy(view.get("watchlist") or [])}


def restore_view(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Restore the exact host object after validating the v2 wire semantics."""
    if not isinstance(packet, Mapping) or not isinstance(packet.get("view"), Mapping):
        raise ValueError("公开输入视图包无效")
    sidecar = packet.get("sidecar")
    if not isinstance(sidecar, Mapping) or sidecar.get("schema_version") != SIDECAR_SCHEMA:
        raise ValueError("公开输入视图 sidecar 无效")
    view = dict(packet["view"])
    if sidecar.get("view_sha256") != _sha(view):
        raise ValueError("公开输入视图摘要不一致")
    decoded = decode_view(view)
    if sidecar.get("semantic_sha256") != _sha(decoded):
        raise ValueError("公开输入视图业务语义摘要不一致")
    original = unpack(sidecar.get("original") or {})
    if sidecar.get("original_sha256") != _sha(original):
        raise ValueError("公开输入原始对象摘要不一致")
    if decoded != _project_original(original["report"], original.get("policy_context") or {}):
        raise ValueError("公开输入视图与主机原始业务对象不一致")
    return original


__all__ = ["VIEW_SCHEMA", "SIDECAR_SCHEMA", "build_view", "decode_view",
           "restore_view", "select_observation_ids"]
