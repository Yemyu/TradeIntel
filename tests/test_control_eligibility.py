import csv
import tempfile
import unittest
from pathlib import Path

from scripts.build_control_eligibility import (
    audit_list1_preperiod,
    classify_families,
    scope_matches,
)


class ControlEligibilityTests(unittest.TestCase):
    def test_scope_expansion_uses_official_code_sets_and_heading_ranges(self):
        by_hts8 = {
            "84501100": {("8450110000", "845011")},
            "84502000": {("8450200000", "845020")},
        }
        by_hts10 = {"7616995160": {("7616995160", "761699")}}
        by_source_hs6 = {
            "720610": {("7206100000", "720610")},
            "721650": {("7216500000", "721650")},
            "721651": {("7216510000", "721651")},
        }

        washers, fallbacks, missing = scope_matches(
            {
                "policy_id": "us_201_washers_2018",
                "coverage_level": "HTS8_set",
                "hts_code": "8450.11.00;8450.20.00",
            },
            by_hts8=by_hts8,
            by_hts10=by_hts10,
            by_source_hs6=by_source_hs6,
            canonical_hs6_universe={
                "845011",
                "845020",
                "720610",
                "721650",
                "721651",
            },
        )
        self.assertEqual(
            washers,
            {("8450110000", "845011"), ("8450200000", "845020")},
        )
        self.assertEqual(fallbacks, set())
        self.assertEqual(missing, [])

        steel, fallbacks, missing = scope_matches(
            {
                "policy_id": "us_232_steel_2018",
                "coverage_level": "heading_range",
                "hts_code": "7206.10–7216.50",
            },
            by_hts8=by_hts8,
            by_hts10=by_hts10,
            by_source_hs6=by_source_hs6,
            canonical_hs6_universe={
                "845011",
                "845020",
                "720610",
                "721650",
                "721651",
            },
        )
        self.assertEqual(
            steel,
            {("7206100000", "720610"), ("7216500000", "721650")},
        )
        self.assertEqual(fallbacks, set())
        self.assertEqual(missing, [])

        fallback, fallback_targets, missing = scope_matches(
            {
                "policy_id": "us_301_list3_2018",
                "coverage_level": "HTS8",
                "hts_code": "0810.30.00",
            },
            by_hts8=by_hts8,
            by_hts10=by_hts10,
            by_source_hs6=by_source_hs6,
            canonical_hs6_universe=set(),
        )
        self.assertEqual(fallback, set())
        self.assertEqual(fallback_targets, {"081030"})
        self.assertEqual(missing, [])

    def test_classification_separates_pure_mixed_contaminated_and_inactive(self):
        values = {
            "100001": 100,
            "100002": 100,
            "100003": 100,
            "100004": 100,
            "100005": 100,
            "100006": 100,
        }
        months = {
            hs6: {(2016, month) for month in range(1, 25)} for hs6 in values
        }
        months["100006"] = {(2016, month) for month in range(1, 24)}
        list1 = {"100001": 100, "100002": 50, "100005": 100, "100006": 100}
        policy_hs6 = {
            "us_301_list1_2018": {"100001", "100002", "100005", "100006"},
            "us_301_list2_2018": {"100004", "100005"},
        }

        rows, counts = classify_families(
            china_value_by_hs6=values,
            positive_months_by_hs6=months,
            list1_value_by_hs6=list1,
            policy_hs6=policy_hs6,
            explicit_exclusion_hs6=set(),
            naics3_by_hs6={},
            minimum_positive_months=24,
            selection_window="2016-01_to_2018-05",
        )
        by_hs6 = {row["hs6_2017"]: row for row in rows}
        self.assertEqual(by_hs6["100001"]["primary_role"], "treated_candidate")
        self.assertIn("mixed_list1_pre_value_share", by_hs6["100002"]["exclusion_reasons"])
        self.assertEqual(by_hs6["100003"]["primary_role"], "control_candidate")
        self.assertIn("direct_policy_scope_overlap", by_hs6["100004"]["exclusion_reasons"])
        self.assertIn("concurrent_policy_scope_overlap", by_hs6["100005"]["exclusion_reasons"])
        self.assertIn("insufficient_positive_pre_months", by_hs6["100006"]["exclusion_reasons"])
        self.assertEqual(counts["primary_role_treated_candidate"], 1)
        self.assertEqual(counts["primary_role_control_candidate"], 1)

    def test_mapping_audit_ignores_post_policy_and_other_origins(self):
        fieldnames = [
            "year",
            "month",
            "origin_code",
            "origin_name",
            "hts10",
            "hts8",
            "import_value_consumption_usd",
        ]
        with tempfile.TemporaryDirectory() as directory:
            trade_path = Path(directory) / "trade.csv"
            with trade_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(
                    [
                        {
                            "year": 2018,
                            "month": 5,
                            "origin_code": "5700",
                            "origin_name": "CHINA",
                            "hts10": "8401100010",
                            "hts8": "84011000",
                            "import_value_consumption_usd": 100,
                        },
                        {
                            "year": 2015,
                            "month": 12,
                            "origin_code": "5700",
                            "origin_name": "CHINA",
                            "hts10": "8401100010",
                            "hts8": "84011000",
                            "import_value_consumption_usd": 777,
                        },
                        {
                            "year": 2018,
                            "month": 8,
                            "origin_code": "5700",
                            "origin_name": "CHINA",
                            "hts10": "8401100010",
                            "hts8": "84011000",
                            "import_value_consumption_usd": 999,
                        },
                        {
                            "year": 2018,
                            "month": 5,
                            "origin_code": "1220",
                            "origin_name": "CANADA",
                            "hts10": "8401100010",
                            "hts8": "84011000",
                            "import_value_consumption_usd": 200,
                        },
                    ]
                )
            mapping = {
                2018: {
                    "8401100010": {
                        "historical_validity_status": "valid",
                        "mapping_status": "same_hs6_prefix",
                        "hs6_2017": "840110",
                    }
                }
            }
            audit, values, exceptions = audit_list1_preperiod(
                trade_path,
                mapping,
                pre_start=(2016, 1),
                pre_end=(2018, 5),
                official_list1_hts8={"84011000"},
            )
        self.assertEqual(audit["raw_china_value_usd"], 100)
        self.assertEqual(audit["mapped_china_value_usd"], 100)
        self.assertEqual(values, {"840110": 100})
        self.assertEqual(exceptions, [])

    def test_mapping_audit_writes_auditable_ambiguity_detail(self):
        fieldnames = [
            "year",
            "month",
            "origin_code",
            "origin_name",
            "hts10",
            "hts8",
            "import_value_consumption_usd",
        ]
        with tempfile.TemporaryDirectory() as directory:
            trade_path = Path(directory) / "trade.csv"
            with trade_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(
                    {
                        "year": 2017,
                        "month": 4,
                        "origin_code": "5700",
                        "origin_name": "CHINA",
                        "hts10": "9999999999",
                        "hts8": "99999999",
                        "import_value_consumption_usd": 25,
                    }
                )
            mapping = {
                2017: {
                    "9999999999": {
                        "source_hs6": "999999",
                        "historical_validity_status": "valid",
                        "mapping_status": "wco_partial_or_ambiguous",
                        "hs6_2017": "",
                        "wco_candidate_hs6": "999998|999997",
                        "wco_partial_or_ex": "1",
                    }
                }
            }
            audit, values, exceptions = audit_list1_preperiod(
                trade_path,
                mapping,
                pre_start=(2016, 1),
                pre_end=(2018, 5),
                official_list1_hts8={"99999999"},
            )
        self.assertEqual(audit["ambiguous_value_share"], 1.0)
        self.assertEqual(values, {})
        self.assertEqual(exceptions[0]["pre_china_value_usd"], 25)
        self.assertEqual(
            exceptions[0]["resolution_status"],
            "requires_official_concordance_resolution",
        )


if __name__ == "__main__":
    unittest.main()
