"""Offline policy fixtures; these are not real model accuracy tests."""
from copy import deepcopy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from test_e2_policy_search import make_store
from tradeintel_ai.policy_search import PolicySearch
from tradeintel_ai.trade_agent_policy_evidence import evidence_bundles, evidence_summary
from tradeintel_ai.trade_agent_tools import TradeAgentTools
from tradeintel_ai.trade_agent import TradeResearchAgent, read_public_session
from tradeintel_ai.agent import ModelResponse, ModelToolCall
from tradeintel_ai.trade_agent_store import read_session
from tradeintel_ai.policy_documents import build_document, build_document_store
from tradeintel_ai.policy_search import set_required_dependencies
import json
import uuid

DATA = Path(__file__).resolve().parents[1] / "tmp/handoff-runs/trade-demo-data-20260925"


class PolicyEvidenceTests(unittest.TestCase):
    def test_dependencies_keep_version_and_source(self):
        store = make_store()
        result = PolicySearch(store).search("2804.61.00")
        bundle = evidence_bundles(store, result)[0]
        self.assertEqual(bundle["hit"]["text"], result["hits"][0]["text"])
        self.assertEqual(len(bundle["required_context"]), 5)
        for clause in bundle["required_context"]:
            self.assertEqual(clause["doc_version"], bundle["doc_version"])
            if clause["status"] == "known":
                self.assertTrue(clause["url"])
                self.assertEqual(clause["offset_unit"], "character")
            else:
                self.assertIn("本份", clause["boundary"])

    def test_undetermined_not_reportable(self):
        store = make_store()
        store["documents"][0]["required_dependencies"]["exceptions"] = {"status": "undetermined"}
        result = PolicySearch(store).search("2804.61.00")
        self.assertEqual(result["status"], "incomplete_required_context")
        self.assertEqual(evidence_bundles(store, result), [])

    def test_statuses_are_not_no_evidence(self):
        for status in ("scope_refused", "incomplete_required_context", "limited"):
            self.assertEqual(evidence_summary([{"status": status}], [])["status"], status)
        self.assertEqual(evidence_summary([], [])["status"], "not_searched")
        self.assertEqual(evidence_summary([{"status": "no_evidence"}], [])["status"], "no_evidence")

    def test_partial_and_copy_isolation(self):
        searches = [{"status": "candidate_evidence"}, {"status": "incomplete_required_context"}]
        bundles = [{"hit": {"text": "unaltered"}}]
        view = evidence_summary(searches, bundles)
        self.assertEqual(view["status"], "partial")
        bundles[0]["hit"]["text"] = "changed"
        self.assertEqual(view["evidence_bundles"][0]["hit"]["text"], "unaltered")

    def test_separate_long_exception_and_version_identity(self):
        documents = []
        for revision in ("first", "second"):
            doc = build_document({"policy_id": "fixture", "sources": [
                {"id": "same:p1", "url": "https://example.test/notice", "text": "2804.61.00 silicon tariff " + revision},
                {"id": "same:p2", "url": "https://example.test/notice", "text": "x" * 600 + " EXCEPTION: special end use only."}]},
                doc_id="same", status="enabled")
            set_required_dependencies(doc, {
                "effective_date": {"status": "known", "section_ids": ["same:p1:para1"]},
                "origin": {"status": "known", "section_ids": ["same:p1:para1"]},
                "conditions": {"status": "known", "section_ids": ["same:p1:para1"]},
                "exceptions": {"status": "known", "section_ids": ["same:p2:para1"]}})
            documents.append(doc)
        store = build_document_store(documents, policy_id="fixture", data_version="fixture-only")
        bundles = evidence_bundles(store, PolicySearch(store).search("2804.61.00"))
        self.assertEqual(len({b["doc_version"] for b in bundles}), 2)
        for bundle in bundles:
            exception = next(c for c in bundle["required_context"] if c["dependency"] == "exceptions")
            self.assertTrue(exception["text"].endswith("special end use only."))
            self.assertEqual(exception["doc_version"], bundle["doc_version"])

    @unittest.skipUnless(DATA.is_dir(), "local data absent")
    def test_save_restart_and_same_request_do_not_search_or_call_again(self):
        class Model:
            def __init__(self): self.calls = 0
            def complete(self, *, messages, tools):
                self.calls += 1
                last = messages[-1]
                if last["role"] == "user":
                    name, args = "search_products", {"term": "大豆", "flow": "import"}
                elif last["name"] == "search_products":
                    candidate = json.loads(last["content"])["candidates"][0]["id"]
                    name, args = "query_trade", {"candidate_id": candidate, "flow": "import", "partner": "all", "period": {"type": "latest_contiguous"}}
                elif last["name"] == "query_trade":
                    name, args = "search_policy", {"query": "2804.61.00"}
                else:
                    report = next(json.loads(m["content"]) for m in messages if m.get("name") == "query_trade")
                    hit = json.loads(last["content"])["hits"][0]
                    name, args = "finish", {"report_ids": [report["report_id"]], "source_ids": [hit["citation_id"]]}
                return ModelResponse(tool_calls=(ModelToolCall(uuid.uuid4().hex, name, args),))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); directory = root / ".local/announcement-docs"
            directory.mkdir(parents=True); (directory / "fixture.json").touch()
            model = Model(); request = uuid.uuid4().hex; question = "美国大豆进口和本地政策资料"
            with patch("tradeintel_ai.announcement_store.load_announcement_store", return_value=make_store()):
                first = TradeResearchAgent(DATA, root, model).turn(question, request)
            self.assertEqual(first["turns"][-1]["status"], "completed")
            saved = read_session(root, first["session_id"])
            self.assertEqual(len(saved["turns"][-1]["policy_evidence"]["evidence_bundles"]), 1)
            with patch("tradeintel_ai.announcement_store.load_announcement_store", side_effect=AssertionError("must not re-search")):
                replay = TradeResearchAgent(DATA, root, model).turn(question, request)
                restored = read_public_session(root, first["session_id"])
            self.assertEqual(first, replay)
            self.assertEqual(first, restored)
            self.assertEqual(model.calls, 4)
            self.assertEqual(saved, read_session(root, first["session_id"]))

    @unittest.skipUnless(DATA.is_dir(), "local data absent")
    def test_tool_bridge_preserves_refusal_and_full_unit_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            directory = root / ".local/announcement-docs"
            directory.mkdir(parents=True)
            (directory / "fixture.json").touch()
            store = make_store()
            with patch("tradeintel_ai.announcement_store.load_announcement_store", return_value=store):
                tools = TradeAgentTools(DATA, root, question="政策")
                result = tools.search_policy("2804.61.00")
                self.assertLessEqual(len(json.dumps(result, ensure_ascii=False)), 25000)
                self.assertTrue(result["hits"])
                self.assertEqual(len(result["policy_evidence"]["evidence_bundles"][0]["required_context"]), 5)
                refusal = tools.search_policy("current tariff rate")
                self.assertEqual(refusal["status"], "scope_refused")
                oversized = deepcopy(PolicySearch(store).search("2804.61.00"))
                for hit in oversized["hits"]:
                    hit["text"] += "x" * 13000
                with patch("tradeintel_ai.policy_search.PolicySearch.search", return_value=oversized):
                    limited = tools.search_policy("2804.61.00")
                self.assertEqual(limited["status"], "limited")
                self.assertEqual(limited["hits"], [])
                diagnostic_heavy = deepcopy(oversized)
                diagnostic_heavy["reason"] = "diagnostic " * 4000
                fresh = TradeAgentTools(DATA, root, question="政策")
                with patch("tradeintel_ai.policy_search.PolicySearch.search", return_value=diagnostic_heavy):
                    bounded = fresh.search_policy("2804.61.00")
                self.assertLessEqual(len(json.dumps(bounded, ensure_ascii=False)), 25000)
                self.assertEqual(bounded["status"], "limited")
                self.assertEqual(fresh.policy_sources, {})
                self.assertEqual(fresh.policy_searches[0]["reason"], diagnostic_heavy["reason"])


if __name__ == "__main__":
    unittest.main()
