"""The formal runner is checked with a fake provider and isolated ledgers."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tradeintel_ai.model_adapter import ModelAdapterError, OpenAICompatibleConfig
from tradeintel_ai.trade_explanation import messages, report_sha256

from scripts.run_trade_model_eval import ROOT, check, run_one, screen
from tests.test_trade_v3_canary_prepare import _report


class TradeModelEvalRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.report = _report()
        self.digest = report_sha256(self.report)
        self.prompt = messages(self.report, self.digest)
        self.example = json.loads(self.prompt[-1]["content"])["format_example"]
        self.config = OpenAICompatibleConfig("https://api.deepseek.com", "deepseek-flash",
                                             "fake-unit-test-only", 90, 0)
        self.params = {"thinking": {"type": "enabled"},
                       "reasoning_effort": "high", "max_tokens": 2048}
        self.calls: list[str] = []

    def _answer(self, *, finish_reason: str = "stop") -> SimpleNamespace:
        return SimpleNamespace(text=json.dumps(self.example, ensure_ascii=False),
                               metadata={"model": "deepseek-flash",
                                         "finish_reason": finish_reason,
                                         "usage": {"prompt_tokens": 80, "completion_tokens": 60}})

    def _run(self, case_id: str, outcome: object) -> dict:
        (self.folder / "MANIFEST.json").write_bytes(b"{}")
        calls = self.calls
        class FakeModel:
            def __init__(self, *args, **kwargs):
                self.params = kwargs["request_params"]

            def complete(self, *, messages, tools):
                calls.append(case_id)
                assert tools == []
                assert self.params["max_tokens"] == 2048
                if isinstance(outcome, BaseException):
                    raise outcome
                return outcome

        with (patch("scripts.run_trade_model_eval._ledger_root", return_value=self.folder),
              patch("scripts.run_trade_model_eval._verified",
                    return_value={"source_report_sha256_by_scenario": {case_id: self.digest}}),
              patch("scripts.run_trade_model_eval._case_inputs",
                    return_value=(self.prompt, self.report, self.digest)),
              patch("scripts.run_trade_model_eval._config",
                    return_value=(self.config, self.params, "config-digest", "deepseek")),
              patch("scripts.run_trade_model_eval.OpenAICompatibleModel", FakeModel)):
            return run_one(ROOT, self.folder, self.folder, "deepseek-flash-high", case_id)

    def test_one_call_per_question_and_screen_before_next(self) -> None:
        first = self._run("t1", self._answer())
        self.assertEqual(first["status"], "needs_review")
        self.assertEqual(first["contract_pass"], True)
        self.assertEqual(first["usage"]["completion_tokens"], 60)
        self.assertTrue((self.folder / "t1.raw.txt").is_file())
        with self.assertRaisesRegex(ValueError, "已有调用记录"):
            self._run("t1", self._answer())
        with self.assertRaisesRegex(ValueError, "尚未完成"):
            self._run("t2", self._answer())
        with patch("scripts.run_trade_model_eval._ledger_root", return_value=self.folder):
            result = screen(ROOT, "deepseek-flash-high", "t1", outcome="clear",
                            reviewer="unit-test", note="参考事实未见严重错误")
        self.assertTrue(result["next_case_allowed"])
        second = self._run("t2", self._answer())
        self.assertEqual(second["status"], "needs_review")
        self.assertEqual(self.calls, ["t1", "t2"])

    def test_contract_failure_stops_model(self) -> None:
        result = self._run("t1", self._answer(finish_reason="length"))
        self.assertEqual(result["status"], "invalid_answer")
        self.assertEqual(result["error_category"], "finish_reason_not_stop")
        with self.assertRaisesRegex(ValueError, "尚未完成"):
            self._run("t2", self._answer())

    def test_unknown_outcome_and_rejection_never_retry(self) -> None:
        for error, expected in ((ModelAdapterError("timeout"), "unknown_outcome"),
                                (ModelAdapterError("rejected", details={"http_status": 400}), "failed")):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as folder:
                self.folder = Path(folder)
                result = self._run("t1", error)
                self.assertEqual(result["status"], expected)
                with self.assertRaisesRegex(ValueError, "已有调用记录"):
                    self._run("t1", self._answer())
                with self.assertRaisesRegex(ValueError, "尚未完成"):
                    self._run("t2", self._answer())

    def test_tampered_raw_cannot_be_screened(self) -> None:
        self._run("t1", self._answer())
        (self.folder / "t1.raw.txt").write_text("modified", encoding="utf-8")
        with patch("scripts.run_trade_model_eval._ledger_root", return_value=self.folder):
            with self.assertRaisesRegex(ValueError, "原答尚未完成"):
                screen(ROOT, "deepseek-flash-high", "t1", outcome="clear",
                       reviewer="unit-test", note="不应通过")

    def test_preflight_never_calls_model(self) -> None:
        with (patch("scripts.run_trade_model_eval._ledger_root", return_value=self.folder),
              patch("scripts.run_trade_model_eval._verified", return_value={}),
              patch("scripts.run_trade_model_eval._case_inputs",
                    return_value=(self.prompt, self.report, self.digest)),
              patch("scripts.run_trade_model_eval._config",
                    return_value=(self.config, self.params, "config-digest", "deepseek")),
              patch("scripts.run_trade_model_eval.OpenAICompatibleModel") as model):
            result = check(ROOT, self.folder, self.folder, "deepseek-flash-high", "t1")
        self.assertEqual(result["api_calls_this_check"], 0)
        model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
