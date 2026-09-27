"""The new statistical bridge must not turn data rows into policy effects."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from src.tradeintel_ai.announcement_flow import (
    REQUIRED_FIELDS, confirm_and_enable, load_announcement_store,
    save_announcement_store, submit_candidates,
)
from src.tradeintel_ai.announcement_trade_bridge import inspect_published_import_coverage
from src.tradeintel_ai.trade_data_repository import TradeDataError, TradeDataRepository
from src.tradeintel_ai.web_app import _handle_announcement_import


SOURCE_HASH = "a" * 64
NOTICE = "\n".join((
    "Synthetic official notice for bridge tests",
    "Products of China are covered.",
    "HTS 28046100 and HTS 38180000 are listed.",
))
CSV_FIELDS = (
    "year", "month", "hts10", "hts8",
    "china_import_value_consumption_usd", "all_origin_import_value_consumption_usd",
    "china_observed", "all_origin_observed", "source_sha256",
)


class AnnouncementTradeBridgeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="announcement-trade-bridge-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.policy_id = "policy-bridge"
        imported = _handle_announcement_import(self.root, {
            "policy_id": self.policy_id,
            "source_id": "notice:bridge",
            "url": "https://official.example/bridge",
            "text": NOTICE,
        })
        self.doc_version = imported["doc_version"]
        self._publish_month([
            ("2804610010", "28046100", 100, 1),
            ("2804610020", "28046100", 0, 0),
            ("3818000010", "38180000", 200, 1),
        ])
        self.version = TradeDataRepository(self.root).catalog()["dataset_version"]

    def _publish_month(self, rows):
        directory = self.root / "data/processed/trade_hts10/monthly"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "trade_hts10_2026_07.csv"
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for hts10, hts8, china_value, china_observed in rows:
                writer.writerow({
                    "year": 2026, "month": 7, "hts10": hts10, "hts8": hts8,
                    "china_import_value_consumption_usd": china_value,
                    "all_origin_import_value_consumption_usd": china_value,
                    "china_observed": china_observed, "all_origin_observed": 1,
                    "source_sha256": SOURCE_HASH,
                })
        (directory.parent / "manifest.json").write_text(json.dumps({"months": [{
            "year": 2026, "month": 7, "status": "processed",
            "monthly_output": "data/processed/trade_hts10/monthly/trade_hts10_2026_07.csv",
            "source_sha256": SOURCE_HASH,
            "source_url": "https://www.census.gov/fixture",
        }]}), encoding="utf-8")

    def _enable(self, *, codes=None, origin="China"):
        codes = codes or [
            {"code": "28046100", "precision": "whole_hts8"},
            {"code": "38180000", "precision": "whole_hts8"},
        ]
        store = load_announcement_store(self.root, self.policy_id)
        sections = store["documents"][0]["sections"]

        def evidence(needle):
            section = next(item for item in sections if needle in item["text"])
            return [{"doc_version": self.doc_version, "section_id": section["id"],
                     "quote": needle}]

        fields = []
        for name in REQUIRED_FIELDS:
            if name == "origin":
                fields.append({"field": name, "status": "known", "value": origin,
                               "evidence": evidence("Products of China")})
            elif name == "hts_codes":
                fields.append({"field": name, "status": "known", "value": codes,
                               "evidence": evidence("HTS 28046100 and HTS 38180000")})
            else:
                fields.append({"field": name, "status": "unknown", "value": None,
                               "reason": "合成材料没有经过该字段的人工核验"})
        submitted = submit_candidates(self.root, self.policy_id, self.doc_version, fields)
        confirm_and_enable(self.root, self.policy_id, self.doc_version, fields,
                           confirmed_by="bridge-test",
                           expected_candidate_digest=submitted["candidate_digest"])

    def _inspect(self, **overrides):
        kwargs = {"month": "2026-07", "dataset_version": self.version}
        kwargs.update(overrides)
        return inspect_published_import_coverage(
            self.root, self.policy_id, self.doc_version, **kwargs)

    def test_two_observed_codes_are_statistics_not_policy_amounts(self):
        self._enable()
        result = self._inspect()
        self.assertEqual(result["statistical_status"], "all_selected_observed")
        self.assertEqual(result["observed_codes"], 2)
        self.assertEqual(result["status_counts"]["observed"], 2)
        self.assertEqual(result["policy_amount_status"], "not_determined")
        self.assertNotIn("policy_exposure_usd", result)
        self.assertNotIn("year_over_year", result)
        self.assertEqual([row["observed_import_value_consumption_usd"] for row in result["rows"]],
                         [100, 200])
        self.assertEqual(result["rows"][0]["matched_hts10"], 2)
        self.assertEqual(result["rows"][0]["observed_hts10"], 1)
        self.assertEqual(result["rows"][0]["not_observed_hts10"], 1)
        self.assertEqual(result["subcode_observation_status"],
                         "some_matched_hts10_not_observed")
        self.assertEqual(result["source_sha256"], SOURCE_HASH)
        self.assertRegex(result["processed_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(result["result_sha256"], r"^[0-9a-f]{64}$")

    def test_missing_and_unobserved_are_not_zero(self):
        self._enable(codes=[
            {"code": "28046100", "precision": "whole_hts8"},
            {"code": "72071000", "precision": "whole_hts8"},
        ])
        result = self._inspect()
        self.assertEqual(result["statistical_status"], "partly_observed")
        self.assertEqual(result["rows"][1]["status"], "no_record")
        self.assertIsNone(result["rows"][1]["observed_import_value_consumption_usd"])
        # A line exists, but China's data is not observed.  This is also not
        # interchangeable with an observed monetary zero.
        self._publish_month([("2804610010", "28046100", 0, 0)])
        new_version = TradeDataRepository(self.root).catalog()["dataset_version"]
        result = self._inspect(dataset_version=new_version)
        self.assertEqual(result["rows"][0]["status"], "not_observed")
        self.assertIsNone(result["rows"][0]["observed_import_value_consumption_usd"])
        self._publish_month([("2804610010", "28046100", 0, 1)])
        zero_version = TradeDataRepository(self.root).catalog()["dataset_version"]
        zero_result = self._inspect(dataset_version=zero_version)
        self.assertEqual(zero_result["rows"][0]["status"], "observed")
        self.assertEqual(zero_result["rows"][0]["observed_import_value_consumption_usd"], 0)

    def test_partial_legal_code_is_not_upgraded_by_a_statistical_row(self):
        self._enable(codes=[
            {"code": "28046100", "precision": "partial_ex"},
            {"code": "38180000", "precision": "whole_hts8"},
        ])
        result = self._inspect()
        self.assertEqual(result["selected_codes"], ["38180000"])
        self.assertEqual(result["scope_status"], "contains_partial_policy_codes")
        self.assertEqual(result["partial_policy_entries"][0]["precision"], "partial_ex")
        self.assertEqual(result["policy_amount_status"], "not_determined")
        with self.assertRaisesRegex(ValueError, "whole HTS8"):
            self._inspect(requested_codes=["28046100"])

    def test_other_origin_and_unconfirmed_notice_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "已启用"):
            self._inspect()
        self._enable(origin="Brazil")
        with self.assertRaisesRegex(ValueError, "中国原产地"):
            self._inspect()

    def test_explicit_subset_and_stale_version(self):
        self._enable()
        result = self._inspect(requested_codes=["38180000"])
        self.assertEqual(result["selected_codes"], ["38180000"])
        self.assertEqual(result["unselected_whole_codes"], ["28046100"])
        with self.assertRaisesRegex(ValueError, "唯一子集"):
            self._inspect(requested_codes=["38180000", "38180000"])
        self._publish_month([("3818000010", "38180000", 200, 1)])
        with self.assertRaises(TradeDataError):
            self._inspect()

    def test_tampered_candidate_and_unpublished_month_fail_closed(self):
        self._enable()
        result = self._inspect(month="2026-08")
        self.assertEqual(result["statistical_status"], "none_observed")
        self.assertTrue(all(row["status"] == "not_processed" for row in result["rows"]))
        self.assertIsNone(result["processed_sha256"])
        store = load_announcement_store(self.root, self.policy_id)
        store["announcement_candidates"][self.doc_version]["candidate"]["fields"][0]["value"] = "tampered"
        save_announcement_store(self.root, self.policy_id, store)
        with self.assertRaisesRegex(ValueError, "candidate content changed"):
            self._inspect()


if __name__ == "__main__":
    unittest.main()
