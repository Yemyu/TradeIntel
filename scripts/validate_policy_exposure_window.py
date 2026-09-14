"""Validate a multi-month policy exposure extraction without recalculating it.

This is a provenance and integrity check for the deterministic extraction
layer. It does not infer a policy effect and does not call a language model.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from zipfile import BadZipFile, ZipFile

try:
    from scripts.build_trade_panel import month_range
    from scripts.extract_policy_case_monthly import (
        DEFAULT_ARCHIVE_DIR,
        DEFAULT_MANIFEST,
        DEFAULT_OUTPUT_DIR,
        DEFAULT_POLICY,
        FIELDS,
        load_policy_scope,
    )
    from scripts.inventory_census_import import (
        InventoryError,
        load_country_names,
        resolve_member,
        sha256_file,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from build_trade_panel import month_range  # type: ignore[no-redef]
    from extract_policy_case_monthly import (  # type: ignore[no-redef]
        DEFAULT_ARCHIVE_DIR,
        DEFAULT_MANIFEST,
        DEFAULT_OUTPUT_DIR,
        DEFAULT_POLICY,
        FIELDS,
        load_policy_scope,
    )
    from inventory_census_import import (  # type: ignore[no-redef]
        InventoryError,
        load_country_names,
        resolve_member,
        sha256_file,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise InventoryError(f"Missing monthly output: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != FIELDS:
            raise InventoryError(
                f"Unexpected fields in {path}: {reader.fieldnames}; expected {FIELDS}"
            )
        return list(reader)


def _concord_codes(zip_file: ZipFile) -> set[str]:
    codes: set[str] = set()
    with zip_file.open(resolve_member(zip_file, "CONCORD.TXT")) as handle:
        for raw in handle:
            line = raw.decode("latin-1").rstrip("\r\n")
            if len(line) >= 10 and line[:10].isdigit():
                codes.add(line[:10])
    if not codes:
        raise InventoryError("CONCORD.TXT has no ten-digit HTS codes")
    return codes


def validate_window(
    *,
    start: tuple[int, int],
    end: tuple[int, int],
    policy_path: Path,
    archive_dir: Path,
    output_dir: Path,
    manifest_path: Path,
) -> dict[str, object]:
    policy_id, _descriptions, policy_codes = load_policy_scope(policy_path)
    expected_sources = month_range(start, end)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("policy_id") != policy_id:
        raise InventoryError("Manifest policy_id does not match the registered policy")
    manifest_rows = payload.get("months")
    if not isinstance(manifest_rows, list):
        raise InventoryError("Manifest months is not a list")
    manifest_by_key = {(int(row["year"]), int(row["month"])): row for row in manifest_rows}
    if len(manifest_by_key) != len(manifest_rows):
        raise InventoryError("Manifest contains duplicate year-month entries")

    summaries: list[dict[str, object]] = []
    for source in expected_sources:
        key = (source.year, source.month)
        manifest = manifest_by_key.get(key)
        if manifest is None:
            raise InventoryError(f"Manifest is missing {source.year}-{source.month:02d}")
        archive_path = archive_dir / source.filename
        output_path = output_dir / f"{policy_id}_{source.year}_{source.month:02d}.csv"
        if not archive_path.exists():
            raise InventoryError(f"Missing retained archive: {archive_path}")
        actual_hash = sha256_file(archive_path)
        if actual_hash != manifest.get("source_sha256"):
            raise InventoryError(f"Archive hash mismatch for {source.filename}")
        rows = _read_rows(output_path)
        keys: set[tuple[str, str, str, str, str]] = set()
        observed_codes: set[str] = set()
        total = 0
        detail_rows = 0
        with ZipFile(archive_path) as archive:
            resolve_member(archive, "IMP_DETL.TXT")
            resolve_member(archive, "COUNTRY.TXT")
            country_names = load_country_names(archive)
            concord = _concord_codes(archive)
        for row in rows:
            row_key = (
                row["policy_id"], row["year"], row["month"],
                row["canonical_hts8"], row["hts10"], row["origin_code"],
            )
            if row_key in keys:
                raise InventoryError(f"Duplicate output key in {output_path}: {row_key}")
            keys.add(row_key)
            if row["policy_id"] != policy_id or row["year"] != str(source.year) or row["month"] != str(source.month):
                raise InventoryError(f"Wrong policy or month in {output_path}: {row}")
            if row["canonical_hts8"] not in policy_codes:
                raise InventoryError(f"Out-of-scope HTS8 in {output_path}: {row['canonical_hts8']}")
            if row["hts10"] not in concord:
                raise InventoryError(f"HTS10 absent from CONCORD.TXT in {source.filename}: {row['hts10']}")
            if row["source_sha256"] != actual_hash:
                raise InventoryError(f"Output source hash mismatch in {output_path}")
            value = int(row["import_value_consumption_usd"])
            count = int(row["detail_row_count"])
            if value < 0 or count < 1:
                raise InventoryError(f"Invalid value/count in {output_path}: {row}")
            total += value
            detail_rows += count
            observed_codes.add(row["canonical_hts8"])
        missing_codes = policy_codes - observed_codes
        if missing_codes:
            raise InventoryError(f"{source.year}-{source.month:02d} lacks policy codes: {sorted(missing_codes)}")
        if total != int(manifest["total_consumption_value_usd"]):
            raise InventoryError(f"Total mismatch for {source.year}-{source.month:02d}")
        if detail_rows != int(manifest["matched_detail_rows"]):
            raise InventoryError(f"Detail-row count mismatch for {source.year}-{source.month:02d}")
        summaries.append({
            "year": source.year,
            "month": source.month,
            "archive": _display(archive_path),
            "archive_sha256": actual_hash,
            "archive_bytes": archive_path.stat().st_size,
            "output": _display(output_path),
            "output_sha256": sha256_file(output_path),
            "output_rows": len(rows),
            "matched_detail_rows": detail_rows,
            "observed_hts8_count": len(observed_codes),
            "observed_hts10_count": len({row["hts10"] for row in rows}),
            "origin_count": len({row["origin_code"] for row in rows}),
            "total_consumption_value_usd": total,
            "country_table_entries": len(country_names),
        })
    return {
        "status": "validated",
        "policy_id": policy_id,
        "window": {
            "start": f"{start[0]}-{start[1]:02d}",
            "end": f"{end[0]}-{end[1]:02d}",
            "month_count": len(expected_sources),
        },
        "checks": [
            "连续月份均有保留 ZIP 与月度 CSV",
            "ZIP SHA-256 与提取清单一致",
            "明细/国家表/CONCORD 成员存在且路径无歧义",
            "输出键唯一、月份和 policy_id 正确",
            f"登记的 {len(policy_codes)} 个政策 HTS8 每月均有记录",
            "观察到的 HTS10 均存在于当月 CONCORD",
            "CSV 汇总金额和明细行数与 manifest 一致",
        ],
        "months": summaries,
    }


def _month(value: str) -> tuple[int, int]:
    try:
        year, month = (int(part) for part in value.split("-", 1))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Expected YYYY-MM, found {value!r}") from exc
    if month < 1 or month > 12:
        raise argparse.ArgumentTypeError(f"Invalid month in {value!r}")
    return year, month


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=_month, required=True)
    parser.add_argument("--end", type=_month, required=True)
    parser.add_argument("--policy-products", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = validate_window(
            start=args.start, end=args.end, policy_path=args.policy_products,
            archive_dir=args.archive_dir, output_dir=args.output_dir,
            manifest_path=args.manifest,
        )
    except (FileNotFoundError, InventoryError, ValueError, BadZipFile) as exc:
        print(f"Policy exposure validation failed: {exc}", file=sys.stderr)
        return 1
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "month_count": result["window"]["month_count"], "json": str(args.json_output) if args.json_output else None}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
