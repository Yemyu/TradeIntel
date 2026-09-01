"""Execute the final pre-registered maximum-cardinality matching experiment.

The v1 nearest-neighbour experiment failed two balance gates.  The v2 global
assignment was infeasible because it forced all 284 uniquely classified treated
families to remain.  v3 allows a transparent policy-pre overlap trim while
requiring at least 252 of the original 315 treated candidates, and keeps the
same industry, reuse, balance, and distance safeguards.

Only the pre-policy feature table is read before the optimization succeeds.  A
full post-policy panel is loaded only if every v3 adoption gate passes.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

try:
    from scripts.build_prepolicy_matching import (
        CONTINUOUS_FEATURES,
        DEFAULT_CANDIDATE_PANEL,
        DEFAULT_DESIGN,
        DEFAULT_FEATURES,
        DEFAULT_PANEL,
        PRE_END,
        PRE_START,
        build_candidate_panel,
        compute_balance,
        feature_distance,
        load_panel,
        load_design,
        month_keys,
        pooled_sd,
        pool_standardization,
    )
    from scripts.build_globally_balanced_matching import load_feature_records
except ModuleNotFoundError:  # pragma: no cover - supports direct execution
    from build_prepolicy_matching import (  # type: ignore[no-redef]
        CONTINUOUS_FEATURES,
        DEFAULT_CANDIDATE_PANEL,
        DEFAULT_DESIGN,
        DEFAULT_FEATURES,
        DEFAULT_PANEL,
        PRE_END,
        PRE_START,
        build_candidate_panel,
        compute_balance,
        feature_distance,
        load_panel,
        load_design,
        month_keys,
        pooled_sd,
        pool_standardization,
    )
    from build_globally_balanced_matching import load_feature_records  # type: ignore[no-redef]


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAUSAL_DIR = PROJECT_ROOT / "data/processed/causal"
DEFAULT_PAIRS_V3 = CAUSAL_DIR / "matched_control_pairs_v3.csv"
DEFAULT_EXCLUDED_V3 = CAUSAL_DIR / "matching_excluded_treated_v3.csv"
DEFAULT_REPORT_JSON_V3 = CAUSAL_DIR / "matching_balance_report_v3.json"
DEFAULT_REPORT_MD_V3 = CAUSAL_DIR / "matching_balance_report_v3.md"
DEFAULT_CANDIDATE_PANEL_V3 = CAUSAL_DIR / "causal_candidate_panel_v3.csv"

EXPERIMENT_ID = "maximum_cardinality_balanced_overlap_matching_v3"
CONTROL_COUNT_PER_TREATED = 3
MAX_REUSE = 10
MIN_INCLUDED_TREATED = 252
INTERNAL_SMD_LIMIT = 0.09
FINAL_SMD_LIMIT = 0.10
TIME_LIMIT_SECONDS = 300.0

PAIR_V3_FIELDS = [
    "treated_hs6",
    "control_hs6",
    "naics3",
    "distance",
    "nearest_distance_rank",
    "edge_weight",
    "control_reuse_count",
    "feature_period",
    "matching_experiment_id",
    "post_policy_activity_used_for_matching",
]

EXCLUDED_FIELDS = [
    "hs6_2017",
    "naics3",
    "naics3_candidates",
    "third_nearest_distance",
    "china_share_of_all_origin_imports",
    "control_share_min",
    "control_share_max",
    "exclusion_reason",
    "post_policy_activity_used_for_matching",
]


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.unlink(missing_ok=True)
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def add_constraint(
    coefficients: dict[int, float],
    lower: float,
    upper: float,
    rows: list[int],
    columns: list[int],
    data: list[float],
    lower_bounds: list[float],
    upper_bounds: list[float],
) -> None:
    row_number = len(lower_bounds)
    for column, value in coefficients.items():
        if value:
            rows.append(row_number)
            columns.append(column)
            data.append(value)
    lower_bounds.append(lower)
    upper_bounds.append(upper)


def percentile_by_index(values: list[float], quantile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    return ordered[round(quantile * (len(ordered) - 1))]


def effective_sample_size(weights: Iterable[float]) -> float:
    values = [float(weight) for weight in weights if weight > 0]
    if not values:
        return 0.0
    total = sum(values)
    return total * total / sum(value * value for value in values)


def build_edges(
    records: dict[str, dict[str, object]],
) -> tuple[
    list[dict[str, object]],
    dict[str, list[int]],
    dict[str, list[int]],
    dict[str, list[dict[str, object]]],
]:
    treated_by_naics: dict[str, list[dict[str, object]]] = defaultdict(list)
    controls_by_naics: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in records.values():
        if not record["match_eligible"]:
            continue
        if record["primary_role"] == "treated_candidate":
            treated_by_naics[str(record["naics3"])].append(record)
        elif record["primary_role"] == "control_candidate":
            controls_by_naics[str(record["naics3"])].append(record)

    edges: list[dict[str, object]] = []
    treated_edge_indices: dict[str, list[int]] = defaultdict(list)
    control_edge_indices: dict[str, list[int]] = defaultdict(list)
    nearest_rank: dict[str, list[dict[str, object]]] = {}
    for naics in sorted(treated_by_naics):
        controls = sorted(controls_by_naics.get(naics, []), key=lambda row: str(row["hs6_2017"]))
        if not controls:
            continue
        means, sds, _zero_sd = pool_standardization(controls)
        for treated in sorted(treated_by_naics[naics], key=lambda row: str(row["hs6_2017"])):
            ranked = sorted(
                (
                    feature_distance(treated, control, means, sds),
                    str(control["hs6_2017"]),
                    control,
                )
                for control in controls
            )
            nearest_rank[str(treated["hs6_2017"])] = [
                {"control_hs6": control_hs6, "distance": distance, "rank": rank}
                for rank, (distance, control_hs6, _control) in enumerate(ranked, start=1)
            ]
            for distance, control_hs6, _control in ranked:
                edge_index = len(edges)
                edges.append(
                    {
                        "treated_hs6": str(treated["hs6_2017"]),
                        "control_hs6": control_hs6,
                        "naics3": naics,
                        "distance": float(distance),
                    }
                )
                treated_edge_indices[str(treated["hs6_2017"])].append(edge_index)
                control_edge_indices[control_hs6].append(edge_index)
    return edges, dict(treated_edge_indices), dict(control_edge_indices), nearest_rank


def _build_matrix(
    records: dict[str, dict[str, object]],
    edges: list[dict[str, object]],
    treated_edges: dict[str, list[int]],
    control_edges: dict[str, list[int]],
    *,
    include_minimum: bool,
    fixed_treated_count: int | None = None,
) -> tuple[coo_matrix, np.ndarray, np.ndarray, np.ndarray]:
    treated = sorted(
        (
            row
            for row in records.values()
            if row["match_eligible"] and row["primary_role"] == "treated_candidate"
        ),
        key=lambda row: str(row["hs6_2017"]),
    )
    controls = sorted(
        (
            row
            for row in records.values()
            if row["match_eligible"] and row["primary_role"] == "control_candidate"
        ),
        key=lambda row: str(row["hs6_2017"]),
    )
    treated_index = {str(row["hs6_2017"]): index for index, row in enumerate(treated)}
    edge_count = len(edges)
    variable_count = edge_count + len(treated)
    rows: list[int] = []
    columns: list[int] = []
    data: list[float] = []
    lower_bounds: list[float] = []
    upper_bounds: list[float] = []

    # Each selected treated must have exactly three distinct control edges.
    for hs6 in sorted(treated_edges):
        coefficients = {index: 1.0 for index in treated_edges[hs6]}
        coefficients[edge_count + treated_index[hs6]] = -CONTROL_COUNT_PER_TREATED
        add_constraint(
            coefficients,
            0.0,
            0.0,
            rows,
            columns,
            data,
            lower_bounds,
            upper_bounds,
        )

    # A control can be reused across treated families, but not more than ten times.
    for hs6 in sorted(control_edges):
        add_constraint(
            {index: 1.0 for index in control_edges[hs6]},
            0.0,
            MAX_REUSE,
            rows,
            columns,
            data,
            lower_bounds,
            upper_bounds,
        )

    treated_values = {
        feature: [float(row[feature]) for row in treated]
        for feature in CONTINUOUS_FEATURES
    }
    control_values = {
        feature: [float(row[feature]) for row in controls]
        for feature in CONTINUOUS_FEATURES
    }
    treated_means = {
        feature: sum(values) / len(values) if values else 0.0
        for feature, values in treated_values.items()
    }
    pooled_sds = {
        feature: pooled_sd(treated_values[feature], control_values[feature])
        for feature in CONTINUOUS_FEATURES
    }

    # The selected treated count is variable.  Multiplying both group means by
    # 3*N keeps the balance constraint linear in edge and treated variables:
    # |3 sum(z_t*T_t) - sum(x_e*C_e)| <= 3*delta*sum(z_t).
    for feature in CONTINUOUS_FEATURES:
        delta = INTERNAL_SMD_LIMIT * pooled_sds[feature]
        upper_coefficients: dict[int, float] = {}
        lower_coefficients: dict[int, float] = {}
        for index, edge in enumerate(edges):
            control_value = float(records[str(edge["control_hs6"])][feature])
            upper_coefficients[index] = -control_value
            lower_coefficients[index] = control_value
        for index, row in enumerate(treated):
            treated_value = float(row[feature])
            upper_coefficients[edge_count + index] = 3.0 * treated_value - 3.0 * delta
            lower_coefficients[edge_count + index] = -3.0 * treated_value - 3.0 * delta
        add_constraint(
            upper_coefficients,
            -math.inf,
            0.0,
            rows,
            columns,
            data,
            lower_bounds,
            upper_bounds,
        )
        add_constraint(
            lower_coefficients,
            -math.inf,
            0.0,
            rows,
            columns,
            data,
            lower_bounds,
            upper_bounds,
        )

    if include_minimum:
        add_constraint(
            {edge_count + index: 1.0 for index in range(len(treated))},
            MIN_INCLUDED_TREATED,
            math.inf,
            rows,
            columns,
            data,
            lower_bounds,
            upper_bounds,
        )
    if fixed_treated_count is not None:
        add_constraint(
            {edge_count + index: 1.0 for index in range(len(treated))},
            fixed_treated_count,
            fixed_treated_count,
            rows,
            columns,
            data,
            lower_bounds,
            upper_bounds,
        )
    matrix = coo_matrix((data, (rows, columns)), shape=(len(lower_bounds), variable_count))
    lower = np.asarray(lower_bounds, dtype=float)
    upper = np.asarray(upper_bounds, dtype=float)
    return matrix, lower, upper, np.asarray(treated_means[CONTINUOUS_FEATURES[0]] if treated_means else 0.0)


def solve_stage(
    records: dict[str, dict[str, object]],
    *,
    maximize_cardinality: bool,
    fixed_treated_count: int | None = None,
) -> tuple[object, list[dict[str, object]], dict[str, object]]:
    edges, treated_edges, control_edges, nearest_rank = build_edges(records)
    matrix, lower, upper, _unused = _build_matrix(
        records,
        edges,
        treated_edges,
        control_edges,
        include_minimum=maximize_cardinality,
        fixed_treated_count=fixed_treated_count,
    )
    edge_count = len(edges)
    variable_count = edge_count + len(treated_edges)
    if maximize_cardinality:
        costs = np.array(
            [1e-10 * (index + 1) for index in range(edge_count)]
            + [-1.0 + 1e-10 * (index + 1) for index in range(len(treated_edges))],
            dtype=float,
        )
    else:
        costs = np.array(
            [float(edge["distance"]) + 1e-10 * (index + 1) for index, edge in enumerate(edges)]
            + [1e-12 * (index + 1) for index in range(len(treated_edges))],
            dtype=float,
        )
    result = milp(
        c=costs,
        integrality=np.ones(variable_count, dtype=np.int8),
        bounds=Bounds(np.zeros(variable_count), np.ones(variable_count)),
        constraints=LinearConstraint(matrix.tocsr(), lower, upper),
        options={"time_limit": TIME_LIMIT_SECONDS, "mip_rel_gap": 0.0, "presolve": True},
    )
    info: dict[str, object] = {
        "status_code": int(result.status),
        "message": str(result.message),
        "success": bool(result.success),
        "objective": float(result.fun) if result.fun is not None else None,
        "edge_count": edge_count,
        "variable_count": variable_count,
        "constraint_count": matrix.shape[0],
        "time_limit_seconds": TIME_LIMIT_SECONDS,
        "stage": "maximize_cardinality" if maximize_cardinality else "minimize_distance_at_max_cardinality",
    }
    if not result.success or result.x is None:
        return result, [], {"solver": info, "edges": edges, "nearest_rank": nearest_rank}
    selected = [edge.copy() for index, edge in enumerate(edges) if float(result.x[index]) > 0.5]
    treated_count = sum(
        float(result.x[edge_count + index]) > 0.5 for index in range(len(treated_edges))
    )
    for edge in selected:
        ranks = nearest_rank[str(edge["treated_hs6"])]
        edge["nearest_distance_rank"] = next(
            int(item["rank"]) for item in ranks if item["control_hs6"] == edge["control_hs6"]
        )
    info["selected_edges"] = len(selected)
    info["selected_treated"] = int(treated_count)
    return result, selected, {"solver": info, "edges": edges, "nearest_rank": nearest_rank}


def pair_rows_from_edges(edges: list[dict[str, object]]) -> tuple[list[dict[str, object]], Counter[str]]:
    reuse_counts: Counter[str] = Counter(str(edge["control_hs6"]) for edge in edges)
    rows: list[dict[str, object]] = []
    for edge in sorted(
        edges,
        key=lambda item: (
            str(item["treated_hs6"]),
            float(item["distance"]),
            str(item["control_hs6"]),
        ),
    ):
        rows.append(
            {
                "treated_hs6": edge["treated_hs6"],
                "control_hs6": edge["control_hs6"],
                "naics3": edge["naics3"],
                "distance": f"{float(edge['distance']):.12f}",
                "nearest_distance_rank": edge.get("nearest_distance_rank", ""),
                "edge_weight": f"{1 / CONTROL_COUNT_PER_TREATED:.12f}",
                "control_reuse_count": reuse_counts[str(edge["control_hs6"])],
                "feature_period": "2016-01_to_2018-05",
                "matching_experiment_id": EXPERIMENT_ID,
                "post_policy_activity_used_for_matching": 0,
            }
        )
    return rows, reuse_counts


def excluded_rows(
    records: dict[str, dict[str, object]],
    included_treated: set[str],
) -> list[dict[str, object]]:
    controls_by_naics: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in records.values():
        if record["match_eligible"] and record["primary_role"] == "control_candidate":
            controls_by_naics[str(record["naics3"])].append(record)
    rows: list[dict[str, object]] = []
    for hs6, record in sorted(records.items()):
        if not (record["match_eligible"] and record["primary_role"] == "treated_candidate"):
            continue
        if hs6 in included_treated:
            continue
        controls = controls_by_naics.get(str(record["naics3"]), [])
        means, sds, _zero = pool_standardization(controls) if controls else ({}, {}, [])
        distances = (
            sorted(feature_distance(record, control, means, sds) for control in controls)
            if controls
            else []
        )
        shares = [float(control["china_share_of_all_origin_imports"]) for control in controls]
        rows.append(
            {
                "hs6_2017": hs6,
                "naics3": record["naics3"],
                "naics3_candidates": record["naics3_candidates"],
                "third_nearest_distance": f"{distances[2]:.12f}" if len(distances) >= 3 else "",
                "china_share_of_all_origin_imports": f"{float(record['china_share_of_all_origin_imports']):.12f}",
                "control_share_min": f"{min(shares):.12f}" if shares else "",
                "control_share_max": f"{max(shares):.12f}" if shares else "",
                "exclusion_reason": "not_selected_by_maximum_cardinality_balance_solver",
                "post_policy_activity_used_for_matching": 0,
            }
        )
    return rows


def build_markdown(report: dict[str, object]) -> str:
    metrics = report["metrics"]
    gates = report["gates"]
    mean_distance = metrics["mean_distance"]
    p95_distance = metrics["p95_distance"]
    mean_distance_text = "未执行" if mean_distance is None else f"{float(mean_distance):.6f}"
    p95_distance_text = "未执行" if p95_distance is None else f"{float(p95_distance):.6f}"
    lines = [
        "# Phase 09c：最大基数平衡子样本匹配 v3 报告",
        "",
        f"> 状态：`{report['status']}`",
        "",
        "v3 是在 v1 平衡失败、v2 全样本无可行解之后，运行前登记的最后一次匹配实验。它只使用 2016-01 至 2018-05 的政策前特征。",
        "",
        "## 结果摘要",
        "",
        f"- 可唯一确定 NAICS3 的处理候选：{metrics['eligible_treated']:,}；最大基数解保留：{metrics['selected_treated']:,}；覆盖全部315个候选的比例：{metrics['coverage_rate']:.2%}。",
        f"- 选择匹配边：{metrics['selected_edges']:,}；不同对照：{metrics['unique_controls_used']:,}；控制有效样本量：{metrics['control_effective_sample_size']:.2f}。",
        f"- 平均标准化距离：{mean_distance_text}（上限 {metrics['mean_distance_max']:.6f}）；95分位距离：{p95_distance_text}（上限 {metrics['p95_distance_max']:.6f}）。",
        f"- 最大对照复用：{metrics['maximum_control_reuse']}（上限 {metrics['maximum_control_reuse_max']}）。",
        "",
        "## 采纳门槛",
        "",
        "| 门槛 | 实际值 | 结果 |",
        "|---|---:|---|",
        f"| 至少保留252/315处理候选 | {metrics['selected_treated']:,}（{metrics['coverage_rate']:.2%}） | {'通过' if gates['coverage'] else '失败'} |",
        f"| 控制有效样本量 ≥ 100 | {metrics['control_effective_sample_size']:.2f} | {'通过' if gates['effective_sample_size'] else '失败'} |",
        f"| 最大复用 ≤ 10 | {metrics['maximum_control_reuse']} | {'通过' if gates['maximum_reuse'] else '失败'} |",
        f"| 平均距离不超过基准125% | {mean_distance_text} | {'通过' if gates['mean_distance'] else '失败'} |",
        f"| 95分位距离不超过基准125% | {p95_distance_text} | {'通过' if gates['p95_distance'] else '失败'} |",
    ]
    for feature, item in report["balance"]["features"].items():
        observed = f"{item['absolute_matched_smd']:.6f}" if metrics["selected_edges"] else "未执行"
        lines.append(
            f"| `{feature}` 绝对 SMD < 0.10 | {observed} | {'通过' if item['passed'] else '失败'} |"
        )
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "如果 v3 通过，后续结果只适用于政策前特征具有足够共同支持的重叠子样本，不能外推为全部原始 List 1 商品的平均效果。被优化器排除的处理商品及其政策前支持诊断见 `matching_excluded_treated_v3.csv`。",
            "",
            "所有配对、退出和门槛计算都没有使用政策后结果。若状态为阻断，项目不进入前趋势检验，也不运行事件研究。",
            "",
            f"第一阶段求解器：`{report['solver']['stage_one']['status_code']}`；{report['solver']['stage_one']['message']}",
        ]
    )
    if report["solver"].get("stage_two"):
        lines.append(
            f"第二阶段求解器：`{report['solver']['stage_two']['status_code']}`；{report['solver']['stage_two']['message']}"
        )
    return "\n".join(lines) + "\n"


def update_design_status(path: Path, status: str) -> None:
    with path.open(encoding="utf-8") as handle:
        design = json.load(handle)
    design["status"] = status
    if isinstance(design.get("matching_cardinality_experiment"), dict):
        design["matching_cardinality_experiment"]["status"] = status
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_outputs(
    *,
    design_path: Path = DEFAULT_DESIGN,
    features_path: Path = DEFAULT_FEATURES,
    panel_path: Path = DEFAULT_PANEL,
    pairs_path: Path = DEFAULT_PAIRS_V3,
    excluded_path: Path = DEFAULT_EXCLUDED_V3,
    report_json_path: Path = DEFAULT_REPORT_JSON_V3,
    report_md_path: Path = DEFAULT_REPORT_MD_V3,
    candidate_panel_path: Path = DEFAULT_CANDIDATE_PANEL_V3,
) -> dict[str, object]:
    design = load_design(design_path)
    experiment = design.get("matching_cardinality_experiment", {})
    if experiment.get("experiment_id") != EXPERIMENT_ID:
        raise ValueError("Frozen v3 experiment is missing from the design")
    records = load_feature_records(features_path)

    first_result, _first_edges, first_meta = solve_stage(
        records,
        maximize_cardinality=True,
    )
    solver_report: dict[str, object] = {"stage_one": first_meta["solver"]}
    selected_edges: list[dict[str, object]] = []
    maximum_treated: int | None = None
    if first_result.success and first_result.x is not None:
        maximum_treated = int(first_meta["solver"].get("selected_treated", 0))
        second_result, selected_edges, second_meta = solve_stage(
            records,
            maximize_cardinality=False,
            fixed_treated_count=maximum_treated,
        )
        solver_report["stage_two"] = second_meta["solver"]
        if not second_result.success:
            selected_edges = []
    pair_rows, reuse_counts = pair_rows_from_edges(selected_edges)
    write_csv(pairs_path, PAIR_V3_FIELDS, pair_rows)

    pair_for_balance = [
        {
            "treated_hs6": str(edge["treated_hs6"]),
            "control_hs6": str(edge["control_hs6"]),
            "edge_weight": 1.0 / CONTROL_COUNT_PER_TREATED,
        }
        for edge in selected_edges
    ]
    balance = compute_balance(records, pair_for_balance)
    selected_treated = {str(edge["treated_hs6"]) for edge in selected_edges}
    distances = [float(edge["distance"]) for edge in selected_edges]
    metrics: dict[str, object] = {
        "eligible_treated": sum(
            row["match_eligible"] and row["primary_role"] == "treated_candidate" for row in records.values()
        ),
        "eligible_control": sum(
            row["match_eligible"] and row["primary_role"] == "control_candidate" for row in records.values()
        ),
        "coverage_denominator": sum(row["primary_role"] == "treated_candidate" for row in records.values()),
        "selected_treated": len(selected_treated),
        "selected_edges": len(selected_edges),
        "coverage_rate": 0.0,
        "unique_controls_used": len(reuse_counts),
        "control_effective_sample_size": effective_sample_size(
            count / CONTROL_COUNT_PER_TREATED for count in reuse_counts.values()
        ),
        "maximum_control_reuse": max(reuse_counts.values(), default=0),
        "maximum_control_reuse_max": MAX_REUSE,
        "mean_distance": sum(distances) / len(distances) if distances else None,
        "p95_distance": percentile_by_index(distances, 0.95) if distances else None,
        "mean_distance_max": float(experiment["adoption_thresholds"]["mean_distance_max"]),
        "p95_distance_max": float(experiment["adoption_thresholds"]["p95_distance_max"]),
    }
    metrics["coverage_rate"] = (
        metrics["selected_treated"] / metrics["coverage_denominator"]
        if metrics["coverage_denominator"]
        else 0.0
    )
    gates = {
        "coverage": int(metrics["selected_treated"]) >= MIN_INCLUDED_TREATED
        and float(metrics["coverage_rate"]) >= float(experiment["adoption_thresholds"]["coverage_rate_min"]),
        "effective_sample_size": float(metrics["control_effective_sample_size"])
        >= float(experiment["adoption_thresholds"]["control_effective_sample_size_min"]),
        "maximum_reuse": int(metrics["maximum_control_reuse"])
        <= int(experiment["adoption_thresholds"]["maximum_control_reuse_max"]),
        "mean_distance": metrics["mean_distance"] is not None
        and float(metrics["mean_distance"]) <= float(metrics["mean_distance_max"]),
        "p95_distance": metrics["p95_distance"] is not None
        and float(metrics["p95_distance"]) <= float(metrics["p95_distance_max"]),
        "balance": bool(balance["all_features_passed"])
        and all(
            math.isfinite(float(item["matched_smd"]))
            and abs(float(item["matched_smd"])) < FINAL_SMD_LIMIT
            for item in balance["features"].values()
        ),
    }
    gates["all_passed"] = all(gates.values()) and bool(selected_edges)
    status = "matching_v3_gates_passed_pretrend_pending" if gates["all_passed"] else "blocked_before_pretrend_v3"

    excluded = excluded_rows(records, selected_treated)
    write_csv(excluded_path, EXCLUDED_FIELDS, excluded)
    report: dict[str, object] = {
        "status": status,
        "stage": "phase_09c_maximum_cardinality_matching_execution",
        "protocol_id": design["protocol_id"],
        "matching_experiment_id": EXPERIMENT_ID,
        "feature_period": ["2016-01", "2018-05"],
        "post_policy_activity_used_for_matching": False,
        "solver": solver_report,
        "metrics": metrics,
        "gates": gates,
        "balance": balance,
        "excluded_treated_count": len(excluded),
        "outputs": {
            "matched_control_pairs_v3.csv": str(pairs_path.relative_to(PROJECT_ROOT)),
            "matching_excluded_treated_v3.csv": str(excluded_path.relative_to(PROJECT_ROOT)),
            "matching_balance_report_v3.json": str(report_json_path.relative_to(PROJECT_ROOT)),
            "matching_balance_report_v3.md": str(report_md_path.relative_to(PROJECT_ROOT)),
        },
        "blocked_outputs": ["causal_candidate_panel_v3.csv", "event_study_results.csv"],
        "estimand_boundary": "If adopted, the effect would apply only to the maximum policy-pre overlap subpopulation, not all original List 1 treated families.",
        "adoption_rule": "At least 252/315 treated, all absolute SMD < 0.10, control ESS >= 100, maximum reuse <= 10, and both distance caps pass.",
        "stop_rule": "If v3 is infeasible or any gate fails, do not design a fourth matching experiment or inspect post-policy outcomes.",
    }
    if gates["all_passed"]:
        selected_hs6 = sorted(selected_treated | {str(edge["control_hs6"]) for edge in selected_edges})
        pre_keys = set(month_keys(PRE_START, PRE_END))
        panel_keys = set(month_keys((2016, 1), (2019, 12)))
        _unused_pre, all_by_key = load_panel(
            panel_path,
            set(selected_hs6),
            pre_keys=pre_keys,
            panel_keys=panel_keys,
        )
        control_weights = defaultdict(float)
        for edge in selected_edges:
            control_weights[str(edge["control_hs6"])] += 1.0 / CONTROL_COUNT_PER_TREATED
        build_candidate_panel(
            candidate_panel_path,
            selected_hs6=selected_hs6,
            records=records,
            all_by_key=all_by_key,
            panel_keys=sorted(panel_keys),
            use_counts=reuse_counts,
            control_weights=dict(control_weights),
        )
        report["outputs"]["causal_candidate_panel_v3.csv"] = str(candidate_panel_path.relative_to(PROJECT_ROOT))
        report["blocked_outputs"] = []
        report["candidate_panel"] = {
            "selected_hs6": len(selected_hs6),
            "rows": len(selected_hs6) * len(panel_keys),
            "months": len(panel_keys),
            "analysis_weights": "treated=1; controls=matched_edge_count/3",
        }
    update_design_status(design_path, status)
    report_json_path.parent.mkdir(parents=True, exist_ok=True)
    report_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    report_md_path.write_text(build_markdown(report), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", type=Path, default=DEFAULT_DESIGN)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--pairs", type=Path, default=DEFAULT_PAIRS_V3)
    parser.add_argument("--excluded", type=Path, default=DEFAULT_EXCLUDED_V3)
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON_V3)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD_V3)
    parser.add_argument("--candidate-panel", type=Path, default=DEFAULT_CANDIDATE_PANEL_V3)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_outputs(
        design_path=args.design,
        features_path=args.features,
        panel_path=args.panel,
        pairs_path=args.pairs,
        excluded_path=args.excluded,
        report_json_path=args.report_json,
        report_md_path=args.report_md,
        candidate_panel_path=args.candidate_panel,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
