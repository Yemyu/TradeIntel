"""Extract one registered policy's HTS8 scope at HTS10 x origin detail.

This is a descriptive exposure layer.  It never estimates a policy effect and
does not treat a missing trade row as evidence that a tariff code is invalid.
The raw Census ZIP is retained, and every output row carries its source hash.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zipfile import BadZipFile, ZipFile

try:
    from scripts.build_trade_panel import MonthSource, download_archive, month_range
    from scripts.inventory_census_import import (
        COUNTRY_MEMBER,
        DETAIL_MEMBER,
        resolve_member,
        InventoryError,
        load_country_names,
        parse_detail_line,
        sha256_file,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from build_trade_panel import MonthSource, download_archive, month_range  # type: ignore[no-redef]
    from inventory_census_import import (  # type: ignore[no-redef]
        COUNTRY_MEMBER,
        DETAIL_MEMBER,
        resolve_member,
        InventoryError,
        load_country_names,
        parse_detail_line,
        sha256_file,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = Path("data/processed/policy/section301_review2025_products.csv")
DEFAULT_ARCHIVE_DIR = Path("data/raw/trade-detail")
DEFAULT_OUTPUT_DIR = Path("data/processed/policy_exposure/monthly")
DEFAULT_MANIFEST = Path("data/processed/policy_exposure/manifest.json")
FIELDS = [
    "policy_id", "year", "month", "canonical_hts8", "hts10", "origin_code",
    "origin_name", "import_value_consumption_usd", "detail_row_count",
    "source_url", "source_file_name", "source_sha256",
]


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def load_policy_scope(path: Path) -> tuple[str, dict[str, str], set[str]]:
    """Load and validate one policy's explicit eight-digit scope."""

    if not path.exists():
        raise InventoryError(f"Policy product file is missing: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise InventoryError(f"Policy product file is empty: {path}")
    required = {"policy_id", "canonical_hts8", "product_description", "effective_date"}
    if not required.issubset(rows[0]):
        raise InventoryError(f"Policy product file is missing fields: {sorted(required - set(rows[0]))}")
    policy_ids = {row["policy_id"].strip() for row in rows}
    if len(policy_ids) != 1 or "" in policy_ids:
        raise InventoryError("One extraction run must contain exactly one non-empty policy_id")
    policy_id = next(iter(policy_ids))
    descriptions: dict[str, str] = {}
    codes: set[str] = set()
    for row in rows:
        code = row["canonical_hts8"].replace(".", "").strip()
        if len(code) != 8 or not code.isdigit():
            raise InventoryError(f"Invalid canonical HTS8: {row['canonical_hts8']!r}")
        if code in codes:
            raise InventoryError(f"Duplicate canonical HTS8: {code}")
        codes.add(code)
        descriptions[code] = row["product_description"].strip()
    return policy_id, descriptions, codes


def _write_rows(
    path: Path,
    *,
    policy_id: str,
    source: MonthSource,
    source_hash: str,
    values: dict[tuple[str, str, str], int],
    counts: Counter[tuple[str, str, str]],
    names: dict[str, str],
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.unlink(missing_ok=True)
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        for (hts8, origin_code, hts10), value in sorted(values.items()):
            writer.writerow({
                "policy_id": policy_id,
                "year": source.year,
                "month": source.month,
                "canonical_hts8": hts8,
                "hts10": hts10,
                "origin_code": origin_code,
                "origin_name": names.get(origin_code, "<unknown>"),
                "import_value_consumption_usd": value,
                "detail_row_count": counts[(hts8, origin_code, hts10)],
                "source_url": source.url,
                "source_file_name": source.filename,
                "source_sha256": source_hash,
            })
    temporary.replace(path)
    return len(values)


def process_archive(
    archive_path: Path,
    source: MonthSource,
    *,
    policy_id: str,
    policy_codes: set[str],
    output_path: Path,
    retrieved_at_utc: str,
) -> dict[str, object]:
    """Read a validated Census archive and write product-origin groups."""

    source_hash = sha256_file(archive_path)
    values: defaultdict[tuple[str, str, str], int] = defaultdict(int)
    counts: Counter[tuple[str, str, str]] = Counter()
    observed_months: set[tuple[int, int]] = set()
    observed_codes: set[str] = set()
    raw_detail_rows = 0
    matched_detail_rows = 0
    try:
        with ZipFile(archive_path) as zip_file:
            detail_member = resolve_member(zip_file, DETAIL_MEMBER)
            names = load_country_names(zip_file)
            with zip_file.open(detail_member) as handle:
                for line_number, raw in enumerate(handle, start=1):
                    raw_detail_rows += 1
                    record = parse_detail_line(raw, line_number=line_number)
                    observed_months.add((record.year, record.month))
                    if record.hts8 not in policy_codes:
                        continue
                    matched_detail_rows += 1
                    observed_codes.add(record.hts8)
                    key = (record.hts8, record.country_code, record.hts10)
                    values[key] += record.consumption_value_usd
                    counts[key] += 1
    except (BadZipFile, OSError) as exc:
        raise InventoryError(f"Could not read Census archive {archive_path}: {exc}") from exc
    expected_month = (source.year, source.month)
    if observed_months != {expected_month}:
        raise InventoryError(
            f"{archive_path.name} contains months {sorted(observed_months)}, expected only {expected_month}"
        )
    row_count = _write_rows(
        output_path, policy_id=policy_id, source=source, source_hash=source_hash,
        values=values, counts=counts, names=names,
    )
    return {
        "policy_id": policy_id,
        "year": source.year,
        "month": source.month,
        "source_url": source.url,
        "source_file_name": source.filename,
        "source_sha256": source_hash,
        "source_archive_bytes": archive_path.stat().st_size,
        "source_retrieved_at_utc": retrieved_at_utc,
        "status": "processed",
        "raw_archive_retained_after_processing": True,
        "raw_detail_rows": raw_detail_rows,
        "matched_detail_rows": matched_detail_rows,
        "observed_policy_hts8": sorted(observed_codes),
        "missing_policy_hts8_in_month": sorted(policy_codes - observed_codes),
        "unique_product_origin_groups": row_count,
        "unique_hts10_count": len({key[2] for key in values}),
        "unique_origin_count": len({key[1] for key in values}),
        "total_consumption_value_usd": sum(values.values()),
        "monthly_output": _display(output_path),
    }


def _load_manifest(path: Path) -> dict[tuple[int, int], dict[str, object]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {(int(item["year"]), int(item["month"])): item for item in payload.get("months", [])}


def _write_manifest(path: Path, policy_id: str, records: dict[tuple[int, int], dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "policy_id": policy_id,
        "status": "policy_exposure_monthly_extracted",
        "raw_archive_retention": "retained_until_project_data_design_is_settled",
        "months": [records[key] for key in sorted(records)],
    }
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def extract(
    *,
    sources: list[MonthSource],
    policy_path: Path,
    archive_dir: Path,
    output_dir: Path,
    manifest_path: Path,
    allow_download: bool,
) -> dict[str, object]:
    policy_id, _descriptions, policy_codes = load_policy_scope(policy_path)
    records = _load_manifest(manifest_path)
    for source in sources:
        key = (source.year, source.month)
        output_path = output_dir / f"{policy_id}_{source.year}_{source.month:02d}.csv"
        archive_path, download_status, retrieved_at = download_archive(
            source, archive_dir, allow_download=allow_download
        )
        existing = records.get(key)
        if (
            existing and output_path.exists()
            and existing.get("source_sha256") == sha256_file(archive_path)
            and existing.get("policy_id") == policy_id
        ):
            print(f"{source.year}-{source.month:02d}: already_processed")
            continue
        result = process_archive(
            archive_path, source, policy_id=policy_id, policy_codes=policy_codes,
            output_path=output_path, retrieved_at_utc=retrieved_at,
        )
        result["download_status"] = download_status
        records[key] = result
        _write_manifest(manifest_path, policy_id, records)
        print(
            f"{source.year}-{source.month:02d}: {download_status}, "
            f"matched={result['matched_detail_rows']}, groups={result['unique_product_origin_groups']}"
        )
    _write_manifest(manifest_path, policy_id, records)
    return {
        "status": "policy_exposure_monthly_extracted",
        "policy_id": policy_id,
        "source_scope": {
            "start": f"{sources[0].year}-{sources[0].month:02d}",
            "end": f"{sources[-1].year}-{sources[-1].month:02d}",
            "month_count": len(sources),
        },
        "manifest": _display(manifest_path),
    }


def _month(value: str) -> tuple[int, int]:
    try:
        year, month = (int(part) for part in value.split("-", 1))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Expected YYYY-MM, found {value!r}") from exc
    if not 1 <= month <= 12:
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
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = extract(
            sources=month_range(args.start, args.end), policy_path=args.policy_products,
            archive_dir=args.archive_dir, output_dir=args.output_dir,
            manifest_path=args.manifest, allow_download=not args.no_download,
        )
    except (FileNotFoundError, InventoryError, ValueError) as exc:
        print(f"Policy exposure extraction failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
