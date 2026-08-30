"""Acceptance checks for the policy-contamination evidence layer."""

import csv
import json
import unittest
from collections import Counter

from scripts.build_policy_contamination import (
    CAUSAL_DIR,
    CONTROL_REPORT_JSON,
    EXPOSURE_CSV,
    EXCLUSION_CSV,
    LIST2_NOTICE,
    LIST3_NOTICE,
    SOURCE_MANIFEST,
    extract_list2_codes,
    extract_list3_codes,
)


class CausalPolicySourceTests(unittest.TestCase):
    @unittest.skipUnless(LIST2_NOTICE.exists(), "Official List 2 PDF is not present")
    def test_list2_official_code_count(self) -> None:
        self.assertEqual(len(extract_list2_codes()), 279)

    @unittest.skipUnless(LIST3_NOTICE.exists(), "Official List 3 PDF is not present")
    def test_list3_official_code_count(self) -> None:
        self.assertEqual(len(extract_list3_codes()), 5745)

    def test_exposure_output_has_expected_code_counts_and_dates(self) -> None:
        with EXPOSURE_CSV.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))

        counts = Counter(row["policy_id"] for row in rows)
        self.assertEqual(counts["us_301_list1_2018"], 818)
        self.assertEqual(counts["us_301_list2_2018"], 279)
        self.assertEqual(counts["us_301_list3_2018"], 5745)
        self.assertEqual(len(rows), len({row["exposure_id"] for row in rows}) )

        expected_dates = {
            "us_301_list1_2018": ("2018-06-15", "2018-07-06"),
            "us_301_list2_2018": ("2018-08-16", "2018-08-23"),
            "us_301_list3_2018": ("2018-09-21", "2018-09-24"),
        }
        for policy_id, (announcement, effective) in expected_dates.items():
            policy_rows = [row for row in rows if row["policy_id"] == policy_id]
            self.assertTrue(policy_rows)
            self.assertEqual({row["announcement_date"] for row in policy_rows}, {announcement})
            self.assertEqual({row["effective_date"] for row in policy_rows}, {effective})
            self.assertEqual({row["scope_status"] for row in policy_rows}, {"official_code"})

        rule_rows = [row for row in rows if row["coverage_level"] != "HTS8"]
        self.assertGreaterEqual(len(rule_rows), 5)
        self.assertTrue(
            all(
                row["scope_status"] == "official_scope_rule_requires_hts_history_expansion"
                for row in rule_rows
            )
        )

    def test_exclusion_timeline_is_complete_and_conservative(self) -> None:
        with EXCLUSION_CSV.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 9)
        self.assertEqual(len({row["batch_id"] for row in rows}), 9)
        self.assertEqual({row["effective_date"] for row in rows}, {"2018-07-06"})
        self.assertTrue(all(row["source_url"].startswith("https://ustr.gov/") for row in rows))
        self.assertTrue(all(row["scope_status"] != "fully_parsed" for row in rows))

    def test_manifest_records_mapping_block(self) -> None:
        self.assertTrue(CAUSAL_DIR.exists())
        with SOURCE_MANIFEST.open(encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(
            manifest["status"], "policy_exposure_built_mapping_blocked_source_access"
        )
        self.assertEqual(manifest["census_mapping"]["status"], "blocked_source_access")
        self.assertEqual(manifest["counts"]["list3_hts8"], 5745)

        with CONTROL_REPORT_JSON.open(encoding="utf-8") as handle:
            report = json.load(handle)
        self.assertEqual(report["status"], "blocked_source_access")
        self.assertIn("causal_candidate_panel.csv", report["blocked_outputs"])


if __name__ == "__main__":
    unittest.main()
