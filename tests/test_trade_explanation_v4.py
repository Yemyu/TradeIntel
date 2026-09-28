"""Offline relation-card boundaries; no model provider is contacted."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tradeintel_ai.trade_explanation import report_sha256
from tradeintel_ai.trade_explanation_v4 import (PROTOCOL, build_snapshot, messages,
                                                parse, snapshot_sha256)
from tradeintel_ai.trade_query_flow import generate_trade_report, prepare_trade_question
from tradeintel_ai.trade_report_store import create_record, load_record, public_state
from tests.test_trade_query_flow import fixture


class V4RelationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        fixture(self.root)
        question = "最近美国大豆进口有什么变化"
        proposal = prepare_trade_question(self.root, question)
        self.report = generate_trade_report(self.root, question, selected_flow="import",
                                            dataset_version=proposal["dataset_version"])

    def snapshot(self, report=None):
        report = report or self.report
        return build_snapshot(report, report_sha256(report))

    def set_tail(self, values, *, report=None):
        report = report or self.report
        for row, value in zip(report["series"][-len(values):], values):
            row["value_usd"] = value
        report["summary"]["latest_value_usd"] = report["series"][-1]["value_usd"]
        report["summary"]["month_change_usd"] = values[-1] - values[-2]
        report["summary"]["period_total_usd"] = sum(row["value_usd"] for row in report["series"])

    def test_constant_or_one_change_skips_model(self):
        snapshot = self.snapshot()
        self.assertEqual(snapshot["eligible_card_ids"], [])
        with self.assertRaisesRegex(ValueError, "不调用模型"):
            messages(self.report, snapshot, snapshot_sha256(snapshot))
        self.set_tail([10, 10, 12])
        self.assertEqual(self.snapshot()["eligible_card_ids"], [])

    def test_contiguous_run_and_reversal(self):
        self.set_tail([9, 10, 11, 12])
        snapshot = self.snapshot()
        self.assertIn("import.recent_run", snapshot["eligible_card_ids"])
        run = next(card for card in snapshot["cards"] if card["id"] == "import.recent_run")
        self.assertEqual(run["consecutive_changes"], 3)
        self.assertIn("连续3次", run["fact"])
        self.assertNotIn("整个查询区间一直", run["fact"])
        self.set_tail([10, 9, 11])
        snapshot = self.snapshot()
        self.assertIn("import.recent_turn", snapshot["eligible_card_ids"])
        self.assertNotIn("import.recent_run", snapshot["eligible_card_ids"])

    def test_missing_month_breaks_run_and_year_boundary_blocks_turn(self):
        self.set_tail([9, 10, 11, 12])
        self.report["series"][-3]["status"] = "not_processed"
        self.report["series"][-3]["value_usd"] = None
        snapshot = self.snapshot()
        self.assertNotIn("import.recent_run", snapshot["eligible_card_ids"])
        other = copy.deepcopy(self.report)
        other["series"] = other["series"][-3:]
        for row, month, value in zip(other["series"], ("2025-11", "2025-12", "2026-01"), (10, 9, 11)):
            row.update(month=month, status="observed", value_usd=value)
        other["summary"]["complete_window"] = True
        other["summary"]["period_total_usd"] = 30
        other["scope"].update(start_month="2025-11", end_month="2026-01")
        self.assertNotIn("import.recent_turn", self.snapshot(other)["eligible_card_ids"])
        self.assertNotIn("import.latest_change", {card["id"] for card in self.snapshot(other)["cards"]})

    def test_no_observed_amount_still_saves_readable_report(self):
        for row in self.report["series"]:
            row.update(status="not_processed", value_usd=None)
        self.report["summary"].update(latest_value_usd=None, month_change_usd=None,
                                      period_total_usd=None, complete_window=False)
        saved = create_record(self.root, self.report, explanation_protocol=PROTOCOL)
        self.assertFalse(saved["explanation"]["available"])
        self.assertEqual(saved["explanation"]["observations"], [])
        self.assertEqual(len(load_record(self.root, saved["report_id"])["relation_snapshot"]["unavailable"]), 3)

    def test_zero_and_tied_extremes_are_facts_not_ai_eligibility(self):
        self.set_tail([0, 0, 0])
        snapshot = self.snapshot()
        self.assertFalse(snapshot["eligible_card_ids"])
        high_low = next(card for card in snapshot["cards"] if card["id"] == "import.observed_extremes")
        self.assertIn("最低为0美元", high_low["fact"])
        self.assertIn("2026-05、2026-06、2026-07", high_low["fact"])

    def test_same_year_peak_gap_is_page_fact_not_model_eligibility(self):
        for row in self.report["series"]:
            row["value_usd"] = 1
        self.set_tail([10, 30, 20])
        snapshot = self.snapshot()
        card = next(card for card in snapshot["cards"]
                    if card["id"] == "import.same_year_peak_gap")
        self.assertEqual(card["latest_month"], "2026-07")
        self.assertEqual(card["high_months"], ["2026-06"])
        self.assertEqual(card["gap_usd"], 10)
        self.assertNotIn("import.same_year_peak_gap", snapshot["eligible_card_ids"])

    def test_both_directions_relation_is_not_a_balance(self):
        self.set_tail([10, 11])
        exports = copy.deepcopy(self.report)
        exports["scope"].update(flow="export", metric="total_export_fas_usd",
                                partner="ALL_DESTINATIONS")
        exports["series"][-2]["value_usd"] = 20
        exports["series"][-1]["value_usd"] = 19
        exports["summary"]["month_change_usd"] = -1
        exports["summary"]["period_total_usd"] = sum(row["value_usd"] for row in exports["series"])
        both = {"kind": "trade-query-both-v1", "question": "大豆进出口有什么变化",
                "scope": dict(self.report["scope"], flow="both"),
                "import_report": self.report, "export_report": exports}
        snapshot = self.snapshot(both)
        self.assertIn("both.latest_relation", snapshot["eligible_card_ids"])
        fact = next(card["fact"] for card in snapshot["cards"] if card["id"] == "both.latest_relation")
        self.assertIn("不同向", fact)
        self.assertIn("不相减", fact)

    def test_parse_requires_relation_and_snapshot_identity(self):
        self.set_tail([10, 11, 12])
        snapshot = self.snapshot()
        digest = report_sha256(self.report)
        snap_digest = snapshot_sha256(snapshot)
        self.assertNotIn("format_example", messages(self.report, snapshot, snap_digest)[-1]["content"])
        answer = {"schema_version": PROTOCOL, "report_sha256": digest,
                  "relation_snapshot_sha256": snap_digest,
                  "interpretations": [{"observation_ids": ["import.recent_run"],
                                       "text": "进口金额最近接连增加，但不能据此认定整个期间一直上涨。"}]}
        parsed = parse(json.dumps(answer, ensure_ascii=False), self.report, snapshot, snap_digest)
        self.assertEqual(parsed["status"], "needs_review")
        answer["interpretations"][0]["observation_ids"] = ["import.period_total"]
        with self.assertRaisesRegex(ValueError, "关系卡"):
            parse(json.dumps(answer, ensure_ascii=False), self.report, snapshot, snap_digest)
        answer["interpretations"][0]["observation_ids"] = ["import.recent_run"]
        answer["interpretations"][0]["text"] = "小麦出口在本区间呈增加走势，可见整体贸易持续改善。"
        with self.assertRaisesRegex(ValueError, "全期走势"):
            parse(json.dumps(answer, ensure_ascii=False), self.report, snapshot, snap_digest)
        answer["interpretations"][0]["text"] = "进口金额最近接连增加，但不能据此认定整个期间一直上涨。"
        answer["relation_snapshot_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "不匹配"):
            parse(json.dumps(answer, ensure_ascii=False), self.report, snapshot, snap_digest)

    def test_new_record_pins_cards_and_old_record_defaults_to_v3(self):
        self.set_tail([10, 11, 12])
        new = create_record(self.root, self.report, explanation_protocol=PROTOCOL)
        record = load_record(self.root, new["report_id"])
        self.assertEqual(record["explanation_protocol"], PROTOCOL)
        self.assertTrue(new["explanation"]["available"])
        old = create_record(self.root, self.report)
        self.assertEqual(old["explanation"]["protocol"], "trade-data-explanation-v3")
        # Historical on-disk records had no protocol field at all.
        old_path = self.root / ".local/trade-reports" / f"{old['report_id']}.json"
        old_record = json.loads(old_path.read_text())
        del old_record["explanation_protocol"]
        old_path.write_text(json.dumps(old_record))
        self.assertEqual(load_record(self.root, old["report_id"])["report_sha256"], old["report_sha256"])

    def test_historical_v1_v2_answers_read_without_relabeling_v3_cards(self):
        for legacy in ("trade-data-explanation-v1", "trade-data-explanation-v2"):
            old = create_record(self.root, self.report)
            old_path = self.root / ".local/trade-reports" / f"{old['report_id']}.json"
            record = json.loads(old_path.read_text())
            del record["explanation_protocol"]
            raw = "historical answer"
            raw_digest = hashlib.sha256(raw.encode()).hexdigest()
            record["explanation"].update(status="needs_review", raw_text=raw,
                                         raw_sha256=raw_digest,
                                         parsed={"schema_version": legacy,
                                                 "report_sha256": old["report_sha256"],
                                                 "raw_sha256": raw_digest,
                                                 "interpretations": [{"observation_id": "import.latest",
                                                                      "text": "历史记录"}]})
            old_path.write_text(json.dumps(record))
            state = public_state(load_record(self.root, old["report_id"]))
            self.assertEqual(state["explanation"]["protocol"], legacy)
            self.assertEqual(state["explanation"]["observations"], [])

    def test_changed_relation_snapshot_is_rejected_on_load(self):
        self.set_tail([10, 11, 12])
        saved = create_record(self.root, self.report, explanation_protocol=PROTOCOL)
        path = self.root / ".local/trade-reports" / f"{saved['report_id']}.json"
        record = json.loads(path.read_text())
        record["relation_snapshot"]["cards"][0]["fact"] = "擅自改写的事实"
        record["relation_snapshot_sha256"] = snapshot_sha256(record["relation_snapshot"])
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "关系卡"):
            load_record(self.root, saved["report_id"])


if __name__ == "__main__":
    unittest.main()
