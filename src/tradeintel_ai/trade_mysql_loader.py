"""Safe, versioned MySQL mirror loading for published trade snapshots.

The CSV snapshot remains authoritative. MySQL is a query copy, and a month is
accepted only after every stored field has been read back and compared.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, TextIO

from .trade_mysql_mirror import (
    DatasetAudit,
    MonthAudit,
    TradeMirrorError,
    iter_export_mysql_rows,
    iter_import_mysql_rows,
)


class MysqlMirrorLoadError(TradeMirrorError):
    """A database state or client failure prevents a safe mirror load."""


OLD_TABLES = frozenset({
    "policy_event", "policy_product", "trade_monthly", "origin_dimension",
    "policy_origin_mapping", "hts8_coverage",
})
TARGET_COLUMNS = {
    "trade_dataset_release": (
        "dataset_id", "data_version", "reporter", "flow", "classification",
        "metric", "source_manifest_sha256", "published_at_utc",
    ),
    "trade_dataset_month": (
        "dataset_id", "data_version", "year", "month", "status", "source_url",
        "source_sha256", "processed_sha256", "row_count",
    ),
    "trade_import_hts10_monthly": (
        "dataset_id", "data_version", "year", "month", "reporter", "flow",
        "classification", "hts10", "partner_key",
        "import_value_consumption_usd", "observed", "source_sha256",
    ),
    "trade_export_scheduleb10_monthly": (
        "dataset_id", "data_version", "year", "month", "scheduleb10",
        "partner_code", "domestic_export_fas_usd", "foreign_reexport_fas_usd",
        "total_export_fas_usd", "domestic_observed", "foreign_observed",
        "source_sha256",
    ),
    "trade_mysql_mirror_verification": (
        "dataset_id", "data_version", "source_manifest_sha256",
        "verified_month_count", "csv_row_count", "expected_sql_row_count",
        "verified_sql_row_count", "audit_sha256", "verified_at_utc",
    ),
}
TARGET_TABLES = frozenset(TARGET_COLUMNS)
PRIMARY_KEYS = {
    "trade_dataset_release": ("dataset_id", "data_version"),
    "trade_dataset_month": ("dataset_id", "data_version", "year", "month"),
    "trade_import_hts10_monthly": (
        "dataset_id", "data_version", "year", "month", "reporter", "flow",
        "classification", "hts10", "partner_key",
    ),
    "trade_export_scheduleb10_monthly": (
        "dataset_id", "data_version", "year", "month", "scheduleb10", "partner_code",
    ),
    "trade_mysql_mirror_verification": ("dataset_id", "data_version"),
}
FOREIGN_KEYS = {
    "trade_dataset_month": ("fk_trade_month_release", "trade_dataset_release"),
    "trade_import_hts10_monthly": ("fk_trade_product_month", "trade_dataset_month"),
    "trade_export_scheduleb10_monthly": ("fk_trade_export_product_month", "trade_dataset_month"),
    "trade_mysql_mirror_verification": (
        "fk_trade_mirror_verification_release", "trade_dataset_release",
    ),
}
OBSERVED_CHECKS = {
    "chk_trade_product_value": "import_value_consumption_usd",
    "chk_trade_export_domestic": "domestic_export_fas_usd",
    "chk_trade_export_foreign": "foreign_reexport_fas_usd",
}
FLOW_TABLE = {
    "import": "trade_import_hts10_monthly",
    "export": "trade_export_scheduleb10_monthly",
}
SQL_BATCH_ROWS = 200
SQL_MAX_STATEMENT_BYTES = 1_000_000


def mysql_executable() -> str:
    found = shutil.which("mysql")
    if found:
        return found
    fallback = Path("/usr/local/mysql/bin/mysql")
    if fallback.is_file():
        return str(fallback)
    raise MysqlMirrorLoadError("找不到本机 MySQL 命令行客户端")


@dataclass(frozen=True)
class MysqlCli:
    executable: str
    login_path: str = "tradeintel"
    database: str = "tradeintel"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.login_path):
            raise MysqlMirrorLoadError("MySQL 登录路径名称无效")
        if self.database != "tradeintel":
            raise MysqlMirrorLoadError("镜像命令只允许使用 tradeintel 数据库")

    def _args(self, *, database: bool = True, quick: bool = False) -> list[str]:
        args = [
            self.executable, f"--login-path={self.login_path}",
            "--batch", "--raw", "--skip-column-names",
            "--default-character-set=utf8mb4", "--connect-timeout=5",
        ]
        if quick:
            args.append("--quick")
        if database:
            args.append(self.database)
        return args

    @staticmethod
    def _failure(result: subprocess.CompletedProcess[str]) -> MysqlMirrorLoadError:
        detail = (result.stderr or result.stdout or "MySQL 客户端未返回错误详情").strip()
        return MysqlMirrorLoadError(f"MySQL 执行失败（退出码 {result.returncode}）：{detail[-1200:]}")

    def query(self, sql: str, *, timeout: int = 60) -> list[tuple[str, ...]]:
        result = subprocess.run(
            [*self._args(database=False), "--execute", sql, self.database],
            capture_output=True, text=True,
            encoding="utf-8", timeout=timeout, check=False,
        )
        if result.returncode:
            raise self._failure(result)
        return [tuple(line.split("\t")) for line in result.stdout.splitlines()]

    def run_file(self, stream: TextIO, *, database: bool = True,
                 timeout: int = 3600) -> str:
        stream.seek(0)
        result = subprocess.run(
            self._args(database=database), stdin=stream, capture_output=True,
            text=True, encoding="utf-8", timeout=timeout, check=False,
        )
        if result.returncode:
            raise self._failure(result)
        return result.stdout.strip()

    def export_query(self, sql: str, output: TextIO, *, timeout: int = 3600) -> None:
        result = subprocess.run(
            [*self._args(database=False, quick=True), "--execute", sql,
             self.database], stdout=output,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", timeout=timeout,
            check=False,
        )
        if result.returncode:
            raise self._failure(result)
        output.flush()
        output.seek(0)


def _single(rows: list[tuple[str, ...]], label: str) -> tuple[str, ...] | None:
    if len(rows) > 1:
        raise MysqlMirrorLoadError(f"{label} 在数据库中出现重复记录")
    return rows[0] if rows else None


def _literal(value: object) -> str:
    if value is None:
        return "NULL"
    if type(value) is bool:
        return "1" if value else "0"
    if type(value) is int and value >= 0:
        return str(value)
    if isinstance(value, str):
        # Hex text is independent of NO_BACKSLASH_ESCAPES and preserves codes.
        return f"CONVERT(0x{value.encode('utf-8').hex()} USING utf8mb4)"
    raise MysqlMirrorLoadError(f"不能编码到 SQL 的值类型：{type(value).__name__}")


def _where(dataset: DatasetAudit, month: MonthAudit) -> str:
    return (
        f"dataset_id={_literal(dataset.dataset_id)} "
        f"AND data_version={_literal(dataset.data_version)} "
        f"AND year={month.year} AND month={month.month}"
    )


def _check_manifest(root: Path, dataset: DatasetAudit) -> None:
    relative = ("data/processed/trade_hts10/manifest.json" if dataset.flow == "import"
                else "data/processed/trade_scheduleb10/manifest.json")
    path = root / relative
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != dataset.manifest_sha256:
        raise MysqlMirrorLoadError("数据清单在离线审计后发生变化；停止写入")


def _insert(table: str, columns: tuple[str, ...], values: Iterable[object]) -> str:
    if table not in TARGET_COLUMNS or any(column not in TARGET_COLUMNS[table] for column in columns):
        raise MysqlMirrorLoadError("目标表或字段不在镜像白名单")
    items = tuple(values)
    if len(items) != len(columns):
        raise MysqlMirrorLoadError("INSERT 字段数与值数不一致")
    return (f"INSERT INTO {table} ({','.join(columns)}) VALUES ("
            + ",".join(_literal(item) for item in items) + ");\n")


def write_month_script(
    stream: TextIO, dataset: DatasetAudit, month: MonthAudit,
    rows: Iterable[tuple[object, ...]], *, release_exists: bool,
    batch_rows: int = SQL_BATCH_ROWS,
    max_statement_bytes: int = SQL_MAX_STATEMENT_BYTES,
) -> int:
    """Finish an entire month's SQL before it is passed to the MySQL client."""
    if batch_rows < 1 or max_statement_bytes < 1024:
        raise MysqlMirrorLoadError("批次上限无效")
    table = FLOW_TABLE[dataset.flow]
    columns = TARGET_COLUMNS[table]
    stream.write("START TRANSACTION;\n")
    if not release_exists:
        release_columns = TARGET_COLUMNS["trade_dataset_release"][:-1]
        release_values = (
            dataset.dataset_id, dataset.data_version, dataset.reporter,
            dataset.flow, dataset.classification, dataset.metric,
            dataset.manifest_sha256,
        )
        stream.write(
            "INSERT INTO trade_dataset_release ("
            + ",".join((*release_columns, "published_at_utc"))
            + ") VALUES ("
            + ",".join(_literal(value) for value in release_values)
            + ",UTC_TIMESTAMP());\n"
        )
    stream.write(_insert(
        "trade_dataset_month", TARGET_COLUMNS["trade_dataset_month"],
        (dataset.dataset_id, dataset.data_version, month.year, month.month,
         "queryable_detail", month.source_url, month.source_sha256,
         month.processed_sha256, month.csv_rows),
    ))
    prefix = f"INSERT INTO {table} ({','.join(columns)}) VALUES "
    batch: list[str] = []
    batch_bytes = len(prefix)
    count = 0

    def flush() -> None:
        nonlocal batch_bytes
        if batch:
            stream.write(prefix + ",".join(batch) + ";\n")
            batch.clear()
            batch_bytes = len(prefix)

    for row in rows:
        if len(row) != len(columns):
            raise MysqlMirrorLoadError(f"{month.month_key} 明细行字段数不符")
        value_sql = "(" + ",".join(_literal(item) for item in row) + ")"
        value_bytes = len(value_sql) + 2
        if len(prefix) + value_bytes > max_statement_bytes:
            raise MysqlMirrorLoadError("单条记录超过 SQL 批次长度上限")
        if batch and (len(batch) >= batch_rows or
                      batch_bytes + value_bytes > max_statement_bytes):
            flush()
        batch.append(value_sql)
        batch_bytes += value_bytes
        count += 1
    flush()
    if count != month.sql_rows:
        raise MysqlMirrorLoadError(
            f"{month.month_key} 生成 {count} 行，与离线审计 {month.sql_rows} 行不一致"
        )
    stream.write("COMMIT;\n")
    stream.write(
        "SELECT 'MIRROR_COMMIT_OK', COUNT(*) FROM " + table
        + " WHERE " + _where(dataset, month) + ";\n"
    )
    return count


def _schema_tables(client: MysqlCli) -> set[str]:
    rows = client.query(
        "SELECT TABLE_NAME FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=DATABASE()"
    )
    return {row[0] for row in rows}


def check_connection(client: MysqlCli) -> dict[str, str]:
    row = _single(client.query(
        "SELECT VERSION(), CURRENT_USER(), DATABASE(), @@SESSION.sql_mode"
    ), "MySQL 连接")
    if row is None or len(row) != 4 or row[2] != client.database:
        raise MysqlMirrorLoadError("连接到的数据库不是 tradeintel")
    modes = set(row[3].split(","))
    if not modes.intersection({"STRICT_TRANS_TABLES", "STRICT_ALL_TABLES"}):
        raise MysqlMirrorLoadError("当前 MySQL 会话未开启严格 SQL 模式")
    tables = _schema_tables(client)
    if not OLD_TABLES.issubset(tables):
        raise MysqlMirrorLoadError("tradeintel 缺少既有旧表；拒绝在错误数据库中建镜像")
    return {"mysql_version": row[0], "account": row[1],
            "database": row[2], "sql_mode": row[3]}


def validate_schema(client: MysqlCli) -> None:
    tables = _schema_tables(client)
    if not TARGET_TABLES.issubset(tables):
        raise MysqlMirrorLoadError("镜像表缺失或只建成一部分")
    for table, expected_columns in TARGET_COLUMNS.items():
        engine = _single(client.query(
            "SELECT ENGINE FROM information_schema.TABLES "
            f"WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='{table}'"
        ), f"{table} 存储引擎")
        if engine != ("InnoDB",):
            raise MysqlMirrorLoadError(f"{table} 必须使用 InnoDB")
        columns = tuple(row[0] for row in client.query(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            f"WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='{table}' "
            "ORDER BY ORDINAL_POSITION"
        ))
        if columns != expected_columns:
            raise MysqlMirrorLoadError(f"{table} 字段顺序或字段集合与方案不符")
        primary = tuple(row[0] for row in client.query(
            "SELECT COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE "
            f"WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='{table}' "
            "AND CONSTRAINT_NAME='PRIMARY' ORDER BY ORDINAL_POSITION"
        ))
        if primary != PRIMARY_KEYS[table]:
            raise MysqlMirrorLoadError(f"{table} 主键与方案不符")
    for table, (constraint, target) in FOREIGN_KEYS.items():
        rows = client.query(
            "SELECT DISTINCT REFERENCED_TABLE_NAME FROM "
            "information_schema.KEY_COLUMN_USAGE "
            f"WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='{table}' "
            f"AND CONSTRAINT_NAME='{constraint}'"
        )
        if rows != [(target,)]:
            raise MysqlMirrorLoadError(f"{table} 外键 {constraint} 与方案不符")
    for constraint, column in OBSERVED_CHECKS.items():
        row = _single(client.query(
            "SELECT CHECK_CLAUSE FROM information_schema.CHECK_CONSTRAINTS "
            f"WHERE CONSTRAINT_SCHEMA=DATABASE() AND CONSTRAINT_NAME='{constraint}'"
        ), constraint)
        if row is None:
            raise MysqlMirrorLoadError(f"缺少金额空值约束 {constraint}")
        clause = re.sub(r"[\s`()]", "", row[0].lower())
        if f"{column}isnotnull" not in clause:
            raise MysqlMirrorLoadError(f"金额空值约束 {constraint} 未修正")


def ensure_schema(client: MysqlCli, schema_file: Path, *, apply: bool) -> bool:
    tables = _schema_tables(client)
    present = TARGET_TABLES.intersection(tables)
    if present and present != TARGET_TABLES:
        raise MysqlMirrorLoadError("镜像表只建成一部分；需先人工核对，不能自动补建")
    if present == TARGET_TABLES:
        validate_schema(client)
        return False
    if not apply:
        return False
    schema = schema_file.read_text(encoding="utf-8")
    statements = [part.strip() for part in re.sub(
        r"(?m)^--.*$", "", schema).split(";") if part.strip()]
    create_tables = [re.match(
        r"(?is)^CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+([a-z0-9_]+)\s*\(",
        statement,
    ) for statement in statements[2:]]
    if (len(statements) != 2 + len(OLD_TABLES) + len(TARGET_TABLES)
            or not re.match(r"(?is)^CREATE\s+DATABASE\s+IF\s+NOT\s+EXISTS\s+tradeintel\b",
                            statements[0])
            or not re.fullmatch(r"(?is)USE\s+tradeintel", statements[1])
            or any(match is None for match in create_tables)
            or {match.group(1).lower() for match in create_tables if match}
            != OLD_TABLES | TARGET_TABLES):
        raise MysqlMirrorLoadError("schema.sql 含未批准的 SQL 语句")
    with schema_file.open("r", encoding="utf-8") as stream:
        client.run_file(stream, database=False, timeout=120)
    validate_schema(client)
    return True


def _release_row(client: MysqlCli, dataset: DatasetAudit) -> tuple[str, ...] | None:
    row = _single(client.query(
        "SELECT reporter,flow,classification,metric,source_manifest_sha256 "
        "FROM trade_dataset_release WHERE dataset_id="
        + _literal(dataset.dataset_id) + " AND data_version="
        + _literal(dataset.data_version)
    ), "版本登记")
    expected = (dataset.reporter, dataset.flow, dataset.classification,
                dataset.metric, dataset.manifest_sha256)
    if row is not None and row != expected:
        raise MysqlMirrorLoadError("同一数据版本的来源清单或定义与现有登记不一致")
    return row


def _month_row(client: MysqlCli, dataset: DatasetAudit,
               month: MonthAudit) -> tuple[str, ...] | None:
    row = _single(client.query(
        "SELECT status,source_url,source_sha256,processed_sha256,row_count "
        "FROM trade_dataset_month WHERE " + _where(dataset, month)
    ), "月份登记")
    expected = ("queryable_detail", month.source_url, month.source_sha256,
                month.processed_sha256, str(month.csv_rows))
    if row is not None and row != expected:
        raise MysqlMirrorLoadError(f"{month.month_key} 月份登记与同版文件不一致")
    return row


def _detail_count(client: MysqlCli, dataset: DatasetAudit, month: MonthAudit) -> int:
    row = _single(client.query(
        f"SELECT COUNT(*) FROM {FLOW_TABLE[dataset.flow]} WHERE "
        + _where(dataset, month)
    ), "明细行数")
    if row is None or len(row) != 1:
        raise MysqlMirrorLoadError("无法读取 MySQL 明细行数")
    return int(row[0])


def _verification_row(client: MysqlCli, dataset: DatasetAudit) -> tuple[str, ...] | None:
    row = _single(client.query(
        "SELECT source_manifest_sha256,verified_month_count,csv_row_count,"
        "expected_sql_row_count,verified_sql_row_count,audit_sha256 "
        "FROM trade_mysql_mirror_verification WHERE dataset_id="
        + _literal(dataset.dataset_id) + " AND data_version="
        + _literal(dataset.data_version)
    ), "整版验收记录")
    if row is not None and row[0] != dataset.manifest_sha256:
        raise MysqlMirrorLoadError("整版验收记录来源清单与当前版本不一致")
    return row


def _decode_row(dataset: DatasetAudit, line: str) -> tuple[object, ...]:
    cells = line.rstrip("\r\n").split("\t")
    if len(cells) != 12:
        raise MysqlMirrorLoadError("MySQL 明细读回列数不符")
    for index in (2, 3):
        cells[index] = int(cells[index])
    if dataset.flow == "import":
        cells[9] = None if cells[9] == "NULL" else int(cells[9])
        cells[10] = bool(int(cells[10]))
    else:
        for index in (6, 7):
            cells[index] = None if cells[index] == "NULL" else int(cells[index])
        cells[8] = int(cells[8])
        cells[9] = bool(int(cells[9]))
        cells[10] = bool(int(cells[10]))
    return tuple(cells)


def compare_rows(dataset: DatasetAudit, expected: list[tuple[object, ...]],
                 actual: TextIO) -> int:
    key_positions = (7, 8) if dataset.flow == "import" else (4, 5)
    expected.sort(key=lambda row: tuple(row[index] for index in key_positions))
    matched = 0
    for matched, wanted in enumerate(expected, 1):
        line = actual.readline()
        if not line:
            raise MysqlMirrorLoadError(f"数据库少于预期行数；第 {matched} 行缺失")
        got = _decode_row(dataset, line)
        if got != wanted:
            key = "/".join(str(wanted[index]) for index in key_positions)
            raise MysqlMirrorLoadError(f"逐行读回第 {matched} 行不一致：{key}")
    if actual.readline():
        raise MysqlMirrorLoadError("数据库行数多于预期")
    return matched


def reconcile_month(client: MysqlCli, root: Path, dataset: DatasetAudit,
                    month: MonthAudit) -> dict[str, object]:
    if _release_row(client, dataset) is None or _month_row(client, dataset, month) is None:
        raise MysqlMirrorLoadError(f"{month.month_key} 缺少版本或月份登记")
    if _detail_count(client, dataset, month) != month.sql_rows:
        raise MysqlMirrorLoadError(f"{month.month_key} MySQL 明细行数与文件不符")
    iterator = (iter_import_mysql_rows if dataset.flow == "import"
                else iter_export_mysql_rows)
    expected = list(iterator(root, month, dataset.data_version))
    if len(expected) != month.sql_rows:
        raise MysqlMirrorLoadError(f"{month.month_key} CSV 映射行数已变化")
    table = FLOW_TABLE[dataset.flow]
    columns = TARGET_COLUMNS[table]
    order = "hts10,partner_key" if dataset.flow == "import" else "scheduleb10,partner_code"
    sql = (f"SELECT {','.join(columns)} FROM {table} WHERE "
           + _where(dataset, month) + f" ORDER BY {order}")
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as output:
        client.export_query(sql, output)
        compared = compare_rows(dataset, expected, output)
    if dataset.flow == "import":
        aggregate_sql = (
            "SELECT COUNT(*),"
            "COALESCE(SUM(CASE WHEN partner_key='CHINA' THEN "
            "COALESCE(import_value_consumption_usd,0) ELSE 0 END),0),"
            "COALESCE(SUM(CASE WHEN partner_key='ALL_ORIGINS' THEN "
            "COALESCE(import_value_consumption_usd,0) ELSE 0 END),0),"
            "COALESCE(SUM(CASE WHEN partner_key='CHINA' THEN observed ELSE 0 END),0) "
            f"FROM {table} WHERE " + _where(dataset, month)
        )
        expected_aggregate = (
            month.sql_rows, month.metrics["china_value_usd"],
            month.metrics["all_origin_value_usd"],
            month.metrics["china_observed_hts10_count"],
        )
    else:
        aggregate_sql = (
            "SELECT COUNT(*),COALESCE(SUM(domestic_export_fas_usd),0),"
            "COALESCE(SUM(foreign_reexport_fas_usd),0),"
            "COALESCE(SUM(total_export_fas_usd),0),"
            "COALESCE(SUM(domestic_observed),0),"
            "COALESCE(SUM(foreign_observed),0) "
            f"FROM {table} WHERE " + _where(dataset, month)
        )
        expected_aggregate = (
            month.sql_rows, month.metrics["domestic_export_fas_usd"],
            month.metrics["foreign_reexport_fas_usd"],
            month.metrics["total_export_fas_usd"],
            month.metrics["domestic_observed_rows"],
            month.metrics["foreign_observed_rows"],
        )
    row = _single(client.query(aggregate_sql), "数据库月汇总")
    if row is None or tuple(int(value) for value in row) != expected_aggregate:
        raise MysqlMirrorLoadError(f"{month.month_key} MySQL 月汇总与文件不符")
    return {
        "month": month.month_key, "csv_rows": month.csv_rows,
        "verified_sql_rows": compared, "row_mismatches": 0,
        "aggregate_mismatches": 0, "processed_sha256": month.processed_sha256,
    }


def finalize_release(
    client: MysqlCli, root: Path, dataset: DatasetAudit, *, apply: bool,
    audit_path: Path | None = None,
) -> dict[str, object]:
    """Re-read every published month, then optionally record full verification."""
    _check_manifest(root, dataset)
    existing = _verification_row(client, dataset)
    month_results: list[dict[str, object]] = []
    for month in dataset.months:
        month_results.append(reconcile_month(client, root, dataset, month))
    _check_manifest(root, dataset)
    payload: dict[str, object] = {
        "dataset_id": dataset.dataset_id,
        "data_version": dataset.data_version,
        "source_manifest_sha256": dataset.manifest_sha256,
        "verified_month_count": len(dataset.months),
        "csv_row_count": dataset.csv_rows,
        "expected_sql_row_count": dataset.sql_rows,
        "verified_sql_row_count": sum(int(item["verified_sql_rows"]) for item in month_results),
        "months": month_results,
    }
    audit_sha = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    payload["audit_sha256"] = audit_sha
    if audit_path is not None:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    expected_counts = (
        dataset.manifest_sha256, str(len(dataset.months)), str(dataset.csv_rows),
        str(dataset.sql_rows), str(dataset.sql_rows), audit_sha,
    )
    if existing is not None:
        if existing != expected_counts:
            raise MysqlMirrorLoadError("已有整版验收记录与本次完整复核摘要不一致")
        return {**payload, "action": "already_verified", "full_release_verified": True}
    if not apply:
        return {**payload, "action": "would_record_verification",
                "full_release_verified": False}
    columns = TARGET_COLUMNS["trade_mysql_mirror_verification"]
    values = (dataset.dataset_id, dataset.data_version, dataset.manifest_sha256,
              len(dataset.months), dataset.csv_rows, dataset.sql_rows, dataset.sql_rows,
              audit_sha)
    statement = (
        f"INSERT INTO trade_mysql_mirror_verification ({','.join(columns)}) VALUES ("
        + ",".join(_literal(value) for value in values)
        + ",UTC_TIMESTAMP());\n"
    )
    with tempfile.TemporaryFile(mode="w+t", encoding="ascii") as stream:
        stream.write("START TRANSACTION;\n" + statement + "COMMIT;\n")
        client.run_file(stream)
    recorded = _verification_row(client, dataset)
    if recorded != expected_counts:
        raise MysqlMirrorLoadError("整版验收记录写入后读回不一致")
    return {**payload, "action": "recorded_verification", "full_release_verified": True}


def load_month(client: MysqlCli, root: Path, dataset: DatasetAudit,
               month: MonthAudit, *, apply: bool) -> dict[str, object]:
    _check_manifest(root, dataset)
    release = _release_row(client, dataset)
    existing_month = _month_row(client, dataset, month)
    existing_rows = _detail_count(client, dataset, month)
    marker = client.query(
        "SELECT source_manifest_sha256 FROM trade_mysql_mirror_verification "
        "WHERE dataset_id=" + _literal(dataset.dataset_id)
        + " AND data_version=" + _literal(dataset.data_version)
    )
    if marker and (len(marker) != 1 or marker[0] != (dataset.manifest_sha256,)):
        raise MysqlMirrorLoadError("整版验收记录与当前来源清单不一致")
    if existing_month is not None:
        result = reconcile_month(client, root, dataset, month)
        return {**result, "action": "already_matched", "full_release_verified": bool(marker)}
    if existing_rows or marker:
        raise MysqlMirrorLoadError("已有明细或整版验收记录，但缺少当前月份登记")
    if not apply:
        return {
            "month": month.month_key, "csv_rows": month.csv_rows,
            "expected_sql_rows": month.sql_rows, "action": "would_load",
            "full_release_verified": False,
        }
    iterator = (iter_import_mysql_rows if dataset.flow == "import"
                else iter_export_mysql_rows)
    with tempfile.TemporaryFile(mode="w+t", encoding="ascii") as script:
        written = write_month_script(
            script, dataset, month, iterator(root, month, dataset.data_version),
            release_exists=release is not None,
        )
        _check_manifest(root, dataset)
        try:
            marker_output = client.run_file(script)
        except (MysqlMirrorLoadError, subprocess.TimeoutExpired) as exc:
            return _reconcile_uncertain_write(client, root, dataset, month, exc)
    expected_marker = f"MIRROR_COMMIT_OK\t{written}"
    if marker_output != expected_marker:
        return _reconcile_uncertain_write(
            client, root, dataset, month,
            MysqlMirrorLoadError("提交标记不完整或行数不符"),
        )
    result = reconcile_month(client, root, dataset, month)
    return {**result, "action": "loaded_and_matched", "full_release_verified": False}


def _reconcile_uncertain_write(
    client: MysqlCli, root: Path, dataset: DatasetAudit, month: MonthAudit,
    reason: Exception,
) -> dict[str, object]:
    """Never retry a possibly committed transaction; inspect fresh DB state."""
    try:
        state = _month_row(client, dataset, month)
        count = _detail_count(client, dataset, month)
    except (MysqlMirrorLoadError, subprocess.TimeoutExpired) as exc:
        raise MysqlMirrorLoadError(
            f"{month.month_key} 写入结果未知且无法重新查询；不得自动重试：{exc}"
        ) from reason
    if state is not None and count == month.sql_rows:
        try:
            result = reconcile_month(client, root, dataset, month)
        except (MysqlMirrorLoadError, subprocess.TimeoutExpired) as exc:
            raise MysqlMirrorLoadError(
                f"{month.month_key} 写入后有记录但逐行核对失败；不得自动清理或重试：{exc}"
            ) from reason
        return {**result, "action": "matched_after_unknown_outcome",
                "full_release_verified": False}
    if state is None and count == 0:
        raise MysqlMirrorLoadError(
            f"{month.month_key} 写入未见提交；本轮未自动重试：{reason}"
        ) from reason
    raise MysqlMirrorLoadError(
        f"{month.month_key} 写入结果不完整（月份登记={state is not None}，"
        f"明细行数={count}）；停止且不自动清理：{reason}"
    ) from reason
