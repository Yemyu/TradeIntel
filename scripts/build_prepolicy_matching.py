"""Build the frozen policy-pre matching layer for the causal case.

This script deliberately has no dependency on pandas, scipy, or a database.  It
reads the already audited HS6-by-month panel and the Phase 07 eligibility table,
uses only 2016-01 through 2018-05, and writes auditable feature, pair, balance,
and (only after the gates pass) candidate-panel outputs.

The matching rule is frozen in ``config/causal_control_design.json``.  In
particular, no post-policy outcome is read to select industries, controls, or
parameters.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAUSAL_DIR = PROJECT_ROOT / "data/processed/causal"
DEFAULT_DESIGN = PROJECT_ROOT / "config/causal_control_design.json"
DEFAULT_PANEL = CAUSAL_DIR / "causal_trade_hs6_monthly.csv"
DEFAULT_ELIGIBILITY = CAUSAL_DIR / "control_eligibility.csv"
DEFAULT_FEATURES = CAUSAL_DIR / "control_candidate_features.csv"
DEFAULT_PAIRS = CAUSAL_DIR / "matched_control_pairs.csv"
DEFAULT_CANDIDATE_PANEL = CAUSAL_DIR / "causal_candidate_panel.csv"
DEFAULT_REPORT_JSON = CAUSAL_DIR / "matching_balance_report.json"
DEFAULT_REPORT_MD = CAUSAL_DIR / "matching_balance_report.md"

PRE_START = (2016, 1)
PRE_END = (2018, 5)
PANEL_START = (2016, 1)
PANEL_END = (2019, 12)
CHINA_ORIGIN_CODE = "5700"

CONTINUOUS_FEATURES = [
    "log_mean_monthly_china_import_value",
    "pretrend_slope",
    "monthly_volatility",
    "china_share_of_all_origin_imports",
]

FEATURE_FIELDS = [
    "hs6_2017",
    "assignment_status",
    "primary_role",
    "naics3_candidates",
    "naics3",
    "match_eligible",
    "match_exclusion_reason",
    "selection_window",
    "pre_months",
    "positive_pre_months_actual",
    "positive_pre_months_eligibility",
    "mean_china_import_value_usd",
    "total_china_import_value_usd",
    "total_all_origin_import_value_usd",
    "log_mean_monthly_china_import_value",
    "pretrend_slope",
    "monthly_volatility",
    "china_share_of_all_origin_imports",
    "post_policy_activity_used_for_matching",
]

PAIR_FIELDS = [
    "treated_hs6",
    "control_hs6",
    "naics3",
    "rank",
    "distance",
    "edge_weight",
    "feature_period",
    "post_policy_activity_used_for_matching",
]

CANDIDATE_PANEL_FIELDS = [
    "year",
    "month",
    "hs6_2017",
    "analysis_role",
    "analysis_weight",
    "matched_control_use_count",
    "matched_control_weight",
    "china_import_value_consumption_usd",
    "all_origin_import_value_consumption_usd",
    "china_share",
    "source_hts10_count",
    "source_hts10_mapped_count",
    "source_url",
    "source_file_name",
    "source_sha256",
    "post_policy_activity_used_for_matching",
]


def month_keys(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    """Return every inclusive year-month key in chronological order."""

    keys: list[tuple[int, int]] = []
    year, month = start
    while (year, month) <= end:
        keys.append((year, month))
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return keys


def parse_number(value: str | int | float | None) -> float:
    """Parse a non-negative trade amount, treating an empty cell as zero."""

    if value is None or str(value).strip() == "":
        return 0.0
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"Trade value must be finite and non-negative: {value!r}")
    return number


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, object]]) -> None:
    """Atomically write a UTF-8 CSV so an interrupted run leaves no partial file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.unlink(missing_ok=True)
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def load_design(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        design = json.load(handle)
    if design.get("protocol_id") != "section301_list1_control_v1":
        raise ValueError(f"Unexpected causal protocol in {path}")
    matching = design.get("matching", {})
    if matching.get("post_outcomes_allowed") is not False:
        raise ValueError("Frozen matching design must prohibit post-policy outcomes")
    if matching.get("number_of_controls") != 3:
        raise ValueError("This implementation requires the frozen three-control rule")
    if matching.get("replacement") is not True:
        raise ValueError("This implementation requires frozen matching with replacement")
    return design


def unique_naics3(value: str) -> tuple[str, str]:
    """Return (unique code, exclusion reason) without guessing ambiguous codes."""

    candidates = sorted({item.strip() for item in value.split("|") if item.strip()})
    if not candidates:
        return "", "missing_naics3_candidates"
    if len(candidates) != 1:
        return "", "ambiguous_naics3_candidates"
    return candidates[0], ""


def load_eligibility(path: Path) -> dict[str, dict[str, str]]:
    """Load and validate the frozen Phase 07 candidate table."""

    records: dict[str, dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            hs6 = row["hs6_2017"].strip()
            if not hs6 or hs6 in records:
                raise ValueError(f"Duplicate or empty eligibility key: {hs6!r}")
            if row["primary_role"] not in {"treated_candidate", "control_candidate", "excluded"}:
                raise ValueError(f"Unexpected eligibility role for {hs6}: {row['primary_role']}")
            records[hs6] = row
    if not records:
        raise ValueError("Eligibility table is empty")
    return records


def load_panel(
    path: Path,
    candidate_hs6: set[str],
    *,
    pre_keys: set[tuple[int, int]],
    panel_keys: set[tuple[int, int]],
) -> tuple[
    dict[str, dict[tuple[int, int], dict[str, object]]],
    dict[tuple[str, tuple[int, int]], dict[str, object]],
]:
    """Load candidate rows and reject duplicate HS6 × month business keys."""

    pre_by_hs6: dict[str, dict[tuple[int, int], dict[str, object]]] = defaultdict(dict)
    all_by_key: dict[tuple[str, tuple[int, int]], dict[str, object]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            hs6 = row["hs6_2017"].strip()
            if hs6 not in candidate_hs6:
                continue
            key_month = (int(row["year"]), int(row["month"]))
            if key_month not in panel_keys:
                continue
            key = (hs6, key_month)
            if key in all_by_key:
                raise ValueError(f"Duplicate panel key: {hs6}/{key_month[0]}-{key_month[1]:02d}")
            record: dict[str, object] = {
                "year": key_month[0],
                "month": key_month[1],
                "china": parse_number(row["china_import_value_consumption_usd"]),
                "all_origin": parse_number(row["all_origin_import_value_consumption_usd"]),
                "source_hts10_count": row.get("source_hts10_count", ""),
                "source_hts10_mapped_count": row.get("source_hts10_mapped_count", ""),
                "source_url": row.get("source_url", ""),
                "source_file_name": row.get("source_file_name", ""),
                "source_sha256": row.get("source_sha256", ""),
            }
            if record["china"] > record["all_origin"]:
                raise ValueError(f"China value exceeds all-origin value: {hs6}/{key_month}")
            all_by_key[key] = record
            if key_month in pre_keys:
                pre_by_hs6[hs6][key_month] = record
    return dict(pre_by_hs6), all_by_key


def sample_sd(values: Sequence[float]) -> float:
    """Sample standard deviation, with zero for a one-value/constant pool."""

    if len(values) <= 1:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(max(variance, 0.0))


def ols_slope(values: Sequence[float]) -> float:
    """Slope of values on equally spaced month indices 0..n-1."""

    if len(values) <= 1:
        return 0.0
    x_mean = (len(values) - 1) / 2
    y_mean = sum(values) / len(values)
    denominator = sum((index - x_mean) ** 2 for index in range(len(values)))
    if denominator == 0:
        return 0.0
    return sum((index - x_mean) * (value - y_mean) for index, value in enumerate(values)) / denominator


def compute_preperiod_features(
    china_values: Sequence[float], all_origin_values: Sequence[float]
) -> dict[str, float]:
    """Compute the four frozen features from a complete policy-pre period."""

    if len(china_values) != len(all_origin_values) or not china_values:
        raise ValueError("China and all-origin series must have the same non-zero length")
    if any(value < 0 for value in list(china_values) + list(all_origin_values)):
        raise ValueError("Feature inputs must be non-negative")
    if any(china > all_origin for china, all_origin in zip(china_values, all_origin_values)):
        raise ValueError("China cannot exceed all-origin in a monthly feature input")
    log_values = [math.log1p(value) for value in china_values]
    total_china = sum(china_values)
    total_all = sum(all_origin_values)
    return {
        "mean_china_import_value_usd": sum(china_values) / len(china_values),
        "total_china_import_value_usd": total_china,
        "total_all_origin_import_value_usd": total_all,
        "log_mean_monthly_china_import_value": math.log1p(sum(china_values) / len(china_values)),
        "pretrend_slope": ols_slope(log_values),
        "monthly_volatility": sample_sd(log_values),
        "china_share_of_all_origin_imports": total_china / total_all if total_all else 0.0,
    }


def build_feature_records(
    eligibility: dict[str, dict[str, str]],
    pre_by_hs6: dict[str, dict[tuple[int, int], dict[str, object]]],
    pre_keys: Sequence[tuple[int, int]],
) -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    """Create numeric feature records and their CSV audit rows."""

    numeric: dict[str, dict[str, object]] = {}
    audit_rows: list[dict[str, object]] = []
    for hs6 in sorted(eligibility):
        source = eligibility[hs6]
        role = source["primary_role"]
        naics, exclusion_reason = unique_naics3(source.get("naics3_candidates", ""))
        match_eligible = role in {"treated_candidate", "control_candidate"} and not exclusion_reason
        rows = pre_by_hs6.get(hs6, {})
        china_values = [float(rows.get(key, {}).get("china", 0.0)) for key in pre_keys]
        all_values = [float(rows.get(key, {}).get("all_origin", 0.0)) for key in pre_keys]
        features = compute_preperiod_features(china_values, all_values)
        positive_months = sum(value > 0 for value in china_values)
        record: dict[str, object] = {
            "hs6_2017": hs6,
            "primary_role": role,
            "assignment_status": source.get("assignment_status", ""),
            "naics3_candidates": source.get("naics3_candidates", ""),
            "naics3": naics,
            "match_eligible": match_eligible,
            "match_exclusion_reason": exclusion_reason if role != "excluded" else "not_a_phase07_candidate",
            "selection_window": source.get("selection_window", "2016-01_to_2018-05"),
            "positive_pre_months_actual": positive_months,
            "positive_pre_months_eligibility": int(source.get("positive_pre_months", "0") or 0),
            **features,
        }
        numeric[hs6] = record
        if role in {"treated_candidate", "control_candidate"}:
            audit_rows.append(
                {
                "hs6_2017": hs6,
                "assignment_status": record["assignment_status"],
                "primary_role": role,
                "naics3_candidates": record["naics3_candidates"],
                "naics3": naics,
                "match_eligible": int(match_eligible),
                "match_exclusion_reason": record["match_exclusion_reason"],
                "selection_window": record["selection_window"],
                "pre_months": len(pre_keys),
                "positive_pre_months_actual": positive_months,
                "positive_pre_months_eligibility": record["positive_pre_months_eligibility"],
                "mean_china_import_value_usd": f"{features['mean_china_import_value_usd']:.6f}",
                "total_china_import_value_usd": f"{features['total_china_import_value_usd']:.6f}",
                "total_all_origin_import_value_usd": f"{features['total_all_origin_import_value_usd']:.6f}",
                "log_mean_monthly_china_import_value": f"{features['log_mean_monthly_china_import_value']:.12f}",
                "pretrend_slope": f"{features['pretrend_slope']:.12f}",
                "monthly_volatility": f"{features['monthly_volatility']:.12f}",
                "china_share_of_all_origin_imports": f"{features['china_share_of_all_origin_imports']:.12f}",
                "post_policy_activity_used_for_matching": 0,
                }
            )
    return numeric, audit_rows


def pool_standardization(
    controls: Sequence[dict[str, object]],
) -> tuple[dict[str, float], dict[str, float], list[str]]:
    """Return control-pool means, sample SDs, and features with zero SD."""

    means: dict[str, float] = {}
    sds: dict[str, float] = {}
    zero_sd: list[str] = []
    for feature in CONTINUOUS_FEATURES:
        values = [float(row[feature]) for row in controls]
        means[feature] = sum(values) / len(values) if values else 0.0
        sds[feature] = sample_sd(values)
        if sds[feature] == 0.0:
            zero_sd.append(feature)
    return means, sds, zero_sd


def standardized_value(value: float, mean: float, sd: float) -> float:
    return (value - mean) / sd if sd else 0.0


def feature_distance(
    treated: dict[str, object],
    control: dict[str, object],
    means: dict[str, float],
    sds: dict[str, float],
) -> float:
    """Euclidean distance on within-industry standardized features."""

    squared = 0.0
    for feature in CONTINUOUS_FEATURES:
        treated_z = standardized_value(float(treated[feature]), means[feature], sds[feature])
        control_z = standardized_value(float(control[feature]), means[feature], sds[feature])
        squared += (treated_z - control_z) ** 2
    return math.sqrt(squared)


def match_nearest_controls(
    records: dict[str, dict[str, object]],
    *,
    number_of_controls: int = 3,
) -> tuple[list[dict[str, object]], dict[str, list[str]], dict[str, list[str]]]:
    """Match each uniquely classified treated family to nearest controls."""

    treated_by_naics: dict[str, list[dict[str, object]]] = defaultdict(list)
    controls_by_naics: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in records.values():
        if not record["match_eligible"]:
            continue
        naics = str(record["naics3"])
        if record["primary_role"] == "treated_candidate":
            treated_by_naics[naics].append(record)
        elif record["primary_role"] == "control_candidate":
            controls_by_naics[naics].append(record)

    pairs: list[dict[str, object]] = []
    pool_audit: dict[str, list[str]] = {}
    for naics in sorted(treated_by_naics):
        controls = sorted(controls_by_naics.get(naics, []), key=lambda row: str(row["hs6_2017"]))
        if not controls:
            pool_audit[naics] = ["no_controls"]
            continue
        means, sds, zero_sd = pool_standardization(controls)
        pool_audit[naics] = zero_sd
        for treated in sorted(treated_by_naics[naics], key=lambda row: str(row["hs6_2017"])):
            ranked = sorted(
                (
                    (feature_distance(treated, control, means, sds), str(control["hs6_2017"]), control)
                    for control in controls
                ),
                key=lambda item: (item[0], item[1]),
            )
            selected = ranked[: min(number_of_controls, len(ranked))]
            for rank, (distance, control_hs6, _control) in enumerate(selected, start=1):
                pairs.append(
                    {
                        "treated_hs6": str(treated["hs6_2017"]),
                        "control_hs6": control_hs6,
                        "naics3": naics,
                        "rank": rank,
                        "distance": distance,
                        "edge_weight": 1.0 / len(selected),
                    }
                )
    return pairs, dict(treated_by_naics), dict(controls_by_naics)


def pooled_sd(first: Sequence[float], second: Sequence[float]) -> float:
    """Pooled sample SD used as the frozen SMD denominator."""

    if len(first) + len(second) <= 2:
        return 0.0
    first_sd = sample_sd(first)
    second_sd = sample_sd(second)
    numerator = max(len(first) - 1, 0) * first_sd**2 + max(len(second) - 1, 0) * second_sd**2
    return math.sqrt(max(numerator / (len(first) + len(second) - 2), 0.0))


def standardized_mean_difference(difference: float, denominator: float) -> float:
    if denominator == 0.0:
        return 0.0 if difference == 0.0 else math.inf
    return difference / denominator


def compute_balance(
    records: dict[str, dict[str, object]],
    pairs: Sequence[dict[str, object]],
    *,
    threshold: float = 0.10,
) -> dict[str, object]:
    """Calculate pre-match and matched weighted SMDs for every feature."""

    eligible_treated = [
        row for row in records.values() if row["match_eligible"] and row["primary_role"] == "treated_candidate"
    ]
    eligible_controls = [
        row for row in records.values() if row["match_eligible"] and row["primary_role"] == "control_candidate"
    ]
    pair_treated_hs6 = sorted({str(pair["treated_hs6"]) for pair in pairs})
    matched_treated = [records[hs6] for hs6 in pair_treated_hs6]
    control_edges = [(records[str(pair["control_hs6"])], float(pair["edge_weight"])) for pair in pairs]
    has_matched_sample = bool(matched_treated) and bool(control_edges)
    features: dict[str, dict[str, object]] = {}
    for feature in CONTINUOUS_FEATURES:
        pre_treated_values = [float(row[feature]) for row in eligible_treated]
        pre_control_values = [float(row[feature]) for row in eligible_controls]
        matched_treated_values = [float(row[feature]) for row in matched_treated]
        total_weight = sum(weight for _row, weight in control_edges)
        matched_control_mean = (
            sum(float(row[feature]) * weight for row, weight in control_edges) / total_weight
            if total_weight
            else 0.0
        )
        pre_treated_mean = sum(pre_treated_values) / len(pre_treated_values) if pre_treated_values else 0.0
        pre_control_mean = sum(pre_control_values) / len(pre_control_values) if pre_control_values else 0.0
        matched_treated_mean = (
            sum(matched_treated_values) / len(matched_treated_values) if matched_treated_values else 0.0
        )
        denominator = pooled_sd(pre_treated_values, pre_control_values)
        pre_smd = standardized_mean_difference(pre_treated_mean - pre_control_mean, denominator)
        matched_smd = standardized_mean_difference(matched_treated_mean - matched_control_mean, denominator)
        features[feature] = {
            "pre_match_treated_mean": pre_treated_mean,
            "pre_match_control_mean": pre_control_mean,
            "matched_treated_mean": matched_treated_mean,
            "matched_control_weighted_mean": matched_control_mean,
            "pooled_sd": denominator,
            "pre_match_smd": pre_smd,
            "matched_smd": matched_smd,
            "absolute_matched_smd": abs(matched_smd),
            "passed": has_matched_sample
            and math.isfinite(matched_smd)
            and abs(matched_smd) < threshold,
        }
    return {
        "threshold": threshold,
        "features": features,
        "all_features_passed": has_matched_sample
        and all(bool(item["passed"]) for item in features.values()),
        "matched_treated_count": len(matched_treated),
        "matched_control_edge_count": len(control_edges),
        "matched_control_weight": sum(weight for _row, weight in control_edges),
    }


def format_number(value: float) -> str:
    if math.isinf(value):
        return "∞"
    return f"{value:.6f}"


def build_candidate_panel(
    output_path: Path,
    *,
    selected_hs6: Sequence[str],
    records: dict[str, dict[str, object]],
    all_by_key: dict[tuple[str, tuple[int, int]], dict[str, object]],
    panel_keys: Sequence[tuple[int, int]],
    use_counts: Counter[str],
    control_weights: dict[str, float],
) -> None:
    """Write a weighted 48-month panel only after matching gates pass."""

    rows: list[dict[str, object]] = []
    for hs6 in sorted(selected_hs6):
        record = records[hs6]
        role = "treated" if record["primary_role"] == "treated_candidate" else "control"
        use_count = int(use_counts.get(hs6, 0))
        control_weight = control_weights.get(hs6, 0.0) if role == "control" else 0.0
        analysis_weight = 1.0 if role == "treated" else control_weight
        for year, month in panel_keys:
            source = all_by_key.get((hs6, (year, month)), {})
            china = float(source.get("china", 0.0))
            all_origin = float(source.get("all_origin", 0.0))
            rows.append(
                {
                    "year": year,
                    "month": month,
                    "hs6_2017": hs6,
                    "analysis_role": role,
                    "analysis_weight": f"{analysis_weight:.12f}",
                    "matched_control_use_count": use_count,
                    "matched_control_weight": f"{control_weight:.12f}",
                    "china_import_value_consumption_usd": f"{china:.6f}",
                    "all_origin_import_value_consumption_usd": f"{all_origin:.6f}",
                    "china_share": f"{china / all_origin if all_origin else 0.0:.12f}",
                    "source_hts10_count": source.get("source_hts10_count", ""),
                    "source_hts10_mapped_count": source.get("source_hts10_mapped_count", ""),
                    "source_url": source.get("source_url", ""),
                    "source_file_name": source.get("source_file_name", ""),
                    "source_sha256": source.get("source_sha256", ""),
                    "post_policy_activity_used_for_matching": 0,
                }
            )
    write_csv(output_path, CANDIDATE_PANEL_FIELDS, rows)


def build_markdown(report: dict[str, object]) -> str:
    """Create the Chinese, learner-facing execution report."""

    counts = report["counts"]
    coverage = report["coverage"]
    balance = report["balance"]
    lines = [
        "# Phase 09：政策前匹配与平衡性报告",
        "",
        f"> 状态：`{report['status']}`",
        "",
        "本阶段只使用 2016-01 至 2018-05 的 29 个月数据。2018-06 及以后没有参与特征计算、行业筛选、对照选择或参数调整。",
        "",
        "## 先看结论",
        "",
        f"- Phase 07 候选：{counts['eligibility_treated']:,} 个处理、{counts['eligibility_control']:,} 个对照。",
        f"- 因 NAICS3 唯一性进入主匹配：{counts['match_eligible_treated']:,} 个处理、{counts['match_eligible_control']:,} 个对照。",
        f"- 实际获得至少两个对照的处理商品：{coverage['treated_with_at_least_two_controls']:,}/{coverage['coverage_denominator']:,}（{coverage['coverage_rate']:.2%}）。",
        f"- 生成匹配边：{counts['matched_pairs']:,} 条；同一对照允许被多个处理商品复用，每条边权重为 1/3。",
        "",
        "## 门槛",
        "",
        "| 门槛 | 实际值 | 规则 | 结果 |",
        "|---|---:|---:|---|",
        f"| 匹配覆盖率 | {coverage['coverage_rate']:.2%} | ≥ {coverage['coverage_threshold']:.2%} | {'通过' if coverage['passed'] else '失败'} |",
    ]
    for feature in CONTINUOUS_FEATURES:
        item = balance["features"][feature]
        lines.append(
            f"| `{feature}` 匹配后绝对 SMD | {item['absolute_matched_smd']:.6f} | < {balance['threshold']:.2f} | {'通过' if item['passed'] else '失败'} |"
        )
    lines.extend(
        [
            "",
            "## 怎样读这张表",
            "",
            "`SMD` 是标准化均值差：先比较处理组和加权对照组的平均特征，再除以匹配前两组的合并标准差。0 表示两组平均值相同；绝对值越小，政策前可比性越好。0.10 是本项目运行前固定的采纳门槛，不是机器学习准确率。",
            "",
            "`NAICS3` 是三位行业分类。主匹配要求处理和对照都有唯一行业代码；多个候选行业的商品被保留在特征表中，但不被猜测性地放进主匹配。",
            "",
            "## 防泄漏记录",
            "",
            "- `post_policy_activity_used_for_matching = 0`；",
            "- 特征窗口固定为 2016-01 至 2018-05；",
            "- 没有查看政策后涨跌来选择控制，也没有为了通过门槛而更换控制池。",
            "",
            f"如果状态为 `{report['status']}`，它只表示匹配层的覆盖与平衡结果；还不表示平行趋势通过，更不表示已经估计出关税因果效应。",
        ]
    )
    if report["status"] != "matching_gates_passed_pretrend_pending":
        lines.extend(
            [
                "",
                "因此本轮不生成可供事件研究使用的 `causal_candidate_panel.csv`，也不进入政策前趋势检验。按冻结规则，下一步应先解释失败原因，而不是观察政策后结果后重新挑选对照。",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "匹配覆盖和平衡门槛通过，已生成稳定的 48 个月候选面板。下一阶段仍必须单独检查政策前趋势，趋势门槛通过前不能发布因果估计。",
            ]
        )
    return "\n".join(lines) + "\n"


def update_design_status(path: Path, status: str) -> None:
    with path.open(encoding="utf-8") as handle:
        design = json.load(handle)
    design["status"] = status
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_outputs(
    *,
    design_path: Path = DEFAULT_DESIGN,
    panel_path: Path = DEFAULT_PANEL,
    eligibility_path: Path = DEFAULT_ELIGIBILITY,
    features_path: Path = DEFAULT_FEATURES,
    pairs_path: Path = DEFAULT_PAIRS,
    candidate_panel_path: Path = DEFAULT_CANDIDATE_PANEL,
    report_json_path: Path = DEFAULT_REPORT_JSON,
    report_md_path: Path = DEFAULT_REPORT_MD,
) -> dict[str, object]:
    design = load_design(design_path)
    eligibility = load_eligibility(eligibility_path)
    pre_keys_list = month_keys(PRE_START, PRE_END)
    panel_keys_list = month_keys(PANEL_START, PANEL_END)
    pre_keys = set(pre_keys_list)
    panel_keys = set(panel_keys_list)
    candidate_hs6 = {
        hs6
        for hs6, row in eligibility.items()
        if row["primary_role"] in {"treated_candidate", "control_candidate"}
    }
    # First pass intentionally reads only the clean pre-policy window.  The
    # post-policy rows are not even loaded until all matching gates pass.
    pre_by_hs6, _pre_only_rows = load_panel(
        panel_path,
        candidate_hs6,
        pre_keys=pre_keys,
        panel_keys=pre_keys,
    )
    records, feature_rows = build_feature_records(eligibility, pre_by_hs6, pre_keys_list)
    write_csv(features_path, FEATURE_FIELDS, feature_rows)

    pairs, treated_by_naics, controls_by_naics = match_nearest_controls(records)
    pair_rows = [
        {
            **pair,
            "rank": pair["rank"],
            "distance": f"{float(pair['distance']):.12f}",
            "edge_weight": f"{float(pair['edge_weight']):.12f}",
            "feature_period": "2016-01_to_2018-05",
            "post_policy_activity_used_for_matching": 0,
        }
        for pair in pairs
    ]
    pair_rows.sort(key=lambda row: (row["treated_hs6"], int(row["rank"]), row["control_hs6"]))
    write_csv(pairs_path, PAIR_FIELDS, pair_rows)

    use_counts: Counter[str] = Counter(str(pair["control_hs6"]) for pair in pairs)
    control_weights: defaultdict[str, float] = defaultdict(float)
    for pair in pairs:
        control_weights[str(pair["control_hs6"])] += float(pair["edge_weight"])
    pair_counts: Counter[str] = Counter(str(pair["treated_hs6"]) for pair in pairs)
    eligibility_treated = sum(row["primary_role"] == "treated_candidate" for row in eligibility.values())
    eligibility_control = sum(row["primary_role"] == "control_candidate" for row in eligibility.values())
    match_eligible_treated = sum(
        row["match_eligible"] and row["primary_role"] == "treated_candidate" for row in records.values()
    )
    match_eligible_control = sum(
        row["match_eligible"] and row["primary_role"] == "control_candidate" for row in records.values()
    )
    covered_two = sum(count >= 2 for count in pair_counts.values())
    coverage_denominator = eligibility_treated
    matching = design["matching"]
    threshold_match = re.search(r"(\d+)_percent", str(matching["coverage_threshold"]))
    if not threshold_match:
        raise ValueError("Frozen coverage threshold must contain an explicit percentage")
    coverage_threshold = int(threshold_match.group(1)) / 100.0
    coverage_rate = covered_two / coverage_denominator if coverage_denominator else 0.0
    coverage_passed = coverage_rate >= coverage_threshold
    balance = compute_balance(records, pairs)
    gates_passed = coverage_passed and bool(balance["all_features_passed"])
    status = "matching_gates_passed_pretrend_pending" if gates_passed else "blocked_before_pretrend"

    zero_sd_by_naics = {
        naics: features for naics, features in sorted(
            (
                naics,
                pool_standardization(controls_by_naics[naics])[2],
            )
            for naics in controls_by_naics
            if controls_by_naics[naics]
        )
        if features
    }
    report: dict[str, object] = {
        "status": status,
        "stage": "phase_09_prepolicy_matching_execution",
        "protocol_id": design["protocol_id"],
        "feature_period": ["2016-01", "2018-05"],
        "post_policy_activity_used_for_matching": False,
        "counts": {
            "eligibility_treated": eligibility_treated,
            "eligibility_control": eligibility_control,
            "match_eligible_treated": match_eligible_treated,
            "match_eligible_control": match_eligible_control,
            "treated_excluded_for_naics3": eligibility_treated - match_eligible_treated,
            "control_excluded_for_naics3": eligibility_control - match_eligible_control,
            "treated_industries_with_candidates": len(treated_by_naics),
            "matched_treated": len(pair_counts),
            "matched_pairs": len(pairs),
            "unique_controls_used": len(use_counts),
        },
        "coverage": {
            "coverage_denominator": coverage_denominator,
            "treated_with_at_least_two_controls": covered_two,
            "coverage_rate": coverage_rate,
            "coverage_threshold": coverage_threshold,
            "passed": coverage_passed,
            "treated_with_three_controls": sum(count >= 3 for count in pair_counts.values()),
        },
        "balance": balance,
        "zero_sd_by_naics": zero_sd_by_naics,
        "outputs": {
            "control_candidate_features.csv": str(features_path.relative_to(PROJECT_ROOT)),
            "matched_control_pairs.csv": str(pairs_path.relative_to(PROJECT_ROOT)),
            "matching_balance_report.json": str(report_json_path.relative_to(PROJECT_ROOT)),
            "matching_balance_report.md": str(report_md_path.relative_to(PROJECT_ROOT)),
        },
        "blocked_outputs": [] if gates_passed else ["causal_candidate_panel.csv", "event_study_results.csv"],
        "assumptions": {
            "hypothesis": "Most treated families have at least two similar clean controls within the same NAICS3.",
            "baseline": "All Phase 07 treated/control candidates with exactly one NAICS3, before matching.",
            "adoption_rule": "Coverage >= 80% of all Phase 07 treated candidates and every matched continuous-feature absolute SMD < 0.10.",
            "stop_rule": "If either gate fails, do not inspect post-policy outcomes to retune the design.",
        },
    }
    if gates_passed:
        selected_hs6 = list(pair_counts) + sorted(use_counts)
        selected_hs6 = sorted(set(selected_hs6))
        _unused_pre, all_by_key = load_panel(
            panel_path,
            set(selected_hs6),
            pre_keys=pre_keys,
            panel_keys=panel_keys,
        )
        build_candidate_panel(
            candidate_panel_path,
            selected_hs6=selected_hs6,
            records=records,
            all_by_key=all_by_key,
            panel_keys=panel_keys_list,
            use_counts=use_counts,
            control_weights=dict(control_weights),
        )
        report["outputs"]["causal_candidate_panel.csv"] = str(candidate_panel_path.relative_to(PROJECT_ROOT))
        report["candidate_panel"] = {
            "selected_hs6": len(selected_hs6),
            "rows": len(selected_hs6) * len(panel_keys_list),
            "months": len(panel_keys_list),
            "analysis_weights": "treated=1; controls=number_of_matched_edges/3",
        }
    update_design_status(design_path, status)
    report_json_path.parent.mkdir(parents=True, exist_ok=True)
    report_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_md_path.write_text(build_markdown(report), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", type=Path, default=DEFAULT_DESIGN)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--eligibility", type=Path, default=DEFAULT_ELIGIBILITY)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--pairs", type=Path, default=DEFAULT_PAIRS)
    parser.add_argument("--candidate-panel", type=Path, default=DEFAULT_CANDIDATE_PANEL)
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_outputs(
        design_path=args.design,
        panel_path=args.panel,
        eligibility_path=args.eligibility,
        features_path=args.features,
        pairs_path=args.pairs,
        candidate_panel_path=args.candidate_panel,
        report_json_path=args.report_json,
        report_md_path=args.report_md,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
