"""Build an HTS8 candidate panel from retained pre-policy HTS10 files.

The script aggregates only the fixed metadata candidates from protocol 0050.
It keeps missing months explicit through observation flags, applies the frozen
24-positive-China-month activity screen, and does not read any post-policy
outcome or perform matching.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from build_hts6_mapping import read_historical_validity
from build_control_eligibility import sha256_file
from inventory_stable_hts8 import continuous


ROOT = Path(__file__).resolve().parents[1]
START = (2016, 1)
END = (2018, 5)
MONTHS = [
    (year, month)
    for year in range(2016, 2019)
    for month in range(1, 13)
    if (year, month) <= END
]

MONTH_FIELDS = [
    "year",
    "month",
    "hts8",
    "naics4",
    "metadata_role",
    "all_origin_import_value_consumption_usd",
    "china_import_value_consumption_usd",
    "all_origin_observed",
    "china_observed",
    "positive_china",
    "observed_child_hts10_count",
    "observed_china_child_hts10_count",
    "observation_status",
    "unobserved_child_hts10_count",
    "source_url",
    "source_file_name",
    "source_sha256",
]

QUALIFICATION_FIELDS = [
    "hts8",
    "naics4",
    "metadata_role",
    "child_hts10_count",
    "all_origin_observed_months",
    "china_observed_months",
    "positive_china_months",
    "all_origin_value_usd",
    "china_value_usd",
    "activity_threshold",
    "activity_eligible",
    "main_route_candidate",
    "screening_note",
]


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def load_inventory(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError(f"No candidate records in {path}")
    seen: set[str] = set()
    for record in records:
        hts8 = str(record.get("hts8", ""))
        children = record.get("children")
        if len(hts8) != 8 or not hts8.isdigit() or hts8 in seen:
            raise ValueError(f"Invalid or duplicate candidate HTS8: {hts8}")
        if not isinstance(children, list) or not children or any(
            len(str(code)) != 10 or not str(code).isdigit() or not str(code).startswith(hts8)
            for code in children
        ):
            raise ValueError(f"Invalid child code list for {hts8}")
        seen.add(hts8)
    return records


def load_month(path: Path) -> tuple[dict[str, dict[str, object]], dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {
            "year", "month", "hts10", "hts8", "china_import_value_consumption_usd",
            "all_origin_import_value_consumption_usd", "china_observed", "all_origin_observed",
            "china_detail_row_count", "all_origin_detail_row_count", "source_url",
            "source_file_name", "source_sha256",
        }
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError(f"Missing HTS10 fields in {path}")
        rows: dict[str, dict[str, object]] = {}
        source: dict[str, str] | None = None
        for row in reader:
            code = row["hts10"]
            if code in rows:
                raise ValueError(f"Duplicate HTS10 in {path}: {code}")
            if (int(row["year"]), int(row["month"])) != _month_from_path(path):
                raise ValueError(f"Month mismatch in {path}: {code}")
            if row["hts8"] != code[:8]:
                raise ValueError(f"HTS8 prefix mismatch in {path}: {code}")
            metadata = {
                key: row[key]
                for key in ("source_url", "source_file_name", "source_sha256")
            }
            if source is None:
                source = metadata
            elif source != metadata:
                raise ValueError(f"Inconsistent source metadata in {path}")
            all_value = int(row["all_origin_import_value_consumption_usd"])
            china_value = int(row["china_import_value_consumption_usd"])
            all_rows = int(row["all_origin_detail_row_count"])
            china_rows = int(row["china_detail_row_count"])
            if all_value < 0 or china_value < 0 or china_value > all_value:
                raise ValueError(f"Invalid amounts in {path}: {code}")
            if all_rows <= 0 or china_rows < 0 or china_rows > all_rows:
                raise ValueError(f"Invalid detail counts in {path}: {code}")
            if row["all_origin_observed"] != "1" or row["china_observed"] != str(int(china_rows > 0)):
                raise ValueError(f"Observation flag mismatch in {path}: {code}")
            rows[code] = {
                "all_value": all_value,
                "china_value": china_value,
                "all_observed": row["all_origin_observed"] == "1",
                "china_observed": row["china_observed"] == "1",
                "source": metadata,
            }
        if source is None:
            raise ValueError(f"Empty HTS10 month file: {path}")
        return rows, source


def _month_from_path(path: Path) -> tuple[int, int]:
    stem = path.stem
    year, month = stem.rsplit("_", 2)[-2:]
    return int(year), int(month)


def _write(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.unlink(missing_ok=True)
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def build(
    *,
    inventory_path: Path,
    panel_dir: Path,
    monthly_output: Path,
    qualification_output: Path,
    report_output: Path,
) -> dict[str, object]:
    candidates = load_inventory(inventory_path)
    history = read_historical_validity()
    for record in candidates:
        for code in record["children"]:
            if not any(continuous(f"{x['begin']}→{x['end']}") for x in history.get(str(code), [])):
                raise ValueError(f"Child lacks confirmed full-window validity: {code}")
    by_hts8 = {str(record["hts8"]): record for record in candidates}
    states: dict[tuple[int, int], dict[str, dict[str, object]]] = {}
    monthly_rows: list[dict[str, object]] = []

    for year, month in MONTHS:
        path = panel_dir / f"trade_hts10_{year}_{month:02d}.csv"
        if not path.exists():
            raise FileNotFoundError(path)
        raw, source = load_month(path)
        for code in raw:
            if code[:8] in by_hts8 and code not in by_hts8[code[:8]]["children"]:
                raise ValueError(f"Unlisted child would be omitted from HTS8 aggregation: {code} in {path}")
        month_state: dict[str, dict[str, object]] = {}
        for hts8, record in by_hts8.items():
            children = {str(code) for code in record["children"]}
            observed = {code: raw[code] for code in children if code in raw}
            all_value = sum(int(item["all_value"]) for item in observed.values())
            china_value = sum(int(item["china_value"]) for item in observed.values())
            china_observed = any(bool(item["china_observed"]) for item in observed.values())
            all_observed = bool(observed)
            state = {
                "all_value": all_value,
                "china_value": china_value,
                "all_observed": all_observed,
                "china_observed": china_observed,
                "observed_child_count": len(observed),
                "observed_china_child_count": sum(
                    int(bool(item["china_observed"])) for item in observed.values()
                ),
                "source": source,
            }
            month_state[hts8] = state
            monthly_rows.append(
                {
                    "year": year,
                    "month": month,
                    "hts8": hts8,
                    "naics4": record["naics4"],
                    "metadata_role": record["role"],
                    "all_origin_import_value_consumption_usd": all_value if all_observed else "",
                    "china_import_value_consumption_usd": china_value if china_observed else "",
                    "all_origin_observed": int(all_observed),
                    "china_observed": int(china_observed),
                    "positive_china": int(china_value > 0),
                    "observed_child_hts10_count": len(observed),
                    "observed_china_child_hts10_count": state["observed_china_child_count"],
                    "observation_status": observation_status(all_observed, china_observed, china_value),
                    "unobserved_child_hts10_count": len(children) - len(observed),
                    "source_url": source["source_url"],
                    "source_file_name": source["source_file_name"],
                    "source_sha256": source["source_sha256"],
                }
            )
        states[(year, month)] = month_state

    qualification_rows: list[dict[str, object]] = []
    for hts8, record in sorted(by_hts8.items()):
        selected = [states[key][hts8] for key in MONTHS]
        positive = sum(int(item["china_value"] > 0) for item in selected)
        all_observed = sum(int(item["all_observed"]) for item in selected)
        china_observed = sum(int(item["china_observed"]) for item in selected)
        all_value = sum(int(item["all_value"]) for item in selected)
        china_value = sum(int(item["china_value"]) for item in selected)
        eligible = positive >= 24
        route_candidate = eligible and record["role"] in {"treated", "control"}
        note = "eligible_by_frozen_24_positive_month_rule" if eligible else "below_frozen_24_positive_month_rule"
        if eligible and all_observed < 29:
            note += ";some_all_origin_months_absent"
        qualification_rows.append(
            {
                "hts8": hts8,
                "naics4": record["naics4"],
                "metadata_role": record["role"],
                "child_hts10_count": len(record["children"]),
                "all_origin_observed_months": all_observed,
                "china_observed_months": china_observed,
                "positive_china_months": positive,
                "all_origin_value_usd": all_value,
                "china_value_usd": china_value,
                "activity_threshold": 24,
                "activity_eligible": int(eligible),
                "main_route_candidate": int(route_candidate),
                "screening_note": note,
            }
        )

    _write(monthly_output, MONTH_FIELDS, monthly_rows)
    _write(qualification_output, QUALIFICATION_FIELDS, qualification_rows)

    sector_summary: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in qualification_rows:
        sector = str(row["naics4"])
        role = str(row["metadata_role"])
        sector_summary[sector][f"metadata_{role}"] += 1
        sector_summary[sector]["activity_eligible"] += int(row["activity_eligible"])
        sector_summary[sector]["main_route_candidates"] += int(row["main_route_candidate"])
    family_summary = {}
    for sector in sorted(sector_summary):
        family_summary[sector] = {}
        for role in ("treated", "control"):
            pool = [x for x in qualification_rows if x["naics4"] == sector and x["metadata_role"] == role]
            kept = [x for x in pool if x["main_route_candidate"]]
            denom = sum(x["china_value_usd"] for x in pool)
            numerator = sum(x["china_value_usd"] for x in kept)
            family_summary[sector][role] = dict(
                hts8_count=len(kept), hs6_family_count=len({x["hts8"][:6] for x in kept}),
                observed_china_value_usd=numerator,
                metadata_pool_observed_china_value_usd=denom,
                observed_value_retained_share=numerator / denom if denom else None)
    report = {
        "status": "hts8_candidate_panel_built",
        "source_scope": {"start": "2016-01", "end": "2018-05", "month_count": len(MONTHS)},
        "policy_post_data_used": False,
        "candidate_count": len(candidates),
        "monthly_rows": len(monthly_rows),
        "activity_rule": "positive China amount in at least 24 of 29 policy-pre months",
        "metadata_inventory": rel(inventory_path),
        "outputs": {"monthly": rel(monthly_output), "qualification": rel(qualification_output)},
        "sector_summary": {key: dict(value) for key, value in sorted(sector_summary.items())},
        "family_summary": family_summary,
        "source_sha256": {rel(p): sha256_file(p) for p in [inventory_path, ROOT / "data/raw/policy/census-import-historical-hs-numbers.xlsx"] + [panel_dir / f"trade_hts10_{y}_{m:02d}.csv" for y,m in MONTHS]},
        "missing_amount_encoding": "empty CSV cell when origin not observed; observed-only totals are not imputed full-period totals",
        "interpretation": "Qualification is a policy-pre activity screen, not a matched control set or causal estimate.",
    }
    report_output.parent.mkdir(parents=True, exist_ok=True)
    report_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def observation_status(all_observed: bool, china_observed: bool, china_value: int) -> str:
    if not all_observed:
        return "no_all_origin_record"
    if not china_observed:
        return "no_china_record"
    return "observed_positive" if china_value > 0 else "observed_zero"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=Path("data/processed/causal/hts8_stable_inventory.json"))
    parser.add_argument("--panel-dir", type=Path, default=Path("data/processed/trade_hts10/monthly"))
    parser.add_argument("--monthly-output", type=Path, default=Path("data/processed/trade_hts8/monthly/hts8_candidates_prepolicy_v2.csv"))
    parser.add_argument("--qualification-output", type=Path, default=Path("data/processed/causal/hts8_candidate_qualification_v2.csv"))
    parser.add_argument("--report-output", type=Path, default=Path("data/processed/causal/hts8_candidate_panel_report_v2.json"))
    args = parser.parse_args()
    report = build(
        inventory_path=args.inventory,
        panel_dir=args.panel_dir,
        monthly_output=args.monthly_output,
        qualification_output=args.qualification_output,
        report_output=args.report_output,
    )
    print(json.dumps({key: report[key] for key in ("candidate_count", "monthly_rows", "sector_summary")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
