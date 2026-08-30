"""Build a transparent statistical baseline for the first policy case.

The baseline compares the same calendar months across adjacent years and
tracks China's share of all origins.  It is deliberately descriptive: the
current dataset contains only treated List 1 products and other origins may
also respond to the tariff, so they are not a clean causal control group.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = Path("data/processed/analysis/policy_case_monthly.csv")
DEFAULT_OUTPUT_DIR = Path("data/processed/analysis")
EVENT_MONTH = (2018, 7)
ANNOUNCEMENT_MONTH = (2018, 6)
POLICY_HTS8_COUNT = 818
COVERAGE_COUNT_GAP_THRESHOLD = 0.01


class StatisticalBaselineError(RuntimeError):
    """Raised when the descriptive baseline cannot be computed safely."""


def month_key(year: int, month: int) -> tuple[int, int]:
    if month < 1 or month > 12:
        raise StatisticalBaselineError(f"Invalid month: {year}-{month}")
    return year, month


def month_index(key: tuple[int, int]) -> int:
    return key[0] * 12 + key[1] - 1


def event_time(key: tuple[int, int]) -> int:
    return month_index(key) - month_index(EVENT_MONTH)


def classify_analysis_phase(key: tuple[int, int]) -> str:
    if key < ANNOUNCEMENT_MONTH:
        return "clean_pre"
    if key == ANNOUNCEMENT_MONTH:
        return "announcement_anticipation"
    if key == EVENT_MONTH:
        return "effective_month_transition"
    if key <= (2018, 12):
        return "immediate_post"
    return "later_post_monitoring"


def percent_change(before: int | float, after: int | float) -> float | None:
    if before == 0:
        return None
    return (after - before) / before


def load_monthly(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            try:
                year = int(raw["year"])
                month = int(raw["month"])
                target = int(raw["target_import_value_consumption_usd"])
                others = int(raw["other_origins_import_value_consumption_usd"])
                total = int(raw["all_origins_import_value_consumption_usd"])
                observed_policy_codes = int(raw["unique_policy_hts8_count"])
            except (KeyError, ValueError) as exc:
                raise StatisticalBaselineError(f"Invalid monthly row: {raw}") from exc
            key = month_key(year, month)
            if (
                min(target, others, total, observed_policy_codes) < 0
                or target + others != total
                or total == 0
                or observed_policy_codes > POLICY_HTS8_COUNT
            ):
                raise StatisticalBaselineError(f"Inconsistent monthly values: {raw}")
            rows.append(
                {
                    "key": key,
                    "year": year,
                    "month": month,
                    "month_label": f"{year:04d}-{month:02d}",
                    "target_origin": raw["target_origin"],
                    "target_origin_code": raw["target_origin_code"],
                    "target": target,
                    "others": others,
                    "total": total,
                    "share": target / total,
                    "observed_policy_codes": observed_policy_codes,
                }
            )
    rows.sort(key=lambda row: row["key"])
    if len(rows) != 48:
        raise StatisticalBaselineError(f"Expected 48 months, found {len(rows)}")
    keys = [row["key"] for row in rows]
    if len(set(keys)) != len(keys):
        raise StatisticalBaselineError("Monthly input contains duplicate months")
    if any(month_index(right) - month_index(left) != 1 for left, right in zip(keys, keys[1:])):
        raise StatisticalBaselineError("Monthly input is not continuous")
    if len({row["target_origin_code"] for row in rows}) != 1:
        raise StatisticalBaselineError("Target origin changes across months")
    return rows


def period_comparison(
    by_key: dict[tuple[int, int], dict[str, object]],
    *,
    comparison_id: str,
    interpretation: str,
    current_keys: list[tuple[int, int]],
    reference_keys: list[tuple[int, int]],
) -> dict[str, object]:
    if len(current_keys) != len(reference_keys) or not current_keys:
        raise StatisticalBaselineError("Comparison windows must be non-empty and equal")
    try:
        current = [by_key[key] for key in current_keys]
        reference = [by_key[key] for key in reference_keys]
    except KeyError as exc:
        raise StatisticalBaselineError(f"Comparison month is missing: {exc.args[0]}") from exc

    def total(rows: list[dict[str, object]], field: str) -> int:
        return sum(int(row[field]) for row in rows)

    current_target = total(current, "target")
    reference_target = total(reference, "target")
    current_others = total(current, "others")
    reference_others = total(reference, "others")
    current_all = total(current, "total")
    reference_all = total(reference, "total")
    current_share = current_target / current_all
    reference_share = reference_target / reference_all
    current_coverage_average = sum(
        int(row["observed_policy_codes"]) for row in current
    ) / len(current)
    reference_coverage_average = sum(
        int(row["observed_policy_codes"]) for row in reference
    ) / len(reference)
    coverage_gap_ratio = abs(
        current_coverage_average - reference_coverage_average
    ) / POLICY_HTS8_COUNT
    coverage_status = (
        "pass_count_gap_le_1pct"
        if coverage_gap_ratio <= COVERAGE_COUNT_GAP_THRESHOLD
        else "review_count_gap_gt_1pct"
    )
    return {
        "comparison_id": comparison_id,
        "interpretation": interpretation,
        "current_months": [str(row["month_label"]) for row in current],
        "reference_months": [str(row["month_label"]) for row in reference],
        "months_per_window": len(current),
        "target_total_current_usd": current_target,
        "target_total_reference_usd": reference_target,
        "target_change_pct": percent_change(reference_target, current_target),
        "other_origins_total_current_usd": current_others,
        "other_origins_total_reference_usd": reference_others,
        "other_origins_change_pct": percent_change(reference_others, current_others),
        "all_origins_total_current_usd": current_all,
        "all_origins_total_reference_usd": reference_all,
        "all_origins_change_pct": percent_change(reference_all, current_all),
        "target_share_current": current_share,
        "target_share_reference": reference_share,
        "target_share_change_percentage_points": (current_share - reference_share) * 100,
        "observed_hts8_average_current": current_coverage_average,
        "observed_hts8_average_reference": reference_coverage_average,
        "observed_hts8_count_gap_ratio": coverage_gap_ratio,
        "coverage_comparability_status": coverage_status,
        "coverage_limit": (
            "Count similarity is only a screening check; it does not prove identical "
            "HTS composition or resolve classification revisions."
        ),
    }


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _write_report(path: Path, summary: dict[str, object]) -> None:
    primary = summary["comparisons"]["immediate_post_same_months"]
    placebo = summary["comparisons"]["pre_policy_placebo_same_months"]
    persistence = summary["comparisons"]["persistence_monitoring_same_months"]

    def pct(value: object) -> str:
        return f"{float(value) * 100:.1f}%"

    def pp(value: object) -> str:
        return f"{float(value):.1f} 个百分点"

    content = f"""# Section 301 List 1 描述性统计基线

> 结论级别：描述性证据；不作因果声称

## 核心结果

主窗口使用 2018 年 8–12 月，并与 2017 年相同月份比较：

- 中国相关商品进口额同比变化：{pct(primary['target_change_pct'])}；
- 其他原产地相关商品进口额同比变化：{pct(primary['other_origins_change_pct'])}；
- 所有原产地相关商品进口额同比变化：{pct(primary['all_origins_change_pct'])}；
- 中国在这些商品进口中的份额变化：{pp(primary['target_share_change_percentage_points'])}。
- 两个窗口的月均可观测 HTS8 数量约为 {primary['observed_hts8_average_reference']:.1f} 和 {primary['observed_hts8_average_current']:.1f}，数量差距低于预设的 1% 初筛门槛；但这不代表商品构成完全相同。

## 为什么还不能说是关税造成的

当前面板只包含被 List 1 覆盖的商品，没有未被加征关税的相似商品作为干净对照；其他国家还可能因贸易转移受到政策间接影响，因此“其他原产地”也不是无污染对照组。产品排除、企业提前进口和同期宏观变化同样可能影响结果。

## 两个辅助窗口

- 政策前安慰剂窗口（2017 年 8–12 月对 2016 年同期）的 HTS8 数量差距为 {pct(placebo['observed_hts8_count_gap_ratio'])}，超过 1% 初筛门槛，因此结果被标记为 `review`，不能拿来判断政策前趋势。这说明下一步必须补商品跨版本映射。
- 持续性监测窗口（2019 年 8–12 月对 2018 年同期）：中国进口额变化 {pct(persistence['target_change_pct'])}，份额变化 {pp(persistence['target_share_change_percentage_points'])}。两个窗口都处于政策实施后，所以它只能描述后续走势，不能估计政策效应。

## 使用规则

AI 可以引用这些数字回答“观察到了什么”，但必须同时返回 `causal_claim=false` 和因果限制。只有补充未处理商品、产品排除时间线并通过前趋势与稳健性检查后，才允许评估因果模型。
"""
    path.write_text(content, encoding="utf-8")


def build_statistical_baseline(
    input_path: Path = DEFAULT_INPUT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, object]:
    rows = load_monthly(input_path)
    by_key = {row["key"]: row for row in rows}

    comparisons = [
        period_comparison(
            by_key,
            comparison_id="recent_clean_pre_same_months",
            interpretation="Recent pre-policy diagnostic; not a treatment estimate.",
            current_keys=[(2018, month) for month in range(1, 6)],
            reference_keys=[(2017, month) for month in range(1, 6)],
        ),
        period_comparison(
            by_key,
            comparison_id="pre_policy_placebo_same_months",
            interpretation="Placebo comparison before treatment; reveals existing movement.",
            current_keys=[(2017, month) for month in range(8, 13)],
            reference_keys=[(2016, month) for month in range(8, 13)],
        ),
        period_comparison(
            by_key,
            comparison_id="immediate_post_same_months",
            interpretation="Primary descriptive rollout window; not a causal estimate.",
            current_keys=[(2018, month) for month in range(8, 13)],
            reference_keys=[(2017, month) for month in range(8, 13)],
        ),
        period_comparison(
            by_key,
            comparison_id="persistence_monitoring_same_months",
            interpretation="Both windows are post-policy; monitoring only.",
            current_keys=[(2019, month) for month in range(8, 13)],
            reference_keys=[(2018, month) for month in range(8, 13)],
        ),
    ]

    monthly_output_rows: list[dict[str, object]] = []
    for row in rows:
        key = row["key"]
        previous = by_key.get((key[0] - 1, key[1]))
        monthly_output_rows.append(
            {
                "year": row["year"],
                "month": row["month"],
                "month_label": row["month_label"],
                "event_time_month": event_time(key),
                "analysis_phase": classify_analysis_phase(key),
                "target_import_value_usd": row["target"],
                "target_value_yoy_pct": (
                    percent_change(previous["target"], row["target"])
                    if previous is not None
                    else None
                ),
                "other_origins_import_value_usd": row["others"],
                "other_origins_value_yoy_pct": (
                    percent_change(previous["others"], row["others"])
                    if previous is not None
                    else None
                ),
                "all_origins_import_value_usd": row["total"],
                "all_origins_value_yoy_pct": (
                    percent_change(previous["total"], row["total"])
                    if previous is not None
                    else None
                ),
                "target_share": row["share"],
                "observed_policy_hts8_count": row["observed_policy_codes"],
                "target_share_yoy_change_percentage_points": (
                    (float(row["share"]) - float(previous["share"])) * 100
                    if previous is not None
                    else None
                ),
            }
        )

    comparisons_by_id = {str(row["comparison_id"]): row for row in comparisons}
    summary: dict[str, object] = {
        "analysis_type": "same_calendar_month_descriptive_baseline",
        "causal_claim": False,
        "decision": "descriptive_only_causal_model_blocked",
        "decision_reason": (
            "The panel contains treated products only, other origins may be affected "
            "through trade diversion, and product exclusions are not yet modelled."
        ),
        "policy_effective_month": "2018-07",
        "announcement_anticipation_month": "2018-06",
        "transition_rule": "Exclude June and July 2018 from the primary clean comparison.",
        "coverage_screen": {
            "policy_hts8_count": POLICY_HTS8_COUNT,
            "maximum_window_average_count_gap_ratio": COVERAGE_COUNT_GAP_THRESHOLD,
            "limit": "A count screen cannot replace an official cross-version HTS mapping.",
        },
        "input": str(input_path),
        "months": len(rows),
        "target_origin": rows[0]["target_origin"],
        "target_origin_code": rows[0]["target_origin_code"],
        "comparisons": comparisons_by_id,
        "adoption": {
            "descriptive_baseline": "accepted",
            "causal_event_study": "blocked",
            "requirements_to_unblock": [
                "Add comparable non-List-1 product data selected without post-policy outcomes.",
                "Complete an official cross-version HTS mapping for the study window.",
                "Model List 1 exclusion timing and product coverage changes.",
                "Assess pre-trends, overlap, spillovers, and sensitivity specifications.",
            ],
        },
        "outputs": {
            "monthly": str(output_dir / "statistical_baseline_monthly.csv"),
            "summary": str(output_dir / "statistical_baseline_summary.json"),
            "report": str(output_dir / "statistical_baseline_report.md"),
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "statistical_baseline_monthly.csv", monthly_output_rows)
    (output_dir / "statistical_baseline_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_report(output_dir / "statistical_baseline_report.md", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = build_statistical_baseline(args.input, args.output_dir)
    except (FileNotFoundError, StatisticalBaselineError) as exc:
        print(f"Statistical baseline failed: {exc}", file=sys.stderr)
        return 1
    primary = summary["comparisons"]["immediate_post_same_months"]
    print("Statistical baseline: descriptive_only_causal_model_blocked")
    print(f"Immediate post target change: {primary['target_change_pct']:.6f}")
    print(
        "Immediate post target share change (pp): "
        f"{primary['target_share_change_percentage_points']:.6f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
