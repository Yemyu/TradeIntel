"""Read-only, fixed-width audit of one Census merchandise-export monthly ZIP.

This module does not publish a queryable release.  It checks the first real
month before an export adapter is allowed to rely on its record layout.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from zipfile import BadZipFile, ZipFile


SOURCE_URL_TEMPLATE = "https://www.census.gov/trade/downloads/{year}/Merch/ex_m/EXDB{yy:02d}{month:02d}.ZIP"
MAX_ARCHIVE_BYTES = 200_000_000
MAX_UNCOMPRESSED_BYTES = 2 * 1024**3
REQUIRED_MEMBERS = {
    "CONCORD.TXT": 235,
    "COUNTRY.TXT": 61,
    "EXP_COMM.TXT": 373,
    "EXP_DETL.TXT": 323,
}
PRODUCTS = {"1201": "大豆", "1005": "玉米"}


class ExportAuditError(ValueError):
    """The archive cannot be interpreted according to the official layout."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _member_names(archive: ZipFile) -> dict[str, str]:
    names: dict[str, str] = {}
    for info in archive.infolist():
        if info.is_dir():
            continue
        base = info.filename.rsplit("/", 1)[-1].upper()
        if base in REQUIRED_MEMBERS:
            if base in names:
                raise ExportAuditError(f"压缩包内重复必需文件：{base}")
            names[base] = info.filename
    missing = sorted(set(REQUIRED_MEMBERS) - set(names))
    if missing:
        raise ExportAuditError(f"压缩包缺少必需文件：{', '.join(missing)}")
    return names


def _rows(archive: ZipFile, member: str, width: int):
    with archive.open(member) as stream:
        for line_number, raw in enumerate(stream, 1):
            row = raw.rstrip(b"\r\n")
            if len(row) != width:
                raise ExportAuditError(
                    f"{member} 第 {line_number} 行长度为 {len(row)}，预期 {width}"
                )
            yield line_number, row


def _digits(row: bytes, begin: int, end: int, field: str, member: str, line_number: int) -> str:
    value = row[begin:end].strip()
    if not value or not value.isdigit():
        raise ExportAuditError(f"{member} 第 {line_number} 行 {field} 不是有效非负整数")
    return value.decode("ascii")


def _df(row: bytes, member: str, line_number: int) -> str:
    value = row[:1].decode("ascii")
    if value not in {"1", "2"}:
        raise ExportAuditError(f"{member} 第 {line_number} 行国产/再出口标记无效")
    return value


def _month(row: bytes, year_slice: tuple[int, int], month_slice: tuple[int, int],
           member: str, line_number: int, expected_year: int, expected_month: int) -> None:
    year = int(_digits(row, *year_slice, "年份", member, line_number))
    month = int(_digits(row, *month_slice, "月份", member, line_number))
    if (year, month) != (expected_year, expected_month):
        raise ExportAuditError(f"{member} 第 {line_number} 行月份与包名不一致")


def audit_export_month(archive_path: Path, *, year: int, month: int) -> dict:
    """Return exact-dollar reconciliation and destination evidence for one month.

    A failed reconciliation is returned as ``status=failed`` (not published).
    Structural failures raise ExportAuditError.  No member is extracted to disk.
    """
    path = Path(archive_path)
    if not 2010 <= year <= 2100 or not 1 <= month <= 12:
        raise ExportAuditError("年份或月份无效")
    expected_name = f"EXDB{year % 100:02d}{month:02d}.ZIP"
    if path.name.upper() != expected_name:
        raise ExportAuditError(f"文件名必须是 {expected_name}")
    size = path.stat().st_size
    if size > MAX_ARCHIVE_BYTES:
        raise ExportAuditError("压缩包超过单月预设上限")
    try:
        archive = ZipFile(path)
    except BadZipFile as exc:
        raise ExportAuditError("不是有效的 ZIP 压缩包") from exc
    with archive:
        expanded = sum(item.file_size for item in archive.infolist() if not item.is_dir())
        if expanded > MAX_UNCOMPRESSED_BYTES:
            raise ExportAuditError("压缩包声明的解压体积超过预设上限")
        members = _member_names(archive)
        countries: dict[str, str] = {}
        for line_number, row in _rows(archive, members["COUNTRY.TXT"], 61):
            code = _digits(row, 0, 4, "国家码", "COUNTRY.TXT", line_number)
            name = row[11:61].decode("ascii").strip()
            if code in countries or not name:
                raise ExportAuditError("COUNTRY.TXT 存在重复代码或空名称")
            countries[code] = name
        china_codes = [code for code, name in countries.items() if name == "CHINA"]
        if len(china_codes) != 1:
            raise ExportAuditError("COUNTRY.TXT 不能唯一识别 CHINA")
        china_code = china_codes[0]

        concord_codes: dict[str, set[str]] = {prefix: set() for prefix in PRODUCTS}
        for line_number, row in _rows(archive, members["CONCORD.TXT"], 235):
            code = _digits(row, 0, 10, "Schedule B 编码", "CONCORD.TXT", line_number)
            if len(code) != 10:
                raise ExportAuditError("CONCORD.TXT 商品编码不是十位")
            for prefix in PRODUCTS:
                if code.startswith(prefix):
                    if code in concord_codes[prefix]:
                        raise ExportAuditError(f"CONCORD.TXT 重复商品编码 {code}")
                    concord_codes[prefix].add(code)

        commodity_totals: dict[tuple[str, str], int] = {}
        comm_rows = 0
        for line_number, row in _rows(archive, members["EXP_COMM.TXT"], 373):
            df = _df(row, "EXP_COMM.TXT", line_number)
            code = _digits(row, 1, 11, "商品编码", "EXP_COMM.TXT", line_number)
            _month(row, (67, 71), (71, 73), "EXP_COMM.TXT", line_number, year, month)
            value = int(_digits(row, 118, 133, "月度出口额", "EXP_COMM.TXT", line_number))
            key = (df, code)
            if len(code) != 10 or key in commodity_totals:
                raise ExportAuditError(f"EXP_COMM.TXT 商品汇总重复或编码无效：{key}")
            commodity_totals[key] = value
            comm_rows += 1

        detail_totals: dict[tuple[str, str], int] = defaultdict(int)
        product_country: dict[tuple[str, str, str], int] = defaultdict(int)
        target_seen: set[tuple[str, str, str, str]] = set()
        target_unknown_codes: set[str] = set()
        detail_rows = zero_rows = 0
        for line_number, row in _rows(archive, members["EXP_DETL.TXT"], 323):
            df = _df(row, "EXP_DETL.TXT", line_number)
            code = _digits(row, 1, 11, "商品编码", "EXP_DETL.TXT", line_number)
            country = _digits(row, 11, 15, "目的国码", "EXP_DETL.TXT", line_number)
            district = _digits(row, 15, 17, "出口地区码", "EXP_DETL.TXT", line_number)
            _month(row, (17, 21), (21, 23), "EXP_DETL.TXT", line_number, year, month)
            value = int(_digits(row, 68, 83, "月度出口额", "EXP_DETL.TXT", line_number))
            if len(code) != 10 or len(country) != 4 or len(district) != 2:
                raise ExportAuditError(f"EXP_DETL.TXT 第 {line_number} 行编码长度无效")
            detail_totals[(df, code)] += value
            detail_rows += 1
            zero_rows += value == 0
            for prefix in PRODUCTS:
                if code.startswith(prefix):
                    key = (df, code, country, district)
                    if key in target_seen:
                        raise ExportAuditError(f"EXP_DETL.TXT 重复目标商品明细：{key}")
                    target_seen.add(key)
                    if code not in concord_codes[prefix]:
                        target_unknown_codes.add(code)
                    product_country[(prefix, df, country)] += value

        mismatch_keys = [key for key in sorted(set(commodity_totals) | set(detail_totals))
                         if commodity_totals.get(key) != detail_totals.get(key)]
        products: dict[str, dict] = {}
        for prefix, label in PRODUCTS.items():
            codes = sorted(concord_codes[prefix])
            by_df = {
                df: {
                    "detail_usd": sum(detail_totals.get((df, code), 0) for code in codes),
                    "commodity_usd": sum(commodity_totals.get((df, code), 0) for code in codes),
                }
                for df in ("1", "2")
            }
            country_amounts = defaultdict(int)
            for (product_prefix, df, country), value in product_country.items():
                if product_prefix == prefix:
                    country_amounts[country] += value
            top = sorted(country_amounts.items(), key=lambda item: (-item[1], item[0]))[:10]
            products[prefix] = {
                "label": label,
                "schedule_b_10_codes": codes,
                "domestic_usd": by_df["1"]["detail_usd"],
                "foreign_reexports_usd": by_df["2"]["detail_usd"],
                "total_usd": by_df["1"]["detail_usd"] + by_df["2"]["detail_usd"],
                "commodity_reference_total_usd": by_df["1"]["commodity_usd"] + by_df["2"]["commodity_usd"],
                "china_destination_code": china_code,
                "china_destination_usd": country_amounts.get(china_code, 0),
                "top_destinations": [
                    {"country_code": code, "country_name": countries.get(code), "value_usd": value}
                    for code, value in top
                ],
                "destination_codes_missing_from_country_file": sorted(
                    code for code in country_amounts if code not in countries
                ),
            }

        status = "passed"
        if mismatch_keys or target_unknown_codes or any(
            not item["schedule_b_10_codes"] or item["destination_codes_missing_from_country_file"]
            for item in products.values()
        ):
            status = "failed"
        return {
            "status": status,
            "year": year,
            "month": month,
            "source_url": SOURCE_URL_TEMPLATE.format(year=year, yy=year % 100, month=month),
            "source_file": expected_name,
            "source_bytes": size,
            "source_sha256": _sha256(path),
            "declared_uncompressed_bytes": expanded,
            "records": {"detail": detail_rows, "commodity": comm_rows, "detail_zero_value": zero_rows},
            "all_commodity_reconciliation": {
                "matched": len(mismatch_keys) == 0,
                "mismatch_count": len(mismatch_keys),
                "first_mismatches": [
                    {"df": df, "schedule_b_10": code,
                     "detail_usd": detail_totals.get((df, code)),
                     "commodity_usd": commodity_totals.get((df, code))}
                    for df, code in mismatch_keys[:20]
                ],
            },
            "target_codes_missing_from_concord": sorted(target_unknown_codes),
            "products": products,
        }
