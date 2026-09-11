"""Extract reusable all-origin/China HTS10 monthly detail without HS6 folding.

This is a preparation layer for a possible finer-grained research design.  It
does not select controls, classify policy exposure, or estimate an effect. Raw
Census ZIP archives are deliberately retained by this pipeline until the
project's data design is settled.
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
        InventoryError,
        load_country_names,
        parse_detail_line,
        sha256_file,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE_DIR = Path("data/raw/trade-detail")
DEFAULT_MONTHLY_DIR = Path("data/processed/trade_hts10/monthly")
DEFAULT_MANIFEST = Path("data/processed/trade_hts10/manifest.json")
DEFAULT_SOURCE_MANIFEST = Path("data/processed/trade/source_manifest.csv")

FIELDS = [
    "year",
    "month",
    "hts10",
    "hts8",
    "china_import_value_consumption_usd",
    "all_origin_import_value_consumption_usd",
    "china_observed",
    "all_origin_observed",
    "china_detail_row_count",
    "all_origin_detail_row_count",
    "source_url",
    "source_file_name",
    "source_sha256",
]


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _expected_hashes(path: Path) -> dict[tuple[int, int], str]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {
            (int(row["year"]), int(row["month"])): row["source_sha256"].strip()
            for row in csv.DictReader(handle)
            if row.get("source_sha256", "").strip()
        }


def _write_rows(
    output_path: Path,
    source: MonthSource,
    source_hash: str,
    all_values: dict[str, int],
    china_values: dict[str, int],
    all_counts: Counter[str],
    china_counts: Counter[str],
) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".part")
    temporary.unlink(missing_ok=True)
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        for hts10 in sorted(all_values):
            writer.writerow(
                {
                    "year": source.year,
                    "month": source.month,
                    "hts10": hts10,
                    "hts8": hts10[:8],
                    "china_import_value_consumption_usd": china_values.get(hts10, 0),
                    "all_origin_import_value_consumption_usd": all_values[hts10],
                    "china_observed": int(hts10 in china_values),
                    "all_origin_observed": 1,
                    "china_detail_row_count": china_counts.get(hts10, 0),
                    "all_origin_detail_row_count": all_counts[hts10],
                    "source_url": source.url,
                    "source_file_name": source.filename,
                    "source_sha256": source_hash,
                }
            )
    temporary.replace(output_path)
    return len(all_values)


def process_archive(
    archive_path: Path,
    source: MonthSource,
    output_path: Path,
    retrieved_at_utc: str,
    *,
    expected_source_sha256: str = "",
) -> dict[str, object]:
    """Extract one month and retain the archive; no HS6 mapping is applied."""

    source_hash = sha256_file(archive_path)
    if expected_source_sha256 and source_hash != expected_source_sha256:
        raise InventoryError(
            f"Source checksum changed for {source.year}-{source.month:02d}: "
            f"expected {expected_source_sha256}, found {source_hash}"
        )
    all_values: defaultdict[str, int] = defaultdict(int)
    china_values: defaultdict[str, int] = defaultdict(int)
    all_counts: Counter[str] = Counter()
    china_counts: Counter[str] = Counter()
    observed_months: set[tuple[int, int]] = set()
    raw_detail_rows = 0
    china_code: str | None = None
    try:
        with ZipFile(archive_path) as zip_file:
            if COUNTRY_MEMBER not in zip_file.namelist() or DETAIL_MEMBER not in zip_file.namelist():
                raise InventoryError(f"Archive is missing required members: {archive_path}")
            names = load_country_names(zip_file)
            china_codes = [code for code, name in names.items() if name.upper() == "CHINA"]
            if len(china_codes) != 1:
                raise InventoryError(f"Expected one CHINA country code, found {china_codes}")
            china_code = china_codes[0]
            with zip_file.open(DETAIL_MEMBER) as handle:
                for line_number, raw in enumerate(handle, start=1):
                    raw_detail_rows += 1
                    record = parse_detail_line(raw, line_number=line_number)
                    observed_months.add((record.year, record.month))
                    all_values[record.hts10] += record.consumption_value_usd
                    all_counts[record.hts10] += 1
                    if record.country_code == china_code:
                        china_values[record.hts10] += record.consumption_value_usd
                        china_counts[record.hts10] += 1
    except (BadZipFile, OSError) as exc:
        raise InventoryError(f"Could not read Census archive {archive_path}: {exc}") from exc
    if observed_months != {(source.year, source.month)}:
        raise InventoryError(
            f"{archive_path.name} contains months {sorted(observed_months)}, "
            f"expected only {(source.year, source.month)}"
        )
    output_rows = _write_rows(
        output_path, source, source_hash, all_values, china_values, all_counts, china_counts
    )
    return {
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
        "unique_hts10_count": len(all_values),
        "china_unique_hts10_count": len(china_values),
        "output_rows": output_rows,
        "raw_all_origin_value_usd": sum(all_values.values()),
        "raw_china_value_usd": sum(china_values.values()),
        "monthly_output": _display(output_path),
    }


def _load_manifest(path: Path) -> dict[tuple[int, int], dict[str, object]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {(int(row["year"]), int(row["month"])): row for row in payload.get("months", [])}


def _write_manifest(path: Path, records: dict[tuple[int, int], dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "hts10_monthly_detail_extracted",
        "retention_policy": "raw_archives_retained_until_project_data_design_is_settled",
        "months": [records[key] for key in sorted(records)],
    }
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def extract(
    *,
    sources: list[MonthSource],
    archive_dir: Path,
    monthly_dir: Path,
    manifest_path: Path,
    expected_manifest_path: Path,
    allow_download: bool,
) -> dict[str, object]:
    records = _load_manifest(manifest_path)
    expected = _expected_hashes(expected_manifest_path)
    for source in sources:
        key = (source.year, source.month)
        output = monthly_dir / f"trade_hts10_{source.year}_{source.month:02d}.csv"
        existing = records.get(key)
        if (
            existing
            and output.exists()
            and existing.get("source_url") == source.url
            and existing.get("raw_archive_retained_after_processing") is True
            and existing.get("source_sha256") == expected.get(key, existing.get("source_sha256"))
            and (archive_dir / source.filename).exists()
        ):
            print(f"{source.year}-{source.month:02d}: already_extracted_archive_retained")
            continue
        archive, status, retrieved = download_archive(source, archive_dir, allow_download=allow_download)
        result = process_archive(
            archive, source, output, retrieved, expected_source_sha256=expected.get(key, "")
        )
        result["download_status"] = status
        records[key] = result
        _write_manifest(manifest_path, records)
        print(
            f"{source.year}-{source.month:02d}: {status}, "
            f"hts10={result['unique_hts10_count']}, rows={result['output_rows']}"
        )
    if not all((monthly_dir / f"trade_hts10_{s.year}_{s.month:02d}.csv").exists() for s in sources):
        raise InventoryError("A requested monthly output is missing")
    _write_manifest(manifest_path, records)
    return {
        "status": "hts10_monthly_detail_extracted",
        "source_scope": {"start": f"{sources[0].year}-{sources[0].month:02d}", "end": f"{sources[-1].year}-{sources[-1].month:02d}", "month_count": len(sources)},
        "retention_policy": "raw_archives_retained_until_project_data_design_is_settled",
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
    parser.add_argument("--start", type=_month, default=(2016, 1))
    parser.add_argument("--end", type=_month, default=(2016, 1))
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    parser.add_argument("--monthly-output-dir", type=Path, default=DEFAULT_MONTHLY_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--expected-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = extract(
            sources=month_range(args.start, args.end),
            archive_dir=args.archive_dir,
            monthly_dir=args.monthly_output_dir,
            manifest_path=args.manifest,
            expected_manifest_path=args.expected_manifest,
            allow_download=not args.no_download,
        )
    except (FileNotFoundError, InventoryError, ValueError) as exc:
        print(f"HTS10 extraction failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
