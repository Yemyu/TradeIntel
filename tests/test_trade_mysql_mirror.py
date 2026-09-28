from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.tradeintel_ai.trade_mysql_mirror import (
    TradeMirrorError,
    _json_digest,
    audit_trade_mysql_files,
    inspect_export_snapshot,
    inspect_import_snapshot,
    iter_export_mysql_rows,
    iter_import_mysql_rows,
)


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
IMPORT_SHA = "a" * 64
EXPORT_SHA = "b" * 64
COUNTRY_SHA = "c" * 64


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, object]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _import_fixture(root: Path, *, duplicate: bool = False, bad_observed: bool = False) -> None:
    relative = "data/processed/trade_hts10/monthly/trade_hts10_2026_07.csv"
    rows = [
        {"year": 2026, "month": 7, "hts10": "0101210010", "hts8": "01012100",
         "china_import_value_consumption_usd": 0,
         "all_origin_import_value_consumption_usd": 12,
         "china_observed": 0 if not bad_observed else 1, "all_origin_observed": 1,
         "china_detail_row_count": 0, "all_origin_detail_row_count": 5,
         "source_url": "https://www.census.gov/fixture/IMDB2607.ZIP",
         "source_file_name": "IMDB2607.ZIP", "source_sha256": IMPORT_SHA},
        {"year": 2026, "month": 7, "hts10": "0101210020", "hts8": "01012100",
         "china_import_value_consumption_usd": 0,
         "all_origin_import_value_consumption_usd": 10,
         "china_observed": 1, "all_origin_observed": 1,
         "china_detail_row_count": 1, "all_origin_detail_row_count": 6,
         "source_url": "https://www.census.gov/fixture/IMDB2607.ZIP",
         "source_file_name": "IMDB2607.ZIP", "source_sha256": IMPORT_SHA},
    ]
    if duplicate:
        rows[1]["hts10"] = rows[0]["hts10"]
    _write_csv(root / relative, IMPORT_FIELDS, rows)
    item = {
        "year": 2026, "month": 7, "status": "processed",
        "monthly_output": relative, "source_sha256": IMPORT_SHA,
        "source_url": "https://www.census.gov/fixture/IMDB2607.ZIP",
        "source_file_name": "IMDB2607.ZIP", "output_rows": 2,
        "unique_hts10_count": 2, "raw_all_origin_value_usd": 22,
        "raw_china_value_usd": 0, "raw_detail_rows": 11,
    }
    (root / "data/processed/trade_hts10/manifest.json").write_text(
        json.dumps({"status": "fixture", "months": [item]}, sort_keys=True), encoding="utf-8")


def _export_fixture(root: Path, *, bad_total: bool = False) -> None:
    relative = ("data/processed/trade_scheduleb10/monthly/"
                "export_scheduleb10_2026_07_bbbbbbbbbbbb.csv")
    rows = [
        {"year": 2026, "month": 7, "scheduleb10": "0101210000", "partner_code": "5700",
         "domestic_export_fas_usd": 100, "foreign_reexport_fas_usd": "",
         "total_export_fas_usd": 100 if not bad_total else 101,
         "domestic_observed": 1, "foreign_observed": 0, "source_sha256": EXPORT_SHA},
        {"year": 2026, "month": 7, "scheduleb10": "0101210000", "partner_code": "2010",
         "domestic_export_fas_usd": 0, "foreign_reexport_fas_usd": 3,
         "total_export_fas_usd": 3, "domestic_observed": 1,
         "foreign_observed": 1, "source_sha256": EXPORT_SHA},
    ]
    file_sha = _write_csv(root / relative, EXPORT_FIELDS, rows)
    item = {
        "year": 2026, "month": 7, "status": "processed", "source_sha256": EXPORT_SHA,
        "processed_sha256": file_sha, "processed_file": relative,
        "processed_rows": 2, "source_url": "https://www.census.gov/fixture/EXDB2607.ZIP",
        "source_file_name": "EXDB2607.ZIP", "commodity_reconciliation_mismatch_count": 0,
        "country_file_sha256": COUNTRY_SHA, "china_destination_code": "5700",
    }
    version = _json_digest([{"year": 2026, "month": 7,
                             "source_sha256": EXPORT_SHA, "processed_sha256": file_sha}])
    (root / "data/processed/trade_scheduleb10/manifest.json").write_text(
        json.dumps({"dataset_id": "census-us-export-scheduleb10",
                    "dataset_version": version, "months": [item]},
                   sort_keys=True), encoding="utf-8")


class TradeMysqlMirrorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        _import_fixture(self.root)
        _export_fixture(self.root)

    def test_audits_current_file_shapes_and_keeps_versions_separate(self):
        report = audit_trade_mysql_files(self.root)
        self.assertEqual(report["status"], "offline_file_audit_passed_not_mysql_verified")
        self.assertFalse(report["database_checked"])
        imports, exports = report["datasets"]
        self.assertEqual(imports["month_count"], 1)
        self.assertEqual(imports["csv_rows"], 2)
        self.assertEqual(imports["sql_rows"], 4)
        self.assertEqual(len(imports["data_version"]), 64)
        self.assertEqual(exports["month_count"], 1)
        self.assertEqual(exports["csv_rows"], 2)
        self.assertEqual(exports["sql_rows"], 2)
        self.assertNotEqual(imports["data_version"], exports["data_version"])

    def test_import_normalizes_unobserved_zero_to_null_but_preserves_true_zero(self):
        audit = inspect_import_snapshot(self.root)
        rows = list(iter_import_mysql_rows(self.root, audit.months[0], audit.data_version))
        self.assertEqual(rows[0][8:11], ("CHINA", None, False))
        self.assertEqual(rows[1][8:11], ("ALL_ORIGINS", 12, True))
        self.assertEqual(rows[2][8:11], ("CHINA", 0, True))

    def test_export_preserves_missing_component_and_checks_totals(self):
        audit = inspect_export_snapshot(self.root)
        rows = list(iter_export_mysql_rows(self.root, audit.months[0], audit.data_version))
        self.assertEqual(rows[0][6:11], (100, None, 100, True, False))
        self.assertEqual(rows[1][6:11], (0, 3, 3, True, True))

    def test_duplicate_import_code_is_rejected(self):
        _import_fixture(self.root, duplicate=True)
        with self.assertRaisesRegex(TradeMirrorError, "HTS10 重复"):
            inspect_import_snapshot(self.root)

    def test_import_observed_flag_must_match_detail_count(self):
        _import_fixture(self.root, bad_observed=True)
        with self.assertRaisesRegex(TradeMirrorError, "观察标志与明细行数不一致"):
            inspect_import_snapshot(self.root)

    def test_export_total_must_equal_observed_components(self):
        _export_fixture(self.root, bad_total=True)
        with self.assertRaisesRegex(TradeMirrorError, "总额不等于"):
            inspect_export_snapshot(self.root)

    def test_modified_file_after_manifest_generation_is_rejected(self):
        path = self.root / "data/processed/trade_hts10/monthly/trade_hts10_2026_07.csv"
        contents = path.read_text(encoding="utf-8")
        path.write_text(contents.replace(",12,", ",13,", 1), encoding="utf-8")
        with self.assertRaisesRegex(TradeMirrorError, "金额合计与原始清单不一致"):
            inspect_import_snapshot(self.root)

    def test_file_change_after_audit_is_rejected_before_row_mapping(self):
        audit = inspect_import_snapshot(self.root)
        path = self.root / audit.months[0].file
        path.write_text(path.read_text(encoding="utf-8").replace(",12,", ",13,", 1),
                        encoding="utf-8")
        with self.assertRaisesRegex(TradeMirrorError, "加工文件摘要已变化"):
            next(iter_import_mysql_rows(self.root, audit.months[0], audit.data_version))


if __name__ == "__main__":
    unittest.main()
