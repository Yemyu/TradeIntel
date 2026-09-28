from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tradeintel_ai.trade_mysql_loader import (
    MysqlMirrorLoadError, compare_rows, load_month, write_month_script,
)
from src.tradeintel_ai.trade_mysql_mirror import DatasetAudit, MonthAudit, TradeMirrorError


def _dataset(flow: str, manifest_sha: str) -> tuple[DatasetAudit, MonthAudit]:
    csv_rows = 2 if flow == "import" else 1
    sql_rows = 4 if flow == "import" else 1
    month = MonthAudit(
        2026, 7, "fixture.csv", "a" * 64, "b" * 64,
        "https://www.census.gov/fixture", "fixture.zip", csv_rows, sql_rows, {},
    )
    dataset = DatasetAudit(
        "census-us-import-hts10" if flow == "import" else "census-us-export-scheduleb10",
        "c" * 64, "US", flow, "US-HTS10" if flow == "import" else "US-SCHEDULE-B-10",
        "import_value_consumption_usd" if flow == "import" else "total_export_fas_usd",
        manifest_sha, (month,),
    )
    return dataset, month


def _import_rows(dataset: DatasetAudit) -> list[tuple[object, ...]]:
    common = (dataset.dataset_id, dataset.data_version, 2026, 7,
              "US", "import", "US-HTS10")
    return [
        common + ("0101210010", "CHINA", None, False, "a" * 64),
        common + ("0101210010", "ALL_ORIGINS", 12, True, "a" * 64),
        common + ("0101210020", "CHINA", 0, True, "a" * 64),
        common + ("0101210020", "ALL_ORIGINS", 10, True, "a" * 64),
    ]


class TradeMysqlLoaderTests(unittest.TestCase):
    def test_sql_script_preserves_null_and_real_zero_and_commits_last(self):
        dataset, month = _dataset("import", "d" * 64)
        output = io.StringIO()
        written = write_month_script(output, dataset, month, _import_rows(dataset),
                                     release_exists=False, batch_rows=2)
        sql = output.getvalue()
        self.assertEqual(written, 4)
        self.assertIn("NULL,0,", sql)
        self.assertIn(",0,1,", sql)
        self.assertEqual(sql.count("INSERT INTO trade_import_hts10_monthly"), 2)
        self.assertLess(sql.index("INSERT INTO trade_dataset_release"), sql.index("COMMIT;"))
        self.assertEqual(sql.count("COMMIT;"), 1)
        self.assertLess(sql.index("COMMIT;"), sql.index("SELECT 'MIRROR_COMMIT_OK'"))
        self.assertIn("CONVERT(0x" + dataset.dataset_id.encode().hex(), sql)

    def test_generation_failure_never_writes_commit(self):
        dataset, month = _dataset("import", "d" * 64)

        def broken_rows():
            yield _import_rows(dataset)[0]
            raise TradeMirrorError("文件末次摘要变化")

        output = io.StringIO()
        with self.assertRaises(TradeMirrorError):
            write_month_script(output, dataset, month, broken_rows(), release_exists=True)
        self.assertNotIn("COMMIT;", output.getvalue())

    def test_wrong_row_count_never_writes_commit(self):
        dataset, month = _dataset("export", "d" * 64)
        output = io.StringIO()
        with self.assertRaisesRegex(MysqlMirrorLoadError, "生成 0 行"):
            write_month_script(output, dataset, month, (), release_exists=False)
        self.assertNotIn("COMMIT;", output.getvalue())

    def test_readback_compares_null_and_observed_zero(self):
        dataset, _ = _dataset("import", "d" * 64)
        rows = _import_rows(dataset)
        lines = []
        for row in sorted(rows, key=lambda item: (item[7], item[8])):
            lines.append("\t".join("NULL" if value is None else
                                   str(int(value)) if isinstance(value, bool) else
                                   str(value) for value in row))
        self.assertEqual(compare_rows(dataset, rows.copy(), io.StringIO("\n".join(lines) + "\n")), 4)
        bad = "\n".join(lines).replace("\tNULL\t0\t", "\t0\t0\t", 1) + "\n"
        with self.assertRaisesRegex(MysqlMirrorLoadError, "不一致"):
            compare_rows(dataset, rows.copy(), io.StringIO(bad))

    def test_uncertain_write_only_accepts_a_new_verified_readback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = Path("data/processed/trade_hts10/manifest.json")
            (root / relative).parent.mkdir(parents=True)
            content = b"fixture"
            (root / relative).write_bytes(content)
            dataset, month = _dataset("import", hashlib.sha256(content).hexdigest())

            class StubClient:
                def __init__(self):
                    self.calls = 0

                def query(self, _sql):
                    return []

                def run_file(self, _script):
                    self.calls += 1
                    raise MysqlMirrorLoadError("connection dropped")

            client = StubClient()
            with (patch("src.tradeintel_ai.trade_mysql_loader._release_row", return_value=None),
                  patch("src.tradeintel_ai.trade_mysql_loader._month_row", side_effect=[None, ("ok",)]),
                  patch("src.tradeintel_ai.trade_mysql_loader._detail_count", side_effect=[0, 4]),
                  patch("src.tradeintel_ai.trade_mysql_loader.iter_import_mysql_rows",
                        return_value=iter(_import_rows(dataset))),
                  patch("src.tradeintel_ai.trade_mysql_loader.reconcile_month",
                        return_value={"verified_sql_rows": 4, "row_mismatches": 0})):
                result = load_month(client, root, dataset, month, apply=True)
            self.assertEqual(client.calls, 1)
            self.assertEqual(result["action"], "matched_after_unknown_outcome")

    def test_existing_month_mismatch_stops_without_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = Path("data/processed/trade_hts10/manifest.json")
            (root / relative).parent.mkdir(parents=True)
            content = b"fixture"
            (root / relative).write_bytes(content)
            dataset, month = _dataset("import", hashlib.sha256(content).hexdigest())

            class StubClient:
                def query(self, _sql):
                    return []

                def run_file(self, _script):
                    raise AssertionError("must not write")

            with (patch("src.tradeintel_ai.trade_mysql_loader._release_row", return_value=("ok",)),
                  patch("src.tradeintel_ai.trade_mysql_loader._month_row", return_value=("ok",)),
                  patch("src.tradeintel_ai.trade_mysql_loader._detail_count", return_value=4),
                  patch("src.tradeintel_ai.trade_mysql_loader.reconcile_month",
                        side_effect=MysqlMirrorLoadError("逐行不一致"))):
                with self.assertRaisesRegex(MysqlMirrorLoadError, "逐行不一致"):
                    load_month(StubClient(), root, dataset, month, apply=True)


if __name__ == "__main__":
    unittest.main()
