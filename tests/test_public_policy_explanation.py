"""Offline prototype tests, not evidence of model quality."""
import copy
import json
from pathlib import Path
import unittest

from src.tradeintel_ai import public_policy_explanation as policy
from src.tradeintel_ai.public_brief_explanation import parse as parse_v1
from src.tradeintel_ai.session_brief import build_temporal_session_brief
from tests.test_public_explanation_flow import _request, VERSION


class PolicyPrototypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.brief = build_temporal_session_brief(Path(__file__).resolve().parents[1],
                                                _request(), data_version=VERSION)
        cls.report = cls.brief["report"]
        cls.context = cls.brief["policy_context"]
        cls.question = "这项关税调整改了什么？"

    def setUp(self):
        self.messages = policy.messages(self.question, self.report, policy_context=self.context)
        payload = json.loads(self.messages[1]["content"])
        self.answer = {"schema_version": policy.PROTOCOL,
            "binding_sha256": payload["binding_sha256"],
            "policy_explanations": [
                {"topic": "change", "source_ids": ["p2"], "text": "该公告列示相关商品的附加关税安排，不能将附加税理解为全部税负。"},
                {"topic": "applicability", "source_ids": ["p1", "p2"], "text": "原产地、商品限定和消费入境条件均需核对，不能仅凭商品名称判定。"},
                {"topic": "limits", "source_ids": ["p1"], "text": "这是存档事件，不代表现行完整税则，例外尚未核全。"}],
            "interpretations": [{"observation_id": "o1", "kind": "meaning", "text": "这是贸易金额观察，不代表政策造成的损失。"}],
            "watchlist": []}

    def parse(self):
        return policy.parse(json.dumps(self.answer, ensure_ascii=False), self.report,
                            question=self.question, policy_context=self.context)

    def test_source_bound_policy_and_trade_sections_are_separate(self):
        result = self.parse()
        self.assertEqual(result["status"], "manual_review_required")
        self.assertEqual(len(result["policy_explanations"]), 3)
        self.assertEqual(result["policy_explanations"][0]["source_ids"], [self.context["sources"][1]["id"]])
        self.assertNotEqual(result["interpretations"][0]["observation_id"], "o1")

    def test_policy_sources_are_rejected_as_trade_observations_in_v1(self):
        legacy = {k: self.answer[k] for k in ("interpretations", "watchlist")}
        legacy["schema_version"] = "public-brief-explanation-v1"
        legacy["interpretations"][0]["observation_id"] = "p1"
        with self.assertRaises(ValueError):
            parse_v1(json.dumps(legacy), self.report)

    def test_bad_refs_are_controlled_errors(self):
        for ids in ([], ["p999"], ["o1"], ["p1", "p1"], [{}], [True], "p1"):
            with self.subTest(ids=ids):
                self.answer["policy_explanations"][0]["source_ids"] = ids
                with self.assertRaises(ValueError): self.parse()

    def test_missing_policy_topic_is_rejected(self):
        self.answer["policy_explanations"].pop()
        with self.assertRaises(ValueError): self.parse()

    def test_duplicate_and_malformed_topics_are_rejected(self):
        for topic in ("change", {}, None):
            self.answer["policy_explanations"][1]["topic"] = topic
            with self.assertRaises(ValueError): self.parse()

    def test_changed_question_breaks_binding(self):
        self.question = "换一个政策再解释"
        with self.assertRaises(ValueError): self.parse()

    def test_changed_source_text_breaks_binding_or_validation(self):
        changed = copy.deepcopy(self.context)
        changed["sources"][0]["text"] += " changed"
        with self.assertRaises(ValueError):
            policy.parse(json.dumps(self.answer), self.report, question=self.question, policy_context=changed)

    def test_new_numbers_and_markup_are_rejected(self):
        for text in ("税率50%", "百分之五十", "<b>内容</b>", "https://example.com", ""):
            self.answer["policy_explanations"][0]["text"] = text
            with self.assertRaises(ValueError): self.parse()

    def test_duplicate_json_keys_rejected(self):
        raw = json.dumps(self.answer).replace('"schema_version":', '"schema_version":"duplicate","schema_version":', 1)
        with self.assertRaises(ValueError):
            policy.parse(raw, self.report, question=self.question, policy_context=self.context)

    def test_no_grading_material_in_payload(self):
        payload = json.loads(self.messages[1]["content"])
        self.assertEqual(payload["schema_version"], policy.PROTOCOL)
        self.assertNotIn("references", payload)
        self.assertNotIn("answer", payload)
        self.assertNotIn("review", payload)
        self.assertIn("policy", payload["view"])

    def test_reader_report_uses_plain_language_and_hides_internal_ids(self):
        from src.tradeintel_ai.public_report import build_public_report, render_public_report
        parsed = self.parse()
        report = build_public_report(
            self.report["evidence"], self.report["request"],
            explanations=parsed["interpretations"],
            policy_explanations=parsed["policy_explanations"],
            watchlist=parsed["watchlist"], policy_context=self.context)
        rendered = render_public_report(report)

        self.assertIn("# 国际贸易政策与数据观察简报", rendered)
        self.assertIn("适用条件和排除情形尚未逐项核实", rendered)
        self.assertIn("尚未核实", rendered)
        self.assertIn("美国人口普查局 2026-07 月官方进口数据", rendered)
        self.assertIn("CBP公告第9页", rendered)
        self.assertIn("| `38180000` | 掺杂用于电子工业的化学元素；圆片、晶圆及相关化合物 | 50% |", rendered)
        self.assertIn("| 2026-07 | 38180000 |", rendered)
        for internal in ("us_301_review2025_tungsten_solar", "explanation_draft",
                         "observation:", "data_version", "unverified", "unknown",
                         "data/processed/"):
            with self.subTest(internal=internal):
                self.assertNotIn(internal, rendered)

    def test_prompt_json_example_matches_parser_contract(self):
        system = self.messages[0]["content"]
        self.assertIn("topic逐字使用change、applicability、limits各一次，不得翻译", system)
        self.assertIn("text和rationale正文不输出阿拉伯数字", system)
        marker = "结构示例："
        self.assertIn(marker, system)
        sample, _ = json.JSONDecoder().raw_decode(system.split(marker, 1)[1].lstrip())
        self.assertEqual([item["topic"] for item in sample],
                         ["change", "applicability", "limits"])
        self.assertTrue(all(set(item) == {"topic", "source_ids", "text"} for item in sample))

        payload = json.loads(self.messages[1]["content"])
        source_id = payload["view"]["policy"]["sources"]["rows"][0][0]
        answer = copy.deepcopy(self.answer)
        answer["policy_explanations"] = [
            {**item, "source_ids": [source_id], "text": "这是用于验证结构的说明文本。"}
            for item in sample
        ]
        parsed = policy.parse(json.dumps(answer, ensure_ascii=False), self.report,
                               question=self.question, policy_context=self.context)
        self.assertEqual(parsed["status"], "manual_review_required")
        self.assertEqual([item["topic"] for item in parsed["policy_explanations"]],
                         ["change", "applicability", "limits"])

        object_shaped = copy.deepcopy(answer)
        object_shaped["policy_explanations"] = {
            item["topic"]: item for item in object_shaped["policy_explanations"]
        }
        with self.assertRaises(ValueError):
            policy.parse(json.dumps(object_shaped), self.report,
                         question=self.question, policy_context=self.context)

        translated_topic = copy.deepcopy(answer)
        translated_topic["policy_explanations"][0]["topic"] = "政策变化"
        with self.assertRaises(ValueError):
            policy.parse(json.dumps(translated_topic, ensure_ascii=False), self.report,
                         question=self.question, policy_context=self.context)

        unfilled_placeholder = copy.deepcopy(answer)
        unfilled_placeholder["policy_explanations"][0]["source_ids"] = ["<p-id>"]
        with self.assertRaises(ValueError):
            policy.parse(json.dumps(unfilled_placeholder), self.report,
                         question=self.question, policy_context=self.context)

    def test_policy_followup_context_is_sent_and_bound(self):
        context = {"schema_version": "public-request-context-v1",
                   "kind": "prior_program_report", "parent_request_digest": "a" * 64,
                   "parent_data_version": VERSION, "parent_task_id": "previous",
                   "parent_window": self.report["request"]["window"],
                   "selected_products": self.report["request"]["products"],
                   "summary": ["上一份报告介绍了贸易金额变化。"]}
        messages = policy.messages(self.question, self.report,
                                   policy_context=self.context, request_context=context)
        payload = json.loads(messages[1]["content"])
        self.assertEqual(payload["request_context"], context)
        self.answer["binding_sha256"] = payload["binding_sha256"]
        policy.parse(json.dumps(self.answer), self.report, question=self.question,
                     policy_context=self.context, request_context=context)
        context["summary"] = ["另一份报告。"]
        with self.assertRaisesRegex(ValueError, "不匹配"):
            policy.parse(json.dumps(self.answer), self.report, question=self.question,
                         policy_context=self.context, request_context=context)

    def test_session_parser_enforces_total_policy_and_trade_length(self):
        for item in self.answer["policy_explanations"]:
            item["text"] = "政" * 350
        self.answer["interpretations"] = [
            {"observation_id": f"o{i}", "kind": "meaning", "text": "贸" * 350}
            for i in range(1, 4)]
        with self.assertRaisesRegex(ValueError, "2000"):
            self.parse()

    def test_rejected_core_policy_section_blocks_publication(self):
        from src.tradeintel_ai.interpretation_review_store import validate_public_session_review
        expected = [{"kind": "interpretation", "index": 0}] + [
            {"kind": "policy_explanation", "index": i} for i in range(3)]
        for rejected in range(3):
            decisions = [{**item, "verdict": "reject" if item["kind"] == "policy_explanation"
                          and item["index"] == rejected else "accept", "reason": "原文核对结果"}
                         for item in expected]
            result = validate_public_session_review(
                {"facts_checked": True, "decisions": decisions}, expected, reviewer="test")
            self.assertFalse(result["eligible_for_export"])

    def test_trade_report_shape_stays_compatible_and_policy_ids_are_checked(self):
        from src.tradeintel_ai.public_report import build_public_report
        args = (self.report["evidence"], self.report["request"])
        report = build_public_report(*args, policy_context=self.context)
        self.assertNotIn("policy_explanations", report)
        for bad in ({"topic": {}, "source_ids": [self.context["sources"][0]["id"]], "text": "说明"},
                    {"topic": "change", "source_ids": [{}], "text": "说明"}):
            with self.assertRaises(ValueError):
                build_public_report(*args, policy_context=self.context, policy_explanations=[bad])

    def test_structural_success_does_not_certify_entailment(self):
        self.answer["policy_explanations"][0]["text"] = "这个说法并没有被引用证明。"
        self.assertEqual(self.parse()["status"], "manual_review_required")

    def test_snapshot_mode_and_protocol_cannot_be_mixed(self):
        from src.tradeintel_ai.session_explanation import build_public_snapshot
        snap = build_public_snapshot(self.brief, question=self.question,
                                     identity={"session_id": "session-0123456789abcdef",
                                               "task_id": "task-1"}, mode="policy")
        snap["protocol"] = "public-brief-explanation-v1"
        with self.assertRaises(ValueError):
            from src.tradeintel_ai.session_explanation import save_public_snapshot
            import tempfile
            with tempfile.TemporaryDirectory() as root:
                save_public_snapshot(Path(root), "session-0123456789abcdef", "task-1", snap)


if __name__ == "__main__": unittest.main()
