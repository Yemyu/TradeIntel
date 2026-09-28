"""Freezing the four question materials preserves inputs and scoring offline."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.freeze_trade_model_eval import ROOT, freeze, verify_frozen
from tests.test_trade_model_eval_prepare import _report


class FreezeTradeModelEvalTests(unittest.TestCase):
    def test_freeze_verifies_identical_inputs_and_rubric(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate, frozen = root / "candidate", root / "frozen"
            cases = json.loads((ROOT / "evals/trade_model_v3/scenarios.json").read_text())
            choices = [
                {"status": "needs_product_choice", "catalog_version": "catalog",
                 "candidates": [{"id": case["selected_product_id"], "label": case["id"]}]}
                for case in cases["scenarios"]
            ]
            proposals = [
                {"status": "ready", "flow": case["flow"], "catalog_version": "catalog",
                 "dataset_version": "fixture-version", "start_month": case["start_month"],
                 "end_month": case["end_month"]}
                for case in cases["scenarios"]
            ]
            reports = []
            for case in cases["scenarios"]:
                report = _report()
                product_code = case["selected_product_id"].split(":", 1)[1]
                report["scope"].update(flow=case["flow"], product_code=product_code,
                                       product_label=case["id"],
                                       start_month=case["start_month"], end_month=case["end_month"])
                if case["flow"] == "both":
                    import_report, export_report = dict(report), dict(report)
                    import_report["scope"] = {**report["scope"], "flow": "import"}
                    export_report["scope"] = {**report["scope"], "flow": "export"}
                    report = {"kind": "trade-query-both-v1", "question": case["question"],
                              "import_report": import_report, "export_report": export_report}
                else:
                    report["question"] = case["question"]
                    report["scope"]["flow"] = case["flow"]
                reports.append(report)
            with (patch("scripts.prepare_trade_model_eval.prepare_trade_question",
                        side_effect=[item for pair in zip(choices, proposals) for item in pair]),
                  patch("scripts.prepare_trade_model_eval.generate_trade_report",
                        side_effect=reports)):
                # Use the actual candidate builder through the normal package command surface.
                from scripts.prepare_trade_model_eval import build_candidate
                build_candidate(ROOT, candidate)
            result = freeze(ROOT, candidate, frozen)
            self.assertEqual(result["model_results"], 0)
            self.assertEqual(verify_frozen(ROOT, candidate, frozen)["scenarios"], 4)
            self.assertEqual(json.loads((frozen / "MANIFEST.json").read_text())["api_calls_in_freeze"], 0)
            self.assertTrue((frozen / "SCORING.json").is_file())
            self.assertTrue((frozen / "MODEL_MATRIX.json").is_file())
            with self.assertRaises(FileExistsError):
                freeze(ROOT, candidate, frozen)
            target = frozen / "references/t1.json"
            target.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "摘要不符"):
                verify_frozen(ROOT, candidate, frozen)


if __name__ == "__main__":
    unittest.main()
