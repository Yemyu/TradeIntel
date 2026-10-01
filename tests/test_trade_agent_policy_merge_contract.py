"""Stable evidence identity and corrected finish, entirely offline."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import json
import tempfile
import unittest
import uuid
from unittest.mock import patch

from test_e2_policy_search import make_store
from tradeintel_ai.trade_agent_tools import TradeAgentTools, _policy_evidence_identity
from tradeintel_ai.trade_data_repository import TradeDataError
from tradeintel_ai.trade_agent import TradeResearchAgent
from tradeintel_ai.agent import ModelResponse, ModelToolCall
from scripts.score_us_agent_retest import check_policy_bundles, check_public_turn

DATA = Path(__file__).resolve().parents[1] / "tmp/handoff-runs/trade-demo-data-20260925"
NOTICE = DATA.parents[0] / "us-agent-retest-20261001-v5/bootstrap/runtime/.local/announcement-docs/us_301_review2025_tungsten_solar.json"


@unittest.skipUnless(DATA.is_dir(), "local data absent")
class PolicyMergeContractTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        directory = self.root / ".local/announcement-docs"
        directory.mkdir(parents=True)
        (directory / "fixture.json").touch()

    def tools(self):
        return TradeAgentTools(DATA, self.root, question="本地政策", today=date(2026, 10, 1))

    def test_real_query_pairs_accept_metadata_change_and_keep_original(self):
        if not NOTICE.is_file():
            self.skipTest("saved policy absent")
        store = json.loads(NOTICE.read_text())
        for a, b in (("钨 加税 关税", "9903.91.11 tungsten additional duty 301"),
                     ("大豆 美国 进口 出口 关税 政策 soybean", "soybean 大豆 农产品 中国 关税 出口限制")):
            tools = self.tools()
            with patch("tradeintel_ai.announcement_store.load_announcement_store", return_value=store):
                first = tools.search_policy(a)
                original = deepcopy(tools.policy_bundles)
                second = tools.search_policy(b)
                tools.search_policy(b)
            common = set(original) & {h["citation_id"] for h in second["hits"]}
            self.assertTrue(common)
            self.assertTrue(any(original[c]["hit"].get("score") != next(h["score"] for h in second["hits"] if h["citation_id"] == c) for c in common))
            for c in common:
                self.assertEqual(tools.policy_bundles[c], original[c])
            checked = check_policy_bundles(list(tools.policy_bundles.values()), store)
            self.assertFalse(checked.get("errors"), checked)

    def test_only_two_hit_metadata_fields_ignored(self):
        bundle = {"doc_version": "v1", "hit": {"citation_id": "v1:p1", "text": "law",
                  "source_id": "p1", "url": "https://example.test", "page": 1,
                  "offset": 0, "doc_version": "v1", "policy_id": "policy", "score": 1},
                  "required_context": [{"dependency": "exceptions", "text": "special end use", "status": "known"}]}
        changed = deepcopy(bundle); changed["hit"].update(score=None, matched_codes=["99039111"])
        self.assertEqual(_policy_evidence_identity(bundle), _policy_evidence_identity(changed))
        self.assertEqual(bundle["hit"]["score"], 1)
        for key in ("citation_id", "text", "source_id", "url", "page", "offset", "doc_version", "policy_id", "new_unknown_field"):
            changed = deepcopy(bundle); changed["hit"][key] = "different"
            with self.subTest(field=key):
                self.assertNotEqual(_policy_evidence_identity(bundle), _policy_evidence_identity(changed))
        for key in ("text", "status", "dependency", "offset", "doc_version"):
            changed = deepcopy(bundle); changed["required_context"][0][key] = "different"
            self.assertNotEqual(_policy_evidence_identity(bundle), _policy_evidence_identity(changed))

    def test_production_merge_rejects_changed_full_dependency(self):
        tools = self.tools(); store = make_store()
        with patch("tradeintel_ai.announcement_store.load_announcement_store", return_value=store):
            tools.search_policy("2804.61.00")
            bundle = deepcopy(next(iter(tools.policy_bundles.values())))
            bundle["required_context"][0]["text"] = "conflicting legal clause"
            with patch("tradeintel_ai.trade_agent_policy_evidence.evidence_bundles", return_value=[bundle]):
                with self.assertRaises(TradeDataError):
                    tools.search_policy("2804.61.00")

    def test_same_call_duplicate_metadata_keeps_one_bundle(self):
        tools = self.tools(); store = make_store()
        with patch("tradeintel_ai.announcement_store.load_announcement_store", return_value=store):
            tools.search_policy("2804.61.00")
            first = deepcopy(next(iter(tools.policy_bundles.values())))
            second = deepcopy(first); second["hit"]["score"] = 77
            fresh = self.tools()
            with patch("tradeintel_ai.trade_agent_policy_evidence.evidence_bundles", return_value=[first, second]):
                result = fresh.search_policy("2804.61.00")
        self.assertEqual(len(result["hits"]), 1)
        self.assertEqual(len(fresh.policy_bundles), 1)

    def test_wrong_page_id_rejected_then_actual_citation_completes(self):
        feedback = []
        class Model:
            calls = 0
            def complete(model, *, messages, tools):
                model.calls += 1
                if messages[-1]["role"] == "user":
                    name, args = "search_products", {"term": "钨及其制品", "flow": "import"}
                else:
                    last = messages[-1]; result = json.loads(last["content"])
                    if last["name"] == "search_products":
                        name, args = "query_trade", {"candidate_id": result["candidates"][0]["id"], "flow": "import", "partner": "all", "period": {"type": "latest_contiguous", "count": 3}}
                    elif last["name"] == "query_trade":
                        model.rid = result["report_id"]
                        name, args = "search_policy", {"query": "2804.61.00"}
                    elif last["name"] == "search_policy":
                        name, args = "finish", {"report_ids": [model.rid], "source_ids": [result["hits"][0]["source_id"]]}
                    else:
                        feedback.append(result)
                        name, args = "finish", {"report_ids": result["available_report_ids"], "source_ids": result["available_policy_citation_ids"]}
                return ModelResponse(tool_calls=(ModelToolCall(uuid.uuid4().hex, name, args),))
        with patch("tradeintel_ai.announcement_store.load_announcement_store", return_value=make_store()):
            model = Model()
            state = TradeResearchAgent(DATA, self.root, model).turn("美国钨及其制品进口和本地公告", uuid.uuid4().hex)
        self.assertEqual(model.calls, 5)
        self.assertEqual(feedback[0]["error_code"], "invalid_finish_reference")
        self.assertEqual(state["turns"][-1]["status"], "completed")

    def test_historical_v2_pilot_refuses_v3_before_model_use(self):
        from scripts import run_trade_agent_supplemental_pilot as pilot
        with patch.object(pilot, "ROOT", self.root), patch.object(pilot.first, "preflight", return_value=({}, None)):
            with self.assertRaisesRegex(ValueError, "完成工具合同不是已定版本"):
                pilot.preflight("soybean-oil")

    def test_real_tungsten_two_searches_and_corrected_finish_fit_six_rounds(self):
        if not NOTICE.is_file():
            self.skipTest("saved policy absent")
        store = json.loads(NOTICE.read_text())
        class Model:
            calls = 0
            def complete(model, *, messages, tools):
                model.calls += 1
                last = messages[-1]
                if last["role"] == "user":
                    name, args = "search_products", {"term": "钨及其制品", "flow": "import"}
                else:
                    result = json.loads(last["content"])
                    if last["name"] == "search_products":
                        name, args = "query_trade", {"candidate_id": result["candidates"][0]["id"], "flow": "import", "partner": "all", "period": {"type": "latest_contiguous", "count": 3}}
                    elif last["name"] == "query_trade":
                        model.rid = result["report_id"]
                        name, args = "search_policy", {"query": "钨 加税 关税"}
                    elif last["name"] == "search_policy" and model.calls == 4:
                        name, args = "search_policy", {"query": "9903.91.11 tungsten additional duty 301"}
                    elif last["name"] == "search_policy":
                        name, args = "finish", {"report_ids": [model.rid], "source_ids": [result["hits"][0]["source_id"]]}
                    else:
                        if result["error_code"] != "invalid_finish_reference":
                            raise AssertionError("unexpected recovery")
                        name, args = "finish", {"report_ids": result["available_report_ids"], "source_ids": result["available_policy_citation_ids"]}
                return ModelResponse(tool_calls=(ModelToolCall(uuid.uuid4().hex, name, args),))
        traces = []
        with patch("tradeintel_ai.announcement_store.load_announcement_store", return_value=store):
            model = Model()
            state = TradeResearchAgent(DATA, self.root, model, today=date(2026, 10, 1), audit_callback=traces.append).turn("美国钨及其制品进口和本地加税公告", uuid.uuid4().hex)
        self.assertEqual(model.calls, 6)
        self.assertEqual(state["turns"][-1]["status"], "completed")
        self.assertTrue(check_policy_bundles(state["turns"][-1]["policy_evidence"]["evidence_bundles"], store)["passed"])
        reference = json.loads((DATA.parent / "us-agent-retest-20261001-v5/reference/trade.json").read_text())
        checked = check_public_turn(self.root, state["turns"][-1],
                                   {"expected_product": "8101", "flow": "import", "partner": "all"}, reference, traces)
        self.assertTrue(checked["passed"], checked)
