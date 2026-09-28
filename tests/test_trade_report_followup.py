"""Focused, provider-free checks for the follow-up fact and response contract."""
import copy
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

from tradeintel_ai.trade_explanation import report_sha256
from tradeintel_ai.trade_report_followup import (PROTOCOL, build_catalog, catalog_sha256,
    messages, parse, question_sha256)
from scripts.prepare_trade_followup_dev import DEFAULT_REPORT, QUESTION, prepare
from scripts import run_trade_followup_dev_once as one_shot


class TradeFollowupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads(DEFAULT_REPORT.read_text(encoding="utf-8"))

    def catalog(self, report=None):
        return build_catalog(report or self.report)

    def answer(self, report=None, question=QUESTION):
        report = report or self.report
        catalog = self.catalog(report)
        return catalog, {"schema_version": PROTOCOL, "report_sha256": report_sha256(report),
                         "followup_question_sha256": question_sha256(question),
                         "catalog_sha256": catalog_sha256(catalog), "mode": "observed",
                         "needed_data": [], "points": [{"text": "最近回升不等于一直上涨，此前还有回落。",
                                                      "fact_ids": ["export.change.2026-03", "export.change.2026-07"]}]}

    def test_wheat_canary_exact_facts_and_budget(self):
        catalog, answer = self.answer()
        facts = {fact["id"]: fact["fact"] for fact in catalog["facts"]}
        self.assertIn("减少17,759,081美元", facts["export.change.2026-03"])
        self.assertIn("增加49,597,132美元", facts["export.change.2026-07"])
        self.assertNotIn("export.change.2026-01", facts)
        prompt = messages(self.report, QUESTION, catalog, catalog_sha256(catalog))
        self.assertLess(len(json.dumps(prompt, ensure_ascii=False).encode()), 24_000)
        checked = parse(json.dumps(answer, ensure_ascii=False), self.report, QUESTION,
                        catalog, catalog_sha256(catalog))
        self.assertEqual(checked["status"], "needs_review")

    def test_missing_not_zero_and_cross_year_block(self):
        report = copy.deepcopy(self.report)
        row = next(row for row in report["series"] if row["month"] == "2026-06")
        row["status"], row["value_usd"] = "not_processed", None
        facts = {fact["id"] for fact in self.catalog(report)["facts"]}
        self.assertNotIn("export.month.2026-06", facts)
        self.assertNotIn("export.change.2026-06", facts)
        self.assertNotIn("export.change.2026-07", facts)
        row["value_usd"] = 0
        with self.assertRaisesRegex(ValueError, "未观察金额"):
            self.catalog(report)

    def test_duplicate_or_reordered_month_rejected(self):
        report = copy.deepcopy(self.report)
        report["series"][1]["month"] = report["series"][0]["month"]
        with self.assertRaisesRegex(ValueError, "顺序"):
            self.catalog(report)

    def test_rank_includes_ties(self):
        report = copy.deepcopy(self.report)
        rows = report["series"]
        for row, month, amount in zip(rows[:4],
                                      ("2026-01", "2026-02", "2026-03", "2026-04"),
                                      (10, 20, 30, 25)):
            row.update(month=month, value_usd=amount)
        report["series"] = rows[:4]
        report["scope"].update(start_month="2026-01", end_month="2026-04")
        facts = {fact["id"]: fact["fact"] for fact in self.catalog(report)["facts"]}
        self.assertIn("排第1", facts["export.rank.2026-02"])
        self.assertIn("排第1", facts["export.rank.2026-03"])
        self.assertIn("2026-02、2026-03", facts["export.rank.2026-03"])
        self.assertIn("排第3", facts["export.rank.2026-04"])

    def test_year_peak_gap_is_a_signed_fact_and_prompt_keeps_budget(self):
        report = copy.deepcopy(self.report)
        report["series"] = report["series"][:4]
        for row, month, amount in zip(report["series"],
                                      ("2026-01", "2026-02", "2026-03", "2026-04"),
                                      (10, 30, 20, 25)):
            row.update(month=month, status="observed", value_usd=amount)
        report["scope"].update(start_month="2026-01", end_month="2026-04")
        catalog = self.catalog(report)
        facts = {fact["id"]: fact["fact"] for fact in catalog["facts"]}
        self.assertIn("export.year_peak_gap.2026-04", facts)
        self.assertIn("最高为2026-02的30美元", facts["export.year_peak_gap.2026-04"])
        self.assertIn("低于该峰值5美元", facts["export.year_peak_gap.2026-04"])
        prompt = messages(report, "这个四月比今年最高月份低多少？", catalog,
                          catalog_sha256(catalog))
        payload = json.loads(prompt[-1]["content"])
        peak_ids = [fact["id"] for fact in payload["facts"] if ".year_peak_gap." in fact["id"]]
        self.assertEqual(peak_ids, ["export.year_peak_gap.2026-04"])

    def test_report_catalog_question_and_fact_binding(self):
        catalog, answer = self.answer()
        digest = catalog_sha256(catalog)
        changed = copy.deepcopy(self.report)
        changed["series"][-1]["value_usd"] += 1
        with self.assertRaisesRegex(ValueError, "不匹配"):
            parse(json.dumps(answer), changed, QUESTION, catalog, digest)
        with self.assertRaisesRegex(ValueError, "不匹配"):
            parse(json.dumps(answer), self.report, "换一个问题", catalog, digest)
        answer["points"][0]["fact_ids"] = ["import.change.2026-03"]
        with self.assertRaisesRegex(ValueError, "事实ID"):
            parse(json.dumps(answer), self.report, QUESTION, catalog, digest)
        altered_catalog = copy.deepcopy(catalog)
        altered_catalog["facts"][0]["fact"] = "错误事实"
        with self.assertRaisesRegex(ValueError, "不匹配"):
            messages(self.report, QUESTION, altered_catalog, catalog_sha256(altered_catalog))

    def test_no_extra_keys_duplicate_json_or_new_figures(self):
        catalog, answer = self.answer()
        digest = catalog_sha256(catalog)
        answer["points"][0]["text"] = "最近增加了1美元。"
        with self.assertRaisesRegex(ValueError, "数字"):
            parse(json.dumps(answer, ensure_ascii=False), self.report, QUESTION, catalog, digest)
        answer["points"][0]["text"] = "最近有回升，但并非一直上涨。"
        answer["extra"] = "unexpected"
        with self.assertRaisesRegex(ValueError, "字段"):
            parse(json.dumps(answer), self.report, QUESTION, catalog, digest)
        answer.pop("extra")
        duplicate = json.dumps(answer, ensure_ascii=False).replace('"mode": "observed"',
                    '"mode": "observed", "mode": "observed"')
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse(duplicate, self.report, QUESTION, catalog, digest)

    def test_cannot_infer_requires_allowed_data(self):
        catalog, answer = self.answer()
        digest = catalog_sha256(catalog)
        answer["mode"] = "cannot_infer"
        answer["needed_data"] = ["quantity", "unit_value"]
        answer["points"] = [{"text": "金额变化不能说明买入的数量变化，需要数量和单位价值。",
                             "fact_ids": ["export.basis"]}]
        self.assertEqual(parse(json.dumps(answer, ensure_ascii=False), self.report, QUESTION,
                               catalog, digest)["status"], "needs_review")
        answer["needed_data"] = ["secret"]
        with self.assertRaisesRegex(ValueError, "资料"):
            parse(json.dumps(answer, ensure_ascii=False), self.report, QUESTION, catalog, digest)

    def test_both_directions_keep_separate_metrics_and_within_budget(self):
        imports = copy.deepcopy(self.report)
        imports["scope"].update(flow="import", metric="import_value_consumption_usd",
                                partner="ALL_ORIGINS")
        exports = copy.deepcopy(self.report)
        both = {"kind": "trade-query-both-v1", "question": "电脑进出口有什么变化？",
                "scope": {"flow": "both"}, "import_report": imports,
                "export_report": exports}
        catalog = self.catalog(both)
        facts = {item["id"]: item["fact"] for item in catalog["facts"]}
        self.assertIn("both.balance_limit", facts)
        self.assertIn("进口消费金额", facts["import.basis"])
        self.assertIn("出口FAS金额", facts["export.basis"])
        prompt = messages(both, "两方向都涨了，差额改善了吗？", catalog,
                          catalog_sha256(catalog))
        self.assertLess(len(json.dumps(prompt, ensure_ascii=False).encode()), 24_000)

    def test_offline_package_is_write_once(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "canary"
            manifest = prepare(DEFAULT_REPORT, output)
            self.assertEqual(manifest["provider_calls"], 0)
            self.assertEqual(len(manifest["files"]), 4)
            for name, digest in manifest["files"].items():
                import hashlib
                self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), digest)
            with self.assertRaises(FileExistsError):
                prepare(DEFAULT_REPORT, output)

    def test_network_preflight_accepts_unauthenticated_401(self):
        error = HTTPError("https://api.deepseek.com", 401, "Unauthorized", {}, None)
        with mock.patch.object(one_shot, "urlopen", side_effect=error):
            one_shot._network_preflight("https://api.deepseek.com")

    def test_dns_failure_does_not_reserve_or_call_model(self):
        with tempfile.TemporaryDirectory() as folder:
            with (mock.patch.object(one_shot, "LOCAL", Path(folder)),
                  mock.patch.object(one_shot, "_package", return_value=({}, {}, [], {})),
                  mock.patch.object(one_shot, "_config", return_value=(
                      mock.Mock(base_url="https://api.deepseek.com"), "config-digest")),
                  mock.patch.object(one_shot, "_read_state", return_value=None),
                  mock.patch.object(one_shot, "urlopen", side_effect=URLError(
                      socket.gaierror("name lookup failed"))),
                  mock.patch.object(one_shot, "_atomic") as save,
                  mock.patch.object(one_shot, "OpenAICompatibleModel") as model):
                with self.assertRaisesRegex(ValueError, "dns_error.*未预留调用名额"):
                    one_shot.run_once()
                save.assert_not_called()
                model.assert_not_called()

    def test_existing_attempt_blocks_before_network_preflight(self):
        with tempfile.TemporaryDirectory() as folder:
            with (mock.patch.object(one_shot, "LOCAL", Path(folder)),
                  mock.patch.object(one_shot, "_package", return_value=({}, {}, [], {})),
                  mock.patch.object(one_shot, "_config", return_value=(
                      mock.Mock(base_url="https://api.deepseek.com"), "config-digest")),
                  mock.patch.object(one_shot, "_read_state", return_value={
                      "status": "unknown_outcome"}),
                  mock.patch.object(one_shot, "_network_preflight") as preflight):
                with self.assertRaisesRegex(ValueError, "不允许自动重试"):
                    one_shot.run_once()
                preflight.assert_not_called()

    def test_empty_model_response_retains_safe_usage_and_finish_reason(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            package = root / "package"
            package.mkdir()
            (package / "manifest.json").write_text("{}", encoding="utf-8")
            local = root / "ledger"
            manifest = {"report_sha256": "report", "question": "question",
                        "followup_question_sha256": "question-hash",
                        "catalog_sha256": "catalog"}
            response = mock.Mock(text="", tool_calls=(), metadata={
                "response_id": "chatcmpl-test-id",
                "model": "deepseek-flash", "finish_reason": "length",
                "usage": {"completion_tokens": 2048,
                          "completion_tokens_details": {"reasoning_tokens": 2048}}})
            provider = mock.Mock()
            provider.complete.return_value = response
            with (mock.patch.object(one_shot, "PACKAGE", package),
                  mock.patch.object(one_shot, "LOCAL", local),
                  mock.patch.object(one_shot, "_package", return_value=(
                      manifest, {}, [], {})),
                  mock.patch.object(one_shot, "_config", return_value=(
                      mock.Mock(base_url="https://api.deepseek.com"), "config-digest")),
                  mock.patch.object(one_shot, "_network_preflight"),
                  mock.patch.object(one_shot, "OpenAICompatibleModel", return_value=provider)):
                result = one_shot.run_once()
            self.assertEqual(result["error_category"], "finish_reason_length_empty_content")
            self.assertEqual(result["response_id"], "chatcmpl-test-id")
            self.assertEqual(result["response_model"], "deepseek-flash")
            self.assertEqual(result["finish_reason"], "length")
            self.assertEqual(result["usage"]["completion_tokens"], 2048)
            self.assertEqual(result["tool_calls_count"], 0)
            self.assertFalse((local / "answer.raw.txt").exists())


if __name__ == "__main__":
    unittest.main()
