"""Download, inventory, and aggregate Census monthly import archives.

The pipeline processes one month at a time.  A month is written to its own
deterministic CSV before the next month starts, so an interrupted run can be
resumed without duplicating rows.  Raw ZIP files are temporary by default;
their URL, filename, size, retrieval time, and SHA-256 are retained in the
source manifest and in every processed row.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile

try:
    from scripts.inventory_census_import import (
        DETAIL_MEMBER,
        InventoryError,
        load_country_names,
        load_policy_hts8,
        parse_detail_line,
        sha256_file,
    )
except ModuleNotFoundError:  # pragma: no cover - supports direct script execution
    from inventory_census_import import (  # type: ignore[no-redef]
        DETAIL_MEMBER,
        InventoryError,
        load_country_names,
        load_policy_hts8,
        parse_detail_line,
        sha256_file,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CENSUS_URL_TEMPLATE = (
    "https://www.census.gov/trade/downloads/{year}/Merch/im_m/IMDB{yy:02d}{month:02d}.ZIP"
)
MANIFEST_FIELDS = [
    "year",
    "month",
    "source_url",
    "source_file_name",
    "source_sha256",
    "source_archive_bytes",
    "source_retrieved_at_utc",
    "status",
    "raw_archive_retained_after_processing",
    "raw_detail_rows",
    "matched_detail_rows",
    "unique_product_origin_groups",
    "policy_hts8_with_trade_rows",
    "policy_hts8_without_trade_rows",
]


@dataclass(frozen=True)
class MonthSource:
    year: int
    month: int
    url: str
    filename: str


def month_source(year: int, month: int) -> MonthSource:
    if month < 1 or month > 12:
        raise ValueError(f"Month must be between 1 and 12, found {month}")
    return MonthSource(
        year=year,
        month=month,
        url=CENSUS_URL_TEMPLATE.format(year=year, yy=year % 100, month=month),
        filename=f"IMDB{year % 100:02d}{month:02d}.ZIP",
    )


def month_range(start: tuple[int, int], end: tuple[int, int]) -> list[MonthSource]:
    start_year, start_month = start
    end_year, end_month = end
    if (start_year, start_month) > (end_year, end_month):
        raise ValueError("Start month must not be after end month")
    sources: list[MonthSource] = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        sources.append(month_source(year, month))
        month += 1
        if month == 13:
            year += 1
            month = 1
    return sources


def parse_month(value: str) -> tuple[int, int]:
    try:
        year_text, month_text = value.split("-", 1)
        year, month = int(year_text), int(month_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Expected YYYY-MM, found {value!r}"
        ) from exc
    if month < 1 or month > 12:
        raise argparse.ArgumentTypeError(f"Invalid month in {value!r}")
    return year, month


def utc_file_time(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(
        microsecond=0
    ).isoformat()


def download_archive(
    source: MonthSource,
    archive_dir: Path,
    *,
    allow_download: bool = True,
) -> tuple[Path, str, str]:
    """Return (path, status, retrieval time) for one source archive."""

    archive_dir.mkdir(parents=True, exist_ok=True)
    destination = archive_dir / source.filename
    if destination.exists():
        return destination, "already_present", utc_file_time(destination)
    if not allow_download:
        raise InventoryError(f"Missing archive and downloads are disabled: {destination}")

    temporary = archive_dir / f"{source.filename}.part"
    temporary.unlink(missing_ok=True)
    request = Request(source.url, headers={"User-Agent": "TradeShockAI/0.1"})
    try:
        with urlopen(request, timeout=120) as response, temporary.open("wb") as handle:
            while chunk := response.read(1024 * 1024):
                handle.write(chunk)
    except (HTTPError, URLError, OSError) as exc:
        temporary.unlink(missing_ok=True)
        raise InventoryError(f"Could not download {source.url}: {exc}") from exc

    if not temporary.exists() or temporary.stat().st_size == 0:
        temporary.unlink(missing_ok=True)
        raise InventoryError(f"Downloaded an empty archive from {source.url}")
    temporary.replace(destination)
    return destination, "downloaded", utc_file_time(destination)


def _write_grouped_rows(
    output_path: Path,
    *,
    year: int,
    month: int,
    aggregate_values: dict[tuple[str, str], int],
    aggregate_rows: Counter[tuple[str, str]],
    country_names: dict[str, str],
    source: MonthSource,
    source_hash: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".part")
    temporary.unlink(missing_ok=True)
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "year",
                "month",
                "origin_code",
                "origin_name",
                "hts10",
                "hts8",
                "import_value_consumption_usd",
                "detail_row_count",
                "source_url",
                "source_file_name",
                "source_sha256",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        for (country_code, hts10), value in sorted(aggregate_values.items()):
            writer.writerow(
                {
                    "year": year,
                    "month": month,
                    "origin_code": country_code,
                    "origin_name": country_names.get(country_code, "<unknown>"),
                    "hts10": hts10,
                    "hts8": hts10[:8],
                    "import_value_consumption_usd": value,
                    "detail_row_count": aggregate_rows[(country_code, hts10)],
                    "source_url": source.url,
                    "source_file_name": source.filename,
                    "source_sha256": source_hash,
                }
            )
    temporary.replace(output_path)


def process_archive(
    archive_path: Path,
    source: MonthSource,
    policy_hts8: set[str],
    output_path: Path,
    retrieved_at_utc: str,
) -> dict[str, object]:
    """Aggregate policy-matching rows from one monthly archive."""

    source_hash = sha256_file(archive_path)
    aggregate_values: defaultdict[tuple[str, str], int] = defaultdict(int)
    aggregate_rows: Counter[tuple[str, str]] = Counter()
    country_names: dict[str, str]
    observed_policy_codes: set[str] = set()
    raw_detail_rows = 0
    matched_detail_rows = 0
    observed_months: set[tuple[int, int]] = set()

    try:
        with ZipFile(archive_path) as zip_file:
            country_names = load_country_names(zip_file)
            with zip_file.open(DETAIL_MEMBER) as handle:
                for line_number, raw in enumerate(handle, start=1):
                    raw_detail_rows += 1
                    record = parse_detail_line(raw, line_number=line_number)
                    observed_months.add((record.year, record.month))
                    if record.hts8 not in policy_hts8:
                        continue
                    matched_detail_rows += 1
                    observed_policy_codes.add(record.hts8)
                    key = (record.country_code, record.hts10)
                    aggregate_values[key] += record.consumption_value_usd
                    aggregate_rows[key] += 1
    except (BadZipFile, OSError, KeyError) as exc:
        raise InventoryError(f"Could not read {archive_path}: {exc}") from exc

    expected_month = (source.year, source.month)
    if observed_months != {expected_month}:
        raise InventoryError(
            f"{archive_path.name} contains months {sorted(observed_months)}, "
            f"expected only {expected_month}"
        )

    _write_grouped_rows(
        output_path,
        year=source.year,
        month=source.month,
        aggregate_values=aggregate_values,
        aggregate_rows=aggregate_rows,
        country_names=country_names,
        source=source,
        source_hash=source_hash,
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
        "raw_archive_retained_after_processing": False,
        "raw_detail_rows": raw_detail_rows,
        "matched_detail_rows": matched_detail_rows,
        "unique_product_origin_groups": len(aggregate_values),
        "unique_hts10_count": len({hts10 for _, hts10 in aggregate_values}),
        "unique_origin_count": len({country_code for country_code, _ in aggregate_values}),
        "total_consumption_value_usd": sum(aggregate_values.values()),
        "policy_hts8_with_trade_rows": len(observed_policy_codes),
        "policy_hts8_without_trade_rows": len(policy_hts8 - observed_policy_codes),
    }


def write_manifest(path: Path, records: dict[tuple[int, int], dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.unlink(missing_ok=True)
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS, lineterminator="\n")
        writer.writeheader()
        for key in sorted(records):
            record = records[key]
            writer.writerow({field: record.get(field, "") for field in MANIFEST_FIELDS})
    temporary.replace(path)


def combine_monthly_outputs(monthly_dir: Path, output_path: Path) -> int:
    files = sorted(monthly_dir.glob("trade_import_*.csv"))
    if not files:
        raise InventoryError(f"No monthly outputs found in {monthly_dir}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".part")
    temporary.unlink(missing_ok=True)
    row_count = 0
    fieldnames: list[str] | None = None
    with temporary.open("w", newline="", encoding="utf-8") as output_handle:
        writer: csv.DictWriter[str] | None = None
        for input_path in files:
            with input_path.open(newline="", encoding="utf-8") as input_handle:
                reader = csv.DictReader(input_handle)
                if fieldnames is None:
                    fieldnames = list(reader.fieldnames or [])
                    writer = csv.DictWriter(
                        output_handle, fieldnames=fieldnames, lineterminator="\n"
                    )
                    writer.writeheader()
                if list(reader.fieldnames or []) != fieldnames:
                    raise InventoryError(f"Schema mismatch in {input_path}")
                assert writer is not None
                for row in reader:
                    writer.writerow(row)
                    row_count += 1
    temporary.replace(output_path)
    return row_count


def _existing_manifest(path: Path) -> dict[tuple[int, int], dict[str, object]]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        records: dict[tuple[int, int], dict[str, object]] = {}
        for row in csv.DictReader(handle):
            records[(int(row["year"]), int(row["month"]))] = dict(row)
        return records


def build_panel(
    *,
    sources: list[MonthSource],
    policy_path: Path,
    archive_dir: Path,
    monthly_dir: Path,
    manifest_path: Path,
    combined_path: Path,
    allow_download: bool,
    keep_raw: bool,
) -> tuple[list[dict[str, object]], int]:
    policy_hts8 = load_policy_hts8(policy_path)
    records = _existing_manifest(manifest_path)
    results: list[dict[str, object]] = []

    for source in sources:
        key = (source.year, source.month)
        output_path = monthly_dir / f"trade_import_{source.year}_{source.month:02d}.csv"
        existing = records.get(key)
        if existing and output_path.exists():
            existing_url = existing.get("source_url")
            if existing_url and existing_url != source.url:
                raise InventoryError(f"Source URL changed for {source.year}-{source.month:02d}")
            results.append(existing)
            print(f"{source.year}-{source.month:02d}: already_processed")
            continue

        archive_path, download_status, retrieved_at = download_archive(
            source, archive_dir, allow_download=allow_download
        )
        try:
            result = process_archive(
                archive_path,
                source,
                policy_hts8,
                output_path,
                retrieved_at,
            )
            result["download_status"] = download_status
            result["raw_archive_retained_after_processing"] = keep_raw
            records[key] = result
            write_manifest(manifest_path, records)
            results.append(result)
            print(
                f"{source.year}-{source.month:02d}: {download_status}, "
                f"matched={result['matched_detail_rows']}, "
                f"groups={result['unique_product_origin_groups']}"
            )
        finally:
            if not keep_raw:
                archive_path.unlink(missing_ok=True)

    row_count = combine_monthly_outputs(monthly_dir, combined_path)
    return results, row_count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=parse_month, default=(2016, 1))
    parser.add_argument("--end", type=parse_month, default=(2019, 12))
    parser.add_argument(
        "--policy-products",
        type=Path,
        default=Path("data/processed/policy/section301_list1_products.csv"),
    )
    parser.add_argument("--archive-dir", type=Path, default=Path("data/raw/trade"))
    parser.add_argument(
        "--monthly-output-dir",
        type=Path,
        default=Path("data/processed/trade/monthly"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/processed/trade/source_manifest.csv"),
    )
    parser.add_argument(
        "--combined-output",
        type=Path,
        default=Path("data/processed/trade/trade_import_monthly.csv"),
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Fail when an archive is absent instead of downloading it",
    )
    parser.add_argument(
        "--keep-raw",
        action="store_true",
        help="Keep local ZIP files after successful processing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        sources = month_range(args.start, args.end)
        results, row_count = build_panel(
            sources=sources,
            policy_path=args.policy_products,
            archive_dir=args.archive_dir,
            monthly_dir=args.monthly_output_dir,
            manifest_path=args.manifest,
            combined_path=args.combined_output,
            allow_download=not args.no_download,
            keep_raw=args.keep_raw,
        )
    except (FileNotFoundError, InventoryError, ValueError) as exc:
        print(f"Trade panel build failed: {exc}", file=sys.stderr)
        return 1

    print(f"Processed months: {len(results)}")
    print(f"Combined panel rows: {row_count}")
    print(f"Wrote {args.manifest}")
    print(f"Wrote {args.combined_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
