"""Load the verified TradeIntel CSV outputs into MySQL.

The script uses the MySQL client already installed on the user's machine and
the password stored in a local mysql_config_editor login path.  It refuses to
load into non-empty tables unless --replace is explicitly supplied.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVENT = PROJECT_ROOT / "data/processed/policy/section301_list1_event.csv"
DEFAULT_PRODUCTS = PROJECT_ROOT / "data/processed/policy/section301_list1_products.csv"
DEFAULT_PANEL = PROJECT_ROOT / "data/processed/trade/trade_import_monthly.csv"
SCHEMA = PROJECT_ROOT / "db/schema.sql"


class MysqlLoadError(RuntimeError):
    """Raised when a safe MySQL load cannot proceed."""


def sql_path(path: Path) -> str:
    """Return a single-quoted SQL path literal."""

    return "'" + str(path.resolve()).replace("\\", "\\\\").replace("'", "\\'") + "'"


def run_mysql(sql: str, *, login_path: str, database: str | None = None) -> str:
    command = [
        "mysql",
        f"--login-path={login_path}",
        "--local-infile=1",
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
        message = result.stderr.strip() or result.stdout.strip()
        raise MysqlLoadError(message)
    return result.stdout


def table_counts(*, login_path: str, database: str) -> dict[str, int]:
    output = run_mysql(
        "SELECT 'policy_event', COUNT(*) FROM policy_event;\n"
        "SELECT 'policy_product', COUNT(*) FROM policy_product;\n"
        "SELECT 'trade_monthly', COUNT(*) FROM trade_monthly;\n",
        login_path=login_path,
        database=database,
    )
    counts: dict[str, int] = {}
    for line in output.splitlines():
        name, count = line.split("\t")
        counts[name] = int(count)
    return counts


def load_event(path: Path) -> str:
    return f"""
LOAD DATA LOCAL INFILE {sql_path(path)}
INTO TABLE policy_event
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY '\\\\'
LINES TERMINATED BY '\\n'
IGNORE 1 LINES
(@policy_id, @policy_name, @importer_name, @target_origin_name,
 @announcement_date, @effective_date, @additional_rate, @source_url)
SET policy_id = @policy_id,
    policy_name = @policy_name,
    importer_name = @importer_name,
    target_origin_name = @target_origin_name,
    target_origin_code = NULL,
    announcement_date = @announcement_date,
    effective_date = @effective_date,
    additional_rate = @additional_rate,
    source_url = @source_url;
"""


def load_products(path: Path) -> str:
    return f"""
LOAD DATA LOCAL INFILE {sql_path(path)}
INTO TABLE policy_product
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY '\\\\'
LINES TERMINATED BY '\\n'
IGNORE 1 LINES
(@policy_id, @raw_hts, @canonical_hts8, @source_annex, @source_page,
 @amended, @amendment_source_page, @source_url, @amendment_source_url,
 @exclusion_status)
SET policy_id = @policy_id,
    raw_hts = @raw_hts,
    canonical_hts8 = REPLACE(TRIM(@canonical_hts8), '.', ''),
    source_annex = @source_annex,
    source_page = @source_page,
    amended = LOWER(@amended) = 'true',
    amendment_source_page = NULLIF(@amendment_source_page, ''),
    source_url = @source_url,
    amendment_source_url = NULLIF(@amendment_source_url, ''),
    exclusion_status = @exclusion_status;
"""


def load_panel(path: Path) -> str:
    return f"""
LOAD DATA LOCAL INFILE {sql_path(path)}
INTO TABLE trade_monthly
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY '\\\\'
LINES TERMINATED BY '\\n'
IGNORE 1 LINES
(year, month, origin_code, origin_name, hts10, @hts8,
 import_value_consumption_usd, detail_row_count, source_url,
 source_file_name, source_sha256)
SET hts8 = REPLACE(TRIM(@hts8), '.', '');
"""


def update_target_origin_code() -> str:
    return """
UPDATE policy_event e
JOIN (
    SELECT UPPER(origin_name) AS origin_name,
           MIN(origin_code) AS origin_code
    FROM trade_monthly
    GROUP BY UPPER(origin_name)
    HAVING COUNT(DISTINCT origin_code) = 1
) o ON UPPER(e.target_origin_name) = o.origin_name
SET e.target_origin_code = o.origin_code;
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login-path", default="tradeintel")
    parser.add_argument("--database", default="tradeintel")
    parser.add_argument("--event", type=Path, default=DEFAULT_EVENT)
    parser.add_argument("--products", type=Path, default=DEFAULT_PRODUCTS)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Explicitly clear the three target tables before loading",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for path in (SCHEMA, args.event, args.products, args.panel):
        if not path.exists():
            print(f"MySQL load failed: missing file {path}", file=sys.stderr)
            return 1
    try:
        run_mysql(SCHEMA.read_text(encoding="utf-8"), login_path=args.login_path)
        counts = table_counts(login_path=args.login_path, database=args.database)
        if any(counts.values()) and not args.replace:
            raise MysqlLoadError(
                f"Target tables are not empty: {counts}. "
                "Use --replace only after checking the database contents."
            )
        if args.replace:
            run_mysql(
                "SET FOREIGN_KEY_CHECKS = 0;\n"
                "TRUNCATE TABLE trade_monthly;\n"
                "TRUNCATE TABLE policy_product;\n"
                "TRUNCATE TABLE policy_event;\n"
                "SET FOREIGN_KEY_CHECKS = 1;\n",
                login_path=args.login_path,
                database=args.database,
            )
        load_sql = (
            load_event(args.event)
            + load_products(args.products)
            + load_panel(args.panel)
            + update_target_origin_code()
        )
        run_mysql(load_sql, login_path=args.login_path, database=args.database)
        print(table_counts(login_path=args.login_path, database=args.database))
        print("Loaded verified policy and trade data into MySQL")
    except (MysqlLoadError, OSError) as exc:
        print(f"MySQL load failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
