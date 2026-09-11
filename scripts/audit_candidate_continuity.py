"""Read local classification metadata, not trade outcomes, for 17 fixed leads."""
import argparse
import csv
import json
from pathlib import Path

from build_hts6_mapping import read_annual_concordance
from build_control_eligibility import sha256_file

ROOT = Path(__file__).resolve().parents[1]


def audit():
    prior = ROOT / "tmp/control-granularity-20260909.json"
    mapping = ROOT / "data/processed/causal/hts_history_mapping.csv"
    manifest = ROOT / "data/processed/causal/causal_trade_panel_manifest.json"
    leads = json.loads(prior.read_text())
    codes = sorted({c for r in leads["records"] if "insufficient" not in r["reasons"]
                    for c in r["uncovered_children"]})
    annual = {y: read_annual_concordance(y) for y in range(2016, 2020)}
    with mapping.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    records = []
    for code in codes:
        values = {str(y): annual[y].get(code) for y in annual}
        records.append({
            "code": code, "annual_metadata": values,
            "present_all_four_years": all(v is not None for v in values.values()),
            "description_unchanged": all(v and v["description"] == values["2018"]["description"] for v in values.values()),
            "units_unchanged": all(v and (v["unit_qy1"], v["unit_qy2"]) ==
                                   (values["2018"]["unit_qy1"], values["2018"]["unit_qy2"]) for v in values.values()),
            "historical_intervals": sorted({r["historical_intervals"] for r in rows if r["source_hts10"] == code}),
        })
    months = json.loads(manifest.read_text())["months"]
    keys = {(m["year"], m["month"]) for m in months}
    if keys != {(y, m) for y in range(2016, 2020) for m in range(1, 13)} or len(months) != 48:
        raise ValueError("Expected 48 unique months")
    sources = [prior, mapping, manifest] + [ROOT / f"data/raw/policy/census-import-concordance-{y}.xls" for y in annual]
    return {
        "scope": "fixed 17 metadata leads; no trade outcome parsing or causal adoption",
        "source_sha256": {str(p.relative_to(ROOT)): sha256_file(p) for p in sources},
        "archive_inventory": {
            "months": len(months), "processed": sum(m["status"] == "processed" for m in months),
            "marked_not_retained": sum(m["raw_archive_retained_after_processing"] is False for m in months),
            "archive_bytes_sum": sum(m["source_archive_bytes"] for m in months),
            "note": "Size sum of monthly archives, not proven cumulative network traffic.",
        },
        "records": records,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit()
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps(result["archive_inventory"], ensure_ascii=False))
    print("Candidate records:", len(result["records"]))
