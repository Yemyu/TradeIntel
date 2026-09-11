"""Summarise fixed HTS10 leads in the extracted pre-policy panel only."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from build_control_eligibility import sha256_file

ROOT = Path(__file__).resolve().parents[1]


def audit(panel_dir: Path, leads_path: Path) -> dict[str, object]:
    leads = json.loads(leads_path.read_text(encoding="utf-8"))
    codes = sorted({
        code
        for record in leads["records"]
        if "insufficient" not in record["reasons"]
        for code in record["uncovered_children"]
    })
    stats = {
        code: {
            "all_origin_observed_months": 0,
            "china_observed_months": 0,
            "positive_china_months": 0,
            "all_origin_value_usd": 0,
            "china_value_usd": 0,
        }
        for code in codes
    }
    files = sorted(panel_dir.glob("trade_hts10_*.csv"))
    if not files:
        raise ValueError(f"No monthly panel files in {panel_dir}")
    months: set[tuple[int, int]] = set()
    for path in files:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                code = row["hts10"]
                if code not in stats:
                    continue
                key = (int(row["year"]), int(row["month"]))
                months.add(key)
                item = stats[code]
                item["all_origin_observed_months"] += int(row["all_origin_observed"])
                item["china_observed_months"] += int(row["china_observed"])
                item["positive_china_months"] += int(
                    int(row["china_import_value_consumption_usd"]) > 0
                )
                item["all_origin_value_usd"] += int(
                    row["all_origin_import_value_consumption_usd"]
                )
                item["china_value_usd"] += int(
                    row["china_import_value_consumption_usd"]
                )
    expected_months = {
        (year, month)
        for year in range(2016, 2019)
        for month in range(1, 13)
        if (year, month) <= (2018, 5)
    }
    if months != expected_months:
        raise ValueError(f"Unexpected panel month set: {sorted(months)}")
    return {
        "scope": "17 fixed uncovered HTS10 leads; 29 pre-policy months; descriptive only",
        "policy_post_data_used": False,
        "panel_sha256": {
            str(path.resolve().relative_to(ROOT)): sha256_file(path) for path in files
        },
        "month_count": len(months),
        "records": stats,
        "interpretation": "Presence and pre-policy value are screening facts, not control eligibility or causal identification.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel-dir", type=Path, default=Path("data/processed/trade_hts10/monthly"))
    parser.add_argument("--leads", type=Path, default=Path("tmp/control-granularity-20260909.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.panel_dir, args.leads)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"month_count": result["month_count"], "candidate_count": len(result["records"])}, ensure_ascii=False))
