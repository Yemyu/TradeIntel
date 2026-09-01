"""Execute the pre-registered globally balanced matching experiment (v2).

The first matching experiment selected three nearest controls independently for
each treated family.  This experiment keeps the same pre-policy candidates and
features, but solves all pair assignments jointly with a mixed-integer linear
program.  It never reads post-policy outcomes before the optimization gates
pass.  NumPy/SciPy are required and must be installed in the project ``.venv``.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

try:
    from scripts.build_prepolicy_matching import (
        CANDIDATE_PANEL_FIELDS,
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
        sample_sd,
    )
except ModuleNotFoundError:  # pragma: no cover - supports direct script execution
    from build_prepolicy_matching import (  # type: ignore[no-redef]
        CANDIDATE_PANEL_FIELDS,
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
        sample_sd,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAUSAL_DIR = PROJECT_ROOT / "data/processed/causal"
DEFAULT_ELIGIBILITY = CAUSAL_DIR / "control_eligibility.csv"
DEFAULT_PAIRS_V2 = CAUSAL_DIR / "matched_control_pairs_v2.csv"
DEFAULT_REPORT_JSON_V2 = CAUSAL_DIR / "matching_balance_report_v2.json"
DEFAULT_REPORT_MD_V2 = CAUSAL_DIR / "matching_balance_report_v2.md"
DEFAULT_CANDIDATE_PANEL_V2 = CAUSAL_DIR / "causal_candidate_panel_v2.csv"
DEFAULT_BASELINE_REPORT = CAUSAL_DIR / "matching_balance_report.json"

MAX_REUSE = 10
INTERNAL_SMD_LIMIT = 0.09
FINAL_SMD_LIMIT = 0.10
CONTROL_COUNT_PER_TREATED = 3
TIME_LIMIT_SECONDS = 300.0

PAIR_V2_FIELDS = [
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


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.unlink(missing_ok=True)
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def load_feature_records(path: Path) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            hs6 = row["hs6_2017"]
            if hs6 in records:
                raise ValueError(f"Duplicate feature key: {hs6}")
            record: dict[str, object] = dict(row)
            record["match_eligible"] = row["match_eligible"] == "1"
            for feature in CONTINUOUS_FEATURES:
                record[feature] = float(row[feature])
            records[hs6] = record
    if not records:
        raise ValueError("Feature table is empty")
    return records


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
        return 0.0
    ordered = sorted(values)
    return ordered[round(quantile * (len(ordered) - 1))]


def effective_sample_size(weights: Iterable[float]) -> float:
    values = [float(weight) for weight in weights if weight > 0]
    if not values:
        return 0.0
    total = sum(values)
    return total * total / sum(value * value for value in values)


def build_edge_list(
    records: dict[str, dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, list[int]], dict[str, list[int]], dict[str, list[dict[str, object]]]]:
    treated_by_naics: dict[str, list[dict[str, object]]] = defaultdict(list)
    controls_by_naics: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in records.values():
        if not record["match_eligible"]:
            continue
        role = record["primary_role"]
        if role == "treated_candidate":
            treated_by_naics[str(record["naics3"])].append(record)
        elif role == "control_candidate":
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
            for distance, control_hs6, control in ranked:
                edge_index = len(edges)
                edge = {
                    "treated_hs6": str(treated["hs6_2017"]),
                    "control_hs6": control_hs6,
                    "naics3": naics,
                    "distance": float(distance),
                }
                edges.append(edge)
                treated_edge_indices[str(treated["hs6_2017"])].append(edge_index)
                control_edge_indices[control_hs6].append(edge_index)
    return edges, dict(treated_edge_indices), dict(control_edge_indices), nearest_rank


def solve_matching(
    records: dict[str, dict[str, object]],
    design: dict[str, object],
) -> tuple[object, list[dict[str, object]], dict[str, object]]:
    """Solve the globally balanced assignment problem."""

    edges, treated_edges, control_edges, nearest_rank = build_edge_list(records)
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
    if not treated or not controls or not edges:
        raise ValueError("No eligible treated/control edge set is available")
    treated_hs6 = {str(row["hs6_2017"]) for row in treated}
    if set(treated_edges) != treated_hs6:
        missing = sorted(treated_hs6 - set(treated_edges))
        raise ValueError(f"Treated families without same-industry controls: {missing[:5]}")

    feature_means = {
        feature: sum(float(row[feature]) for row in treated) / len(treated)
        for feature in CONTINUOUS_FEATURES
    }
    feature_sds = {
        feature: pooled_sd(
            [float(row[feature]) for row in treated],
            [float(row[feature]) for row in controls],
        )
        for feature in CONTINUOUS_FEATURES
    }
    total_edges = len(treated) * CONTROL_COUNT_PER_TREATED
    rows: list[int] = []
    columns: list[int] = []
    data: list[float] = []
    lower_bounds: list[float] = []
    upper_bounds: list[float] = []

    for hs6 in sorted(treated_edges):
        add_constraint(
            {index: 1.0 for index in treated_edges[hs6]},
            CONTROL_COUNT_PER_TREATED,
            CONTROL_COUNT_PER_TREATED,
            rows,
            columns,
            data,
            lower_bounds,
            upper_bounds,
        )
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
    for feature in CONTINUOUS_FEATURES:
        target = feature_means[feature]
        tolerance = INTERNAL_SMD_LIMIT * feature_sds[feature]
        add_constraint(
            {
                index: float(edge["distance"] * 0 + records[str(edge["control_hs6"])][feature])
                for index, edge in enumerate(edges)
            },
            total_edges * (target - tolerance),
            total_edges * (target + tolerance),
            rows,
            columns,
            data,
            lower_bounds,
            upper_bounds,
        )

    # A tiny deterministic secondary cost makes repeated solves choose the same
    # lexicographic edge order without changing the substantive distance goal.
    costs = np.array(
        [float(edge["distance"]) + (index + 1) * 1e-10 for index, edge in enumerate(edges)],
        dtype=float,
    )
    matrix = coo_matrix((data, (rows, columns)), shape=(len(lower_bounds), len(edges))).tocsr()
    result = milp(
        c=costs,
        integrality=np.ones(len(edges), dtype=np.int8),
        bounds=Bounds(np.zeros(len(edges)), np.ones(len(edges))),
        constraints=LinearConstraint(
            matrix,
            np.asarray(lower_bounds, dtype=float),
            np.asarray(upper_bounds, dtype=float),
        ),
        options={"time_limit": TIME_LIMIT_SECONDS, "mip_rel_gap": 0.0, "presolve": True},
    )
    solver_info = {
        "status_code": int(result.status),
        "message": str(result.message),
        "success": bool(result.success),
        "objective": float(result.fun) if result.fun is not None else None,
        "edge_count": len(edges),
        "constraint_count": len(lower_bounds),
        "time_limit_seconds": TIME_LIMIT_SECONDS,
    }
    if not result.success or result.x is None:
        return result, [], {"solver": solver_info}
    selected = [edge for index, edge in enumerate(edges) if float(result.x[index]) > 0.5]
    for edge in selected:
        ranks = nearest_rank[str(edge["treated_hs6"])]
        edge["nearest_distance_rank"] = next(
            int(item["rank"]) for item in ranks if item["control_hs6"] == edge["control_hs6"]
        )
    solver_info["selected_edges"] = len(selected)
    return result, selected, {"solver": solver_info}


def pair_rows_from_edges(edges: list[dict[str, object]]) -> list[dict[str, object]]:
    reuse_counts: Counter[str] = Counter(str(edge["control_hs6"]) for edge in edges)
    rows: list[dict[str, object]] = []
    for edge in sorted(edges, key=lambda item: (str(item["treated_hs6"]), float(item["distance"]), str(item["control_hs6"]))):
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
                "matching_experiment_id": "globally_balanced_optimal_matching_v2",
                "post_policy_activity_used_for_matching": 0,
            }
        )
    return rows


def build_markdown(report: dict[str, object]) -> str:
    gates = report["gates"]
    metrics = report["metrics"]
    lines = [
        "# Phase 09b：全局平衡最优匹配 v2 报告",
        "",
        f"> 状态：`{report['status']}`",
        "",
        "这是在首次三近邻匹配失败后、运行前预先登记的第二个政策前实验。它仍然只使用 2016-01 至 2018-05，不读取政策后结果来选择对照或调整参数。",
        "",
        "## 结果摘要",
        "",
        f"- 处理候选：{metrics['eligible_treated']:,}；覆盖率分母：{metrics['coverage_denominator']:,}；获得至少两个对照：{metrics['treated_with_at_least_two_controls']:,}（{metrics['coverage_rate']:.2%}）。",
        f"- 选择匹配边：{metrics['selected_edges']:,}；使用不同对照：{metrics['unique_controls_used']:,}；控制有效样本量：{metrics['control_effective_sample_size']:.2f}。",
        f"- 平均标准化距离：{metrics['mean_distance']:.6f}（上限 {metrics['mean_distance_max']:.6f}）；95 分位距离：{metrics['p95_distance']:.6f}（上限 {metrics['p95_distance_max']:.6f}）。",
        f"- 最大复用次数：{metrics['maximum_control_reuse']}（上限 {metrics['maximum_control_reuse_max']}）。",
        "",
        "## 门槛",
        "",
        "| 门槛 | 实际值 | 结果 |",
        "|---|---:|---|",
        f"| 覆盖率 ≥ 80% | {metrics['coverage_rate']:.2%} | {'通过' if gates['coverage'] else '失败'} |",
        f"| 控制有效样本量 ≥ 100 | {metrics['control_effective_sample_size']:.2f} | {'通过' if gates['effective_sample_size'] else '失败'} |",
        f"| 最大复用 ≤ 10 | {metrics['maximum_control_reuse']} | {'通过' if gates['maximum_reuse'] else '失败'} |",
        f"| 平均距离不超过基准125% | {metrics['mean_distance']:.6f} | {'通过' if gates['mean_distance'] else '失败'} |",
        f"| 95分位距离不超过基准125% | {metrics['p95_distance']:.6f} | {'通过' if gates['p95_distance'] else '失败'} |",
    ]
    for feature, item in report["balance"]["features"].items():
        observed = (
            f"{item['absolute_matched_smd']:.6f}"
            if report["metrics"]["selected_edges"]
            else "未执行"
        )
        lines.append(
            f"| `{feature}` 绝对 SMD < 0.10 | {observed} | {'通过' if item['passed'] else '失败'} |"
        )
    lines.extend(
        [
            "",
            "## 怎样解释 v2",
            "",
            "v2 不再逐个处理商品独立挑选最近邻，而是一次性决定全部配对，并把总体平衡、对照复用和距离放进同一个优化问题。整数优化器不是大语言模型；它只是严格执行已冻结的数学约束。",
            "",
            "即使 v2 通过，这也只说明观察到的政策前特征达到设计门槛，仍需单独做前趋势检验。若 v2 失败，不能继续查看政策后结果来调参。",
            "",
            f"求解器状态：`{report['solver']['status_code']}`；{report['solver']['message']}",
        ]
    )
    if report["status"] not in {"matching_v2_gates_passed_pretrend_pending"}:
        lines.extend(
            [
                "",
                "本轮仍停在前趋势检验之前，没有生成可用于事件研究的候选面板。",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "v2 的覆盖、平衡、距离和复用门槛均通过，已生成版本化候选面板；下一阶段只能在 Sol 高审查后决定是否进入前趋势检验。",
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
    features_path: Path = DEFAULT_FEATURES,
    panel_path: Path = DEFAULT_PANEL,
    pairs_path: Path = DEFAULT_PAIRS_V2,
    report_json_path: Path = DEFAULT_REPORT_JSON_V2,
    report_md_path: Path = DEFAULT_REPORT_MD_V2,
    candidate_panel_path: Path = DEFAULT_CANDIDATE_PANEL_V2,
) -> dict[str, object]:
    design = load_design(design_path)
    refinement = design.get("matching_refinement_experiment", {})
    if refinement.get("experiment_id") != "globally_balanced_optimal_matching_v2":
        raise ValueError("Frozen v2 experiment is missing from the design")
    records = load_feature_records(features_path)
    _result, selected_edges, solver_info = solve_matching(records, design)
    pair_rows = pair_rows_from_edges(selected_edges)
    write_csv(pairs_path, PAIR_V2_FIELDS, pair_rows)

    treated_hs6 = {str(edge["treated_hs6"]) for edge in selected_edges}
    control_hs6 = {str(edge["control_hs6"]) for edge in selected_edges}
    pair_for_balance = [
        {
            "treated_hs6": str(edge["treated_hs6"]),
            "control_hs6": str(edge["control_hs6"]),
            "edge_weight": 1.0 / CONTROL_COUNT_PER_TREATED,
        }
        for edge in selected_edges
    ]
    balance = compute_balance(records, pair_for_balance)
    reuse_counts: Counter[str] = Counter(str(edge["control_hs6"]) for edge in selected_edges)
    distances = [float(edge["distance"]) for edge in selected_edges]
    metrics: dict[str, object] = {
        "eligible_treated": sum(
            row["match_eligible"] and row["primary_role"] == "treated_candidate" for row in records.values()
        ),
        "eligible_control": sum(
            row["match_eligible"] and row["primary_role"] == "control_candidate" for row in records.values()
        ),
        "coverage_denominator": sum(row["primary_role"] == "treated_candidate" for row in records.values()),
        "treated_with_at_least_two_controls": len(
            {str(edge["treated_hs6"]) for edge in selected_edges}
        ),
        "coverage_rate": 0.0,
        "selected_edges": len(selected_edges),
        "unique_controls_used": len(reuse_counts),
        "control_effective_sample_size": effective_sample_size(
            count / CONTROL_COUNT_PER_TREATED for count in reuse_counts.values()
        ),
        "maximum_control_reuse": max(reuse_counts.values(), default=0),
        "maximum_control_reuse_max": MAX_REUSE,
        "mean_distance": sum(distances) / len(distances) if distances else math.inf,
        "p95_distance": percentile_by_index(distances, 0.95) if distances else math.inf,
        "mean_distance_max": float(refinement["adoption_thresholds"]["mean_distance_max"]),
        "p95_distance_max": float(refinement["adoption_thresholds"]["p95_distance_max"]),
    }
    metrics["coverage_rate"] = (
        metrics["treated_with_at_least_two_controls"] / metrics["coverage_denominator"]
        if metrics["coverage_denominator"]
        else 0.0
    )
    gates = {
        "coverage": float(metrics["coverage_rate"]) >= float(refinement["adoption_thresholds"]["coverage_rate_min"]),
        "effective_sample_size": float(metrics["control_effective_sample_size"])
        >= float(refinement["adoption_thresholds"]["control_effective_sample_size_min"]),
        "maximum_reuse": int(metrics["maximum_control_reuse"])
        <= int(refinement["adoption_thresholds"]["maximum_control_reuse_max"]),
        "mean_distance": float(metrics["mean_distance"]) <= float(metrics["mean_distance_max"]),
        "p95_distance": float(metrics["p95_distance"]) <= float(metrics["p95_distance_max"]),
        "balance": bool(balance["all_features_passed"]),
    }
    gates["all_passed"] = all(gates.values()) and bool(selected_edges)
    status = "matching_v2_gates_passed_pretrend_pending" if gates["all_passed"] else "blocked_before_pretrend_v2"
    report: dict[str, object] = {
        "status": status,
        "stage": "phase_09b_globally_balanced_matching_execution",
        "protocol_id": design["protocol_id"],
        "matching_experiment_id": refinement["experiment_id"],
        "feature_period": ["2016-01", "2018-05"],
        "post_policy_activity_used_for_matching": False,
        "solver": solver_info["solver"],
        "metrics": metrics,
        "gates": gates,
        "balance": balance,
        "outputs": {
            "matched_control_pairs_v2.csv": str(pairs_path.relative_to(PROJECT_ROOT)),
            "matching_balance_report_v2.json": str(report_json_path.relative_to(PROJECT_ROOT)),
            "matching_balance_report_v2.md": str(report_md_path.relative_to(PROJECT_ROOT)),
        },
        "blocked_outputs": ["causal_candidate_panel_v2.csv", "event_study_results.csv"],
        "baseline": {
            "matching_balance_report": str(DEFAULT_BASELINE_REPORT.relative_to(PROJECT_ROOT)),
            "first_run_status": "blocked_before_pretrend",
            "first_run_mean_distance": 0.8287317292296009,
            "first_run_p95_distance": 2.199299793772,
            "first_run_control_effective_sample_size": 52.155769507113085,
            "first_run_maximum_control_reuse": 33,
        },
        "adoption_rule": "Coverage >= 80%, all final absolute SMD < 0.10, control ESS >= 100, maximum reuse <= 10, and distance caps pass.",
        "stop_rule": "If v2 is infeasible or any gate fails, do not inspect post-policy outcomes or relax this experiment's rules.",
    }
    if gates["all_passed"]:
        selected_hs6 = sorted(treated_hs6 | control_hs6)
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
        report["outputs"]["causal_candidate_panel_v2.csv"] = str(candidate_panel_path.relative_to(PROJECT_ROOT))
        report["blocked_outputs"] = []
        report["candidate_panel"] = {
            "selected_hs6": len(selected_hs6),
            "rows": len(selected_hs6) * len(panel_keys),
            "months": len(panel_keys),
            "analysis_weights": "treated=1; controls=matched_edge_count/3",
        }
    update_design_status(design_path, status)
    report_json_path.parent.mkdir(parents=True, exist_ok=True)
    report_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_md_path.write_text(build_markdown(report), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", type=Path, default=DEFAULT_DESIGN)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--pairs", type=Path, default=DEFAULT_PAIRS_V2)
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON_V2)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD_V2)
    parser.add_argument("--candidate-panel", type=Path, default=DEFAULT_CANDIDATE_PANEL_V2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_outputs(
        design_path=args.design,
        features_path=args.features,
        panel_path=args.panel,
        pairs_path=args.pairs,
        report_json_path=args.report_json,
        report_md_path=args.report_md,
        candidate_panel_path=args.candidate_panel,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
