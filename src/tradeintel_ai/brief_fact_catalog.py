"""Trusted, denominator-explicit facts for the v3 brief prototype.

This module is intentionally deterministic.  The evidence bundle is checked
before it is shown to a model, and the complete input bundle is retained in
the catalog as an audit snapshot.  The snapshot is never sent in the model
payload; it is only used to prove that a published catalog can be rebuilt.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import html
import json
import math
import re
from typing import Any


CATALOG_VERSION = "brief-fact-catalog-v1"
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_HTS8 = re.compile(r"^\d{8}$")
_PRODUCT_KINDS = (
    "world_import_usd",
    "china_import_usd",
    "china_share_of_product_percent",
    "product_share_of_scope_world_percent",
    "product_share_of_scope_china_percent",
)
_SCOPE_KINDS = ("scope_world_import_usd", "scope_china_import_usd")
_MONEY_KINDS = {"world_import_usd", "china_import_usd", *_SCOPE_KINDS}


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: Any) -> str:
    return hashlib.sha256(_stable(value).encode("utf-8")).hexdigest()


def _is_finite_number(value: Any) -> bool:
    return (isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _decimal(value: Any, label: str) -> Decimal:
    if not _is_finite_number(value):
        raise ValueError(f"{label} must be a finite number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} is not numeric") from exc
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    return result


def _money(value: Any) -> str:
    if type(value) is not int or value < 0:
        raise ValueError("fact money must be a non-negative integer")
    return f"{value:,}"


def _percent(value: Any) -> str:
    number = _decimal(value, "fact percentage")
    if number < 0 or number > 100:
        raise ValueError("fact percentage is outside 0..100")
    return f"{float(number):.4f}".rstrip("0").rstrip(".")


def _rounded_percent(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    value = (Decimal(numerator) * Decimal("100") / Decimal(denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return float(value)


def _same_number(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    try:
        return _decimal(left, "number") == _decimal(right, "number")
    except ValueError:
        return False


def _source_ids(sources: list[dict[str, Any]]) -> set[str]:
    return {item["id"] for item in sources}


def _policy_source_ids(policy_facts: dict[str, Any]) -> set[str]:
    return {item["id"] for item in policy_facts.get("sources", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)}


def _validate_policy_identity(bundle: dict[str, Any], profile_codes: set[str]) -> dict[str, Any]:
    policy = bundle.get("policy_facts")
    if not isinstance(policy, dict):
        raise ValueError("policy facts are required for a linked brief")
    if policy.get("policy_id") != bundle.get("policy_id") or policy.get("data_version") != bundle.get("data_version"):
        raise ValueError("policy facts identity does not match the evidence bundle")
    if not policy.get("policy_id") or not policy.get("data_version"):
        raise ValueError("policy facts need a policy ID and data version")
    if policy.get("schema_version") in ("archived-policy-facts-v1", "archived-policy-facts-v2"):
        from .policy_facts_contract import validate_policy_facts
        # Archived projections perform their own provenance checks.  A minimal
        # synthetic fixture remains supported for unit tests and demos.
        validate_policy_facts(policy)
    policy_sources = policy.get("sources")
    if policy_sources is not None:
        if not isinstance(policy_sources, list) or any(not isinstance(item, dict) for item in policy_sources):
            raise ValueError("policy sources must be a list of objects")
        policy_source_values = [item.get("id") for item in policy_sources]
        if (any(not isinstance(value, str) or not value for value in policy_source_values)
                or len(set(policy_source_values)) != len(policy_source_values)):
            raise ValueError("policy source IDs must be unique strings")
        if policy.get("schema_version") == "archived-policy-facts-projection-v2":
            for source in policy_sources:
                if not isinstance(source.get("text"), str) or not source.get("text"):
                    raise ValueError("archived policy sources must retain source text")
                if not isinstance(source.get("url"), str) or not source["url"]:
                    raise ValueError("archived policy sources must retain source URLs")
                if source.get("text_sha256") and hashlib.sha256(source["text"].encode("utf-8")).hexdigest() != source["text_sha256"]:
                    raise ValueError(f"policy source text hash mismatch: {source['id']}")
    rates = policy.get("product_rates")
    if not isinstance(rates, list) or not rates:
        raise ValueError("policy product rates are required as an explicit list")
    # The same source ID must never carry two different texts: bundle sources
    # and policy sources sharing an ID must be byte-identical (or one side has
    # no text at all, in which case the hash still has to agree).
    bundle_sources = bundle.get("sources")
    if isinstance(bundle_sources, list):
        by_id = {item.get("id"): item for item in bundle_sources
                 if isinstance(item, dict) and isinstance(item.get("id"), str)}
        for source in (policy_sources or []):
            twin = by_id.get(source["id"])
            if twin is None:
                continue
            for key in ("text", "url"):
                if (source.get(key) is not None and twin.get(key) is not None
                        and source[key] != twin[key]):
                    raise ValueError(f"conflicting duplicated source text: {source['id']}")
            if (source.get("text_sha256") and twin.get("text_sha256")
                    and source["text_sha256"] != twin["text_sha256"]):
                raise ValueError(f"conflicting duplicated source hash: {source['id']}")
    rate_codes: set[str] = set()
    for row in rates:
        if not isinstance(row, dict) or not isinstance(row.get("hts8"), str) or not _HTS8.fullmatch(row["hts8"]):
            raise ValueError("policy product rate has an invalid HTS8")
        if row["hts8"] in rate_codes:
            raise ValueError("policy product rate IDs must be unique")
        rate_codes.add(row["hts8"])
        for key in ("source_id", "origin_source_id"):
            if key in row and (not isinstance(row[key], str) or not row[key]):
                raise ValueError(f"policy product rate {row['hts8']} has an invalid {key}")
        if "additional_duty_percent" in row:
            rate = _decimal(row["additional_duty_percent"], "additional_duty_percent")
            if rate < 0 or rate > 1000:
                raise ValueError("policy duty rate is outside a plausible range")
    if not profile_codes.issubset(rate_codes):
        raise ValueError("policy facts do not cover every requested product")
    requested = policy.get("requested_products")
    if requested is not None:
        if (not isinstance(requested, list) or any(not isinstance(code, str) for code in requested)
                or set(requested) != profile_codes or len(requested) != len(set(requested))):
            raise ValueError("policy requested_products do not match trade profiles")
    return policy


def _validate_bundle(bundle: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(bundle, dict) or bundle.get("schema_version") != "evidence-bundle-v2":
        raise ValueError("v3 requires an evidence-bundle-v2 object")
    request = bundle.get("request")
    if (not isinstance(request, dict) or not isinstance(request.get("month"), str)
            or not _MONTH.fullmatch(request["month"])):
        raise ValueError("bundle request month must be YYYY-MM")
    if not isinstance(request.get("product"), str) or not request["product"]:
        raise ValueError("bundle request must contain a product scope")
    if request.get("focus") not in {"china_amount", "china_share", "contrast"}:
        raise ValueError("bundle request focus is unsupported")
    for key in ("policy_id", "data_version"):
        if not isinstance(bundle.get(key), str) or not bundle[key].strip():
            raise ValueError(f"bundle {key} is required")
    profiles = bundle.get("profiles")
    metrics = bundle.get("metrics")
    observations = bundle.get("observations")
    sources = bundle.get("sources")
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("bundle profiles are required")
    if not isinstance(metrics, list) or not metrics:
        raise ValueError("bundle metrics are required")
    if not isinstance(observations, list):
        raise ValueError("bundle observations are required")
    if not isinstance(sources, list) or not sources:
        raise ValueError("bundle sources are required")
    if any(not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"] for item in sources):
        raise ValueError("every bundle source needs a non-empty id")
    source_ids = _source_ids(sources)
    if len(source_ids) != len(sources):
        raise ValueError("bundle source IDs must be unique")
    codes = [item.get("hts8") if isinstance(item, dict) else None for item in profiles]
    if any(not isinstance(code, str) or not _HTS8.fullmatch(code) for code in codes):
        raise ValueError("all profile products must be HTS8 strings")
    if len(set(codes)) != len(codes):
        raise ValueError("profile products must be unique")
    code_set = set(codes)
    if request["product"] != "all" and code_set != {request["product"]}:
        raise ValueError("single requested product must exactly match the profile scope")
    policy = _validate_policy_identity(bundle, code_set)
    for key in ("scope_source_id", "origin_source_id"):
        if (key in policy and policy[key] is not None and policy[key] != "per_product"
                and policy[key] not in source_ids):
            raise ValueError(f"policy {key} is not present in bundle sources")
    for row in policy.get("product_rates", []):
        for key in ("source_id", "origin_source_id"):
            if key in row and row[key] not in source_ids:
                raise ValueError(f"policy product {row.get('hts8')} {key} is not present in bundle sources")
    metric_id_values = [item.get("id") if isinstance(item, dict) else None for item in metrics]
    if any(not isinstance(value, str) or not value for value in metric_id_values):
        raise ValueError("bundle metric IDs must be non-empty strings")
    metric_ids = set(metric_id_values)
    if len(metric_ids) != len(metrics):
        raise ValueError("bundle metric IDs must be unique")
    observation_id_values = [item.get("id") if isinstance(item, dict) else None for item in observations]
    if any(not isinstance(value, str) or not value for value in observation_id_values):
        raise ValueError("bundle observation IDs must be non-empty strings")
    observation_ids = set(observation_id_values)
    if len(observation_ids) != len(observations):
        raise ValueError("bundle observation IDs must be unique")
    for source in sources:
        if "url" in source and source["url"] is not None and not isinstance(source["url"], str):
            raise ValueError("source URL must be text")
        if source.get("text_sha256") and isinstance(source.get("text"), str):
            if hashlib.sha256(source["text"].encode("utf-8")).hexdigest() != source["text_sha256"]:
                raise ValueError(f"bundle source text hash mismatch: {source['id']}")
    for metric in metrics:
        if not isinstance(metric.get("id"), str):
            raise ValueError("metric IDs must be strings")
        refs = metric.get("source_refs")
        if (not isinstance(refs, list) or not refs
                or any(not isinstance(ref, str) or not ref for ref in refs)
                or len(set(refs)) != len(refs)
                or any(ref not in source_ids for ref in refs)):
            raise ValueError(f"metric {metric.get('id')} has an invalid source reference")
        for key in ("product_scope", "period", "metric_type", "unit", "measure", "value", "status"):
            if key not in metric:
                raise ValueError(f"metric {metric.get('id')} is missing {key}")
        if metric["period"] != request["month"]:
            raise ValueError(f"metric {metric.get('id')} period does not match the request")
    for observation in observations:
        if not isinstance(observation, dict) or not isinstance(observation.get("metric_ids"), list):
            raise ValueError(f"observation {observation.get('id') if isinstance(observation, dict) else None} is malformed")
        metric_refs = observation["metric_ids"]
        if (any(not isinstance(item, str) or not item for item in metric_refs)
                or len(set(metric_refs)) != len(metric_refs)
                or any(item not in metric_ids for item in metric_refs)):
            raise ValueError(f"observation {observation.get('id')} has an invalid metric reference")
        if observation.get("period") != request["month"]:
            raise ValueError(f"observation {observation.get('id')} period does not match the request")
    _validate_metrics_profiles_and_observations(bundle, codes, metrics, observations)
    return request, profiles, metrics, observations, policy


def _validate_metrics_profiles_and_observations(
    bundle: dict[str, Any], codes: list[str], metrics: list[dict[str, Any]], observations: list[dict[str, Any]]
) -> None:
    month = bundle["request"]["month"]
    profiles = {profile["hts8"]: profile for profile in bundle["profiles"]}
    metric_by_id = {metric["id"]: metric for metric in metrics}
    expected_ids = {f"metric.{month}.{code}.{kind}" for code in codes for kind in _PRODUCT_KINDS}
    expected_ids |= {"metric.scope.world_import_usd", "metric.scope.china_import_usd"}
    if set(metric_by_id) != expected_ids:
        missing = sorted(expected_ids - set(metric_by_id))
        extra = sorted(set(metric_by_id) - expected_ids)
        raise ValueError(f"metric coverage mismatch; missing={missing}, extra={extra}")
    expected_metric_values: dict[str, Any] = {}
    for code in codes:
        profile = profiles[code]
        for key in ("world_import_usd", "china_import_usd"):
            value = profile.get(key)
            if type(value) is not int or value < 0:
                raise ValueError(f"profile {code} has an invalid {key}")
        if profile["china_import_usd"] > profile["world_import_usd"]:
            raise ValueError(f"profile {code} has China imports larger than all-origin imports")
        expected_metric_values[f"metric.{month}.{code}.world_import_usd"] = profile["world_import_usd"]
        expected_metric_values[f"metric.{month}.{code}.china_import_usd"] = profile["china_import_usd"]
    scope_world = sum(profile["world_import_usd"] for profile in profiles.values())
    scope_china = sum(profile["china_import_usd"] for profile in profiles.values())
    expected_metric_values["metric.scope.world_import_usd"] = scope_world
    expected_metric_values["metric.scope.china_import_usd"] = scope_china
    for code in codes:
        world = profiles[code]["world_import_usd"]
        china = profiles[code]["china_import_usd"]
        expected_metric_values[f"metric.{month}.{code}.china_share_of_product_percent"] = _rounded_percent(china, world)
        expected_metric_values[f"metric.{month}.{code}.product_share_of_scope_world_percent"] = _rounded_percent(world, scope_world)
        expected_metric_values[f"metric.{month}.{code}.product_share_of_scope_china_percent"] = _rounded_percent(china, scope_china)
    for metric_id, metric in metric_by_id.items():
        parts = metric_id.split(".")
        code = parts[2] if len(parts) == 4 and parts[0] == "metric" else "all"
        kind = metric["metric_type"]
        expected_kind_from_id = (f"scope_{parts[-1]}" if len(parts) == 3 and parts[1] == "scope" else parts[-1])
        if kind != expected_kind_from_id:
            raise ValueError(f"metric {metric_id} type does not match its ID")
        if kind in _SCOPE_KINDS:
            if metric["product_scope"] != "all" or metric["unit"] != "USD" or metric["measure"] != "import_value_consumption_usd":
                raise ValueError(f"scope metric {metric_id} has the wrong scope or unit")
            if metric.get("numerator_id") is not None or metric.get("denominator_id") is not None:
                raise ValueError(f"scope metric {metric_id} must not have ratio pointers")
        elif kind in _PRODUCT_KINDS:
            if code not in profiles or metric["product_scope"] != code:
                raise ValueError(f"metric {metric_id} has the wrong product scope")
            expected_unit = "USD" if kind in {"world_import_usd", "china_import_usd"} else "percent"
            expected_measure = "import_value_consumption_usd" if kind in {"world_import_usd", "china_import_usd"} else "share"
            if metric["unit"] != expected_unit or metric["measure"] != expected_measure:
                raise ValueError(f"metric {metric_id} has the wrong unit or measure")
            if kind in ("world_import_usd", "china_import_usd"):
                if metric.get("numerator_id") is not None or metric.get("denominator_id") is not None:
                    raise ValueError(f"money metric {metric_id} must not have ratio pointers")
            else:
                expected_numerator = (f"metric.{month}.{code}.world_import_usd"
                                      if kind == "product_share_of_scope_world_percent"
                                      else f"metric.{month}.{code}.china_import_usd")
                expected_denominator = {
                    "china_share_of_product_percent": f"metric.{month}.{code}.world_import_usd",
                    "product_share_of_scope_world_percent": "metric.scope.world_import_usd",
                    "product_share_of_scope_china_percent": "metric.scope.china_import_usd",
                }[kind]
                if (metric.get("numerator_id"), metric.get("denominator_id")) != (expected_numerator, expected_denominator):
                    raise ValueError(f"ratio pointers for {metric_id} do not match its definition")
        else:
            raise ValueError(f"unsupported metric type {kind}")
        value = metric.get("value")
        expected = expected_metric_values[metric_id]
        if kind in _MONEY_KINDS:
            if type(value) is not int or value < 0:
                raise ValueError(f"money metric {metric_id} must be a non-negative integer")
        elif value is not None:
            number = _decimal(value, metric_id)
            if number < 0 or number > 100:
                raise ValueError(f"ratio metric {metric_id} is outside 0..100")
        if not _same_number(value, expected):
            raise ValueError(f"metric {metric_id} does not equal its profile-derived value")
        expected_status = "known" if expected is not None else "unknown"
        if metric.get("status") != expected_status or ((value is None) != (expected is None)):
            raise ValueError(f"metric {metric_id} status does not match its value")
    for code, profile in profiles.items():
        for kind in _PRODUCT_KINDS:
            key = f"metric.{month}.{code}.{kind}"
            if not _same_number(profile.get(kind), metric_by_id[key].get("value")):
                raise ValueError(f"profile {code} does not match metric {key}")
    amount_max = max((profile["china_import_usd"] for profile in profiles.values()), default=None)
    amount_leaders = sorted(code for code, profile in profiles.items() if profile["china_import_usd"] == amount_max)
    known_shares = {code: profile["china_share_of_product_percent"] for code, profile in profiles.items()
                    if profile["china_share_of_product_percent"] is not None}
    share_max = max(known_shares.values(), default=None)
    share_leaders = sorted(code for code, value in known_shares.items() if value == share_max) if share_max is not None else []
    expected_observations: dict[str, dict[str, Any]] = {}
    if len(codes) > 1 and amount_leaders:
        expected_observations["observation.amount_leader"] = {
            "type": "amount_leader", "product_scope": "all",
            "metric_ids": [f"metric.{month}.{code}.china_import_usd" for code in amount_leaders],
            "value": amount_leaders,
        }
    if len(codes) > 1 and share_leaders:
        expected_observations["observation.share_leader"] = {
            "type": "share_leader", "product_scope": "all",
            "metric_ids": [f"metric.{month}.{code}.china_share_of_product_percent" for code in share_leaders],
            "value": share_leaders,
        }
    if len(codes) > 1 and amount_leaders and share_leaders and set(amount_leaders) != set(share_leaders):
        expected_observations["observation.rank_contrast"] = {
            "type": "rank_contrast", "product_scope": "all",
            "metric_ids": [metric["id"] for metric in metrics if metric["metric_type"] in ("china_import_usd", "china_share_of_product_percent")],
            "value": {"amount_leader": amount_leaders, "share_leader": share_leaders},
        }
    if len(codes) == 1:
        code = codes[0]
        expected_observations["observation.single_product_profile"] = {
            "type": "single_product_profile", "product_scope": code,
            "metric_ids": [metric["id"] for metric in metrics if metric.get("product_scope") == code],
            "value": code,
        }
    actual = {observation["id"]: observation for observation in observations}
    if set(actual) != set(expected_observations):
        raise ValueError("observation coverage does not match deterministic profile rankings")
    for observation_id, expected in expected_observations.items():
        observation = actual[observation_id]
        for key in ("type", "product_scope", "metric_ids", "value"):
            if observation.get(key) != expected[key]:
                raise ValueError(f"observation {observation_id} does not match its profile-derived value")


def _require_bundle(bundle: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    request, profiles, metrics, observations, _ = _validate_bundle(bundle)
    return request, bundle, metrics, observations


def _policy_refs(bundle: dict[str, Any], codes: list[str], source_ids: set[str]) -> list[dict[str, str]]:
    policy_facts = bundle["policy_facts"]
    rates = {item["hts8"]: item for item in policy_facts["product_rates"]}
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    common = [policy_facts.get("scope_source_id"), policy_facts.get("origin_source_id")]
    for code in codes:
        row = rates.get(code)
        if row is None:
            raise ValueError(f"policy facts do not cover requested product {code}")
        candidates: list[str] = []
        for key in ("source_id", "origin_source_id"):
            if isinstance(row.get(key), str):
                candidates.append(row[key])
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        field_refs = details.get("field_refs") if isinstance(details.get("field_refs"), dict) else {}
        for reference in field_refs.values():
            if isinstance(reference, dict) and isinstance(reference.get("chunk_id"), str):
                candidates.append(reference["chunk_id"])
        candidates.extend(common)
        for source_id in candidates:
            if source_id in source_ids and (source_id, code) not in seen:
                refs.append({"source_id": source_id, "hts8": code})
                seen.add((source_id, code))
        if not any(ref["hts8"] == code for ref in refs):
            raise ValueError(f"policy source for {code} is not in this bundle")
    return refs


def _fact_text(metric: dict[str, Any]) -> str:
    period = metric["period"]
    code = metric["product_scope"]
    kind = metric["metric_type"]
    value = metric["value"]
    labels = {
        "world_import_usd": "美国从所有原产地进口该商品的消费进口金额",
        "china_import_usd": "美国从中国原产地进口该商品的消费进口金额",
        "china_share_of_product_percent": "中国原产金额占美国从所有来源进口该商品的消费进口金额",
        "product_share_of_scope_world_percent": "该商品所有来源金额占本次所选商品范围所有来源消费进口合计金额",
        "product_share_of_scope_china_percent": "该商品中国原产金额占本次所选商品范围中国原产消费进口合计金额",
        "scope_world_import_usd": "本次所选商品范围美国从所有原产地进口的消费进口合计金额",
        "scope_china_import_usd": "本次所选商品范围美国从中国原产地进口的消费进口合计金额",
    }
    if value is None:
        return f"统计期 {period}，HTS {code} 的{labels.get(kind, kind)}未知（分母为零或证据缺失，不能补零）。"
    if kind in _MONEY_KINDS:
        subject = labels[kind] if kind in _SCOPE_KINDS else f"HTS {code}：{labels[kind]}"
        return f"统计期 {period}，{subject}为 {_money(value)} 美元。"
    sentence = f"统计期 {period}，HTS {code}：{labels[kind]} {_percent(value)}%。"
    if kind == "china_share_of_product_percent" and _same_number(value, 100):
        sentence += "（仅表示该统计期该商品美国消费进口的原产地构成，不代表整体供应依赖。）"
    return sentence


def _build_catalog(bundle: dict[str, Any]) -> dict[str, Any]:
    request, profiles, metrics, observations, policy = _validate_bundle(bundle)
    codes = [profile["hts8"] for profile in profiles]
    source_ids = _source_ids(bundle["sources"])
    policy_refs = _policy_refs(bundle, codes, source_ids)
    observation_by_metric: dict[str, list[str]] = {metric["id"]: [] for metric in metrics}
    for observation in observations:
        for metric_id in observation["metric_ids"]:
            observation_by_metric.setdefault(metric_id, []).append(observation["id"])
    facts: list[dict[str, Any]] = []
    for metric in metrics:
        kind = metric["metric_type"]
        facts.append({
            "id": f"fact.{metric['id']}",
            "kind": kind,
            "metric_ids": [metric["id"]],
            "observation_ids": list(observation_by_metric.get(metric["id"], [])),
            "period": metric["period"],
            "reporter": "USA",
            "flow": "consumption_import",
            "product_scope": metric["product_scope"],
            "origin_scope": "all_origins" if kind in {"world_import_usd", "product_share_of_scope_world_percent", "scope_world_import_usd"} else "China",
            "numerator_id": metric.get("numerator_id"),
            "denominator_id": metric.get("denominator_id"),
            "source_refs": list(metric["source_refs"]),
            "status": metric["status"],
            "text": _fact_text(metric),
        })
    catalog: dict[str, Any] = {
        "schema_version": CATALOG_VERSION,
        "policy_id": bundle["policy_id"],
        "data_version": bundle["data_version"],
        "request": deepcopy(request),
        "evidence_sha256": _sha(bundle),
        "facts": facts,
        "observations": deepcopy(observations),
        "policy_refs": policy_refs,
        # Keep the whole policy projection and the complete source text.  This
        # is business evidence for the model, not an instruction channel.
        "policy_facts": deepcopy(policy),
        "sources": deepcopy(bundle["sources"]),
        "limitations": deepcopy(bundle.get("limitations") or []),
        "boundaries": deepcopy(bundle.get("boundaries") or {}),
        # Lossless audit copy: excluded from messages() deliberately.
        "evidence_snapshot": deepcopy(bundle),
    }
    catalog["catalog_sha256"] = _sha(catalog)
    return catalog


def build_fact_catalog(bundle: dict[str, Any]) -> dict[str, Any]:
    """Validate and create a denominator-explicit catalog without model/network access."""
    return _build_catalog(bundle)


def validate_fact_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    """Validate hash, source closure, and deterministic reconstruction from the snapshot."""
    if not isinstance(catalog, dict) or catalog.get("schema_version") != CATALOG_VERSION:
        raise ValueError("invalid brief fact catalog schema")
    recorded = catalog.get("catalog_sha256")
    if not isinstance(recorded, str):
        raise ValueError("catalog hash is required")
    unsigned = deepcopy(catalog)
    unsigned.pop("catalog_sha256", None)
    if _sha(unsigned) != recorded:
        raise ValueError("catalog hash mismatch")
    snapshot = catalog.get("evidence_snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("catalog evidence snapshot is required")
    rebuilt = _build_catalog(snapshot)
    rebuilt_unsigned = deepcopy(rebuilt)
    rebuilt_unsigned.pop("catalog_sha256", None)
    if rebuilt_unsigned != unsigned:
        raise ValueError("catalog does not match its evidence snapshot")
    source_values = [item.get("id") if isinstance(item, dict) else None
                     for item in catalog.get("sources", [])]
    if any(not isinstance(value, str) or not value for value in source_values):
        raise ValueError("invalid source IDs")
    source_ids = set(source_values)
    if len(source_ids) != len(source_values):
        raise ValueError("duplicate source IDs")
    fact_id_values = [item.get("id") if isinstance(item, dict) else None for item in catalog.get("facts", [])]
    if any(not isinstance(value, str) or not value for value in fact_id_values):
        raise ValueError("invalid fact IDs")
    fact_ids = set(fact_id_values)
    if len(fact_ids) != len(catalog.get("facts", [])):
        raise ValueError("invalid fact IDs")
    observation_id_values = [item.get("id") if isinstance(item, dict) else None for item in catalog.get("observations", [])]
    if any(not isinstance(value, str) or not value for value in observation_id_values):
        raise ValueError("invalid observation IDs")
    observation_ids = set(observation_id_values)
    if len(observation_ids) != len(catalog.get("observations", [])):
        raise ValueError("invalid observation IDs")
    for fact in catalog["facts"]:
        refs = fact.get("source_refs", [])
        obs_refs = fact.get("observation_ids", [])
        if (not isinstance(refs, list) or any(not isinstance(ref, str) or ref not in source_ids for ref in refs)):
            raise ValueError("fact has an unknown source")
        if (not isinstance(obs_refs, list)
                or any(not isinstance(obs, str) or obs not in observation_ids for obs in obs_refs)):
            raise ValueError("fact has an unknown observation")
    seen_refs: set[tuple[str, str]] = set()
    for ref in catalog.get("policy_refs", []):
        if (not isinstance(ref, dict) or set(ref) != {"source_id", "hts8"}
                or not isinstance(ref["source_id"], str) or not isinstance(ref["hts8"], str)
                or ref["source_id"] not in source_ids or not _HTS8.fullmatch(ref["hts8"])):
            raise ValueError("invalid policy reference")
        pair = (ref["source_id"], ref["hts8"])
        if pair in seen_refs:
            raise ValueError("duplicate policy reference")
        seen_refs.add(pair)
    return {"status": "valid", "schema_version": CATALOG_VERSION,
            "catalog_sha256": recorded, "fact_count": len(catalog["facts"]),
            "observation_count": len(catalog["observations"]),
            "policy_source_count": len(_policy_source_ids(catalog["policy_facts"]))}


def _safe_text(value: Any) -> str:
    text = html.escape(str(value), quote=True)
    # HTML escaping alone leaves Markdown links/emphasis active.  This is
    # presentation encoding only; the original source bytes remain in the
    # catalog and messages.
    return re.sub(r"([\\`*_[\]()>#+!|~])", r"\\\1", text)


def _quote(value: Any) -> list[str]:
    text = _safe_text(value)
    return [f"> {line}" if line else ">" for line in text.splitlines() or [""]]


_RATE_MEANING = [
    "目录中的 additional_duty_percent 是政策文件存档的“额外从价税率”：",
    "- 它是当年公告加征的额外税率存档，不是现行综合税则，也不包含其他可能适用的税率；",
    "- 消费进口金额不是税基，本目录不计算税款、税负、损失或价格影响；",
    "- 条件/例外状态为 unknown 时只表示本版本未逐笔核验，不代表不存在条件或例外。",
]

_OBSERVATION_MEANINGS = {
    "amount_leader": "中国原产金额最高的登记商品（并列保留）",
    "share_leader": "中国来源占该商品美国进口比例最高的登记商品（并列保留）",
    "rank_contrast": "金额排序与中国来源占比排序的关注对象不同",
    "single_product_profile": "单个商品的金额与来源份额概况（“100%”仅指本次所选范围构成）",
}


def _fact_unknown_reason(metric: dict[str, Any]) -> str:
    if metric.get("denominator_id") is not None:
        return "分母为零或证据缺失，不能补零"
    return "证据缺失，不能补零"


def _observation_lines(catalog: dict[str, Any], profiles: dict[str, dict[str, Any]], cite: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for observation in catalog["observations"]:
        kind = observation.get("type", "unknown")
        meaning = observation.get("meaning") or _OBSERVATION_MEANINGS.get(kind, "")
        lines.append(f"### `{_safe_text(observation['id'])}`（{_safe_text(kind)}）")
        if meaning:
            lines.append(f"含义：{_safe_text(meaning)}")
        value = observation.get("value")
        metric_ids = observation.get("metric_ids", [])
        if kind == "amount_leader" and isinstance(value, list):
            tie = "（并列）" if len(value) > 1 else ""
            amount = profiles[value[0]]["china_import_usd"]
            lines.append(f"- 中国原产金额最高{_tie_note(value)}：{_safe_text(value[0])}{tie}，"
                         f"金额 {_money(amount)} 美元。")
        elif kind == "share_leader" and isinstance(value, list):
            tie = "（并列）" if len(value) > 1 else ""
            share = profiles[value[0]]["china_share_of_product_percent"]
            shown = "未知（分母为零，不能补零）" if share is None else f"{_percent(share)}%"
            lines.append(f"- 中国来源占该商品美国进口比例最高{_tie_note(value)}："
                         f"{_safe_text(value[0])}{tie}，占比 {shown}。")
        elif kind == "rank_contrast" and isinstance(value, dict):
            amount_codes = "、".join(_safe_text(code) for code in value.get("amount_leader", []))
            share_codes = "、".join(_safe_text(code) for code in value.get("share_leader", []))
            lines.append(f"- 金额最高：{amount_codes}；来源占比最高：{share_codes}。"
                         "两个排序衡量不同问题，可能指向不同商品。")
        elif kind == "single_product_profile" and isinstance(value, str):
            profile = profiles[value]
            share = profile["china_share_of_product_percent"]
            shown = "未知（全部来源金额为零）" if share is None else f"{_percent(share)}%"
            lines.append(f"- {_safe_text(value)}：全部来源金额 {_money(profile['world_import_usd'])} 美元，"
                         f"中国原产金额 {_money(profile['china_import_usd'])} 美元，中国来源占比 {shown}。")
        lines.append(f"- 关联指标：{', '.join('`' + _safe_text(mid) + '`' for mid in metric_ids)}")
        lines.append("")
    return lines


def _tie_note(leaders: list[Any]) -> str:
    return "（存在并列，全部列出）" if isinstance(leaders, list) and len(leaders) > 1 else ""


def _product_policy_lines(catalog: dict[str, Any], cite: dict[str, str]) -> list[str]:
    """Per-product rate, conditions and exceptions with complete status."""
    policy = catalog["policy_facts"]
    lines: list[str] = []
    rates = policy.get("product_rates") or []
    requested = policy.get("requested_products")
    if isinstance(requested, list) and requested:
        shown = "、".join(_safe_text(code) for code in requested)
        lines += [f"本次所选商品（requested_products）：{shown}。", ""]
    printed_clauses: dict[str, str] = {}
    for row in rates:
        code = row.get("hts8", "?")
        lines.append(f"### HTS {_safe_text(code)}")
        rate = row.get("additional_duty_percent")
        if rate is None:
            lines.append("- 存档额外税率：未提供（该版本未记录此字段，不能补零）。")
        else:
            lines.append(f"- 存档额外税率：{_safe_text(rate)}%（含义见上节，不是现行综合税则）。")
        reported = row.get("reported_rate")
        if isinstance(reported, dict) and not reported.get("additional_rate_verified"):
            lines.append(f"- 候选确认税率值：{_safe_text(reported.get('value'))}；"
                         f"含义：{_safe_text(reported.get('meaning'))}。尚未映射为额外从价税率。")
        for key in ("source_id", "origin_source_id"):
            if isinstance(row.get(key), str) and row[key] in cite:
                lines.append(f"- {'税率' if key == 'source_id' else '条款'}引用：[{cite[row[key]]}] `{_safe_text(row[key])}`")
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        if details:
            name = details.get("registered_name")
            if isinstance(name, str) and name:
                lines.append(f"- 登记名称（登记元数据，非法律引文）：{_safe_text(name)}")
            name_zh = details.get("registered_name_zh")
            name_zh_status = details.get("registered_name_zh_status")
            if name_zh_status == "known" and isinstance(name_zh, str) and name_zh:
                lines.append(f"- 登记中文名称：{_safe_text(name_zh)}")
            elif name_zh_status == "unknown":
                reason = details.get("registered_name_zh_reason") or "未提供"
                lines.append(f"- 登记中文名称：未知（{_safe_text(reason)}）")
            clause = details.get("original_scope_clause")
            if isinstance(clause, str) and clause:
                if clause in printed_clauses:
                    lines.append(f"- 原始范围条款：与 HTS {_safe_text(printed_clauses[clause])} 的条款相同"
                                 "（共享上下文，原文见上，不重复输出）。")
                else:
                    printed_clauses[clause] = code
                    lines.append("- 原始范围条款（共享上下文，不等于本次请求商品清单）：")
                    lines.extend(_quote(clause))
            for field, label in (("conditions", "条件"), ("exceptions", "例外")):
                block = details.get(field)
                if isinstance(block, dict):
                    status = block.get("status", "unknown")
                    reason = block.get("reason")
                    text = block.get("text") or block.get("items")
                    shown = f"状态：{_safe_text(status)}"
                    if isinstance(reason, str) and reason:
                        shown += f"；原因：{_safe_text(reason)}"
                    if isinstance(text, list) and text:
                        shown += "；内容：" + "；".join(_safe_text(item) for item in text)
                    elif isinstance(text, str) and text:
                        shown += f"；内容：{_safe_text(text)}"
                    lines.append(f"- {label}：{shown}")
                elif block is None:
                    lines.append(f"- {label}：该版本政策事实未提供此字段。")
        else:
            lines.append("- 逐商品条件/例外：该版本政策事实未提供 details 字段（不视为没有条件或例外）。")
        lines.append("")
    return lines


def render_fact_catalog(catalog: dict[str, Any]) -> str:
    """Render the complete deterministic program report (A3) for the catalog.

    The report shows every requested observation (ties included), every
    selected product with its archived rate, per-product conditions and
    exceptions with explicit status/reason, the policy applicability snapshot
    (origin, effective date, clock, timezone, entry events), all sources with
    each passage printed exactly once behind a stable citation anchor, and
    every limitation.  Values, denominators and policy text are program
    output, never model output.
    """
    validate_fact_catalog(catalog)
    cite = {source["id"]: f"S{index}" for index, source in enumerate(catalog["sources"], start=1)}
    profiles = {profile["hts8"]: profile for profile in _profile_view(catalog)}
    codes = [profile["hts8"] for profile in _profile_view(catalog)]
    focus_labels = {"china_amount": "中国原产金额", "china_share": "中国来源占比",
                    "contrast": "金额与占比对照"}
    requested = catalog["request"].get("product", "all")
    scope_label = ("全部所选商品" if requested == "all" else f"单一商品 {requested}")
    lines = ["# 完整程序报告 A3（确定性基准）", "",
             "此报告由程序从证据包生成；金额、比例、分母、政策文本和局限均不是模型生成，"
             "用作评价 AI 解释信息增益的程序基准。", "",
             "## 请求与范围", "",
             f"- 政策：`{_safe_text(catalog['policy_id'])}`",
             f"- 数据版本：`{_safe_text(catalog['data_version'])}`",
             f"- 统计期：{_safe_text(catalog['request']['month'])}",
             f"- 解读重点：{_safe_text(focus_labels.get(catalog['request'].get('focus'), catalog['request'].get('focus')))}",
             f"- 商品范围：{scope_label}（{_safe_text('、'.join(codes))}）",
             f"- 事实目录摘要：`{_safe_text(catalog['catalog_sha256'])}`", ""]
    lines += ["## 全部数据观察（并列保留）", ""]
    lines += _observation_lines(catalog, profiles, cite) or ["（无观察）", ""]
    lines += ["## 全部程序事实（含分母）", ""]
    for fact in catalog["facts"]:
        numerator = fact["numerator_id"] or "不适用（金额指标本身）"
        denominator = fact["denominator_id"] or "不适用（金额指标本身）"
        refs = ", ".join(f"[{cite[ref]}]" for ref in fact["source_refs"] if ref in cite)
        lines.append(f"- `{_safe_text(fact['id'])}`：{_safe_text(fact['text'])}")
        lines.append(f"  - 分子：`{_safe_text(numerator)}`；分母：`{_safe_text(denominator)}`；来源：{refs or '未提供'}")
        if fact.get("status") == "unknown":
            metric = next((m for m in _metric_view(catalog) if m["id"] == fact["metric_ids"][0]), None)
            if metric is not None:
                lines.append(f"  - 未知原因：{_safe_text(_fact_unknown_reason(metric))}")
    lines += ["", "## 税率含义", ""]
    lines += [f"- {item}" for item in _RATE_MEANING]
    lines += ["", "## 逐商品政策：税率、条件与例外", "", f"本次所选商品范围：{scope_label}。", ""]
    lines += _product_policy_lines(catalog, cite)
    policy = catalog["policy_facts"]
    lines += ["## 政策适用范围快照", ""]
    events = policy.get("entry_events", "未知")
    if isinstance(events, list):
        events = "、".join(events)
    origin_ref = policy.get("origin_source_id")
    scope_ref = policy.get("scope_source_id")
    lines += [f"- 原产地：{_safe_text(policy.get('origin', '未知'))}"
              + (f"（引用 [{cite[origin_ref]}]）" if isinstance(origin_ref, str) and origin_ref in cite else ""),
              f"- 生效日期：{_safe_text(policy.get('effective_date', '未知'))}",
              f"- 当地时钟（24小时制）：{_safe_text(policy.get('clock_24h', '未知'))}",
              f"- 时区：{_safe_text(policy.get('timezone', '未知'))}",
              f"- 入境事件：{_safe_text(events)}"]
    if isinstance(scope_ref, str) and scope_ref in cite:
        lines.append(f"- 适用范围条款来源：[{cite[scope_ref]}] `{_safe_text(scope_ref)}`")
    lines += ["", "## 来源目录（每段原文只输出一次）", ""]
    printed_texts: dict[str, list[str]] = {}
    for source in catalog["sources"]:
        anchor = cite[source["id"]]
        url = source.get("url")
        lines.append(f"### [{anchor}] `{_safe_text(source['id'])}`")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            lines.append(f"网址（仅供核验）：`{_safe_text(url)}`")
        text = source.get("text")
        if isinstance(text, str) and text:
            key = text
            if key in printed_texts:
                printed_texts[key].append(source["id"])
                lines.append(f"原文与 [{cite[printed_texts[key][0]]}] 相同，见该条，不再重复输出。")
            else:
                printed_texts[key] = [source["id"]]
                lines.append("原文：")
                lines.extend(_quote(text))
        else:
            lines.append("原文：该来源只提供数据引用，无正文段落。")
        lines.append("")
    limitations = catalog.get("limitations", [])
    lines += ["## 局限（全部列出）", ""]
    if limitations:
        for item in limitations:
            lines.append(f"- [{_safe_text(item.get('id', '?'))}] {_safe_text(item.get('text', ''))}"
                         if isinstance(item, dict) else f"- {_safe_text(item)}")
    else:
        lines.append("- 本目录未登记额外局限；上文边界声明仍然适用。")
    lines += ["", "## 边界声明", "",
              "这些事实描述美国消费进口统计，不证明关税因果、税款、损失、整体供应依赖或替代能力。"
              "单商品“100%”仅指本次所选范围的构成，不是市场全部。此报告不构成法律、税务或因果结论。", ""]
    return "\n".join(lines)


def _profile_view(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    snapshot = catalog.get("evidence_snapshot")
    if isinstance(snapshot, dict) and isinstance(snapshot.get("profiles"), list):
        return snapshot["profiles"]
    return []


def _metric_view(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    snapshot = catalog.get("evidence_snapshot")
    if isinstance(snapshot, dict) and isinstance(snapshot.get("metrics"), list):
        return snapshot["metrics"]
    return []


__all__ = ["CATALOG_VERSION", "build_fact_catalog", "render_fact_catalog", "validate_fact_catalog"]
