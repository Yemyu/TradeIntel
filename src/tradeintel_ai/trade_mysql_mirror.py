"""Offline validation and loss-aware row mapping for MySQL trade snapshots.

This module does not connect to MySQL. It proves that the released files are
internally consistent and exposes the exact rows a future loader must write.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


class TradeMirrorError(ValueError):
    """A published trade snapshot cannot be mirrored without ambiguity."""


IMPORT_FIELDS = (
    "year", "month", "hts10", "hts8",
    "china_import_value_consumption_usd",
    "all_origin_import_value_consumption_usd",
    "china_observed", "all_origin_observed",
    "china_detail_row_count", "all_origin_detail_row_count",
    "source_url", "source_file_name", "source_sha256",
)
EXPORT_FIELDS = (
    "year", "month", "scheduleb10", "partner_code",
    "domestic_export_fas_usd", "foreign_reexport_fas_usd",
    "total_export_fas_usd", "domestic_observed", "foreign_observed",
    "source_sha256",
)
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class MonthAudit:
    year: int
    month: int
    file: str
    source_sha256: str
    processed_sha256: str
    source_url: str
    source_file_name: str
    csv_rows: int
    sql_rows: int
    metrics: dict[str, int]

    @property
    def month_key(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    def as_dict(self) -> dict[str, object]:
        return {
            "month": self.month_key,
            "file": self.file,
            "source_sha256": self.source_sha256,
            "processed_sha256": self.processed_sha256,
            "source_url": self.source_url,
            "source_file_name": self.source_file_name,
            "csv_rows": self.csv_rows,
            "sql_rows": self.sql_rows,
            "metrics": dict(self.metrics),
            "status": "offline_file_audit_passed",
        }


@dataclass(frozen=True)
class DatasetAudit:
    dataset_id: str
    data_version: str
    reporter: str
    flow: str
    classification: str
    metric: str
    manifest_sha256: str
    months: tuple[MonthAudit, ...]

    @property
    def csv_rows(self) -> int:
        return sum(item.csv_rows for item in self.months)

    @property
    def sql_rows(self) -> int:
        return sum(item.sql_rows for item in self.months)

    def as_dict(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "data_version": self.data_version,
            "reporter": self.reporter,
            "flow": self.flow,
            "classification": self.classification,
            "metric": self.metric,
            "manifest_sha256": self.manifest_sha256,
            "month_count": len(self.months),
            "csv_rows": self.csv_rows,
            "sql_rows": self.sql_rows,
            "months": [item.as_dict() for item in self.months],
            "status": "offline_file_audit_passed_not_mysql_verified",
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_digest(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _read_manifest(path: Path) -> tuple[dict[str, object], bytes]:
    try:
        raw = path.read_bytes()
        manifest = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise TradeMirrorError(f"数据清单缺失或无效：{path}") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("months"), list):
        raise TradeMirrorError(f"数据清单结构无效：{path}")
    return manifest, raw


def _positive_year_month(item: dict[str, object], label: str) -> tuple[int, int, str]:
    year, month = item.get("year"), item.get("month")
    if type(year) is not int or type(month) is not int or year < 1900 or not 1 <= month <= 12:
        raise TradeMirrorError(f"{label} 年月无效")
    return year, month, f"{year:04d}-{month:02d}"


def _integer(value: object, label: str, *, blank_allowed: bool = False) -> int | None:
    if blank_allowed and value == "":
        return None
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)", value):
        raise TradeMirrorError(f"{label} 不是非负整数")
    return int(value)


def _observed(value: object, label: str) -> bool:
    if value not in {"0", "1"}:
        raise TradeMirrorError(f"{label} 必须是 0 或 1")
    return value == "1"


def _manifest_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise TradeMirrorError(f"{label} 摘要无效")
    return value


def _processed_path(root: Path, relative: object, expected: str, label: str) -> Path:
    if not isinstance(relative, str) or relative != expected:
        raise TradeMirrorError(f"{label} 加工文件路径不符合清单规则")
    path = root / relative
    if not path.is_file():
        raise TradeMirrorError(f"{label} 加工文件缺失：{relative}")
    return path


def _csv_reader(path: Path, expected_fields: tuple[str, ...], label: str):
    stream = path.open(newline="", encoding="utf-8")
    reader = csv.DictReader(stream)
    if tuple(reader.fieldnames or ()) != expected_fields:
        stream.close()
        raise TradeMirrorError(f"{label} CSV 表头与已发布格式不一致")
    return stream, reader


def inspect_import_snapshot(root: Path) -> DatasetAudit:
    """Validate all currently processed import months and their DB row mapping."""
    root = Path(root)
    manifest_path = root / "data/processed/trade_hts10/manifest.json"
    manifest, raw_manifest = _read_manifest(manifest_path)
    records: dict[str, tuple[dict[str, object], Path, str, int, int]] = {}
    for item in manifest["months"]:
        if not isinstance(item, dict):
            raise TradeMirrorError("进口清单月份记录无效")
        year, month, key = _positive_year_month(item, "进口清单")
        if key in records:
            raise TradeMirrorError(f"进口清单月份重复：{key}")
        if item.get("status") != "processed":
            continue
        source_sha = _manifest_sha(item.get("source_sha256"), f"进口 {key} 原包")
        expected = f"data/processed/trade_hts10/monthly/trade_hts10_{year}_{month:02d}.csv"
        file_path = _processed_path(root, item.get("monthly_output"), expected, f"进口 {key}")
        file_sha = _sha256(file_path)
        # Keep the computed file digest next to the validated record.
        records[key] = (dict(item, _computed_processed_sha256=file_sha), file_path,
                        source_sha, year, month)

    if not records:
        raise TradeMirrorError("进口清单中没有已加工月份")

    published = [
        {"month": key, "source_sha256": item[2],
         "processed_sha256": str(item[0]["_computed_processed_sha256"])}
        for key, item in sorted(records.items())
    ]
    version = _json_digest(published)
    audits: list[MonthAudit] = []
    for key, (item, file_path, source_sha, year, month) in sorted(records.items()):
        before_sha = str(item["_computed_processed_sha256"])
        output_rows = item.get("output_rows")
        unique_codes = item.get("unique_hts10_count")
        raw_all_total = item.get("raw_all_origin_value_usd")
        raw_china_total = item.get("raw_china_value_usd")
        raw_detail_rows = item.get("raw_detail_rows")
        if any(type(value) is not int or value < 0 for value in
               (output_rows, unique_codes, raw_all_total, raw_china_total, raw_detail_rows)):
            raise TradeMirrorError(f"进口 {key} 清单中的行数或金额汇总无效")
        rows = all_total = china_total = all_detail_rows = 0
        china_observed_count = 0
        seen: set[str] = set()
        stream, reader = _csv_reader(file_path, IMPORT_FIELDS, f"进口 {key}")
        try:
            for row in reader:
                rows += 1
                if row["year"] != str(year) or row["month"] != str(month):
                    raise TradeMirrorError(f"进口 {key} CSV 行的年月不一致")
                hts10 = row["hts10"]
                if not re.fullmatch(r"\d{10}", hts10) or row["hts8"] != hts10[:8]:
                    raise TradeMirrorError(f"进口 {key} 商品码无效或 HTS8 不匹配")
                if hts10 in seen:
                    raise TradeMirrorError(f"进口 {key} HTS10 重复：{hts10}")
                seen.add(hts10)
                if row["source_sha256"] != source_sha:
                    raise TradeMirrorError(f"进口 {key} 行的原包摘要不一致")
                if row["source_url"] != item.get("source_url") or row["source_file_name"] != item.get("source_file_name"):
                    raise TradeMirrorError(f"进口 {key} 行的来源信息与清单不一致")
                china_observed = _observed(row["china_observed"], f"进口 {key} 中国观察状态")
                all_observed = _observed(row["all_origin_observed"], f"进口 {key} 全来源观察状态")
                china_value = _integer(row["china_import_value_consumption_usd"], f"进口 {key} 中国金额")
                all_value = _integer(row["all_origin_import_value_consumption_usd"], f"进口 {key} 全来源金额")
                china_count = _integer(row["china_detail_row_count"], f"进口 {key} 中国明细数")
                all_count = _integer(row["all_origin_detail_row_count"], f"进口 {key} 全来源明细数")
                assert isinstance(china_value, int) and isinstance(all_value, int)
                assert isinstance(china_count, int) and isinstance(all_count, int)
                if china_observed != (china_count > 0) or all_observed != (all_count > 0):
                    raise TradeMirrorError(f"进口 {key} 观察标志与明细行数不一致")
                if (not china_observed and china_value != 0) or (not all_observed and all_value != 0):
                    raise TradeMirrorError(f"进口 {key} 未观察金额必须为空或为零占位")
                all_total += all_value
                china_total += china_value
                all_detail_rows += all_count
                china_observed_count += int(china_observed)
        finally:
            stream.close()
        if rows != output_rows or rows != unique_codes:
            raise TradeMirrorError(f"进口 {key} 行数 {rows} 与清单 {output_rows} 不一致")
        if all_total != raw_all_total or china_total != raw_china_total:
            raise TradeMirrorError(f"进口 {key} 金额合计与原始清单不一致")
        if all_detail_rows != raw_detail_rows:
            raise TradeMirrorError(f"进口 {key} 全来源明细行数与清单不一致")
        after_sha = _sha256(file_path)
        if after_sha != before_sha:
            raise TradeMirrorError(f"进口 {key} 文件在核对期间发生变化")
        audits.append(MonthAudit(
            year, month, str(file_path.relative_to(root)), source_sha, after_sha,
            str(item["source_url"]), str(item["source_file_name"]), rows, rows * 2,
            {"all_origin_value_usd": all_total, "china_value_usd": china_total,
             "all_origin_detail_rows": all_detail_rows,
             "china_observed_hts10_count": china_observed_count},
        ))
    # Recompute after full file checks to prevent a mixed-version report.
    final_version = _json_digest([
        {"month": audit.month_key, "source_sha256": audit.source_sha256,
         "processed_sha256": audit.processed_sha256}
        for audit in audits
    ])
    if final_version != version:
        raise TradeMirrorError("进口文件版本在核对过程中发生变化")
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != hashlib.sha256(raw_manifest).hexdigest():
        raise TradeMirrorError("进口清单在核对过程中发生变化")
    return DatasetAudit(
        "census-us-import-hts10", version, "US", "import", "US-HTS10",
        "import_value_consumption_usd", hashlib.sha256(raw_manifest).hexdigest(),
        tuple(audits),
    )


def inspect_export_snapshot(root: Path) -> DatasetAudit:
    """Validate all current Schedule B exports and their DB row mapping."""
    root = Path(root)
    manifest_path = root / "data/processed/trade_scheduleb10/manifest.json"
    manifest, raw_manifest = _read_manifest(manifest_path)
    if manifest.get("dataset_id") != "census-us-export-scheduleb10":
        raise TradeMirrorError("出口数据集编号与当前导出快照不符")
    months = manifest["months"]
    if not months:
        raise TradeMirrorError("出口清单没有月份")
    records: list[tuple[dict[str, object], Path, int, int, str, str]] = []
    seen_months: set[str] = set()
    version_parts: list[dict[str, object]] = []
    for item in months:
        if not isinstance(item, dict):
            raise TradeMirrorError("出口清单月份记录无效")
        year, month, key = _positive_year_month(item, "出口清单")
        if key in seen_months:
            raise TradeMirrorError(f"出口清单月份重复：{key}")
        seen_months.add(key)
        if item.get("status") != "processed":
            raise TradeMirrorError(f"出口 {key} 尚未加工，不能镜像")
        source_sha = _manifest_sha(item.get("source_sha256"), f"出口 {key} 原包")
        processed_sha = _manifest_sha(item.get("processed_sha256"), f"出口 {key} 加工文件")
        if item.get("commodity_reconciliation_mismatch_count") != 0:
            raise TradeMirrorError(f"出口 {key} 源商品汇总对账未通过")
        _manifest_sha(item.get("country_file_sha256"), f"出口 {key} 目的地目录")
        if not re.fullmatch(r"\d{4}", str(item.get("china_destination_code", ""))):
            raise TradeMirrorError(f"出口 {key} 中国目的地码无效")
        expected = (f"data/processed/trade_scheduleb10/monthly/"
                    f"export_scheduleb10_{year}_{month:02d}_{source_sha[:12]}.csv")
        file_path = _processed_path(root, item.get("processed_file"), expected, f"出口 {key}")
        version_parts.append({"year": year, "month": month,
                              "source_sha256": source_sha,
                              "processed_sha256": processed_sha})
        records.append((item, file_path, year, month, source_sha, key))
    if [record[5] for record in records] != sorted(seen_months):
        raise TradeMirrorError("出口清单月份必须按年月升序排列")
    version = _json_digest(version_parts)
    if manifest.get("dataset_version") != version:
        raise TradeMirrorError("出口版本号与清单不一致")

    audits: list[MonthAudit] = []
    for item, file_path, year, month, source_sha, key in records:
        expected_sha = str(item["processed_sha256"])
        if _sha256(file_path) != expected_sha:
            raise TradeMirrorError(f"出口 {key} 加工文件摘要与清单不一致")
        rows = domestic_total = foreign_total = total_amount = 0
        domestic_observed_rows = foreign_observed_rows = 0
        seen: set[tuple[str, str]] = set()
        stream, reader = _csv_reader(file_path, EXPORT_FIELDS, f"出口 {key}")
        try:
            for row in reader:
                rows += 1
                if row["year"] != str(year) or row["month"] != str(month):
                    raise TradeMirrorError(f"出口 {key} CSV 行的年月不一致")
                code, partner = row["scheduleb10"], row["partner_code"]
                if not re.fullmatch(r"\d{10}", code) or not re.fullmatch(r"\d{4}", partner):
                    raise TradeMirrorError(f"出口 {key} 商品码或目的地码无效")
                if (code, partner) in seen:
                    raise TradeMirrorError(f"出口 {key} 商品与目的地组合重复：{code}/{partner}")
                seen.add((code, partner))
                if row["source_sha256"] != source_sha:
                    raise TradeMirrorError(f"出口 {key} 行的原包摘要不一致")
                domestic_observed = _observed(row["domestic_observed"], f"出口 {key} 国产观察状态")
                foreign_observed = _observed(row["foreign_observed"], f"出口 {key} 再出口观察状态")
                if not (domestic_observed or foreign_observed):
                    raise TradeMirrorError(f"出口 {key} 记录没有观察到任何出口分项")
                domestic = _integer(row["domestic_export_fas_usd"], f"出口 {key} 国产金额",
                                    blank_allowed=not domestic_observed)
                foreign = _integer(row["foreign_reexport_fas_usd"], f"出口 {key} 再出口金额",
                                   blank_allowed=not foreign_observed)
                total = _integer(row["total_export_fas_usd"], f"出口 {key} 总金额")
                if domestic_observed != (domestic is not None):
                    raise TradeMirrorError(f"出口 {key} 国产观察标志与金额空值不一致")
                if foreign_observed != (foreign is not None):
                    raise TradeMirrorError(f"出口 {key} 再出口观察标志与金额空值不一致")
                assert isinstance(total, int)
                expected_total = (domestic or 0) + (foreign or 0)
                if total != expected_total:
                    raise TradeMirrorError(f"出口 {key} 总额不等于已观察分项之和")
                domestic_total += domestic or 0
                foreign_total += foreign or 0
                total_amount += total
                domestic_observed_rows += int(domestic_observed)
                foreign_observed_rows += int(foreign_observed)
        finally:
            stream.close()
        if rows != item.get("processed_rows"):
            raise TradeMirrorError(f"出口 {key} 行数与清单不一致")
        if _sha256(file_path) != expected_sha:
            raise TradeMirrorError(f"出口 {key} 文件在核对期间发生变化")
        audits.append(MonthAudit(
            year, month, str(file_path.relative_to(root)), source_sha, expected_sha,
            str(item["source_url"]), str(item["source_file_name"]), rows, rows,
            {"domestic_export_fas_usd": domestic_total,
             "foreign_reexport_fas_usd": foreign_total,
             "total_export_fas_usd": total_amount,
             "domestic_observed_rows": domestic_observed_rows,
             "foreign_observed_rows": foreign_observed_rows},
        ))
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != hashlib.sha256(raw_manifest).hexdigest():
        raise TradeMirrorError("出口清单在核对过程中发生变化")
    return DatasetAudit(
        "census-us-export-scheduleb10", version, "US", "export",
        "US-SCHEDULE-B-10", "total_export_fas_usd",
        hashlib.sha256(raw_manifest).hexdigest(), tuple(audits),
    )


def iter_import_mysql_rows(
    root: Path, month: MonthAudit, dataset_version: str,
) -> Iterator[tuple[object, ...]]:
    """Yield normalized import rows in the existing table's column order."""
    root = Path(root)
    path = root / month.file
    if _sha256(path) != month.processed_sha256:
        raise TradeMirrorError(f"进口 {month.month_key} 加工文件摘要已变化")
    stream, reader = _csv_reader(path, IMPORT_FIELDS, f"进口 {month.month_key}")
    try:
        for row in reader:
            if row["source_sha256"] != month.source_sha256:
                raise TradeMirrorError(f"进口 {month.month_key} 原包摘要已变化")
            china_observed = _observed(row["china_observed"], f"进口 {month.month_key} 中国观察状态")
            all_observed = _observed(row["all_origin_observed"], f"进口 {month.month_key} 全来源观察状态")
            china_value = _integer(row["china_import_value_consumption_usd"], "进口中国金额")
            all_value = _integer(row["all_origin_import_value_consumption_usd"], "进口全来源金额")
            assert isinstance(china_value, int) and isinstance(all_value, int)
            if ((not china_observed and china_value != 0)
                    or (not all_observed and all_value != 0)):
                raise TradeMirrorError(f"进口 {month.month_key} 未观察金额必须为空或为零占位")
            common = ("census-us-import-hts10", dataset_version, month.year,
                      month.month, "US", "import", "US-HTS10", row["hts10"])
            yield common + ("CHINA", china_value if china_observed else None,
                            china_observed, month.source_sha256)
            yield common + ("ALL_ORIGINS", all_value if all_observed else None,
                            all_observed, month.source_sha256)
    finally:
        stream.close()
    if _sha256(path) != month.processed_sha256:
        raise TradeMirrorError(f"进口 {month.month_key} 文件在读取期间发生变化")


def iter_export_mysql_rows(
    root: Path, month: MonthAudit, dataset_version: str,
) -> Iterator[tuple[object, ...]]:
    """Yield normalized Schedule B rows in the new export table's column order."""
    root = Path(root)
    path = root / month.file
    if _sha256(path) != month.processed_sha256:
        raise TradeMirrorError(f"出口 {month.month_key} 加工文件摘要已变化")
    stream, reader = _csv_reader(path, EXPORT_FIELDS, f"出口 {month.month_key}")
    try:
        for row in reader:
            if row["source_sha256"] != month.source_sha256:
                raise TradeMirrorError(f"出口 {month.month_key} 原包摘要已变化")
            domestic_observed = _observed(row["domestic_observed"], "出口国产观察状态")
            foreign_observed = _observed(row["foreign_observed"], "出口再出口观察状态")
            domestic = _integer(row["domestic_export_fas_usd"], "出口国产金额",
                                blank_allowed=not domestic_observed)
            foreign = _integer(row["foreign_reexport_fas_usd"], "出口再出口金额",
                               blank_allowed=not foreign_observed)
            total = _integer(row["total_export_fas_usd"], "出口总金额")
            assert isinstance(total, int)
            yield (
                "census-us-export-scheduleb10", dataset_version,
                month.year, month.month, row["scheduleb10"], row["partner_code"],
                domestic, foreign, total, domestic_observed, foreign_observed,
                month.source_sha256,
            )
    finally:
        stream.close()
    if _sha256(path) != month.processed_sha256:
        raise TradeMirrorError(f"出口 {month.month_key} 文件在读取期间发生变化")


def audit_trade_mysql_files(root: Path) -> dict[str, object]:
    """Return an offline-only report for both current published snapshots."""
    imports = inspect_import_snapshot(root)
    exports = inspect_export_snapshot(root)
    report: dict[str, object] = {
        "status": "offline_file_audit_passed_not_mysql_verified",
        "database_checked": False,
        "api_calls": 0,
        "datasets": [imports.as_dict(), exports.as_dict()],
    }
    report["audit_sha256"] = _json_digest(report)
    return report
