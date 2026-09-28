"""Source-reconciled China trade background for a confirmed broad notice.

The Census CHINA country code is kept separate from Hong Kong.  This report is
descriptive trade context, never an estimate of a notice's legal coverage.
"""
from __future__ import annotations

import csv
from copy import deepcopy
import json
from collections import defaultdict
from pathlib import Path
import re
from typing import Any
from zipfile import BadZipFile, ZipFile

from .announcement_linkage import validate_prepared_linkage_scope
from .announcement_store import load_announcement_store
from .trade_classification_catalog import ClassificationCatalog
from .trade_data_repository import TradeDataError, TradeDataRepository, _sha256
from .trade_report_store import NO_EXPLANATION_PROTOCOL, create_record


REPORT_KIND = "announcement-context-report-v1"
_COUNTRY_ROUTE = REPORT_KIND + ":country"


def _member(archive: ZipFile, name: str) -> str:
    found = [item.filename for item in archive.infolist()
             if not item.is_dir() and item.filename.casefold() == name.casefold()]
    if len(found) != 1:
        raise TradeDataError(f"官方月包缺少唯一的 {name}")
    return found[0]


def _china_code(archive: ZipFile) -> str:
    found = []
    with archive.open(_member(archive, "COUNTRY.TXT")) as stream:
        for raw in stream:
            line = raw.decode("latin-1").rstrip("\r\n")
            if not line:
                continue
            if len(line) < 61 or not line[:4].isdigit():
                raise TradeDataError("官方国别对照表无效")
            if line[11:61].strip().upper() == "CHINA":
                found.append(line[:4])
    if len(found) != 1:
        raise TradeDataError("官方国别对照表中无法唯一识别 CHINA")
    return found[0]


def _reconcile_month(root: Path, month: str, entry: dict[str, Any],
                     classes: ClassificationCatalog) -> dict[str, Any]:
    if entry.get("status") != "queryable_aggregate":
        raise TradeDataError(f"{month} 尚无已发布的完整月包")
    year, number = int(month[:4]), int(month[5:])
    manifest = json.loads(
        (root / "data/processed/trade_hts10/manifest.json").read_text(encoding="utf-8"))
    records = [item for item in manifest["months"]
               if item.get("year") == year and item.get("month") == number]
    if len(records) != 1:
        raise TradeDataError("月包登记记录不唯一")
    registered = records[0]
    if (registered.get("status") != "processed"
            or registered.get("raw_archive_retained_after_processing") is not True
            or registered.get("source_sha256") != entry["source_sha256"]
            or registered.get("source_file_name") != entry["source_file_name"]
            or registered.get("monthly_output") != entry["processed_file"]):
        raise TradeDataError("国家背景要求保留并登记原始官方月包")
    raw_path = root / "data/raw/trade-detail" / entry["source_file_name"]
    processed_path = root / entry["processed_file"]
    if not raw_path.is_file() or _sha256(raw_path) != entry["source_sha256"]:
        raise TradeDataError("官方原始月包缺失或摘要不符")
    processed_hash = _sha256(processed_path)
    if processed_hash != entry["processed_sha256"]:
        raise TradeDataError("处理后月份文件摘要不符")
    all_values: dict[str, int] = defaultdict(int)
    china_values: dict[str, int] = defaultdict(int)
    all_counts: dict[str, int] = defaultdict(int)
    china_counts: dict[str, int] = defaultdict(int)
    raw_rows = 0
    try:
        with ZipFile(raw_path) as archive:
            china_code = _china_code(archive)
            with archive.open(_member(archive, "IMP_DETL.TXT")) as stream:
                for raw in stream:
                    raw_rows += 1
                    line = raw.rstrip(b"\r\n")
                    if len(line) != 688:
                        raise TradeDataError("官方明细行宽度无效")
                    code, country = line[:10].decode("ascii"), line[10:14].decode("ascii")
                    date = line[22:28].decode("ascii")
                    value_text = line[73:88].decode("ascii").strip()
                    if (not re.fullmatch(r"\d{10}", code)
                            or not re.fullmatch(r"\d{4}", country)
                            or date != f"{year:04d}{number:02d}"
                            or not value_text.isdigit()):
                        raise TradeDataError("官方明细商品、国家、月份或金额无效")
                    value = int(value_text)
                    all_values[code] += value
                    all_counts[code] += 1
                    if country == china_code:
                        china_values[code] += value
                        china_counts[code] += 1
    except (BadZipFile, OSError, UnicodeError) as exc:
        raise TradeDataError("官方原始月包无法核对") from exc
    if not raw_rows or not all_values:
        raise TradeDataError("官方原始月包没有可核对的贸易明细")
    if _sha256(raw_path) != entry["source_sha256"]:
        raise TradeDataError("核对期间原始月包发生变化")
    items = classes.month("import", month)["items"]
    if set(all_values) - set(items):
        raise TradeDataError("原始明细包含官方商品目录外的编码")
    observed_codes: set[str] = set()
    processed_china = processed_all = processed_rows = 0
    with processed_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        required = {"year", "month", "hts10", "hts8", "source_url",
                    "source_file_name", "source_sha256", "china_observed",
                    "all_origin_observed", "china_detail_row_count",
                    "all_origin_detail_row_count", "china_import_value_consumption_usd",
                    "all_origin_import_value_consumption_usd"}
        if not required.issubset(reader.fieldnames or []):
            raise TradeDataError("已发布月表缺少国家背景核对字段")
        for row in reader:
            code = row["hts10"]
            if (code in observed_codes or code not in all_values
                    or row["hts8"] != code[:8]
                    or row["year"] != str(year)
                    or row["month"] not in {str(number), f"{number:02d}"}
                    or row["source_url"] != entry["source_url"]
                    or row["source_file_name"] != entry["source_file_name"]
                    or row["source_sha256"] != entry["source_sha256"]):
                raise TradeDataError("已发布月表与官方原始明细的身份不一致")
            observed_codes.add(code)
            expected = (china_values[code], all_values[code], china_counts[code],
                        all_counts[code])
            try:
                actual = (int(row["china_import_value_consumption_usd"]),
                          int(row["all_origin_import_value_consumption_usd"]),
                          int(row["china_detail_row_count"]),
                          int(row["all_origin_detail_row_count"]))
            except ValueError as exc:
                raise TradeDataError("已发布月表的金额或行数无效") from exc
            if (actual != expected or row["china_observed"] != str(int(china_counts[code] > 0))
                    or row["all_origin_observed"] != "1"):
                raise TradeDataError("已发布月表与官方原始明细的金额或观察状态不一致")
            processed_china += actual[0]
            processed_all += actual[1]
            processed_rows += 1
    if _sha256(processed_path) != processed_hash:
        raise TradeDataError("核对期间已发布月表发生变化")
    if (observed_codes != set(all_values)
            or raw_rows != registered.get("raw_detail_rows")
            or processed_rows != registered.get("output_rows")
            or processed_rows != registered.get("unique_hts10_count")
            or processed_china != registered.get("raw_china_value_usd")
            or processed_all != registered.get("raw_all_origin_value_usd")):
        raise TradeDataError("国家背景月度总量、商品集合或原始行数不一致")
    return {"month": month, "status": "source_reconciled",
            "china_mainland_import_value_usd": processed_china,
            "all_origin_import_value_usd": processed_all,
            "raw_detail_rows": raw_rows, "hts10_rows": processed_rows,
            "china_hts10_rows": len(china_counts),
            "source_url": entry["source_url"],
            "source_sha256": entry["source_sha256"],
            "processed_sha256": processed_hash,
            "classification_version": classes.version}


def build_country_context_report(root: Path, prepared: dict[str, Any], *,
                                 trade_root: Path | None = None) -> dict[str, Any]:
    if not isinstance(prepared, dict) or prepared.get("route") != _COUNTRY_ROUTE:
        raise ValueError("这里只能生成已确认的中国大陆贸易背景")
    data_root = Path(trade_root or root)
    validate_prepared_linkage_scope(root, prepared, trade_root=data_root)
    catalog = TradeDataRepository(data_root).catalog()
    classes = ClassificationCatalog(data_root)
    if (catalog["dataset_version"] != prepared["dataset_version"]
            or classes.version != prepared["classification_version"]):
        raise TradeDataError("贸易数据或分类目录版本已变化")
    indexed = {row["month"]: row for row in catalog["months"]}
    monthly = [_reconcile_month(data_root, month, indexed[month], classes)
               for month in prepared["months"]]
    validate_prepared_linkage_scope(root, prepared, trade_root=data_root)
    store = load_announcement_store(root, prepared["policy_id"])
    document = next(row for row in store["documents"]
                    if row["doc_version"] == prepared["doc_version"])
    candidate = store["announcement_candidates"][prepared["doc_version"]]["candidate"]
    return {"kind": REPORT_KIND, "context_type": "country",
            "policy": {"policy_id": prepared["policy_id"],
                       "doc_version": prepared["doc_version"],
                       "candidate_digest": prepared["candidate_digest"],
                       "assessment_digest": prepared["assessment_digest"],
                       "policy_population": prepared["policy_population"],
                       "evidence": deepcopy(prepared["evidence"]),
                       "confirmed_fields": deepcopy(candidate["fields"]),
                       "source_url": document.get("url"),
                       "source_provenance": (store.get("announcement_imports") or {}).get(
                           prepared["doc_version"], {}).get("source_provenance", "unknown"),
                       "rate_evidence_scope": "source_document_only",
                       "current_applicability_status": "not_verified"},
            "scope": {"statistical_population": prepared["statistical_population"],
                      "origin_alignment": prepared["origin_alignment"],
                      "unobserved_eligibility": prepared["unobserved_eligibility"],
                      "reporter": "US", "flow": "import", "partner": "CHINA",
                      "hong_kong_included_in_statistics": False,
                      "metric": "import_value_consumption_usd",
                      "start_month": prepared["start_month"],
                      "end_month": prepared["end_month"],
                      "dataset_id": prepared["dataset_id"],
                      "dataset_version": prepared["dataset_version"],
                      "classification_version": prepared["classification_version"],
                      "prepare_digest": prepared["prepare_digest"],
                      "amount_semantics": "china_trade_background_not_policy_coverage"},
            "monthly": monthly, "policy_amount_status": "not_determined",
            "sources": [{"month": row["month"], "url": row["source_url"],
                         "source_sha256": row["source_sha256"],
                         "processed_sha256": row["processed_sha256"]}
                        for row in monthly],
            "notes": ["金额为所选已发布月包的中国大陆来源美国消费进口逐项合计，不是公告适用金额。",
                      "香港未并入中国大陆来源统计；若公告也涉及香港，本图只反映其中大陆背景。",
                      "邮寄、申报、企业资格等法律条件不在月度商品表中，不能由总额推断合格金额。",
                      "原公告税率不代表报告月份或现在实际适用税率。",
                      "本图不是政策效果或官方单列全国总量。"]}


def generate_country_context_record(root: Path, prepared: dict[str, Any], *,
                                    trade_root: Path | None = None) -> dict[str, Any]:
    report = build_country_context_report(root, prepared, trade_root=trade_root)
    return create_record(root, report, explanation_protocol=NO_EXPLANATION_PROTOCOL)


__all__ = ["REPORT_KIND", "build_country_context_report",
           "generate_country_context_record"]
