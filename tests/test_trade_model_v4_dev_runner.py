"""v4 development runner checks with an isolated ledger and no network calls."""
from __future__ import annotations

from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tradeintel_ai.model_adapter import (
    ModelAdapterError, OpenAICompatibleConfig,
    OpenAICompatibleModel as ActualOpenAICompatibleModel,
)
from tradeintel_ai.trade_explanation_v4 import PROTOCOL
from scripts import run_trade_model_v4_dev as runner


def _answer(case_id: str, *, text: str | None = None, finish: str = "stop",
            usage: dict | None = None) -> SimpleNamespace:
    record = json.loads((runner.FROZEN / "cases" / case_id / "record.json").read_text())
    body = {"schema_version": PROTOCOL,
            "report_sha256": record["report_sha256"],
            "relation_snapshot_sha256": record["relation_snapshot_sha256"],
            "interpretations": [{
                "observation_ids": [record["relation_snapshot"]["eligible_card_ids"][0]],
                "text": {
                    "v4-1": "最近的相邻月份先回落后增加，这只说明局部转向，不代表整个期间都在上涨。",
                    "v4-2": "最近几个相邻月份的出口金额连续减少，但这不代表整个查询期间都在下降。",
                    "v4-3": "进口金额最近连续减少；出口先增加后减少，两边的统计口径不同，不能相减。",
                    "v4-4": "近期进口金额由增加转为减少，仅凭金额不能判断是不是政策造成。",
                }[case_id],
            }]}
    return SimpleNamespace(
        text=json.dumps(body, ensure_ascii=False) if text is None else text,
        tool_calls=(),
        metadata={"response_id": "response-test", "model": runner.MODEL,
                  "finish_reason": finish,
                  "usage": usage if usage is not None else
                  {"prompt_tokens": 1000, "completion_tokens": 600,
                   "total_tokens": 1600}},
    )


class TradeModelV4DevRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix="trade-v4-dev-runner-")
        self.addCleanup(temp.cleanup)
        self.local = Path(temp.name) / ".local" / "trade-model-eval-v4" / "deepseek-flash-high"
        self.config = OpenAICompatibleConfig("https://api.deepseek.com", runner.MODEL,
                                             "unit-test-only", 90, 0)
        self.addCleanup(patch.stopall)
        patch.object(runner, "LOCAL", self.local).start()
        patch.object(runner, "_config", return_value=(self.config, "test-config-hash")).start()
        patch.object(runner, "_deadline", return_value=nullcontext()).start()
        self.calls = []

    def _run(self, case_id="v4-1", outcome=None):
        value = outcome if outcome is not None else _answer(case_id)
        calls = self.calls

        class FakeModel:
            def __init__(self, _config, *, system_prompt, request_params):
                assert system_prompt == ""
                assert request_params == runner.PARAMS

            def complete(self, *, messages, tools):
                calls.append(case_id)
                assert tools == []
                assert messages == json.loads((runner.FROZEN / "cases" / case_id /
                                               "messages.json").read_text())
                if isinstance(value, BaseException):
                    raise value
                return value

        with patch.object(runner, "OpenAICompatibleModel", FakeModel):
            return runner.run_one(case_id=case_id, authorized=True,
                                  price_confirmed_date=runner._today())

    def test_offline_check_and_authorization_gate(self):
        with patch.object(runner, "OpenAICompatibleModel") as model:
            result = runner.check()
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["api_calls_this_check"], 0)
            self.assertEqual(result["max_tokens"], 8192)
            model.assert_not_called()
        self.assertFalse(self.local.exists())
        with self.assertRaisesRegex(ValueError, "明确授权"):
            runner.run_one(case_id="v4-1")
        with self.assertRaisesRegex(ValueError, "当天官方价格"):
            runner.run_one(case_id="v4-1", authorized=True,
                           price_confirmed_date="2000-01-01")
        self.assertEqual(self.calls, [])

    def test_valid_answer_is_saved_once_and_needs_review(self):
        result = self._run()
        self.assertEqual(result["status"], "needs_review")
        self.assertTrue(result["contract_pass"])
        self.assertEqual(result["response_id"], "response-test")
        self.assertEqual(result["interpretation_count"], 1)
        self.assertEqual(self.calls, ["v4-1"])
        self.assertTrue((self.local / "v4-1.raw.txt").is_file())
        with self.assertRaisesRegex(ValueError, "不允许重试"):
            self._run()
        with self.assertRaisesRegex(ValueError, "前题尚未"):
            self._run("v4-2")

    def test_review_requires_verifiable_gain_and_unlocks_next(self):
        self._run()
        with self.assertRaisesRegex(ValueError, "具体对照"):
            runner.review("v4-1", reviewer="reader", note="更易读", severe_error=False,
                          factual_fidelity=True, answers_question=True, reading_gain=True)
        reviewed = runner.review("v4-1", reviewer="reader", note="仅复述", severe_error=False,
                                 factual_fidelity=True, answers_question=True, reading_gain=False)
        self.assertEqual(reviewed["status"], "reviewed_clear")
        second = self._run("v4-2", _answer("v4-2"))
        self.assertEqual(second["status"], "needs_review")
        self.assertEqual(self.calls, ["v4-1", "v4-2"])

    def test_reading_gain_quotes_must_exist_in_baseline_and_raw(self):
        self._run()
        with self.assertRaisesRegex(ValueError, "引文未出现"):
            runner.review("v4-1", reviewer="reader", note="可读性判断", severe_error=False,
                          factual_fidelity=True, answers_question=True, reading_gain=True,
                          baseline_quote="不存在的页面原话", model_quote="最近的相邻月份")
        baseline = (runner.FROZEN / "cases/v4-1/baseline.zh-CN.txt").read_text()
        quote = next(line for line in baseline.splitlines() if "最近三个月" in line)
        result = runner.review("v4-1", reviewer="reader", note="开发者认为解释更清楚，仅供复核",
                               severe_error=False, factual_fidelity=True,
                               answers_question=True, reading_gain=True,
                               baseline_quote=quote, model_quote="最近的相邻月份")
        self.assertTrue(result["reading_gain"])

    def test_concurrent_same_case_only_one_provider_call(self):
        with patch.object(runner, "OpenAICompatibleModel") as model:
            model.return_value.complete.return_value = _answer("v4-1")
            def attempt():
                try:
                    return runner.run_one(case_id="v4-1", authorized=True,
                                          price_confirmed_date=runner._today())
                except ValueError as exc:
                    return str(exc)
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _: attempt(), range(4)))
        self.assertEqual(sum(isinstance(item, dict) and item["status"] == "needs_review"
                             for item in results), 1)
        self.assertEqual(model.return_value.complete.call_count, 1)

    def test_real_adapter_envelope_with_in_memory_http_only(self):
        captured = []
        reply = _answer("v4-1")

        class FakeHTTPResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({
                    "id": "response-test", "model": "DeepSeek-V4.1-Flash",
                    "choices": [{"finish_reason": "stop", "message": {
                        "role": "assistant", "content": reply.text}}],
                    "usage": reply.metadata["usage"],
                }).encode("utf-8")

        def fake_opener(request, *, timeout):
            captured.append((request, timeout))
            return FakeHTTPResponse()

        def adapter_factory(config, *, system_prompt, request_params):
            return ActualOpenAICompatibleModel(config, system_prompt=system_prompt,
                                               request_params=request_params,
                                               opener=fake_opener)

        with patch.object(runner, "OpenAICompatibleModel", adapter_factory):
            result = runner.run_one(case_id="v4-1", authorized=True,
                                    price_confirmed_date=runner._today())
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["response_model"], "DeepSeek-V4.1-Flash")
        self.assertEqual(len(captured), 1)
        request, timeout = captured[0]
        self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(timeout, 90)
        body = json.loads(request.data)
        self.assertEqual(body["model"], "deepseek-flash")
        self.assertEqual(body["messages"], json.loads((runner.FROZEN /
                         "cases/v4-1/messages.json").read_text()))
        self.assertEqual(body["thinking"], {"type": "enabled"})
        self.assertEqual(body["reasoning_effort"], "high")
        self.assertEqual(body["max_tokens"], 8192)
        self.assertNotIn("tools", body)
        self.assertNotIn("unit-test-only", json.dumps(result))
        self.assertNotIn("unit-test-only", (self.local / "v4-1.json").read_text())

    def test_empty_content_keeps_metadata_and_stops(self):
        result = self._run(outcome=_answer("v4-1", text="", finish="length"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_category"], "finish_reason_length_empty_content")
        self.assertEqual(result["usage"]["completion_tokens"], 600)
        self.assertEqual(result["response_id"], "response-test")
        with self.assertRaisesRegex(ValueError, "前题尚未"):
            self._run("v4-2")

    def test_incomplete_and_invalid_content_stops(self):
        for answer, reason in ((_answer("v4-1", finish="length"), "finish_reason_not_stop"),
                               (_answer("v4-1", text="not json"), "contract_rejected"),
                               (_answer("v4-1", usage={}), "usage_missing"),
                               (_answer("v4-1", text="x" * 20_001), "output_over_budget")):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as temporary:
                with patch.object(runner, "LOCAL", Path(temporary) / "ledger"):
                    result = self._run(outcome=answer)
                    self.assertEqual(result["status"], "invalid_answer")
                    self.assertEqual(result["error_category"], reason)

    def test_rejection_and_unknown_outcome_do_not_retry(self):
        for error, status in ((ModelAdapterError("bad", details={"http_status": 400}), "failed"),
                              (ModelAdapterError("timeout"), "unknown_outcome"),
                              (TimeoutError("fake timeout"), "unknown_outcome")):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                with patch.object(runner, "LOCAL", Path(temporary) / "ledger"):
                    result = self._run(outcome=error)
                    self.assertEqual(result["status"], status)
                    with self.assertRaisesRegex(ValueError, "不允许重试"):
                        self._run()

    def test_tampered_freeze_blocks_before_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "frozen"
            shutil.copytree(runner.FROZEN, copy)
            target = copy / "cases/v4-1/messages.json"
            target.write_bytes(target.read_bytes() + b" ")
            with patch.object(runner, "OpenAICompatibleModel") as model:
                with self.assertRaisesRegex(ValueError, "摘要不符"):
                    runner.run_one(frozen=copy, authorized=True,
                                   price_confirmed_date=runner._today())
                model.assert_not_called()

    def test_bad_configuration_blocks_before_model(self):
        with patch.object(runner, "_config", side_effect=ValueError("wrong model")):
            with patch.object(runner, "OpenAICompatibleModel") as model:
                with self.assertRaisesRegex(ValueError, "wrong model"):
                    runner.run_one(authorized=True, price_confirmed_date=runner._today())
                model.assert_not_called()

    def test_orphan_raw_file_and_changed_answer_are_rejected(self):
        self.local.mkdir(parents=True)
        (self.local / "v4-1.raw.txt").write_text("orphan")
        with self.assertRaisesRegex(ValueError, "不允许重试"):
            self._run()
        (self.local / "v4-1.raw.txt").unlink()
        self._run()
        (self.local / "v4-1.raw.txt").write_text("altered")
        with self.assertRaisesRegex(ValueError, "摘要不符"):
            runner.review("v4-1", reviewer="reader", note="审阅", severe_error=False,
                          factual_fidelity=True, answers_question=True, reading_gain=False)

    def test_severe_review_blocks_next_case(self):
        self._run()
        runner.review("v4-1", reviewer="reader", note="事实错误", severe_error=True,
                      factual_fidelity=False, answers_question=False, reading_gain=False)
        with self.assertRaisesRegex(ValueError, "前题尚未"):
            self._run("v4-2")

    def test_prior_ledger_identity_must_match_frozen_packet(self):
        self._run()
        runner.review("v4-1", reviewer="reader", note="无阅读增益", severe_error=False,
                      factual_fidelity=True, answers_question=True, reading_gain=False)
        prior = self.local / "v4-1.json"
        body = json.loads(prior.read_text())
        body["manifest_sha256"] = "0" * 64
        prior.write_text(json.dumps(body))
        with self.assertRaisesRegex(ValueError, "冻结材料或模型配置不一致"):
            self._run("v4-2")

    def test_three_zero_gain_reviews_block_fourth_case_and_report_it(self):
        for case_id in runner.IDS[:3]:
            result = self._run(case_id)
            self.assertEqual(result["status"], "needs_review")
            reviewed = runner.review(case_id, reviewer="reader", note="仅重述页面",
                                     severe_error=False, factual_fidelity=True,
                                     answers_question=True, reading_gain=False)
        self.assertFalse(reviewed["next_case_allowed"])
        self.assertIn("剩余题数", reviewed["next_case_block_reason"])
        with self.assertRaisesRegex(ValueError, "剩余题数"):
            self._run("v4-4")
        self.assertEqual(self.calls, list(runner.IDS[:3]))


if __name__ == "__main__":
    unittest.main()
