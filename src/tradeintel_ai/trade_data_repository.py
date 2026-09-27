"""Bounded access to published US import snapshots and their raw-source inventory.

This is a data layer, not a model tool.  A raw ZIP is discoverable but is never
silently promoted to a queryable month.  The existing policy-case repository
keeps its separate, frozen interpretation.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


class TradeDataError(ValueError):
    """Invalid request or a published snapshot that no longer matches its catalog."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _months_between(start: str, end: str) -> list[str]:
    if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", start) or not re.fullmatch(
        r"20\d{2}-(0[1-9]|1[0-2])", end
    ):
        raise TradeDataError("月份必须使用 YYYY-MM")
    a, b = (int(start[:4]) * 12 + int(start[5:]) - 1,
            int(end[:4]) * 12 + int(end[5:]) - 1)
    if b < a or b - a >= 24:
        raise TradeDataError("月份范围无效，单次最多查询24个月")
    return [_month_key(n // 12, n % 12 + 1) for n in range(a, b + 1)]


@dataclass(frozen=True)
class TradeQuery:
    reporter: str
    flow: str
    product_code: str
    start_month: str
    end_month: str
    partner: str
    dataset_version: str

    def validate(self) -> None:
        if not all(isinstance(value, str) for value in
                   (self.reporter, self.flow, self.product_code, self.start_month,
                    self.end_month, self.partner, self.dataset_version)):
            raise TradeDataError("贸易查询字段必须是文本")
        if self.reporter != "US" or self.flow != "import":
            raise TradeDataError("目前只接入美国进口，出口不能使用进口数据替代")
        if not re.fullmatch(r"(?:\d{4}|\d{6}|\d{8}|\d{10})", self.product_code):
            raise TradeDataError("商品编码必须是 HS4、HS6、HTS8 或 HTS10")
        if self.partner not in {"ALL_ORIGINS", "CHINA"}:
            raise TradeDataError("现有已整理文件只支持全部来源与中国，其他来源须处理原始明细")
        if not re.fullmatch(r"[0-9a-f]{64}", self.dataset_version):
            raise TradeDataError("缺少已登记的数据版本")
        _months_between(self.start_month, self.end_month)


class TradeDataRepository:
    """Read only, exact-code, version-pinned CSV access for the current release."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.manifest = self.root / "data/processed/trade_hts10/manifest.json"
        self.raw_dir = self.root / "data/raw/trade-detail"

    def catalog(self) -> dict[str, object]:
        try:
            manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise TradeDataError("HTS10 数据清单缺失或无效") from exc
        if not isinstance(manifest, dict) or not isinstance(manifest.get("months"), list):
            raise TradeDataError("HTS10 数据清单结构无效")
        records: dict[str, dict[str, object]] = {}
        for item in manifest["months"]:
            if not isinstance(item, dict):
                raise TradeDataError("HTS10 月份记录无效")
            year, month = item.get("year"), item.get("month")
            if type(year) is not int or type(month) is not int or not 1 <= month <= 12:
                raise TradeDataError("HTS10 月份无效")
            key = _month_key(year, month)
            if key in records:
                raise TradeDataError("HTS10 数据清单月份重复")
            name = f"IMDB{year % 100:02d}{month:02d}.ZIP"
            archive = self.raw_dir / name
            rel = item.get("monthly_output")
            processed = isinstance(rel, str) and re.fullmatch(
                rf"data/processed/trade_hts10/monthly/trade_hts10_{year}_{month:02d}\.csv", rel
            ) is not None
            file = self.root / rel if processed else None
            file_hash = (_sha256(file) if item.get("status") == "processed"
                         and re.fullmatch(r"[0-9a-f]{64}", str(item.get("source_sha256", "")))
                         and file is not None and file.is_file() else None)
            records[key] = {
                "month": key, "reporter": "US", "flow": "import",
                "classification": "US-HTS10", "classification_year": year,
                "partner_grain": "ALL_ORIGINS_OR_CHINA_AGGREGATE" if file_hash else "RAW_DETAIL",
                "metric": "import_value_consumption_usd",
                "source_url": item.get("source_url"),
                "source_file_name": name,
                "source_sha256": item.get("source_sha256"),
                "raw_archive": str(archive.relative_to(self.root)) if archive.is_file() else None,
                "processed_file": rel if file_hash else None,
                "processed_sha256": file_hash,
                "status": "queryable_aggregate" if file_hash else
                          ("raw_only" if archive.is_file() else "unavailable"),
            }
        # A downloaded archive absent from the processed manifest is still
        # discoverable; it is not published or assumed to have been audited.
        if self.raw_dir.is_dir():
            for archive in self.raw_dir.glob("IMDB????.ZIP"):
                match = re.fullmatch(r"IMDB(\d{2})(0[1-9]|1[0-2])\.ZIP", archive.name)
                if not match:
                    continue
                year, month = 2000 + int(match[1]), int(match[2])
                key = _month_key(year, month)
                if key in records:
                    continue
                records[key] = {
                    "month": key, "reporter": "US", "flow": "import",
                    "classification": "US-HTS10", "classification_year": year,
                    "partner_grain": "RAW_DETAIL", "metric": "import_value_consumption_usd",
                    "source_url": None, "source_file_name": archive.name,
                    "source_sha256": None,
                    "raw_archive": str(archive.relative_to(self.root)),
                    "processed_file": None, "processed_sha256": None,
                    "status": "raw_only",
                }
        ordered = [records[key] for key in sorted(records)]
        published = [{key: row[key] for key in ("month", "source_sha256", "processed_sha256")}
                     for row in ordered if row["status"] == "queryable_aggregate"]
        version = hashlib.sha256(json.dumps(published, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
        return {"dataset_id": "census-us-import-hts10", "dataset_version": version,
                "months": ordered}

    def query(self, request: TradeQuery) -> dict[str, object]:
        request.validate()
        catalog = self.catalog()
        if request.dataset_version != catalog["dataset_version"]:
            raise TradeDataError("数据版本已变化，请重新确认查询范围")
        indexed = {item["month"]: item for item in catalog["months"]}
        result = []
        for month in _months_between(request.start_month, request.end_month):
            entry = indexed.get(month)
            if entry is None or entry["status"] != "queryable_aggregate":
                result.append({"month": month, "status": "not_processed",
                               "raw_available": bool(entry and entry["raw_archive"]),
                               "classification_year": int(month[:4]),
                               "value_usd": None})
                continue
            path = self.root / entry["processed_file"]
            if _sha256(path) != entry["processed_sha256"]:
                raise TradeDataError("已发布文件与确认的数据版本不一致")
            prefix = request.product_code
            value_field = ("china_import_value_consumption_usd" if request.partner == "CHINA"
                           else "all_origin_import_value_consumption_usd")
            observed_field = ("china_observed" if request.partner == "CHINA"
                              else "all_origin_observed")
            matches = observed = total = 0
            seen_codes: set[str] = set()
            with path.open(newline="", encoding="utf-8") as stream:
                for row in csv.DictReader(stream):
                    hts10 = row.get("hts10", "")
                    if hts10 != prefix and not (len(prefix) in {4, 6, 8} and hts10.startswith(prefix)):
                        continue
                    if hts10 in seen_codes:
                        raise TradeDataError("已发布文件包含重复商品编码")
                    seen_codes.add(hts10)
                    try:
                        row_month = f"{int(row.get('year', 0)):04d}-{int(row.get('month', 0)):02d}"
                    except ValueError as exc:
                        raise TradeDataError("已发布文件月份无效") from exc
                    if row_month != month:
                        raise TradeDataError("已发布文件月份与登记月份不一致")
                    if row.get("source_sha256") != entry["source_sha256"]:
                        raise TradeDataError("商品行与登记的原包摘要不一致")
                    matches += 1
                    if row.get(observed_field) not in {"0", "1"}:
                        raise TradeDataError("观察状态无效")
                    if row[observed_field] == "1":
                        observed += 1
                        try:
                            value = int(row[value_field])
                        except (ValueError, KeyError) as exc:
                            raise TradeDataError("进口金额无效") from exc
                        if value < 0:
                            raise TradeDataError("进口金额不能为负")
                        total += value
            if _sha256(path) != entry["processed_sha256"]:
                raise TradeDataError("查询过程中已发布文件发生变化")
            status = "observed" if observed else ("not_observed" if matches else "no_record")
            result.append({"month": month, "status": status,
                           "classification_year": entry["classification_year"],
                           "value_usd": total if observed else None,
                           "matched_hts10": matches, "observed_hts10": observed,
                           "source_url": entry["source_url"],
                           "source_sha256": entry["source_sha256"]})
        return {"dataset_id": catalog["dataset_id"],
                "dataset_version": catalog["dataset_version"],
                "reporter": request.reporter, "flow": request.flow,
                "product_code": request.product_code, "partner": request.partner,
                "metric": "import_value_consumption_usd", "months": result}
