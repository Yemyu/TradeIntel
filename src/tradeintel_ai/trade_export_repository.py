"""Bounded, version-pinned access to published Census Schedule B exports."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .trade_data_repository import TradeDataError, _months_between, _sha256


@dataclass(frozen=True)
class ExportTradeQuery:
    reporter: str
    flow: str
    product_code: str
    start_month: str
    end_month: str
    partner: str
    dataset_version: str

    def validate(self) -> None:
        fields = (self.reporter, self.flow, self.product_code, self.start_month,
                  self.end_month, self.partner, self.dataset_version)
        if not all(isinstance(value, str) for value in fields):
            raise TradeDataError("出口查询字段必须是文本")
        if self.reporter != "US" or self.flow != "export":
            raise TradeDataError("这份数据只适用于美国出口")
        if not re.fullmatch(r"(?:\d{4}|\d{6}|\d{10})", self.product_code):
            raise TradeDataError("出口商品编码必须是 HS4、HS6 或 Schedule B 10 位码")
        if self.partner not in {"ALL_DESTINATIONS", "CHINA"}:
            raise TradeDataError("当前出口查询只开放全部目的地与中国目的地")
        if not re.fullmatch(r"[0-9a-f]{64}", self.dataset_version):
            raise TradeDataError("缺少已发布的出口数据版本")
        _months_between(self.start_month, self.end_month)


class ExportDataRepository:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.manifest = self.root / "data/processed/trade_scheduleb10/manifest.json"

    def catalog(self) -> dict:
        try:
            manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise TradeDataError("出口数据清单缺失或无效") from exc
        if (not isinstance(manifest, dict) or manifest.get("dataset_id") != "census-us-export-scheduleb10"
                or not isinstance(manifest.get("months"), list)):
            raise TradeDataError("出口数据清单结构无效")
        records: dict[str, dict] = {}
        version_parts = []
        for item in manifest["months"]:
            if not isinstance(item, dict) or type(item.get("year")) is not int or type(item.get("month")) is not int:
                raise TradeDataError("出口月份记录无效")
            year, month = item["year"], item["month"]
            if not 1 <= month <= 12:
                raise TradeDataError("出口月份超出范围")
            key = f"{year:04d}-{month:02d}"
            if key in records:
                raise TradeDataError("出口数据清单月份重复")
            rel = item.get("processed_file")
            if (item.get("status") != "processed" or not isinstance(rel, str)
                    or not re.fullmatch(
                        rf"data/processed/trade_scheduleb10/monthly/export_scheduleb10_{year}_{month:02d}_[0-9a-f]{{12}}\.csv", rel
                    )):
                raise TradeDataError("出口加工文件路径或状态无效")
            file = self.root / rel
            if not file.is_file() or _sha256(file) != item.get("processed_sha256"):
                raise TradeDataError(f"{key} 出口加工文件缺失或摘要不符")
            if not re.fullmatch(r"[0-9a-f]{64}", str(item.get("source_sha256", ""))):
                raise TradeDataError("出口原包摘要无效")
            if not re.fullmatch(r"\d{4}", str(item.get("china_destination_code", ""))):
                raise TradeDataError("中国目的地编码未登记")
            records[key] = dict(item, month_key=key, status="queryable_aggregate")
            version_parts.append({"year": year, "month": month,
                                  "source_sha256": item["source_sha256"],
                                  "processed_sha256": item["processed_sha256"]})
        version = hashlib.sha256(json.dumps(version_parts, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
        if manifest.get("dataset_version") != version:
            raise TradeDataError("出口数据版本与清单内容不符")
        return {"dataset_id": manifest["dataset_id"], "dataset_version": version,
                "months": [records[key] for key in sorted(records)]}

    def query(self, request: ExportTradeQuery) -> dict:
        request.validate()
        catalog = self.catalog()
        if request.dataset_version != catalog["dataset_version"]:
            raise TradeDataError("出口数据版本已变化，请重新确认范围")
        indexed = {item["month_key"]: item for item in catalog["months"]}
        result = []
        for month in _months_between(request.start_month, request.end_month):
            entry = indexed.get(month)
            if entry is None:
                result.append({"month": month, "status": "not_processed", "value_usd": None,
                               "classification_year": int(month[:4])})
                continue
            path = self.root / entry["processed_file"]
            if _sha256(path) != entry["processed_sha256"]:
                raise TradeDataError("已发布出口文件与确认版本不一致")
            partner_code = entry["china_destination_code"] if request.partner == "CHINA" else None
            matched = 0
            codes: set[str] = set()
            domestic = foreign = 0
            with path.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                for row in reader:
                    code = row.get("scheduleb10", "")
                    if not code.startswith(request.product_code) or (
                        len(request.product_code) == 10 and code != request.product_code
                    ):
                        continue
                    if partner_code is not None and row.get("partner_code") != partner_code:
                        continue
                    if row.get("source_sha256") != entry["source_sha256"]:
                        raise TradeDataError("出口行与原包摘要不一致")
                    if row.get("year") != month[:4] or row.get("month") != str(int(month[5:])):
                        raise TradeDataError("出口行与登记月份不一致")
                    if row.get("domestic_observed") not in {"0", "1"} or row.get("foreign_observed") not in {"0", "1"}:
                        raise TradeDataError("出口观察状态无效")
                    try:
                        d = int(row["domestic_export_fas_usd"]) if row["domestic_observed"] == "1" else 0
                        f = int(row["foreign_reexport_fas_usd"]) if row["foreign_observed"] == "1" else 0
                        t = int(row["total_export_fas_usd"])
                    except (KeyError, ValueError) as exc:
                        raise TradeDataError("出口金额字段无效") from exc
                    if min(d, f, t) < 0 or d + f != t:
                        raise TradeDataError("出口国产、再出口与总额不一致")
                    matched += 1
                    codes.add(code)
                    domestic += d
                    foreign += f
            if _sha256(path) != entry["processed_sha256"]:
                raise TradeDataError("查询期间出口文件发生变化")
            result.append({"month": month, "status": "observed" if matched else "no_record",
                           "classification_year": int(month[:4]),
                           "value_usd": domestic + foreign if matched else None,
                           "domestic_value_usd": domestic if matched else None,
                           "foreign_reexport_value_usd": foreign if matched else None,
                           "matched_scheduleb10": len(codes), "matched_country_rows": matched,
                           "source_url": entry["source_url"],
                           "source_sha256": entry["source_sha256"]})
        return {"dataset_id": catalog["dataset_id"],
                "dataset_version": catalog["dataset_version"],
                "reporter": "US", "flow": "export", "product_code": request.product_code,
                "partner": request.partner, "metric": "total_export_fas_usd", "months": result}
