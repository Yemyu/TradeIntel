"""One-call canary ledger tests use a fake provider and no network."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tradeintel_ai.model_adapter import ModelAdapterError, OpenAICompatibleConfig

from scripts.prepare_trade_v3_canary import ROOT, build
from scripts.run_trade_v3_canary import DeadlineExceeded, check, run_once
from tests.test_trade_v3_canary_prepare import _report


class TradeV3CanaryRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.package = self.folder / "package"
        self.ledger = self.folder / "ledger"
        self.ledger.mkdir()
        choice = {"status": "needs_product_choice", "catalog_version": "catalog",
                  "candidates": [{"id": "export:1201", "label": "大豆"}]}
        proposal = {"status": "ready", "flow": "export", "catalog_version": "catalog",
                    "dataset_version": "fixture-version", "start_month": "2025-08",
                    "end_month": "2026-07"}
        with (patch("scripts.prepare_trade_v3_canary.prepare_trade_question",
                    side_effect=[choice, proposal]),
              patch("scripts.prepare_trade_v3_canary.generate_trade_report",
                    return_value=_report())):
            build(ROOT, self.package)
        self.config = OpenAICompatibleConfig("https://api.deepseek.com", "deepseek-flash",
                                             "fake-unit-test-only", 90, 0)
        self.params = {"thinking": {"type": "enabled"},
                       "reasoning_effort": "high", "max_tokens": 2048}

    def _run(self, outcome: object) -> dict:
        calls = self.calls
        class FakeModel:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

            def complete(self, *, messages, tools):
                self_test = calls
                self_test.append((messages, tools, self.kwargs["request_params"]))
                if isinstance(outcome, BaseException):
                    raise outcome
                return outcome

        with (patch("scripts.run_trade_v3_canary._ledger_root", return_value=self.ledger),
              patch("scripts.run_trade_v3_canary._config",
                    return_value=(self.config, self.params, "config-digest")),
              patch("scripts.run_trade_v3_canary.OpenAICompatibleModel", FakeModel)):
            return run_once(ROOT, self.package)

    def test_dry_check_does_not_call_provider(self) -> None:
        with (patch("scripts.run_trade_v3_canary._ledger_root", return_value=self.ledger),
              patch("scripts.run_trade_v3_canary.product_status",
                    return_value={"provider": "deepseek", "model": "deepseek-flash",
                                  "configured": True}),
              patch("scripts.run_trade_v3_canary._config",
                    return_value=(self.config, self.params, "config-digest")),
              patch("scripts.run_trade_v3_canary.OpenAICompatibleModel") as model):
            state = check(ROOT, self.package)
        self.assertEqual(state["ledger_status"], "not_started")
        self.assertTrue(state["fixed_parameters_match"])
        self.assertEqual(state["api_calls_this_check"], 0)
        model.assert_not_called()

    def test_valid_answer_is_saved_once_and_awaits_review(self) -> None:
        self.calls = []
        prompt = json.loads((self.package / "requests/messages.json").read_text())
        example = json.loads(prompt[-1]["content"])["format_example"]
        outcome = SimpleNamespace(text=json.dumps(example, ensure_ascii=False),
                                  metadata={"model": "deepseek-flash", "usage": {"total_tokens": 91},
                                            "finish_reason": "stop"})
        first = self._run(outcome)
        self.assertEqual(first["status"], "needs_review")
        self.assertEqual(first["api_calls_reserved"], 1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][2]["max_tokens"], 2048)
        self.assertEqual(first["usage"]["total_tokens"], 91)
        self.assertTrue((self.ledger / first["raw_file"]).is_file())
        with self.assertRaisesRegex(ValueError, "不能再次调用"):
            self._run(outcome)
        self.assertEqual(len(self.calls), 1)

    def test_provider_rejection_and_unknown_outcome_are_not_retried(self) -> None:
        for error, expected in (
            (ModelAdapterError("rejected", details={"http_status": 400}), "failed"),
            (ModelAdapterError("timeout"), "unknown_outcome"),
            (DeadlineExceeded("deadline"), "unknown_outcome"),
        ):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as folder:
                self.calls = []
                self.ledger = Path(folder)
                first = self._run(error)
                self.assertEqual(first["status"], expected)
                if isinstance(error, DeadlineExceeded):
                    self.assertEqual(first["error_category"], "total_deadline")
                self.assertEqual(len(self.calls), 1)
                with self.assertRaisesRegex(ValueError, "不能再次调用"):
                    self._run(error)
                self.assertEqual(len(self.calls), 1)

    def test_truncated_finish_reason_cannot_be_a_passing_answer(self) -> None:
        self.calls = []
        prompt = json.loads((self.package / "requests/messages.json").read_text())
        example = json.loads(prompt[-1]["content"])["format_example"]
        outcome = SimpleNamespace(text=json.dumps(example, ensure_ascii=False),
                                  metadata={"model": "deepseek-flash", "usage": {},
                                            "finish_reason": "length"})
        result = self._run(outcome)
        self.assertEqual(result["status"], "invalid_answer")
        self.assertEqual(result["error_category"], "finish_reason_not_stop")
        self.assertTrue((self.ledger / result["raw_file"]).is_file())


if __name__ == "__main__":
    unittest.main()
