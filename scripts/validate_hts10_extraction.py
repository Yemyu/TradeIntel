"""Validate the retained pre-policy HTS10 extraction against frozen sources."""
from __future__ import annotations

import argparse
import csv
import json
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def check_rows(extracted, key, record):
    seen = set()
    for item in extracted:
        code = item["hts10"]
        if len(code) != 10 or not code.isdigit() or code in seen:
            raise ValueError(f"Invalid or duplicate HTS10 for {key}: {code}")
        seen.add(code)
        if (int(item["year"]), int(item["month"])) != key or item["hts8"] != code[:8]:
            raise ValueError(f"Row date/code mismatch for {key}")
        for field in ("source_url", "source_file_name", "source_sha256"):
            if item[field] != record[field]:
                raise ValueError(f"Row provenance mismatch for {key}/{field}")
        china = int(item["china_import_value_consumption_usd"])
        total = int(item["all_origin_import_value_consumption_usd"])
        cr, ar = int(item["china_detail_row_count"]), int(item["all_origin_detail_row_count"])
        if not (0 <= china <= total and 0 <= cr <= ar and ar > 0):
            raise ValueError(f"Invalid amounts/counts for {key}/{code}")
        if item["all_origin_observed"] != "1" or item["china_observed"] != str(int(cr > 0)):
            raise ValueError(f"Observation flag mismatch for {key}/{code}")
        if cr == 0 and china != 0:
            raise ValueError(f"Absent China record with nonzero amount for {key}/{code}")


def validate(manifest_path: Path, old_manifest_path: Path, panel_dir: Path, archive_dir: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = manifest.get("months", [])
    expected = [
        (year, month)
        for year in range(2016, 2019)
        for month in range(1, 13)
        if (year, month) <= (2018, 5)
    ]
    actual = [(int(row["year"]), int(row["month"])) for row in rows]
    if actual != expected:
        raise ValueError(f"Expected 29 ordered months, found {actual}")
    old_rows = json.loads(old_manifest_path.read_text(encoding="utf-8"))["months"]
    old = {(int(row["year"]), int(row["month"])): row for row in old_rows}
    output_rows = 0
    for row in rows:
        key = (int(row["year"]), int(row["month"]))
        archive = archive_dir / row["source_file_name"]
        output = panel_dir / f"trade_hts10_{key[0]}_{key[1]:02d}.csv"
        if not archive.exists() or not output.exists():
            raise ValueError(f"Missing retained source/output for {key}")
        if row["status"] != "processed" or row["raw_archive_retained_after_processing"] is not True:
            raise ValueError(f"Incomplete or unretained month {key}")
        for field in ("source_url", "source_file_name", "source_sha256"):
            if row[field] != old[key][field]:
                raise ValueError(f"Frozen source mismatch for {key}/{field}")
        if digest(archive) != row["source_sha256"] or archive.stat().st_size != int(row["source_archive_bytes"]):
            raise ValueError(f"Retained archive changed for {key}")
        if int(row["raw_detail_rows"]) != int(old[key]["raw_detail_rows"]):
            raise ValueError(f"Raw row count mismatch for {key}")
        for field in ("raw_all_origin_value_usd", "raw_china_value_usd"):
            if int(row[field]) != int(old[key][field]):
                raise ValueError(f"Amount mismatch for {key}/{field}")
        with output.open(newline="", encoding="utf-8") as handle:
            extracted = list(csv.DictReader(handle))
        check_rows(extracted, key, row)
        if sum(int(x["all_origin_detail_row_count"]) for x in extracted) != int(row["raw_detail_rows"]):
            raise ValueError(f"Extracted detail counts mismatch for {key}")
        if len(extracted) != int(row["output_rows"]) or len(extracted) != int(row["unique_hts10_count"]):
            raise ValueError(f"HTS10 row count mismatch for {key}")
        all_value = sum(int(item["all_origin_import_value_consumption_usd"]) for item in extracted)
        china_value = sum(int(item["china_import_value_consumption_usd"]) for item in extracted)
        if all_value != int(row["raw_all_origin_value_usd"]) or china_value != int(row["raw_china_value_usd"]):
            raise ValueError(f"Extracted amount mismatch for {key}")
        output_rows += len(extracted)
    if list(archive_dir.glob("*.part")):
        raise ValueError("Incomplete .part archive remains")
    return {
        "months": len(rows),
        "retained_archives": len(list(archive_dir.glob("IMDB*.ZIP"))),
        "output_rows": output_rows,
        "amounts_and_sources": "passed",
        "row_keys_dates_flags_and_archive_hashes": "passed",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("data/processed/trade_hts10/manifest.json"))
    parser.add_argument("--old-manifest", type=Path, default=Path("data/processed/causal/causal_trade_panel_manifest.json"))
    parser.add_argument("--panel-dir", type=Path, default=Path("data/processed/trade_hts10/monthly"))
    parser.add_argument("--archive-dir", type=Path, default=Path("data/raw/trade-detail"))
    args = parser.parse_args()
    print(json.dumps(validate(args.manifest, args.old_manifest, args.panel_dir, args.archive_dir), ensure_ascii=False, indent=2))
