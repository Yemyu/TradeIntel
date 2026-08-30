"""Join the Section 301 policy case to the monthly trade panel.

This module deliberately produces descriptive evidence only.  It aligns the
policy's canonical HTS8 codes and effective month with the already aggregated
trade panel, then compares China with other origins before and after the event.
It does not estimate a causal policy effect.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVENT_PATH = Path("data/processed/policy/section301_list1_event.csv")
DEFAULT_PRODUCTS_PATH = Path("data/processed/policy/section301_list1_products.csv")
DEFAULT_PANEL_PATH = Path("data/processed/trade/trade_import_monthly.csv")
DEFAULT_OUTPUT_DIR = Path("data/processed/analysis")


class PolicyAnalysisError(RuntimeError):
    """Raised when policy and trade data cannot be joined safely."""


def normalise_hts8(value: str) -> str:
    """Return the eight-digit HTS key shared by policy and trade sources."""

    digits = value.replace(".", "").strip()
    if len(digits) != 8 or not digits.isdigit():
        raise PolicyAnalysisError(f"Invalid HTS8 code: {value!r}")
    return digits


def load_policy_event(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1:
        raise PolicyAnalysisError(f"Expected one policy event, found {len(rows)}")
    event = rows[0]
    required = {
        "policy_id",
        "policy_name",
        "target_origin",
        "effective_date",
        "additional_rate",
        "source_url",
    }
    missing = sorted(required - set(event))
    if missing:
        raise PolicyAnalysisError(f"Policy event is missing fields: {missing}")
    try:
        date.fromisoformat(event["effective_date"])
    except ValueError as exc:
        raise PolicyAnalysisError(
            f"Invalid policy effective date: {event['effective_date']!r}"
        ) from exc
    if not event["target_origin"].strip():
        raise PolicyAnalysisError("Policy event has an empty target origin")
    return event


def load_policy_codes(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        codes = {normalise_hts8(row["canonical_hts8"]) for row in csv.DictReader(handle)}
    if not codes:
        raise PolicyAnalysisError("Policy product file contains no HTS8 codes")
    return codes


def month_label(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def classify_month(year: int, month: int, effective_date: date) -> str:
    """Classify a month relative to the policy event.

    The effective month is a transition month because the policy took effect
    on a particular day, while the trade panel is monthly rather than daily.
    """

    event_month = (effective_date.year, effective_date.month)
    current_month = (year, month)
    if current_month < event_month:
        return "pre"
    if current_month == event_month:
        return "transition"
    return "post"


def _parse_trade_row(row: dict[str, str]) -> tuple[int, int, str, str, str, int]:
    try:
        year = int(row["year"])
        month = int(row["month"])
        value = int(row["import_value_consumption_usd"])
    except (KeyError, ValueError) as exc:
        raise PolicyAnalysisError(f"Invalid trade panel row: {row}") from exc
    if month < 1 or month > 12 or value < 0:
        raise PolicyAnalysisError(f"Invalid month or value in trade panel row: {row}")
    try:
        origin_code = row["origin_code"].strip()
        origin_name = row["origin_name"].strip()
        hts8 = normalise_hts8(row["hts8"])
    except KeyError as exc:
        raise PolicyAnalysisError(f"Trade panel row is missing a field: {row}") from exc
    if not origin_code or not origin_name:
        raise PolicyAnalysisError(f"Trade panel row has an empty origin: {row}")
    return year, month, origin_code, origin_name, hts8, value


def _percent_change(before: float, after: float) -> float | None:
    if before == 0:
        return None
    return (after - before) / before


def _period_months(months: Iterable[tuple[int, int]], period: str, effective: date) -> list[tuple[int, int]]:
    return [
        (year, month)
        for year, month in months
        if classify_month(year, month, effective) == period
    ]


def _summary_for_values(
    values: dict[tuple[int, int], int],
    months: list[tuple[int, int]],
) -> dict[str, int | float | None]:
    total = sum(values.get(key, 0) for key in months)
    average = total / len(months) if months else 0.0
    return {
        "months": len(months),
        "total_usd": total,
        "average_monthly_usd": average,
    }


def _write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.unlink(missing_ok=True)
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def analyse_policy_case(
    *,
    event_path: Path = DEFAULT_EVENT_PATH,
    products_path: Path = DEFAULT_PRODUCTS_PATH,
    panel_path: Path = DEFAULT_PANEL_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, object]:
    """Create descriptive policy-case outputs and return the JSON summary."""

    event = load_policy_event(event_path)
    policy_codes = load_policy_codes(products_path)
    effective_date = date.fromisoformat(event["effective_date"])

    monthly_origin_values: defaultdict[tuple[int, int, str, str], int] = defaultdict(int)
    monthly_codes: defaultdict[tuple[int, int], set[str]] = defaultdict(set)
    monthly_matched_rows: defaultdict[tuple[int, int], int] = defaultdict(int)
    panel_rows_read = 0
    matched_rows = 0

    with panel_path.open(newline="", encoding="utf-8") as handle:
        for raw_row in csv.DictReader(handle):
            panel_rows_read += 1
            year, month, origin_code, origin_name, hts8, value = _parse_trade_row(raw_row)
            if hts8 not in policy_codes:
                continue
            key = (year, month, origin_code, origin_name)
            monthly_origin_values[key] += value
            monthly_codes[(year, month)].add(hts8)
            monthly_matched_rows[(year, month)] += 1
            matched_rows += 1

    if not monthly_origin_values:
        raise PolicyAnalysisError("No trade rows matched the policy HTS8 codes")

    observed_months = sorted({(year, month) for year, month, _, _ in monthly_origin_values})
    if len(observed_months) != 48:
        raise PolicyAnalysisError(
            f"Expected 48 monthly observations in the trade panel, found {len(observed_months)}"
        )
    target_name = event["target_origin"].strip().upper()
    target_origins = {
        (origin_code, origin_name)
        for _, _, origin_code, origin_name in monthly_origin_values
        if origin_name.upper() == target_name
    }
    if len(target_origins) != 1:
        raise PolicyAnalysisError(
            f"Expected one trade origin for {event['target_origin']!r}, found {sorted(target_origins)}"
        )
    target_code, target_display_name = next(iter(target_origins))

    monthly_rows: list[dict[str, object]] = []
    target_values: dict[tuple[int, int], int] = {}
    other_values: dict[tuple[int, int], int] = {}
    total_values: dict[tuple[int, int], int] = {}
    for year, month in observed_months:
        origin_keys = [
            key for key in monthly_origin_values if key[0] == year and key[1] == month
        ]
        total = sum(monthly_origin_values[key] for key in origin_keys)
        target = sum(
            monthly_origin_values[key]
            for key in origin_keys
            if key[2] == target_code
        )
        others = total - target
        period = classify_month(year, month, effective_date)
        target_values[(year, month)] = target
        other_values[(year, month)] = others
        total_values[(year, month)] = total
        monthly_rows.append(
            {
                "year": year,
                "month": month,
                "month_label": month_label(year, month),
                "period": period,
                "policy_effective_date": event["effective_date"],
                "target_origin": target_display_name,
                "target_origin_code": target_code,
                "target_import_value_consumption_usd": target,
                "other_origins_import_value_consumption_usd": others,
                "all_origins_import_value_consumption_usd": total,
                "target_share_of_all_origins": target / total if total else None,
                "unique_origin_count": len(origin_keys),
                "unique_policy_hts8_count": len(monthly_codes[(year, month)]),
                "matched_detail_row_count": monthly_matched_rows[(year, month)],
            }
        )

    pre_months = _period_months(observed_months, "pre", effective_date)
    transition_months = _period_months(observed_months, "transition", effective_date)
    post_months = _period_months(observed_months, "post", effective_date)
    if not pre_months or not transition_months or not post_months:
        raise PolicyAnalysisError("Trade panel must contain pre, transition, and post months")

    target_summary_pre = _summary_for_values(target_values, pre_months)
    target_summary_post = _summary_for_values(target_values, post_months)
    other_summary_pre = _summary_for_values(other_values, pre_months)
    other_summary_post = _summary_for_values(other_values, post_months)
    total_summary_pre = _summary_for_values(total_values, pre_months)
    total_summary_post = _summary_for_values(total_values, post_months)

    target_pre_average = float(target_summary_pre["average_monthly_usd"])
    target_post_average = float(target_summary_post["average_monthly_usd"])
    other_pre_average = float(other_summary_pre["average_monthly_usd"])
    other_post_average = float(other_summary_post["average_monthly_usd"])

    origins = sorted(
        {(origin_code, origin_name) for _, _, origin_code, origin_name in monthly_origin_values},
        key=lambda item: (item[1], item[0]),
    )
    country_rows: list[dict[str, object]] = []
    for origin_code, origin_name in origins:
        values = {
            (year, month): monthly_origin_values.get(
                (year, month, origin_code, origin_name), 0
            )
            for year, month in observed_months
        }
        pre_total = sum(values[key] for key in pre_months)
        post_total = sum(values[key] for key in post_months)
        pre_average = pre_total / len(pre_months)
        post_average = post_total / len(post_months)
        country_rows.append(
            {
                "origin_code": origin_code,
                "origin_name": origin_name,
                "is_target_origin": origin_code == target_code,
                "pre_total_usd": pre_total,
                "pre_average_monthly_usd": pre_average,
                "post_total_usd": post_total,
                "post_average_monthly_usd": post_average,
                "change_usd": post_average - pre_average,
                "change_pct": _percent_change(pre_average, post_average),
                "pre_active_months": sum(values[key] > 0 for key in pre_months),
                "post_active_months": sum(values[key] > 0 for key in post_months),
            }
        )
    country_rows.sort(
        key=lambda row: (-float(row["change_usd"]), str(row["origin_name"]), str(row["origin_code"]))
    )

    monthly_output = output_dir / "policy_case_monthly.csv"
    country_output = output_dir / "policy_case_country_change.csv"
    summary_output = output_dir / "policy_case_summary.json"
    _write_csv(
        monthly_output,
        [
            "year",
            "month",
            "month_label",
            "period",
            "policy_effective_date",
            "target_origin",
            "target_origin_code",
            "target_import_value_consumption_usd",
            "other_origins_import_value_consumption_usd",
            "all_origins_import_value_consumption_usd",
            "target_share_of_all_origins",
            "unique_origin_count",
            "unique_policy_hts8_count",
            "matched_detail_row_count",
        ],
        monthly_rows,
    )
    _write_csv(
        country_output,
        [
            "origin_code",
            "origin_name",
            "is_target_origin",
            "pre_total_usd",
            "pre_average_monthly_usd",
            "post_total_usd",
            "post_average_monthly_usd",
            "change_usd",
            "change_pct",
            "pre_active_months",
            "post_active_months",
        ],
        country_rows,
    )

    summary: dict[str, object] = {
        "analysis_type": "descriptive_policy_case_baseline",
        "causal_claim": False,
        "interpretation_limit": (
            "This output describes before/transition/after patterns. "
            "It does not identify a causal tariff effect without a defensible control design."
        ),
        "policy_event": event,
        "policy_hts8_count": len(policy_codes),
        "target_origin": {
            "event_name": event["target_origin"],
            "trade_origin_name": target_display_name,
            "trade_origin_code": target_code,
        },
        "trade_panel": {
            "path": str(panel_path),
            "rows_read": panel_rows_read,
            "policy_matched_rows": matched_rows,
            "months": len(observed_months),
            "origins": len(origins),
            "first_month": month_label(*observed_months[0]),
            "last_month": month_label(*observed_months[-1]),
        },
        "windows": {
            "pre": {
                "first_month": month_label(*pre_months[0]),
                "last_month": month_label(*pre_months[-1]),
                "months": len(pre_months),
            },
            "transition": {
                "months": [month_label(*key) for key in transition_months],
                "reason": "The policy took effect on a day within the monthly data interval.",
            },
            "post": {
                "first_month": month_label(*post_months[0]),
                "last_month": month_label(*post_months[-1]),
                "months": len(post_months),
            },
        },
        "target_origin_summary": {
            "pre": target_summary_pre,
            "post": target_summary_post,
            "average_monthly_change_usd": target_post_average - target_pre_average,
            "average_monthly_change_pct": _percent_change(
                target_pre_average, target_post_average
            ),
        },
        "other_origins_summary": {
            "pre": other_summary_pre,
            "post": other_summary_post,
            "average_monthly_change_usd": other_post_average - other_pre_average,
            "average_monthly_change_pct": _percent_change(
                other_pre_average, other_post_average
            ),
        },
        "all_origins_summary": {
            "pre": total_summary_pre,
            "post": total_summary_post,
        },
        "outputs": {
            "monthly": str(monthly_output),
            "country_change": str(country_output),
            "summary": str(summary_output),
        },
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    temporary = summary_output.with_suffix(summary_output.suffix + ".part")
    temporary.unlink(missing_ok=True)
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(summary_output)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", type=Path, default=DEFAULT_EVENT_PATH)
    parser.add_argument("--products", type=Path, default=DEFAULT_PRODUCTS_PATH)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = analyse_policy_case(
            event_path=args.event,
            products_path=args.products,
            panel_path=args.panel,
            output_dir=args.output_dir,
        )
    except (FileNotFoundError, PolicyAnalysisError, ValueError) as exc:
        print(f"Policy analysis failed: {exc}", file=sys.stderr)
        return 1

    target_change = summary["target_origin_summary"]["average_monthly_change_pct"]
    print(f"Joined policy event to {summary['trade_panel']['months']} monthly observations")
    print(f"Target origin: {summary['target_origin']['trade_origin_name']}")
    print(f"Target pre/post average change: {target_change!r}")
    print(f"Wrote {summary['outputs']['monthly']}")
    print(f"Wrote {summary['outputs']['country_change']}")
    print(f"Wrote {summary['outputs']['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
