"""Load audited quality reference tables into the existing TradeIntel database."""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = PROJECT_ROOT / "db/schema.sql"
DEFAULT_ORIGINS = PROJECT_ROOT / "data/processed/quality/origin_dimension.csv"
DEFAULT_POLICY_ORIGINS = (
    PROJECT_ROOT / "data/processed/quality/policy_origin_mapping.csv"
)
DEFAULT_COVERAGE = PROJECT_ROOT / "data/processed/quality/hts8_coverage.csv"


class QualityLoadError(RuntimeError):
    """Raised when the quality tables cannot be loaded safely."""


def sql_text(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def sql_nullable_text(value: str) -> str:
    return sql_text(value) if value else "NULL"


def read_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except OSError as exc:
        raise QualityLoadError(f"Could not read {path}: {exc}") from exc


def run_mysql(sql: str, *, login_path: str, database: str | None = None) -> str:
    command = [
        "mysql",
        f"--login-path={login_path}",
        "--batch",
        "--raw",
        "--skip-column-names",
    ]
    if database:
        command.append(database)
    result = subprocess.run(
        command,
        input=sql,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise QualityLoadError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def table_counts(*, login_path: str, database: str) -> dict[str, int]:
    output = run_mysql(
        "SELECT 'origin_dimension', COUNT(*) FROM origin_dimension;\n"
        "SELECT 'policy_origin_mapping', COUNT(*) FROM policy_origin_mapping;\n"
        "SELECT 'hts8_coverage', COUNT(*) FROM hts8_coverage;\n",
        login_path=login_path,
        database=database,
    )
    counts: dict[str, int] = {}
    for line in output.splitlines():
        name, count = line.split("\t")
        counts[name] = int(count)
    return counts


def batched_insert(table: str, columns: list[str], values: list[list[str]]) -> str:
    statements: list[str] = []
    batch_size = 200
    for start in range(0, len(values), batch_size):
        batch = values[start : start + batch_size]
        rows = ",\n".join("(" + ", ".join(row) + ")" for row in batch)
        statements.append(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES\n{rows};"
        )
    return "\n".join(statements)


def build_load_sql(
    origins: list[dict[str, str]],
    policy_origins: list[dict[str, str]],
    coverage: list[dict[str, str]],
    *,
    replace: bool,
) -> str:
    statements = ["START TRANSACTION;"]
    if replace:
        statements.extend(
            [
                "DELETE FROM hts8_coverage;",
                "DELETE FROM policy_origin_mapping;",
                "DELETE FROM origin_dimension;",
            ]
        )
    statements.append(
        batched_insert(
            "origin_dimension",
            [
                "origin_code",
                "canonical_origin_name",
                "observed_origin_names",
                "first_observed_month",
                "last_observed_month",
                "name_variant_count",
                "canonical_name_method",
                "quality_status",
                "reference_url",
            ],
            [
                [
                    sql_text(row["origin_code"]),
                    sql_text(row["canonical_origin_name"]),
                    sql_text(row["observed_origin_names"]),
                    sql_text(row["first_observed_month"]),
                    sql_text(row["last_observed_month"]),
                    str(int(row["name_variant_count"])),
                    sql_text(row["canonical_name_method"]),
                    sql_text(row["quality_status"]),
                    sql_text(row["reference_url"]),
                ]
                for row in origins
            ],
        )
    )
    statements.append(
        batched_insert(
            "policy_origin_mapping",
            [
                "policy_id",
                "policy_target_origin_name",
                "origin_code",
                "canonical_origin_name",
                "mapping_method",
                "quality_status",
                "reference_url",
            ],
            [
                [
                    sql_text(row["policy_id"]),
                    sql_text(row["policy_target_origin_name"]),
                    sql_text(row["origin_code"]),
                    sql_text(row["canonical_origin_name"]),
                    sql_text(row["mapping_method"]),
                    sql_text(row["quality_status"]),
                    sql_text(row["reference_url"]),
                ]
                for row in policy_origins
            ],
        )
    )
    statements.append(
        batched_insert(
            "hts8_coverage",
            [
                "policy_id",
                "canonical_hts8",
                "observed_trade_row_count",
                "observed_month_count",
                "first_observed_month",
                "last_observed_month",
                "total_import_value_consumption_usd",
                "coverage_status",
                "policy_source_url",
                "classification_reference_url",
            ],
            [
                [
                    sql_text(row["policy_id"]),
                    sql_text(row["canonical_hts8"]),
                    str(int(row["observed_trade_row_count"])),
                    str(int(row["observed_month_count"])),
                    sql_nullable_text(row["first_observed_month"]),
                    sql_nullable_text(row["last_observed_month"]),
                    str(int(row["total_import_value_consumption_usd"])),
                    sql_text(row["coverage_status"]),
                    sql_text(row["policy_source_url"]),
                    sql_text(row["classification_reference_url"]),
                ]
                for row in coverage
            ],
        )
    )
    statements.extend(
        [
            "UPDATE policy_event e "
            "JOIN policy_origin_mapping m ON m.policy_id = e.policy_id "
            "SET e.target_origin_code = m.origin_code;",
            "COMMIT;",
        ]
    )
    return "\n".join(statement for statement in statements if statement)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login-path", default="tradeintel")
    parser.add_argument("--database", default="tradeintel")
    parser.add_argument("--origins", type=Path, default=DEFAULT_ORIGINS)
    parser.add_argument("--policy-origins", type=Path, default=DEFAULT_POLICY_ORIGINS)
    parser.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument("--replace", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run_mysql(SCHEMA.read_text(encoding="utf-8"), login_path=args.login_path)
        counts = table_counts(login_path=args.login_path, database=args.database)
        if any(counts.values()) and not args.replace:
            raise QualityLoadError(
                f"Quality tables are not empty: {counts}. "
                "Use --replace only after checking their contents."
            )
        origins = read_rows(args.origins)
        policy_origins = read_rows(args.policy_origins)
        coverage = read_rows(args.coverage)
        sql = build_load_sql(
            origins, policy_origins, coverage, replace=args.replace
        )
        run_mysql(sql, login_path=args.login_path, database=args.database)
        print(table_counts(login_path=args.login_path, database=args.database))
        print("Loaded audited quality reference tables into MySQL")
    except (OSError, QualityLoadError) as exc:
        print(f"Quality table load failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
