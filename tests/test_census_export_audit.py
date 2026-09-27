from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from tradeintel_ai.census_export_audit import ExportAuditError, audit_export_month


def _record(width: int, fields: list[tuple[int, int, str]]) -> bytes:
    value = bytearray(b" " * width)
    for begin, end, text in fields:
        value[begin:end] = text.encode("ascii").ljust(end - begin, b" ")
    return bytes(value) + b"\r\n"


def _country(code: str, name: str) -> bytes:
    return _record(61, [(0, 4, code), (11, 61, name)])


def _concord(code: str) -> bytes:
    return _record(235, [(0, 10, code)])


def _commodity(df: str, code: str, value: int) -> bytes:
    return _record(373, [(0, 1, df), (1, 11, code), (67, 71, "2026"),
                         (71, 73, "07"), (118, 133, str(value))])


def _detail(df: str, code: str, country: str, value: int, district: str = "01") -> bytes:
    return _record(323, [(0, 1, df), (1, 11, code), (11, 15, country),
                         (15, 17, district), (17, 21, "2026"), (21, 23, "07"),
                         (68, 83, str(value))])


def _archive(path: Path, *, mismatch: bool = False, duplicate: bool = False) -> None:
    details = [_detail("1", "1201900095", "5700", 100),
               _detail("2", "1201900095", "2010", 2),
               _detail("1", "1005902020", "2010", 50)]
    if duplicate:
        details.append(details[0])
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as bundle:
        bundle.writestr("COUNTRY.TXT", _country("5700", "CHINA") + _country("2010", "MEXICO"))
        bundle.writestr("CONCORD.TXT", _concord("1201900095") + _concord("1005902020"))
        bundle.writestr("EXP_DETL.TXT", b"".join(details))
        bundle.writestr("EXP_COMM.TXT", b"".join([
            _commodity("1", "1201900095", 99 if mismatch else 100),
            _commodity("2", "1201900095", 2),
            _commodity("1", "1005902020", 50),
        ]))


class CensusExportAuditTests(unittest.TestCase):
    def test_reconciles_distinct_domestic_foreign_and_china_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "EXDB2607.ZIP"
            _archive(path)
            result = audit_export_month(path, year=2026, month=7)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["all_commodity_reconciliation"]["mismatch_count"], 0)
            self.assertEqual(result["products"]["1201"]["total_usd"], 102)
            self.assertEqual(result["products"]["1201"]["china_destination_usd"], 100)
            self.assertEqual(result["products"]["1005"]["total_usd"], 50)

    def test_mismatch_prevents_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "EXDB2607.ZIP"
            _archive(path, mismatch=True)
            result = audit_export_month(path, year=2026, month=7)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["all_commodity_reconciliation"]["mismatch_count"], 1)

    def test_duplicate_target_detail_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "EXDB2607.ZIP"
            _archive(path, duplicate=True)
            with self.assertRaisesRegex(ExportAuditError, "重复目标商品明细"):
                audit_export_month(path, year=2026, month=7)


if __name__ == "__main__":
    unittest.main()
