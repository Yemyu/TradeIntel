"""Inventory one Census monthly imports archive for the Section 301 case.

The Census merchandise-import detail file is a fixed-width text file inside a
ZIP archive.  This script deliberately performs an inventory first: it filters
to the audited List 1 HTS8 codes, aggregates the detail rows to
product-country-month groups, and writes a compact report and country summary.
It does not make a policy-effect or causal claim.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZipFile


DETAIL_MEMBER = "IMP_DETL.TXT"
COUNTRY_MEMBER = "COUNTRY.TXT"
EXPECTED_DETAIL_WIDTH = 688


class InventoryError(RuntimeError):
    """Raised when the source does not satisfy the inventory assumptions."""


@dataclass(frozen=True)
class DetailRecord:
    """The fields needed from one fixed-width Census detail row."""

    hts10: str
    hts8: str
    country_code: str
    year: int
    month: int
    consumption_value_usd: int


def normalise_hts8(value: str) -> str:
    """Return an eight-digit HTS key suitable for joining source formats."""

    digits = value.replace(".", "").strip()
    if len(digits) != 8 or not digits.isdigit():
        raise InventoryError(f"Invalid HTS8 code: {value!r}")
    return digits


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_policy_hts8(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        values = {
            normalise_hts8(row["canonical_hts8"])
            for row in csv.DictReader(handle)
        }
    if len(values) != 818:
        raise InventoryError(
            f"Expected 818 unique policy HTS8 codes, found {len(values)}"
        )
    return values


def load_country_names(zip_file: ZipFile) -> dict[str, str]:
    names: dict[str, str] = {}
    with zip_file.open(COUNTRY_MEMBER) as handle:
        for line_number, raw in enumerate(handle, start=1):
            line = raw.decode("latin-1").rstrip("\r\n")
            if not line:
                continue
            if len(line) < 61:
                raise InventoryError(
                    f"{COUNTRY_MEMBER} line {line_number} is shorter than 61 characters"
                )
            code = line[0:4]
            name = line[11:61].strip()
            if not code.isdigit() or not name:
                raise InventoryError(
                    f"Invalid country row at {COUNTRY_MEMBER}:{line_number}"
                )
            names[code] = name
    if not names:
        raise InventoryError(f"No countries found in {COUNTRY_MEMBER}")
    return names


def _parse_integer_field(raw: str, *, field_name: str, line_number: int) -> int:
    value = raw.strip()
    if not value:
        raise InventoryError(
            f"Blank {field_name} at {DETAIL_MEMBER}:{line_number}; "
            "a blank monetary value cannot be treated as zero"
        )
    try:
        parsed = int(value)
    except ValueError as exc:
        raise InventoryError(
            f"Invalid {field_name} at {DETAIL_MEMBER}:{line_number}: {value!r}"
        ) from exc
    if parsed < 0:
        raise InventoryError(
            f"Negative {field_name} at {DETAIL_MEMBER}:{line_number}: {parsed}"
        )
    return parsed


def parse_detail_line(raw: bytes, *, line_number: int) -> DetailRecord:
    line = raw.decode("latin-1").rstrip("\r\n")
    if len(line) != EXPECTED_DETAIL_WIDTH:
        raise InventoryError(
            f"Unexpected detail width at {DETAIL_MEMBER}:{line_number}: "
            f"expected {EXPECTED_DETAIL_WIDTH}, found {len(line)}"
        )

    hts10 = line[0:10]
    country_code = line[10:14]
    year_text = line[22:26]
    month_text = line[26:28]
    if not hts10.isdigit() or len(hts10) != 10:
        raise InventoryError(
            f"Invalid HTS10 at {DETAIL_MEMBER}:{line_number}: {hts10!r}"
        )
    if not year_text.isdigit() or not month_text.isdigit():
        raise InventoryError(
            f"Invalid date at {DETAIL_MEMBER}:{line_number}: "
            f"{year_text!r}-{month_text!r}"
        )
    if not country_code.isdigit() or len(country_code) != 4:
        raise InventoryError(
            f"Invalid country code at {DETAIL_MEMBER}:{line_number}: {country_code!r}"
        )

    return DetailRecord(
        hts10=hts10,
        hts8=hts10[:8],
        country_code=country_code,
        year=int(year_text),
        month=int(month_text),
        consumption_value_usd=_parse_integer_field(
            line[73:88], field_name="con_val_mo", line_number=line_number
        ),
    )


def inventory_archive(
    archive_path: Path,
    policy_path: Path,
    summary_path: Path,
    groups_path: Path,
    report_path: Path,
) -> dict[str, object]:
    policy_hts8 = load_policy_hts8(policy_path)
    archive_hash = sha256_file(archive_path)

    aggregate_values: defaultdict[tuple[str, str], int] = defaultdict(int)
    aggregate_rows: Counter[tuple[str, str]] = Counter()
    country_values: defaultdict[str, int] = defaultdict(int)
    country_rows: Counter[str] = Counter()
    observed_policy_codes: set[str] = set()
    years_months: set[tuple[int, int]] = set()
    raw_detail_rows = 0
    matched_detail_rows = 0

    try:
        with ZipFile(archive_path) as zip_file:
            required_members = {DETAIL_MEMBER, COUNTRY_MEMBER}
            available_members = set(zip_file.namelist())
            missing_members = required_members - available_members
            if missing_members:
                raise InventoryError(
                    f"Archive is missing required members: {sorted(missing_members)}"
                )
            country_names = load_country_names(zip_file)

            with zip_file.open(DETAIL_MEMBER) as handle:
                for line_number, raw in enumerate(handle, start=1):
                    raw_detail_rows += 1
                    record = parse_detail_line(raw, line_number=line_number)
                    years_months.add((record.year, record.month))
                    if record.hts8 not in policy_hts8:
                        continue
                    matched_detail_rows += 1
                    observed_policy_codes.add(record.hts8)
                    key = (record.country_code, record.hts10)
                    aggregate_values[key] += record.consumption_value_usd
                    aggregate_rows[key] += 1
                    country_values[record.country_code] += record.consumption_value_usd
                    country_rows[record.country_code] += 1
    except (BadZipFile, OSError) as exc:
        raise InventoryError(f"Could not read Census archive {archive_path}: {exc}") from exc

    if len(years_months) != 1:
        raise InventoryError(
            f"Expected one month in the sample archive, found {sorted(years_months)}"
        )
    if len(observed_policy_codes) > len(policy_hts8):
        raise InventoryError("Observed more policy codes than the audited policy list")

    year, month = next(iter(years_months))
    china_codes = [code for code, name in country_names.items() if name.upper() == "CHINA"]
    if len(china_codes) != 1:
        raise InventoryError(f"Expected one CHINA country code, found {china_codes}")
    china_code = china_codes[0]

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "year",
                "month",
                "origin_code",
                "origin_name",
                "import_value_consumption_usd",
                "detail_row_count",
                "unique_hts10_count",
                "source_file",
            ],
        )
        writer.writeheader()
        for country_code, value in sorted(
            country_values.items(), key=lambda item: (-item[1], item[0])
        ):
            unique_hts10_count = sum(
                1 for code, _ in aggregate_values if code == country_code
            )
            writer.writerow(
                {
                    "year": year,
                    "month": month,
                    "origin_code": country_code,
                    "origin_name": country_names.get(country_code, "<unknown>"),
                    "import_value_consumption_usd": value,
                    "detail_row_count": country_rows[country_code],
                    "unique_hts10_count": unique_hts10_count,
                    "source_file": str(archive_path),
                }
            )

    groups_path.parent.mkdir(parents=True, exist_ok=True)
    with groups_path.open("w", newline="", encoding="utf-8") as handle:
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
                "source_file",
            ],
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
                    "source_file": str(archive_path),
                }
            )

    top_countries = [
        {
            "origin_code": code,
            "origin_name": country_names.get(code, "<unknown>"),
            "import_value_consumption_usd": value,
            "detail_row_count": country_rows[code],
        }
        for code, value in sorted(
            country_values.items(), key=lambda item: (-item[1], item[0])
        )[:10]
    ]
    report: dict[str, object] = {
        "source": {
            "source_url": (
                "https://www.census.gov/trade/downloads/2018/Merch/im_m/IMDB1807.ZIP"
            ),
            "archive_path": str(archive_path),
            "archive_bytes": archive_path.stat().st_size,
            "archive_sha256": archive_hash,
            "required_members": [COUNTRY_MEMBER, DETAIL_MEMBER],
            "detail_layout": "fixed-width",
            "detail_record_width": EXPECTED_DETAIL_WIDTH,
        },
        "coverage": {"year": year, "month": month, "observed_months": 1},
        "policy_scope": {
            "policy_id": "us_301_list1_2018",
            "audited_policy_hts8_count": len(policy_hts8),
            "policy_hts8_with_trade_rows": len(observed_policy_codes),
            "policy_hts8_without_trade_rows": len(policy_hts8 - observed_policy_codes),
        },
        "detail_inventory": {
            "raw_detail_rows": raw_detail_rows,
            "matched_detail_rows": matched_detail_rows,
            "unique_product_origin_groups": len(aggregate_values),
            "unique_hts10_count": len({hts10 for _, hts10 in aggregate_values}),
            "unique_origin_count": len(country_values),
            "total_consumption_value_usd": sum(country_values.values()),
            "blank_or_invalid_consumption_values": 0,
            "negative_consumption_values": 0,
        },
        "china": {
            "origin_code": china_code,
            "origin_name": country_names[china_code],
            "import_value_consumption_usd": country_values.get(china_code, 0),
            "detail_row_count": country_rows.get(china_code, 0),
        },
        "outputs": {
            "origin_summary_csv": str(summary_path),
            "product_origin_groups_csv": str(groups_path),
        },
        "top_origins_by_consumption_value": top_countries,
        "interpretation_boundary": (
            "This is a source and coverage inventory. It is not a before-after "
            "estimate and does not establish a causal policy effect."
        ),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive",
        type=Path,
        default=Path("data/raw/trade/IMDB1807.ZIP"),
        help="Census monthly ZIP archive",
    )
    parser.add_argument(
        "--policy-products",
        type=Path,
        default=Path("data/processed/policy/section301_list1_products.csv"),
        help="Audited policy-product CSV",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("data/processed/trade/section301_list1_2018_07_by_origin.csv"),
        help="Compact country summary CSV",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/processed/trade/census_2018_07_inventory.json"),
        help="Machine-readable inventory report",
    )
    parser.add_argument(
        "--matched-groups",
        type=Path,
        default=Path(
            "data/processed/trade/section301_list1_2018_07_by_product_origin.csv"
        ),
        help="Product-origin-month aggregate CSV",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = inventory_archive(
            archive_path=args.archive,
            policy_path=args.policy_products,
            summary_path=args.summary,
            groups_path=args.matched_groups,
            report_path=args.report,
        )
    except (FileNotFoundError, InventoryError) as exc:
        print(f"Inventory failed: {exc}", file=sys.stderr)
        return 1

    inventory = report["detail_inventory"]
    scope = report["policy_scope"]
    china = report["china"]
    print(f"Inventoried {report['coverage']['year']}-{report['coverage']['month']:02d}")
    print(f"Raw detail rows: {inventory['raw_detail_rows']}")
    print(f"List 1 matched detail rows: {inventory['matched_detail_rows']}")
    print(f"Product-origin groups: {inventory['unique_product_origin_groups']}")
    print(
        "Policy codes with rows: "
        f"{scope['policy_hts8_with_trade_rows']}/{scope['audited_policy_hts8_count']}"
    )
    print(
        "China consumption value: "
        f"${china['import_value_consumption_usd']:,}"
    )
    print(f"Wrote {args.summary}")
    print(f"Wrote {args.matched_groups}")
    print(f"Wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
