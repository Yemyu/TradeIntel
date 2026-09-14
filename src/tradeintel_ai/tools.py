"""Deterministic, read-only tools exposed to the TradeShock AI layer.

The functions in this module are intentionally boring: they validate a small
parameter set, read declared evidence artifacts, calculate simple aggregates,
and return JSON-shaped dictionaries with sources and limitations.  A language
model may choose one of these tools, but it cannot issue arbitrary SQL or
change the project's causal status.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Callable

from .repository import EvidenceRepository, RepositoryError, default_paths


DEFAULT_POLICY_ID = "us_301_list1_2018"
ALLOWED_SCOPE = "section301_list1"
ALLOWED_COMPARISONS = {
    "recent_clean_pre_same_months",
    "pre_policy_placebo_same_months",
    "immediate_post_same_months",
    "persistence_monitoring_same_months",
}
DATA_START = (2016, 1)
DATA_END = (2019, 12)
HS6_PATTERN = re.compile(r"^[0-9]{6}$")


class ToolError(ValueError):
    """A user-visible tool input or contract error."""


def _month_key(value: str) -> tuple[int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}", value):
        raise ToolError(f"月份必须使用 YYYY-MM 格式：{value!r}")
    year, month = int(value[:4]), int(value[5:])
    if not 1 <= month <= 12:
        raise ToolError(f"月份无效：{value!r}")
    return year, month


def _month_label(key: tuple[int, int]) -> str:
    return f"{key[0]:04d}-{key[1]:02d}"


def _month_range(start: str, end: str) -> list[tuple[int, int]]:
    first, last = _month_key(start), _month_key(end)
    if first < DATA_START or last > DATA_END:
        raise ToolError(
            f"日期必须位于项目固定范围 {_month_label(DATA_START)} 至 {_month_label(DATA_END)}"
        )
    if first > last:
        raise ToolError("start 不能晚于 end")
    result: list[tuple[int, int]] = []
    year, month = first
    while (year, month) <= last:
        result.append((year, month))
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return result


def _normalise_origin(origin: str) -> str:
    if not isinstance(origin, str):
        raise ToolError("origin 必须是 China、other_origins 或 all_origins")
    key = origin.strip().lower().replace(" ", "")
    aliases = {
        "china": "China",
        "中国": "China",
        "target": "China",
        "other_origins": "other_origins",
        "otherorigins": "other_origins",
        "其他原产地": "other_origins",
        "all_origins": "all_origins",
        "allorigins": "all_origins",
        "all": "all_origins",
        "全部原产地": "all_origins",
    }
    try:
        return aliases[key]
    except KeyError as exc:
        raise ToolError("origin 只能是 China、other_origins 或 all_origins") from exc


def _common_result(tool_name: str) -> dict[str, object]:
    return {
        "tool_name": tool_name,
        "tool_version": "1.0",
        "status": "ok",
        "causal_claim": False,
        "post_policy_activity_used_for_matching": False,
    }


def _event_source(repository: EvidenceRepository, event: Mapping[str, str]) -> dict[str, str]:
    return repository.file_source(repository.paths.policy_event, source_url=event.get("source_url"))


def _manifest_sources(
    repository: EvidenceRepository,
    months: Sequence[tuple[int, int]],
) -> list[dict[str, str]]:
    manifest = repository.source_manifest()
    sources: list[dict[str, str]] = []
    for key in months:
        item = manifest.get(key)
        if not item:
            raise RepositoryError(f"来源清单缺少月份：{_month_label(key)}")
        sources.append(
            {
                "kind": "official_census_archive",
                "month": _month_label(key),
                "url": str(item["source_url"]),
                "file_name": str(item["source_file_name"]),
                "sha256": str(item["source_sha256"]),
            }
        )
    return sources


def get_policy_event(
    policy_id: str = DEFAULT_POLICY_ID,
    *,
    repository: EvidenceRepository | None = None,
) -> dict[str, object]:
    """Return one registered policy event and its official source."""

    repository = repository or EvidenceRepository()
    event = repository.policy_event(policy_id)
    products = repository.policy_products(policy_id)
    try:
        rate = float(event["additional_rate"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RepositoryError(f"政策税率无效：{event!r}") from exc
    result = _common_result("get_policy_event")
    result.update(
        {
            "data": {
                "policy_id": event["policy_id"],
                "policy_name": event["policy_name"],
                "importer": event.get("importer", ""),
                "target_origin": event["target_origin"],
                "announcement_date": event["announcement_date"],
                "effective_date": event["effective_date"],
                "transition_month": event["effective_date"][:7],
                "additional_rate": event["additional_rate"],
                "additional_rate_percent": rate * 100,
                "policy_hts8_count": len(products),
            },
            "evidence": {
                "sources": [
                    _event_source(repository, event),
                    repository.file_source(repository.paths.policy_products, source_url=event.get("source_url")),
                ],
                "official_policy_url": event["source_url"],
            },
            "limitations": [
                "该工具返回政策事实，不表示政策已经被识别为因果效应。",
                "月度贸易数据把生效日所在的月份视为 transition，不把整月强行当成干净 post。",
            ],
        }
    )
    return result


def get_trade_series(
    origin: str = "China",
    *,
    policy_id: str = DEFAULT_POLICY_ID,
    scope: str = ALLOWED_SCOPE,
    hs6: str | None = None,
    start: str = "2016-01",
    end: str = "2019-12",
    repository: EvidenceRepository | None = None,
) -> dict[str, object]:
    """Return a fixed-scope monthly import series with source fingerprints.

    Without ``hs6`` the series is the complete Section 301 List 1 aggregate.
    With ``hs6`` it is one of the conservatively mapped List 1 HS6 products;
    the compact causal panel is read only for that explicit product.
    """

    repository = repository or EvidenceRepository()
    if scope != ALLOWED_SCOPE:
        raise ToolError(f"scope 只允许 {ALLOWED_SCOPE!r}")
    event = repository.policy_event(policy_id)
    selected_origin = _normalise_origin(origin)
    months = _month_range(start, end)
    allowed_hs6 = repository.policy_hs6(policy_id)
    if hs6 is not None:
        hs6 = str(hs6).replace(".", "").strip()
        if not HS6_PATTERN.fullmatch(hs6):
            raise ToolError("hs6 必须是 6 位数字")
        if hs6 not in allowed_hs6:
            raise ToolError("hs6 不在已登记的 Section 301 List 1 暴露范围内")

    by_key: dict[tuple[int, int], dict[str, object]] = {}
    input_files: list[dict[str, str]] = []
    if hs6 is None:
        by_key = repository.policy_case_monthly()
        input_files.append(repository.file_source(repository.paths.policy_case_monthly))
    else:
        for row in repository.causal_panel_rows(hs6):
            by_key[(int(row["year"]), int(row["month"]))] = row
        input_files.append(repository.file_source(repository.paths.causal_panel))

    field = {
        "China": "target" if hs6 is None else "china",
        "other_origins": "other_origins",
        "all_origins": "all_origins",
    }[selected_origin]
    series: list[dict[str, object]] = []
    missing_months: list[str] = []
    for key in months:
        row = by_key.get(key)
        if row is None:
            missing_months.append(_month_label(key))
            value = None
            observed_count = 0
            source_hts10_count = 0
            source_hts10_mapped_count = 0
        else:
            value = int(row[field])
            observed_count = int(row.get("unique_policy_hts8_count", 1 if hs6 else 0)) if hs6 is None else 1
            source_hts10_count = int(row.get("source_hts10_count", 0))
            source_hts10_mapped_count = int(row.get("source_hts10_mapped_count", 0))
        series.append(
            {
                "month": _month_label(key),
                "value_usd": value,
                "observed_product_count": observed_count,
                "observed_product_level": "policy_hts8" if hs6 is None else "hs6_2017",
                "source_hts10_count": source_hts10_count,
                "source_hts10_mapped_count": source_hts10_mapped_count,
            }
        )

    result = _common_result("get_trade_series")
    result.update(
        {
            "data": {
                "policy_id": policy_id,
                "scope": scope,
                "hs6": hs6,
                "origin": selected_origin,
                "measure": "import_value_consumption_usd",
                "start": start,
                "end": end,
                "months": len(series),
                "series": series,
                "total_usd": None if missing_months else sum(int(item["value_usd"]) for item in series),
                "observed_total_usd": sum(int(item["value_usd"]) for item in series if item["value_usd"] is not None),
                "coverage_complete": not missing_months,
                "missing_months": missing_months,
            },
            "evidence": {
                "sources": [
                    _event_source(repository, event),
                    repository.file_source(repository.paths.policy_exposure_hs6),
                    repository.file_source(repository.paths.causal_panel_manifest),
                    *input_files,
                    *_manifest_sources(repository, months),
                ],
                "selection_rule": (
                    "Section 301 List 1 HS6 exposure universe; aggregate policy_case_monthly"
                    if hs6 is None
                    else "One explicitly requested HS6 from the audited policy exposure table"
                ),
            },
            "limitations": [
                "金额是描述性贸易指标，工具不会把时间变化解释成关税因果效应。",
                "政策生效月 2018-07 是 transition；需要干净窗口时应使用 get_descriptive_change 的已登记比较。",
                "缺失月份保留 null，完整窗口 total_usd 也为 null；observed_total_usd 只是已观测月份合计。",
            ],
        }
    )
    return result


def get_descriptive_change(
    comparison_id: str = "immediate_post_same_months",
    *,
    policy_id: str = DEFAULT_POLICY_ID,
    repository: EvidenceRepository | None = None,
) -> dict[str, object]:
    """Return one of the precomputed, registered descriptive comparisons."""

    repository = repository or EvidenceRepository()
    if comparison_id not in ALLOWED_COMPARISONS:
        raise ToolError(
            "comparison_id 必须是已登记的四个比较之一："
            + ", ".join(sorted(ALLOWED_COMPARISONS))
        )
    event = repository.policy_event(policy_id)
    summary = repository.statistical_baseline()
    comparisons = summary.get("comparisons")
    if not isinstance(comparisons, dict) or comparison_id not in comparisons:
        raise RepositoryError(f"统计基线缺少比较：{comparison_id}")
    comparison = comparisons[comparison_id]
    if not isinstance(comparison, dict):
        raise RepositoryError(f"统计基线比较不是对象：{comparison_id}")
    result = _common_result("get_descriptive_change")
    result.update(
        {
            "data": {
                "policy_id": policy_id,
                "comparison_id": comparison_id,
                "interpretation": comparison.get("interpretation", ""),
                "reference_months": comparison.get("reference_months", []),
                "current_months": comparison.get("current_months", []),
                "months_per_window": comparison.get("months_per_window", 0),
                "target_change_pct": comparison.get("target_change_pct"),
                "other_origins_change_pct": comparison.get("other_origins_change_pct"),
                "all_origins_change_pct": comparison.get("all_origins_change_pct"),
                "target_share_change_percentage_points": comparison.get(
                    "target_share_change_percentage_points"
                ),
                "coverage_comparability_status": comparison.get(
                    "coverage_comparability_status", ""
                ),
                "observed_hts8_count_gap_ratio": comparison.get(
                    "observed_hts8_count_gap_ratio"
                ),
                "causal_claim": False,
            },
            "evidence": {
                "sources": [
                    _event_source(repository, event),
                    repository.file_source(repository.paths.statistical_baseline_summary),
                    repository.file_source(repository.paths.statistical_baseline_monthly),
                ],
                "formula": "(current window total - reference window total) / reference window total",
            },
            "limitations": [
                "这是相同月份的描述性比较，不是事件研究或因果估计。",
                "中国和其他原产地可能同时受到宏观变化、提前进口和贸易转移影响。",
                str(comparison.get("coverage_limit", "")),
            ],
        }
    )
    return result


def get_data_quality_status(
    *,
    repository: EvidenceRepository | None = None,
) -> dict[str, object]:
    """Return quality rules, review items, fingerprints, and adoption limits."""

    repository = repository or EvidenceRepository()
    report = repository.quality_report()
    rules = report.get("rules", [])
    if not isinstance(rules, list):
        raise RepositoryError("数据质量报告缺少 rules 列表")
    compact_rules = [
        {
            "rule_id": item.get("rule_id"),
            "dimension": item.get("dimension"),
            "severity": item.get("severity"),
            "status": item.get("status"),
            "summary": item.get("summary"),
        }
        for item in rules
        if isinstance(item, dict)
    ]
    result = _common_result("get_data_quality_status")
    result.update(
        {
            "data": {
                "overall_status": report.get("overall_status"),
                "summary": report.get("summary", {}),
                "rules": compact_rules,
                "failed_rules": [item for item in compact_rules if item["status"] == "fail"],
                "review_rules": [item for item in compact_rules if item["status"] == "review"],
                "adoption_decisions": report.get("adoption_decisions", {}),
                "input_fingerprints": report.get("input_fingerprints", {}),
            },
            "evidence": {
                "sources": [repository.file_source(repository.paths.quality_report)],
            },
            "limitations": [
                "pass_with_review 不是无条件通过；复核项必须和数字一起展示。",
                "质量通过只说明数据层满足规则，不会自动解除因果阻断。",
            ],
        }
    )
    return result


def get_causal_readiness(
    *,
    repository: EvidenceRepository | None = None,
) -> dict[str, object]:
    """Return the current causal gate and a hard permission signal."""

    repository = repository or EvidenceRepository()
    design = repository.causal_design()
    eligibility = repository.eligibility_report()
    matching = repository.matching_reports()
    status = str(design.get("status", "unknown"))
    blocked = status.startswith("blocked")
    v1 = matching["v1"]
    v2 = matching["v2"]
    v3 = matching["v3"]
    v1_balance = v1.get("balance", {}).get("features", {})
    v1_failed_features = [
        feature
        for feature, item in v1_balance.items()
        if isinstance(item, dict) and not bool(item.get("passed"))
    ]
    blocking_reasons = [
        f"v1 平衡失败：{', '.join(v1_failed_features) or '未通过'}",
        f"v2 求解器：{v2.get('solver', {}).get('message', '未记录')}",
        f"v3 求解器：{v3.get('solver', {}).get('stage_one', {}).get('message', '未记录')}",
    ]
    result = _common_result("get_causal_readiness")
    result.update(
        {
            "data": {
                "status": status,
                "causal_allowed": False,
                "causal_language_allowed": False,
                "eligibility_status": eligibility.get("status"),
                "matching": {
                    "v1_status": v1.get("status"),
                    "v1_coverage_rate": v1.get("coverage", {}).get("coverage_rate"),
                    "v1_failed_balance_features": v1_failed_features,
                    "v2_status": v2.get("status"),
                    "v2_solver_status_code": v2.get("solver", {}).get("status_code"),
                    "v3_status": v3.get("status"),
                    "v3_solver_status_code": v3.get("solver", {}).get("stage_one", {}).get(
                        "status_code"
                    ),
                    "v3_selected_treated": (v3.get("metrics", {}).get("selected_treated")
                                            if v3.get("solver", {}).get("stage_one", {}).get("success") is True else None),
                    "v3_selection_observed": v3.get("solver", {}).get("stage_one", {}).get("success") is True,
                },
                "pretrend": "not_run",
                "event_study": "not_run",
                "blocking_reasons": blocking_reasons,
                "model_instruction": (
                    "可以回答描述性问题并引用证据；必须拒绝或改写任何‘关税导致’、‘政策造成’等因果断言。"
                ),
                "post_policy_activity_used_for_matching": False,
                "blocked_state_detected": blocked,
            },
            "evidence": {
                "sources": [
                    repository.file_source(repository.paths.causal_design),
                    repository.file_source(repository.paths.eligibility_report),
                    repository.file_source(repository.paths.matching_v1_report),
                    repository.file_source(repository.paths.matching_v2_report),
                    repository.file_source(repository.paths.matching_v3_report),
                ]
            },
            "limitations": [
                "当前因果门槛为 blocked；本工具不会自行放宽匹配规则或生成事件研究。",
                "v3 原报告的 selected_treated=0 是无可行解时的占位；本工具返回 null，不能解释为真实最大匹配数量为零。",
            ],
        }
    )
    return result


def _deduplicate(values: Sequence[object]) -> list[object]:
    seen: set[str] = set()
    result: list[object] = []
    for value in values:
        key = repr(value)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def build_evidence_bundle(
    question: str,
    tool_results: Sequence[Mapping[str, object]],
    *,
    repository: EvidenceRepository | None = None,
) -> dict[str, object]:
    """Combine declared tool results into a source-linked, safety-aware bundle."""

    repository = repository or EvidenceRepository()
    if not isinstance(question, str) or not question.strip():
        raise ToolError("question 不能为空")
    if not isinstance(tool_results, Sequence) or isinstance(tool_results, (str, bytes)):
        raise ToolError("tool_results 必须是工具结果列表")
    if not tool_results:
        raise ToolError("tool_results 不能为空")
    allowed_result_tools = {
        "get_policy_event",
        "get_trade_series",
        "get_descriptive_change",
        "get_data_quality_status",
        "get_causal_readiness",
        "get_policy_exposure_series",
    }
    evidence: list[dict[str, object]] = []
    all_sources: list[object] = []
    all_limitations: list[object] = []
    causal_statuses: list[Mapping[str, object]] = []
    for item in tool_results:
        if not isinstance(item, Mapping):
            raise ToolError("tool_results 中每一项必须是对象")
        tool_name = item.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name:
            raise ToolError("每个工具结果都必须有 tool_name")
        if tool_name not in allowed_result_tools:
            raise ToolError(f"证据包不接受未登记的工具结果：{tool_name}")
        data = item.get("data", {})
        evidence.append({"tool_name": tool_name, "status": item.get("status"), "data": data})
        evidence_block = item.get("evidence", {})
        if isinstance(evidence_block, Mapping):
            sources = evidence_block.get("sources", [])
            if isinstance(sources, Sequence) and not isinstance(sources, (str, bytes)):
                all_sources.extend(sources)
        limitations = item.get("limitations", [])
        if isinstance(limitations, Sequence) and not isinstance(limitations, (str, bytes)):
            all_limitations.extend(limitations)
        if tool_name == "get_causal_readiness" and isinstance(data, Mapping):
            causal_statuses.append(data)
    causal_blocked = any(not bool(item.get("causal_allowed", False)) for item in causal_statuses)
    return {
        "bundle_version": "1.0",
        "question": question.strip(),
        "evidence": evidence,
        "sources": _deduplicate(all_sources),
        "limitations": _deduplicate(all_limitations),
        "safety": {
            "causal_claim": False,
            "causal_language_allowed": False if causal_blocked else False,
            "causal_status_checked": bool(causal_statuses),
            "causal_blocked": causal_blocked,
            "post_policy_activity_used_for_matching": False,
            "unsupported_claims_must_be_refused": True,
        },
        "generated_from_declared_tools": True,
        "data_backend": "verified_csv_artifacts",
        "repository_root": "project_checkout",
    }


class ToolRegistry:
    """A fixed registry suitable for a model's tool-calling schema."""

    def __init__(self, repository: EvidenceRepository | None = None) -> None:
        self.repository = repository or EvidenceRepository()
        self._functions: dict[str, Callable[..., dict[str, object]]] = {
            "get_policy_event": get_policy_event,
            "get_trade_series": get_trade_series,
            "get_descriptive_change": get_descriptive_change,
            "get_data_quality_status": get_data_quality_status,
            "get_causal_readiness": get_causal_readiness,
            "build_evidence_bundle": build_evidence_bundle,
        }

    def names(self) -> list[str]:
        return list(self._functions)

    def schemas(self) -> list[dict[str, object]]:
        """Return provider-neutral JSON schemas for tool calling."""

        return [
            {
                "type": "function",
                "name": "get_policy_event",
                "description": "Read one registered policy event and official source.",
                "parameters": {
                    "type": "object",
                    "properties": {"policy_id": {"type": "string", "default": DEFAULT_POLICY_ID}},
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "get_trade_series",
                "description": "Read a fixed Section 301 List 1 monthly import series.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "origin": {
                            "type": "string",
                            "enum": ["China", "other_origins", "all_origins"],
                            "default": "China",
                        },
                        "policy_id": {"type": "string", "default": DEFAULT_POLICY_ID},
                        "scope": {"type": "string", "enum": [ALLOWED_SCOPE]},
                        "hs6": {"type": ["string", "null"], "pattern": "^[0-9]{6}$"},
                        "start": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}$"},
                        "end": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}$"},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "get_descriptive_change",
                "description": "Read one registered same-calendar-month descriptive comparison.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "comparison_id": {"type": "string", "enum": sorted(ALLOWED_COMPARISONS)},
                        "policy_id": {"type": "string", "default": DEFAULT_POLICY_ID},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "get_data_quality_status",
                "description": "Read audited data-quality rules and adoption decisions.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "type": "function",
                "name": "get_causal_readiness",
                "description": "Read causal gate status and the hard causal-language permission signal.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "type": "function",
                "name": "build_evidence_bundle",
                "description": "Combine declared tool results into a source-linked safety-aware bundle.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "tool_results": {"type": "array", "items": {"type": "object"}},
                    },
                    "required": ["question", "tool_results"],
                    "additionalProperties": False,
                },
            },
        ]

    def call(self, name: str, arguments: Mapping[str, object] | None = None) -> dict[str, object]:
        """Call only a registered function and turn errors into safe results."""

        arguments = dict(arguments or {})
        function = self._functions.get(name)
        if function is None:
            return {
                "tool_name": name,
                "tool_version": "1.0",
                "status": "error",
                "error": {"type": "unknown_tool", "message": f"未登记工具：{name}"},
                "causal_claim": False,
            }
        try:
            if name == "build_evidence_bundle":
                return function(repository=self.repository, **arguments)
            return function(repository=self.repository, **arguments)
        except (ToolError, RepositoryError, OSError, KeyError, TypeError, ValueError) as exc:
            return {
                "tool_name": name,
                "tool_version": "1.0",
                "status": "error",
                "error": {"type": "tool_contract_error", "message": str(exc)},
                "causal_claim": False,
                "post_policy_activity_used_for_matching": False,
            }


def default_registry() -> ToolRegistry:
    """Return a registry rooted at the current checkout."""

    return ToolRegistry(EvidenceRepository(default_paths()))
