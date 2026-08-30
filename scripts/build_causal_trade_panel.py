"""Build a compact all-origin HS6 panel for the frozen causal design.

The existing monthly panel is intentionally List 1-only.  This pipeline reads
the same official Census detail archives again, but aggregates every origin in
one pass and keeps only two values per HTS10: China and all origins.  It then
maps valid HTS10 codes to the fixed ``HS6_2017`` key and writes a compact
monthly HS6 panel.  Ambiguous or historically invalid mappings are excluded
from the panel and counted in the coverage report instead of being guessed.
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
    from scripts.build_trade_panel import (
        MonthSource,
        download_archive,
        month_range,
    )
    from scripts.inventory_census_import import (
        COUNTRY_MEMBER,
        DETAIL_MEMBER,
        InventoryError,
        load_country_names,
        parse_detail_line,
        sha256_file,
    )
except ModuleNotFoundError:  # pragma: no cover - supports direct script execution
    from build_trade_panel import (  # type: ignore[no-redef]
        MonthSource,
        download_archive,
        month_range,
    )
    from inventory_census_import import (  # type: ignore[no-redef]
        COUNTRY_MEMBER,
        DETAIL_MEMBER,
        InventoryError,
        load_country_names,
        parse_detail_line,
        sha256_file,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAPPING = Path("data/processed/causal/hts_history_mapping.csv")
DEFAULT_ARCHIVE_DIR = Path("data/raw/trade-causal")
DEFAULT_MONTHLY_DIR = Path("data/processed/causal/monthly")
DEFAULT_MANIFEST = Path("data/processed/causal/causal_trade_panel_manifest.json")
DEFAULT_COMBINED = Path("data/processed/causal/causal_trade_hs6_monthly.csv")
DEFAULT_REPORT = Path("data/processed/causal/causal_trade_panel_report.json")
DEFAULT_EXPECTED_MANIFEST = Path("data/processed/trade/source_manifest.csv")

PANEL_FIELDS = [
    "year",
    "month",
    "hs6_2017",
    "china_import_value_consumption_usd",
    "all_origin_import_value_consumption_usd",
    "china_share",
    "source_hts10_count",
    "source_hts10_mapped_count",
    "source_url",
    "source_file_name",
    "source_sha256",
]


def display_path(path: Path) -> str:
    """Keep repository paths readable while allowing temporary test paths."""

    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def load_hts_mapping(path: Path) -> dict[int, dict[str, dict[str, str]]]:
    """Load one deterministic HTS10 mapping row for each year and code."""

    by_year: dict[int, dict[str, dict[str, str]]] = defaultdict(dict)
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            year = int(row["source_year"])
            code = row["source_hts10"]
            if code in by_year[year]:
                raise InventoryError(f"Duplicate mapping key: {year}/{code}")
            by_year[year][code] = {
                "hs6_2017": row["hs6_2017"],
                "mapping_status": row["mapping_status"],
                "historical_validity_status": row["historical_validity_status"],
            }
    if not by_year:
        raise InventoryError(f"No HTS mapping rows found in {path}")
    return dict(by_year)


def load_expected_source_hashes(path: Path) -> dict[tuple[int, int], str]:
    """Read the earlier official-source manifest when it is available."""

    if not path.exists():
        return {}
    expected: dict[tuple[int, int], str] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (int(row["year"]), int(row["month"]))
            value = row.get("source_sha256", "").strip()
            if value:
                expected[key] = value
    return expected


def _write_panel_rows(
    output_path: Path,
    *,
    source: MonthSource,
    source_hash: str,
    hs6_all: dict[str, int],
    hs6_china: dict[str, int],
    hs6_hts10_count: dict[str, int],
    hs6_hts10_mapped_count: dict[str, int],
) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".part")
    temporary.unlink(missing_ok=True)
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PANEL_FIELDS, lineterminator="\n")
        writer.writeheader()
        for hs6 in sorted(hs6_all):
            all_value = hs6_all[hs6]
            china_value = hs6_china.get(hs6, 0)
            share = china_value / all_value if all_value else 0.0
            writer.writerow(
                {
                    "year": source.year,
                    "month": source.month,
                    "hs6_2017": hs6,
                    "china_import_value_consumption_usd": china_value,
                    "all_origin_import_value_consumption_usd": all_value,
                    "china_share": f"{share:.12f}",
                    "source_hts10_count": hs6_hts10_count[hs6],
                    "source_hts10_mapped_count": hs6_hts10_mapped_count[hs6],
                    "source_url": source.url,
                    "source_file_name": source.filename,
                    "source_sha256": source_hash,
                }
            )
    temporary.replace(output_path)
    return len(hs6_all)


def process_archive(
    archive_path: Path,
    source: MonthSource,
    mapping: dict[str, dict[str, str]],
    output_path: Path,
    retrieved_at_utc: str,
    *,
    expected_source_sha256: str = "",
) -> dict[str, object]:
    """Aggregate all origins, map valid HTS10 codes, and write one month."""

    source_hash = sha256_file(archive_path)
    if expected_source_sha256 and source_hash != expected_source_sha256:
        raise InventoryError(
            f"Source checksum changed for {source.year}-{source.month:02d}: "
            f"expected {expected_source_sha256}, found {source_hash}"
        )

    all_values: defaultdict[str, int] = defaultdict(int)
    china_values: defaultdict[str, int] = defaultdict(int)
    all_detail_rows: Counter[str] = Counter()
    china_detail_rows: Counter[str] = Counter()
    observed_months: set[tuple[int, int]] = set()
    raw_detail_rows = 0
    china_detail_rows_total = 0
    china_code: str | None = None

    try:
        with ZipFile(archive_path) as zip_file:
            if COUNTRY_MEMBER not in zip_file.namelist() or DETAIL_MEMBER not in zip_file.namelist():
                raise InventoryError(
                    f"Archive is missing {COUNTRY_MEMBER} or {DETAIL_MEMBER}: {archive_path}"
                )
            country_names = load_country_names(zip_file)
            china_codes = [
                code for code, name in country_names.items() if name.upper() == "CHINA"
            ]
            if len(china_codes) != 1:
                raise InventoryError(f"Expected one CHINA country code, found {china_codes}")
            china_code = china_codes[0]

            with zip_file.open(DETAIL_MEMBER) as handle:
                for line_number, raw in enumerate(handle, start=1):
                    raw_detail_rows += 1
                    record = parse_detail_line(raw, line_number=line_number)
                    observed_months.add((record.year, record.month))
                    all_values[record.hts10] += record.consumption_value_usd
                    all_detail_rows[record.hts10] += 1
                    if record.country_code == china_code:
                        china_values[record.hts10] += record.consumption_value_usd
                        china_detail_rows[record.hts10] += 1
                        china_detail_rows_total += 1
    except (BadZipFile, OSError) as exc:
        raise InventoryError(f"Could not read Census archive {archive_path}: {exc}") from exc

    if observed_months != {(source.year, source.month)}:
        raise InventoryError(
            f"{archive_path.name} contains months {sorted(observed_months)}, "
            f"expected only {(source.year, source.month)}"
        )

    hs6_all: defaultdict[str, int] = defaultdict(int)
    hs6_china: defaultdict[str, int] = defaultdict(int)
    hs6_hts10_count: defaultdict[str, int] = defaultdict(int)
    hs6_hts10_mapped_count: defaultdict[str, int] = defaultdict(int)
    excluded_code_counts: Counter[str] = Counter()
    excluded_code_all_value: Counter[str] = Counter()
    excluded_code_china_value: Counter[str] = Counter()

    for hts10, all_value in all_values.items():
        mapped = mapping.get(hts10)
        china_value = china_values.get(hts10, 0)
        if (
            not mapped
            or mapped["historical_validity_status"] != "valid"
            or not mapped["hs6_2017"]
        ):
            if not mapped:
                reason = "not_in_mapping"
            elif mapped["historical_validity_status"] != "valid":
                reason = mapped["historical_validity_status"]
            else:
                reason = mapped["mapping_status"]
            excluded_code_counts[reason] += 1
            excluded_code_all_value[reason] += all_value
            excluded_code_china_value[reason] += china_value
            continue
        hs6 = mapped["hs6_2017"]
        hs6_all[hs6] += all_value
        hs6_china[hs6] += china_value
        hs6_hts10_count[hs6] += 1
        if hts10 in china_values:
            hs6_hts10_mapped_count[hs6] += 1

    panel_rows = _write_panel_rows(
        output_path,
        source=source,
        source_hash=source_hash,
        hs6_all=hs6_all,
        hs6_china=hs6_china,
        hs6_hts10_count=hs6_hts10_count,
        hs6_hts10_mapped_count=hs6_hts10_mapped_count,
    )
    raw_all_value = sum(all_values.values())
    raw_china_value = sum(china_values.values())
    mapped_all_value = sum(hs6_all.values())
    mapped_china_value = sum(hs6_china.values())
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
        "china_detail_rows": china_detail_rows_total,
        "unique_hts10_count": len(all_values),
        "china_unique_hts10_count": len(china_values),
        "output_hs6_rows": panel_rows,
        "raw_all_origin_value_usd": raw_all_value,
        "raw_china_value_usd": raw_china_value,
        "mapped_all_origin_value_usd": mapped_all_value,
        "mapped_china_value_usd": mapped_china_value,
        "all_origin_mapping_coverage": mapped_all_value / raw_all_value if raw_all_value else 0.0,
        "china_mapping_coverage": mapped_china_value / raw_china_value if raw_china_value else 0.0,
        "excluded_hts10_count_by_reason": dict(sorted(excluded_code_counts.items())),
        "excluded_all_origin_value_by_reason": dict(sorted(excluded_code_all_value.items())),
        "excluded_china_value_by_reason": dict(sorted(excluded_code_china_value.items())),
        "monthly_output": display_path(output_path),
    }


def _load_existing_manifest(path: Path) -> dict[tuple[int, int], dict[str, object]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return {
        (int(row["year"]), int(row["month"])): row
        for row in payload.get("months", [])
    }


def _write_manifest(path: Path, *, mapping_sha256: str, records: dict[tuple[int, int], dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "all_origin_hs6_panel_built",
        "mapping_sha256": mapping_sha256,
        "months": [records[key] for key in sorted(records)],
    }
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _combine_monthly_outputs(
    monthly_dir: Path, output_path: Path, sources: list[MonthSource]
) -> int:
    files = [
        monthly_dir / f"causal_trade_hs6_{source.year}_{source.month:02d}.csv"
        for source in sources
    ]
    if not files:
        raise InventoryError(f"No causal monthly outputs found in {monthly_dir}")
    missing = [path for path in files if not path.exists()]
    if missing:
        raise InventoryError(f"Missing monthly outputs: {missing[0]}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".part")
    temporary.unlink(missing_ok=True)
    row_count = 0
    with temporary.open("w", newline="", encoding="utf-8") as output_handle:
        writer = csv.DictWriter(output_handle, fieldnames=PANEL_FIELDS, lineterminator="\n")
        writer.writeheader()
        for input_path in files:
            with input_path.open(newline="", encoding="utf-8") as input_handle:
                reader = csv.DictReader(input_handle)
                if list(reader.fieldnames or []) != PANEL_FIELDS:
                    raise InventoryError(f"Schema mismatch in {input_path}")
                for row in reader:
                    writer.writerow(row)
                    row_count += 1
    temporary.replace(output_path)
    return row_count


def build_panel(
    *,
    sources: list[MonthSource],
    mapping_path: Path,
    archive_dir: Path,
    monthly_dir: Path,
    manifest_path: Path,
    combined_path: Path,
    report_path: Path,
    expected_manifest_path: Path,
    allow_download: bool,
    keep_raw: bool,
) -> dict[str, object]:
    mapping_by_year = load_hts_mapping(mapping_path)
    mapping_sha256 = sha256_file(mapping_path)
    expected_hashes = load_expected_source_hashes(expected_manifest_path)
    records = _load_existing_manifest(manifest_path)
    for source in sources:
        key = (source.year, source.month)
        output_path = monthly_dir / f"causal_trade_hs6_{source.year}_{source.month:02d}.csv"
        existing = records.get(key)
        if (
            existing
            and output_path.exists()
            and existing.get("mapping_sha256") == mapping_sha256
            and existing.get("source_url") == source.url
        ):
            print(f"{source.year}-{source.month:02d}: already_processed")
            continue

        if source.year not in mapping_by_year:
            raise InventoryError(f"No HTS mapping for source year {source.year}")
        archive_path, download_status, retrieved_at = download_archive(
            source, archive_dir, allow_download=allow_download
        )
        try:
            result = process_archive(
                archive_path,
                source,
                mapping_by_year[source.year],
                output_path,
                retrieved_at,
                expected_source_sha256=expected_hashes.get(key, ""),
            )
            result["download_status"] = download_status
            result["raw_archive_retained_after_processing"] = keep_raw
            result["mapping_sha256"] = mapping_sha256
            records[key] = result
            _write_manifest(manifest_path, mapping_sha256=mapping_sha256, records=records)
            print(
                f"{source.year}-{source.month:02d}: {download_status}, "
                f"raw_hts10={result['unique_hts10_count']}, "
                f"hs6_rows={result['output_hs6_rows']}, "
                f"china_coverage={result['china_mapping_coverage']:.4f}"
            )
        finally:
            if not keep_raw:
                archive_path.unlink(missing_ok=True)

    combined_rows = _combine_monthly_outputs(monthly_dir, combined_path, sources)
    selected_records = [records[(source.year, source.month)] for source in sources]
    raw_all = sum(int(row["raw_all_origin_value_usd"]) for row in selected_records)
    raw_china = sum(int(row["raw_china_value_usd"]) for row in selected_records)
    mapped_all = sum(int(row["mapped_all_origin_value_usd"]) for row in selected_records)
    mapped_china = sum(int(row["mapped_china_value_usd"]) for row in selected_records)
    report = {
        "status": "all_origin_hs6_panel_built",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_scope": {
            "start": f"{sources[0].year}-{sources[0].month:02d}",
            "end": f"{sources[-1].year}-{sources[-1].month:02d}",
            "month_count": len(sources),
            "all_origins_read": True,
            "china_origin_code": "5700",
        },
        "mapping": {
            "path": str(mapping_path.relative_to(PROJECT_ROOT)),
            "sha256": mapping_sha256,
            "invalid_or_ambiguous_codes_excluded": True,
        },
        "coverage": {
            "raw_all_origin_value_usd": raw_all,
            "mapped_all_origin_value_usd": mapped_all,
            "all_origin_mapping_coverage": mapped_all / raw_all if raw_all else 0.0,
            "raw_china_value_usd": raw_china,
            "mapped_china_value_usd": mapped_china,
            "china_mapping_coverage": mapped_china / raw_china if raw_china else 0.0,
        },
        "outputs": {
            "combined_panel": str(combined_path.relative_to(PROJECT_ROOT)),
            "combined_rows": combined_rows,
            "manifest": str(manifest_path.relative_to(PROJECT_ROOT)),
        },
        "causal_adoption_status": "not_evaluated_until_control_selection",
        "interpretation_boundary": "This is an all-origin data and mapping-coverage build. It does not select controls or estimate a policy effect.",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_manifest(manifest_path, mapping_sha256=mapping_sha256, records=records)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=_parse_month, default=(2016, 1))
    parser.add_argument("--end", type=_parse_month, default=(2019, 12))
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    parser.add_argument("--monthly-output-dir", type=Path, default=DEFAULT_MONTHLY_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--combined-output", type=Path, default=DEFAULT_COMBINED)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--expected-manifest", type=Path, default=DEFAULT_EXPECTED_MANIFEST)
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--keep-raw", action="store_true")
    return parser


def _parse_month(value: str) -> tuple[int, int]:
    try:
        year_text, month_text = value.split("-", 1)
        year, month = int(year_text), int(month_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Expected YYYY-MM, found {value!r}") from exc
    if month < 1 or month > 12:
        raise argparse.ArgumentTypeError(f"Invalid month in {value!r}")
    return year, month


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        sources = month_range(args.start, args.end)
        report = build_panel(
            sources=sources,
            mapping_path=args.mapping,
            archive_dir=args.archive_dir,
            monthly_dir=args.monthly_output_dir,
            manifest_path=args.manifest,
            combined_path=args.combined_output,
            report_path=args.report,
            expected_manifest_path=args.expected_manifest,
            allow_download=not args.no_download,
            keep_raw=args.keep_raw,
        )
    except (FileNotFoundError, InventoryError, ValueError) as exc:
        print(f"Causal trade panel build failed: {exc}", file=sys.stderr)
        return 1
    print(f"Processed months: {report['source_scope']['month_count']}")
    print(f"Combined HS6 rows: {report['outputs']['combined_rows']}")
    print(f"China mapping coverage: {report['coverage']['china_mapping_coverage']:.4f}")
    print(f"Wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
