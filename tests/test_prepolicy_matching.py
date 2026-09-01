import csv
import json
import math
import unittest
from pathlib import Path

from scripts.build_prepolicy_matching import (
    CONTINUOUS_FEATURES,
    compute_balance,
    compute_preperiod_features,
    feature_distance,
    match_nearest_controls,
    sample_sd,
    unique_naics3,
)
from scripts.build_globally_balanced_matching import effective_sample_size


class PrepolicyMatchingTests(unittest.TestCase):
    def test_unique_naics_requires_one_candidate_and_never_guesses(self):
        self.assertEqual(unique_naics3("333"), ("333", ""))
        self.assertEqual(unique_naics3("333|336"), ("", "ambiguous_naics3_candidates"))
        self.assertEqual(unique_naics3(""), ("", "missing_naics3_candidates"))

    def test_features_use_zero_months_and_frozen_formulas(self):
        result = compute_preperiod_features([0, 10, 0], [10, 20, 10])
        self.assertAlmostEqual(result["mean_china_import_value_usd"], 10 / 3)
        self.assertAlmostEqual(result["log_mean_monthly_china_import_value"], math.log1p(10 / 3))
        self.assertAlmostEqual(result["china_share_of_all_origin_imports"], 10 / 40)
        self.assertAlmostEqual(result["pretrend_slope"], 0.0)
        self.assertGreater(result["monthly_volatility"], 0.0)

    def test_matching_is_same_industry_deterministic_and_with_replacement(self):
        def record(hs6, role, value):
            row = {
                "hs6_2017": hs6,
                "primary_role": role,
                "match_eligible": True,
                "naics3": "333",
            }
            row.update({feature: float(value) for feature in CONTINUOUS_FEATURES})
            return row

        records = {
            "100001": record("100001", "treated_candidate", 1),
            "100002": record("100002", "treated_candidate", 1),
            "200001": record("200001", "control_candidate", 0),
            "200002": record("200002", "control_candidate", 2),
            "200003": record("200003", "control_candidate", 3),
        }
        pairs, _treated, _controls = match_nearest_controls(records)
        self.assertEqual(len(pairs), 6)
        self.assertEqual(
            [pair["control_hs6"] for pair in pairs if pair["treated_hs6"] == "100001"],
            ["200001", "200002", "200003"],
        )
        self.assertEqual(
            [pair["control_hs6"] for pair in pairs if pair["treated_hs6"] == "100002"],
            ["200001", "200002", "200003"],
        )
        self.assertTrue(all(pair["edge_weight"] == 1 / 3 for pair in pairs))

    def test_balance_uses_edge_weighted_controls_and_threshold(self):
        def record(hs6, role, value):
            row = {
                "hs6_2017": hs6,
                "primary_role": role,
                "match_eligible": True,
                "naics3": "333",
            }
            row.update({feature: float(value) for feature in CONTINUOUS_FEATURES})
            return row

        records = {
            "100001": record("100001", "treated_candidate", 1),
            "200001": record("200001", "control_candidate", 1),
            "200002": record("200002", "control_candidate", 1),
        }
        pairs = [
            {"treated_hs6": "100001", "control_hs6": "200001", "edge_weight": 0.5},
            {"treated_hs6": "100001", "control_hs6": "200002", "edge_weight": 0.5},
        ]
        balance = compute_balance(records, pairs)
        self.assertTrue(balance["all_features_passed"])
        self.assertEqual(balance["features"][CONTINUOUS_FEATURES[0]]["matched_smd"], 0.0)

    def test_repository_run_is_blocked_before_pretrend_when_balance_fails(self):
        root = Path(__file__).resolve().parents[1]
        report = json.loads(
            (root / "data/processed/causal/matching_balance_report.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report["status"], "blocked_before_pretrend")
        self.assertFalse(report["balance"]["all_features_passed"])
        self.assertTrue(report["coverage"]["passed"])
        self.assertFalse(report["post_policy_activity_used_for_matching"])
        self.assertFalse((root / "data/processed/causal/causal_candidate_panel.csv").exists())
        with (root / "data/processed/causal/matched_control_pairs.csv").open(
            newline="", encoding="utf-8"
        ) as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 852)

    def test_sample_sd_constant_pool_is_zero(self):
        self.assertEqual(sample_sd([5.0, 5.0, 5.0]), 0.0)

    def test_v2_solver_infeasibility_is_recorded_without_a_candidate_panel(self):
        root = Path(__file__).resolve().parents[1]
        report = json.loads(
            (root / "data/processed/causal/matching_balance_report_v2.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report["status"], "blocked_before_pretrend_v2")
        self.assertEqual(report["solver"]["status_code"], 2)
        self.assertFalse(report["solver"]["success"])
        self.assertFalse(report["post_policy_activity_used_for_matching"])
        self.assertIn("causal_candidate_panel_v2.csv", report["blocked_outputs"])
        self.assertFalse((root / "data/processed/causal/causal_candidate_panel_v2.csv").exists())

    def test_v3_minimum_cardinality_is_blocked_before_pretrend(self):
        root = Path(__file__).resolve().parents[1]
        report = json.loads(
            (root / "data/processed/causal/matching_balance_report_v3.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report["status"], "blocked_before_pretrend_v3")
        self.assertEqual(report["solver"]["stage_one"]["status_code"], 2)
        self.assertFalse(report["solver"]["stage_one"]["success"])
        self.assertEqual(report["metrics"]["selected_treated"], 0)
        self.assertFalse(report["gates"]["coverage"])
        self.assertFalse(report["post_policy_activity_used_for_matching"])
        self.assertEqual(report["excluded_treated_count"], 284)
        self.assertIn("causal_candidate_panel_v3.csv", report["blocked_outputs"])
        self.assertFalse((root / "data/processed/causal/causal_candidate_panel_v3.csv").exists())
        with (root / "data/processed/causal/matched_control_pairs_v3.csv").open(
            newline="", encoding="utf-8"
        ) as handle:
            self.assertEqual(list(csv.DictReader(handle)), [])
        design = json.loads(
            (root / "config/causal_control_design.json").read_text(encoding="utf-8")
        )
        self.assertEqual(design["matching_cardinality_experiment"]["status"], "blocked_before_pretrend_v3")

    def test_effective_sample_size_penalises_control_reuse(self):
        self.assertAlmostEqual(effective_sample_size([1.0, 1.0, 1.0]), 3.0)
        self.assertLess(effective_sample_size([1.0, 1.0, 10.0]), 3.0)


if __name__ == "__main__":
    unittest.main()
