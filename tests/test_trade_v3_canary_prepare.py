"""The development canary is an offline, non-runnable package until authorized."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.prepare_trade_v3_canary import ROOT, build, verify


def _report() -> dict:
    months = [(2025, month) for month in range(8, 13)] + [
        (2026, month) for month in range(1, 8)
    ]
    series = [{"month": f"{year}-{month:02d}", "status": "observed",
               "value_usd": 100 + index} for index, (year, month) in enumerate(months)]
    values = [row["value_usd"] for row in series]
    return {
        "kind": "trade-query-v1", "question": "最近美国大豆出口有什么变化？",
        "scope": {"flow": "export", "product_code": "1201", "product_label": "大豆",
                  "partner": "ALL_DESTINATIONS", "metric": "total_export_fas_usd",
                  "dataset_version": "fixture-version", "start_month": "2025-08",
                  "end_month": "2026-07"},
        "series": series,
        "summary": {"complete_window": True, "latest_month": "2026-07",
                    "previous_month": "2026-06", "latest_value_usd": values[-1],
                    "month_change_usd": values[-1] - values[-2],
                    "period_total_usd": sum(values)},
        "sources": [],
    }


class TradeV3CanaryPrepareTests(unittest.TestCase):
    def test_build_verify_and_tamper_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "canary"
            choice = {"status": "needs_product_choice", "catalog_version": "catalog",
                      "candidates": [{"id": "export:1201", "label": "大豆"}]}
            proposal = {"status": "ready", "flow": "export", "catalog_version": "catalog",
                        "dataset_version": "fixture-version", "start_month": "2025-08",
                        "end_month": "2026-07"}
            with (patch("scripts.prepare_trade_v3_canary.prepare_trade_question",
                        side_effect=[choice, proposal]),
                  patch("scripts.prepare_trade_v3_canary.generate_trade_report",
                        return_value=_report())):
                result = build(ROOT, output)
            self.assertEqual(result["api_calls"], 0)
            self.assertEqual(verify(ROOT, output)["status"],
                             "development_only_not_authorized_to_call")
            self.assertEqual(json.loads((output / "MANIFEST.json").read_text())["model_request"]
                             ["max_tokens"], 2048)
            self.assertNotIn("reference.json", str((output / "requests/messages.json").read_text()))
            with self.assertRaises(FileExistsError):
                build(ROOT, output)
            (output / "requests/messages.json").write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "摘要不符"):
                verify(ROOT, output)

    def test_missing_manifest_is_not_a_runnable_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "不能运行"):
                verify(ROOT, Path(temp))


if __name__ == "__main__":
    unittest.main()
