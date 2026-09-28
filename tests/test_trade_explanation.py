"""Question-focused trade explanations stay bound to deterministic evidence."""
import hashlib
import json
import copy
import tempfile
import threading
import unittest
from pathlib import Path

from tradeintel_ai.trade_explanation import PROTOCOL, messages, observation_catalog, parse, report_sha256
from tradeintel_ai.trade_report_store import (claim_call, create_record, finish_parse,
                                               get_state, load_record, mark_error,
                                               review, save_raw)
from tradeintel_ai.trade_query_flow import generate_trade_report, prepare_trade_question
from tests.test_trade_query_flow import fixture as import_fixture


class TradeExplanationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        import_fixture(self.root)
        question = "最近美国大豆进口有什么变化"
        proposal = prepare_trade_question(self.root, question)
        self.report = generate_trade_report(self.root, question, selected_flow="import",
                                            dataset_version=proposal["dataset_version"])
        self.state = create_record(self.root, self.report)
        self.report_id = self.state["report_id"]
        self.digest = self.state["report_sha256"]

    def response(self, report=None, digest=None, *, interpretations=None):
        report = report or self.report
        digest = digest or report_sha256(report)
        if interpretations is None:
            payload = json.loads(messages(report, digest)[1]["content"])
            interpretations = []
            for group in payload["required_by_direction"]:
                ids = group["required_observation_ids"]
                trend = next((item for item in payload["observations"]
                              if item["id"] in ids and item["id"].endswith(".trend")), None)
                if trend and trend["direction"] == "资料不足":
                    text = "近期走势资料不足，无法判断方向，需要等待连续观测。"
                elif trend:
                    text = f"近来的金额走势呈{trend['direction']}，但仅凭金额无法判断具体变化原因。"
                elif any(item.endswith(".period_total") for item in ids):
                    text = "所选期间合计反映贸易金额规模，不能直接说明实际贸易数量或变化原因。"
                else:
                    text = "最新月金额反映所选期间的贸易规模，还需结合数量和价格资料理解。"
                interpretations.append({"observation_ids": ids, "text": text})
        return json.dumps({"schema_version": PROTOCOL, "report_sha256": digest,
                           "interpretations": interpretations}, ensure_ascii=False)

    def test_messages_send_only_question_relevant_facts(self):
        self.assertEqual(self.digest, report_sha256(self.report))
        prompt = messages(self.report, self.digest)
        payload = json.loads(prompt[1]["content"])
        self.assertEqual(payload["required_observation_ids"], ["import.trend"])
        self.assertEqual([item["id"] for item in payload["observations"]], ["import.trend"])
        self.assertNotIn("monthly_rows", prompt[1]["content"])
        self.assertIn(self.report["scope"]["dataset_version"], prompt[1]["content"])
        self.assertEqual(len(observation_catalog(self.report)), 4)
        trend = next(item for item in observation_catalog(self.report) if item["id"] == "import.trend")
        self.assertEqual(trend["direction"], "持平")
        self.assertIn('"required_observation_ids":["import.trend"]', prompt[1]["content"])
        with self.assertRaisesRegex(ValueError, "摘要"):
            messages(self.report, "0" * 64)

    def test_question_selects_latest_period_or_combined_facts(self):
        checks = (
            ("最新一个月美国大豆进口金额是多少", ["import.latest"]),
            ("美国大豆进口累计总额是多少", ["import.period_total"]),
            ("最近美国大豆进口的最新金额和走势有什么变化", ["import.latest", "import.trend"]),
        )
        for question, expected in checks:
            with self.subTest(question=question):
                changed = copy.deepcopy(self.report)
                changed["question"] = question
                payload = json.loads(messages(changed, report_sha256(changed))[1]["content"])
                self.assertEqual(payload["required_observation_ids"], expected)
                parsed = parse(self.response(changed), changed, report_sha256(changed))
                self.assertEqual(parsed["status"], "needs_review")

    def test_trend_direction_is_derived_from_monthly_rows_and_missing_data_stops_run(self):
        for amount, label in ((-7, "减少"), (5, "增加"), (0, "持平")):
            with self.subTest(amount=amount):
                changed = copy.deepcopy(self.report)
                changed["summary"]["month_change_usd"] = amount
                changed["summary"]["latest_value_usd"] = 12 + amount
                changed["summary"]["period_total_usd"] = 144 + amount
                changed["series"][-1]["value_usd"] = 12 + amount
                digest = report_sha256(changed)
                trend = next(item for item in observation_catalog(changed)
                             if item["id"] == "import.trend")
                self.assertEqual(trend["direction"], label)
                def candidate(body):
                    return json.dumps({"schema_version": PROTOCOL, "report_sha256": digest,
                                       "interpretations": [{"observation_ids": ["import.trend"],
                                                            "text": body}]}, ensure_ascii=False)
                with self.assertRaisesRegex(ValueError, "走势解释"):
                    parse(candidate("这项贸易金额的含义还需要结合数量和价格资料继续分析。"),
                          changed, digest)
                good = f"近来的金额走势呈{label}，但仅凭金额无法判断具体变化原因。"
                self.assertEqual(parse(candidate(good), changed, digest)["status"], "needs_review")

        missing_gap = copy.deepcopy(self.report)
        missing_gap["series"][-2]["status"] = "not_processed"
        missing_gap["series"][-2]["value_usd"] = None
        missing_gap["summary"]["month_change_usd"] = None
        gap_trend = next(item for item in observation_catalog(missing_gap)
                         if item["id"] == "import.trend")
        self.assertEqual(gap_trend["direction"], "资料不足")
        self.assertNotIn("连续", gap_trend["fact"])
        with self.assertRaisesRegex(ValueError, "无法判断"):
            parse(json.dumps({"schema_version": PROTOCOL,
                              "report_sha256": report_sha256(missing_gap),
                              "interpretations": [{"observation_ids": ["import.trend"],
                                                   "text": "近期的贸易金额还需要结合价格和数量资料进一步分析。"}]},
                             ensure_ascii=False), missing_gap, report_sha256(missing_gap))

    def test_trend_handles_runs_ties_single_month_and_missing_latest(self):
        rising = copy.deepcopy(self.report)
        for index, row in enumerate(rising["series"]):
            row["value_usd"] = 100 + index
        rise = next(item for item in observation_catalog(rising) if item["id"] == "import.trend")
        self.assertEqual(rise["direction"], "增加")
        self.assertEqual(rise["consecutive_changes"], 11)
        self.assertIn("连续11个月逐月增加", rise["fact"])
        self.assertIn("并列", next(item for item in observation_catalog(self.report)
                                   if item["id"] == "import.trend")["fact"])

        one_step = copy.deepcopy(self.report)
        one_step["series"][-1]["value_usd"] = 13
        step = next(item for item in observation_catalog(one_step) if item["id"] == "import.trend")
        self.assertEqual(step["consecutive_changes"], 1)
        self.assertIn("较2026年6月增加", step["fact"])

        single = copy.deepcopy(self.report)
        single["series"] = [single["series"][-1]]
        single["scope"]["start_month"] = single["scope"]["end_month"]
        single["summary"]["month_change_usd"] = None
        single["summary"]["period_total_usd"] = None
        single["summary"]["complete_window"] = True
        only = next(item for item in observation_catalog(single) if item["id"] == "import.trend")
        self.assertEqual(only["direction"], "资料不足")
        self.assertIn("无法判断最近走势", only["fact"])

        missing_latest = copy.deepcopy(self.report)
        missing_latest["series"][-1]["status"] = "missing"
        missing_latest["series"][-1]["value_usd"] = None
        missing_latest["summary"]["latest_value_usd"] = None
        missing_latest["summary"]["month_change_usd"] = None
        unavailable = next(item for item in observation_catalog(missing_latest)
                           if item["id"] == "import.trend")
        self.assertEqual(unavailable["direction"], "资料不足")
        self.assertIn("没有可用金额", unavailable["fact"])

    def test_parse_rejects_wrong_report_numbers_unknown_or_duplicate_ids(self):
        self.assertEqual(parse(self.response(), self.report, self.digest)["status"], "needs_review")
        for interpretations in (
            [{"observation_ids": ["export.latest"], "text": "最新月金额反映所选期间的贸易规模，还需结合数量和价格资料理解。"}],
            [{"observation_ids": ["import.latest"], "text": "最近增长了百分之五，所以这项金额已经说明政策效果。"}],
            [{"observation_ids": ["import.trend", "import.trend"],
              "text": "近来的金额走势呈持平，但仅凭金额无法判断具体变化原因。"}],
            [{"observation_ids": ["import.trend", "import.latest"],
              "text": "近来的金额走势呈持平，但仅凭金额无法判断具体变化原因。"}],
            [{"observation_ids": [{"id": "import.trend"}],
              "text": "近来的金额走势呈持平，但仅凭金额无法判断具体变化原因。"}],
        ):
            raw = json.dumps({"schema_version": PROTOCOL, "report_sha256": self.digest,
                              "interpretations": interpretations}, ensure_ascii=False)
            with self.subTest(raw=raw[:60]), self.assertRaises(ValueError):
                parse(raw, self.report, self.digest)
        duplicate_json = ('{"schema_version":"' + PROTOCOL + '","schema_version":"duplicate"}')
        with self.assertRaises(ValueError):
            parse(duplicate_json, self.report, self.digest)

    def test_two_directions_require_one_complete_explanation_each(self):
        exported = copy.deepcopy(self.report)
        exported["scope"]["flow"] = "export"
        exported["scope"]["metric"] = "total_export_fas_usd"
        both = {"kind": "trade-query-both-v1", "question": "大豆贸易怎样",
                "scope": {**self.report["scope"], "flow": "both"},
                "import_report": self.report, "export_report": exported,
                "ai_status": "not_run", "notes": ["不能直接相减"]}
        digest = report_sha256(both)
        ids = {item["id"] for item in observation_catalog(both)}
        self.assertIn("import.trend", ids)
        self.assertIn("export.trend", ids)
        one_sided = {"schema_version": PROTOCOL, "report_sha256": digest,
                     "interpretations": [{"observation_ids": ["import.latest", "import.trend"],
                                          "text": "近期进口金额走势呈持平，但金额不能单独说明贸易原因。"}]}
        with self.assertRaisesRegex(ValueError, "覆盖所有指定观察"):
            parse(json.dumps(one_sided, ensure_ascii=False), both, digest)
        complete = self.response(both, digest)
        self.assertEqual(len(parse(complete, both, digest)["interpretations"]), 2)

        changing = copy.deepcopy(both)
        changing["question"] = "大豆进口和出口有什么变化"
        changing_digest = report_sha256(changing)
        payload = json.loads(messages(changing, changing_digest)[1]["content"])
        self.assertEqual(payload["required_observation_ids"], ["import.trend", "export.trend"])
        self.assertEqual(len(parse(self.response(changing, changing_digest),
                                   changing, changing_digest)["interpretations"]), 2)

    def test_claim_raw_parse_and_review_survive_reload(self):
        prompt = messages(self.report, self.digest)
        request_sha = hashlib.sha256(json.dumps(prompt, ensure_ascii=False).encode()).hexdigest()
        claim_call(self.root, self.report_id, self.digest, model="fake-model",
                   config_sha256="a" * 64, request_sha256=request_sha)
        with self.assertRaisesRegex(ValueError, "不会重复调用"):
            claim_call(self.root, self.report_id, self.digest, model="fake-model",
                       config_sha256="a" * 64, request_sha256=request_sha)
        raw = self.response()
        save_raw(self.root, self.report_id, raw, response_model="fake-model", usage={"total_tokens": 50})
        parsed = parse(raw, self.report, self.digest)
        finish_parse(self.root, self.report_id, parsed)
        state = get_state(self.root, self.report_id)
        self.assertEqual(state["explanation"]["status"], "needs_review")
        self.assertNotIn("raw_text", state["explanation"])
        reviewed = review(self.root, self.report_id, {
            "report_sha256": self.digest, "raw_sha256": parsed["raw_sha256"],
            "revision": 0, "reviewer": "tester", "facts_checked": True,
            "decisions": [{"index": 0, "verdict": "accept", "reason": "核对过金额与局限"}]})
        self.assertEqual(reviewed["explanation"]["status"], "reviewed")
        self.assertEqual(len(reviewed["explanation"]["review"]["decisions"]), 1)
        self.assertEqual(load_record(self.root, self.report_id)["explanation"]["raw_text"], raw)
        with self.assertRaisesRegex(ValueError, "已变化"):
            review(self.root, self.report_id, {
                "report_sha256": self.digest, "raw_sha256": parsed["raw_sha256"],
                "revision": 0, "reviewer": "tester", "facts_checked": True,
                "decisions": [{"index": 0, "verdict": "accept", "reason": "旧副本"}]})

    def test_claim_is_one_call_even_with_threads_and_bad_digest(self):
        with self.assertRaisesRegex(ValueError, "摘要"):
            claim_call(self.root, self.report_id, "0" * 64, model="fake",
                       config_sha256="a" * 64, request_sha256="b" * 64)
        outcomes = []
        def worker():
            try:
                claim_call(self.root, self.report_id, self.digest, model="fake",
                           config_sha256="a" * 64, request_sha256="b" * 64)
                outcomes.append("claimed")
            except ValueError:
                outcomes.append("blocked")
        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(outcomes.count("claimed"), 1)
        self.assertEqual(get_state(self.root, self.report_id)["explanation"]["status"],
                         "provider_call_started")

    def test_failure_and_tampered_report_are_not_success(self):
        claim_call(self.root, self.report_id, self.digest, model="fake",
                   config_sha256="a" * 64, request_sha256="b" * 64)
        mark_error(self.root, self.report_id, "unknown_outcome", "timeout",
                   details={"category": "timeout", "secret": "never"})
        state = get_state(self.root, self.report_id)
        self.assertEqual(state["explanation"]["status"], "unknown_outcome")
        self.assertNotIn("secret", state["explanation"]["error_details"])
        with self.assertRaisesRegex(ValueError, "不会重复调用"):
            claim_call(self.root, self.report_id, self.digest, model="fake",
                       config_sha256="a" * 64, request_sha256="b" * 64)
        file = self.root / ".local/trade-reports" / f"{self.report_id}.json"
        record = json.loads(file.read_text())
        record["report"]["summary"]["latest_value_usd"] = 999999
        file.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "摘要"):
            get_state(self.root, self.report_id)


if __name__ == "__main__":
    unittest.main()
