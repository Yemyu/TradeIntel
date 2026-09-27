"""Publish a verified, all-commodity Census export month as a local snapshot."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile

from .census_export_audit import (
    ExportAuditError,
    _df,
    _digits,
    _member_names,
    _month,
    _rows,
    audit_export_month,
)


FIELDS = (
    "year", "month", "scheduleb10", "partner_code", "domestic_export_fas_usd",
    "foreign_reexport_fas_usd", "total_export_fas_usd", "domestic_observed",
    "foreign_observed", "source_sha256",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def publish_export_month(root: Path, archive_path: Path, *, year: int, month: int) -> dict:
    """Publish only if the ZIP passes full commodity reconciliation.

    The generated CSV has a separate provenance-bearing filename.  Re-running
    against the same ZIP is idempotent; a revised ZIP never silently overwrites
    the old month's CSV.
    """
    root = Path(root)
    archive_path = Path(archive_path)
    audit = audit_export_month(archive_path, year=year, month=month)
    if audit["status"] != "passed":
        raise ExportAuditError("出口明细与商品汇总未通过对账，不得发布")
    source_sha = audit["source_sha256"]
    by_partner: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    seen: set[tuple[str, str, str, str]] = set()
    with ZipFile(archive_path) as archive:
        members = _member_names(archive)
        member = members["EXP_DETL.TXT"]
        country_sha = hashlib.sha256(archive.read(members["COUNTRY.TXT"])).hexdigest()
        for line_number, row in _rows(archive, member, 323):
            df = _df(row, member, line_number)
            code = _digits(row, 1, 11, "商品编码", member, line_number)
            country = _digits(row, 11, 15, "目的国码", member, line_number)
            district = _digits(row, 15, 17, "出口地区码", member, line_number)
            _month(row, (17, 21), (21, 23), member, line_number, year, month)
            value = int(_digits(row, 68, 83, "月度出口额", member, line_number))
            key = (df, code, country, district)
            if key in seen:
                raise ExportAuditError(f"出口明细原始键重复：{key}")
            seen.add(key)
            item = by_partner[(code, country)]
            offset = 0 if df == "1" else 1
            item[offset] += value
            item[2 + offset] = 1

    out_dir = root / "data/processed/trade_scheduleb10/monthly"
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / f"export_scheduleb10_{year}_{month:02d}_{source_sha[:12]}.csv"
    handle = tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8",
                                         prefix=".export-", suffix=".csv.tmp",
                                         dir=out_dir, delete=False)
    temp = Path(handle.name)
    try:
        with handle:
            writer = csv.writer(handle)
            writer.writerow(FIELDS)
            for (code, country), (domestic, foreign, dom_seen, foreign_seen) in sorted(by_partner.items()):
                writer.writerow((year, month, code, country,
                                 domestic if dom_seen else "", foreign if foreign_seen else "",
                                 domestic + foreign, dom_seen, foreign_seen, source_sha))
        generated_sha = _sha256(temp)
        if final.exists():
            if _sha256(final) != generated_sha:
                raise ExportAuditError("同源出口快照已存在但内容不同，拒绝覆盖")
        else:
            os.replace(temp, final)
    finally:
        temp.unlink(missing_ok=True)

    processed_sha = _sha256(final)
    record = {
        "year": year, "month": month, "status": "processed",
        "source_url": audit["source_url"], "source_file_name": audit["source_file"],
        "source_sha256": source_sha, "source_archive_bytes": audit["source_bytes"],
        "country_file_sha256": country_sha,
        "china_destination_code": audit["products"]["1201"]["china_destination_code"],
        "source_detail_rows": audit["records"]["detail"],
        "source_commodity_rows": audit["records"]["commodity"],
        "raw_detail_zero_value_rows": audit["records"]["detail_zero_value"],
        "processed_rows": len(by_partner),
        "processed_file": str(final.relative_to(root)),
        "processed_sha256": processed_sha,
        "commodity_reconciliation_mismatch_count": 0,
    }
    base = root / "data/processed/trade_scheduleb10"
    manifest_path = base / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("dataset_id") != "census-us-export-scheduleb10" or not isinstance(manifest.get("months"), list):
            raise ExportAuditError("现有出口清单结构与预期不符，拒绝覆盖")
        months = [item for item in manifest["months"]
                  if (item.get("year"), item.get("month")) != (year, month)]
        months.append(record)
    else:
        months = [record]
    months.sort(key=lambda item: (item["year"], item["month"]))
    version_parts = [{"year": item["year"], "month": item["month"],
                      "source_sha256": item["source_sha256"],
                      "processed_sha256": item["processed_sha256"]} for item in months]
    version = hashlib.sha256(json.dumps(version_parts, sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest()
    manifest = {
        "dataset_id": "census-us-export-scheduleb10",
        "dataset_version": version,
        "reporter": "US", "flow": "export",
        "classification": "US-SCHEDULE-B-10",
        "metric": "total_export_fas_usd",
        "note": "total = domestic(df=1) + foreign re-exports(df=2); values are monthly, not year-to-date",
        "months": months,
    }
    base.mkdir(parents=True, exist_ok=True)
    temp_manifest = base / ".manifest.json.tmp"
    temp_manifest.write_bytes(_json_bytes(manifest))
    os.replace(temp_manifest, manifest_path)
    return {"dataset_version": version, "record": record, "audit": audit}
