"""S1 policy binding and announcement-store isolation tests."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest

from src.tradeintel_ai.announcement_flow import (REQUIRED_FIELDS, resolve_policy_binding,
                                                 search_policy_binding, submit_candidates,
                                                 confirm_and_enable, load_announcement_store)
from src.tradeintel_ai.policy_candidates import build_candidates
from src.tradeintel_ai.session_store import create_session, load_session, set_request, start_task
from src.tradeintel_ai.web_app import _handle_announcement_import, _handle_session_post


NOTICE = """Official Notice A
Published December 20, 2024.
Effective January 1, 2025 at 00:00 UTC.
Products of China are covered; HTS 28046100 has an additional 50 percent rate.
"""


class _Repository:
    class _Paths:
        root = Path(__file__).resolve().parents[1]
    paths = _Paths()


class S1PolicyBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="s1-binding-")
        self.root = Path(self.tmp.name)
        imported = _handle_announcement_import(self.root, {
            "policy_id": "policy-s1", "source_id": "notice:a:p1",
            "url": "https://official.example/a", "text": NOTICE})
        self.doc_version = imported["doc_version"]
        store = load_announcement_store(self.root, "policy-s1")
        self.store = store
        first = store["documents"][0]["sections"][0]["id"]
        self.fields = [{"field": name, "status": "unknown", "value": None,
                        "reason": "S1 synthetic field"} for name in REQUIRED_FIELDS]
        self.fields[0] = {"field": "title", "status": "known", "value": "Official Notice A",
                          "evidence": [{"doc_version": self.doc_version,
                                        "section_id": first, "quote": "Official Notice A"}]}

    def tearDown(self):
        self.tmp.cleanup()

    def _enable(self):
        ready = submit_candidates(self.root, "policy-s1", self.doc_version, self.fields)
        return confirm_and_enable(
            self.root, "policy-s1", self.doc_version, self.fields,
            confirmed_by="s1-test", expected_candidate_digest=ready["candidate_digest"])

    def test_candidate_digest_is_server_owned_and_stale_digest_rejected(self):
        ready = submit_candidates(self.root, "policy-s1", self.doc_version, self.fields)
        self.assertEqual(ready["candidate_digest"], ready["candidate"]["candidate_digest"])
        with self.assertRaisesRegex(ValueError, "摘要与服务器登记记录"):
            confirm_and_enable(self.root, "policy-s1", self.doc_version, self.fields,
                               confirmed_by="s1-test", expected_candidate_digest="stale")
        enabled = confirm_and_enable(self.root, "policy-s1", self.doc_version, self.fields,
                                     confirmed_by="s1-test",
                                     expected_candidate_digest=ready["candidate_digest"])
        self.assertEqual(enabled["policy_binding"]["doc_version"], self.doc_version)

    def test_candidate_fields_cannot_change_while_reusing_old_digest(self):
        ready = submit_candidates(self.root, "policy-s1", self.doc_version, self.fields)
        changed = [dict(field) for field in self.fields]
        changed[0]["value"] = "Tampered Notice"
        with self.assertRaisesRegex(ValueError, "候选内容已变化"):
            confirm_and_enable(self.root, "policy-s1", self.doc_version, changed,
                               confirmed_by="s1-test",
                               expected_candidate_digest=ready["candidate_digest"])

    def test_binding_is_resolved_from_server_and_search_is_doc_isolated(self):
        enabled = self._enable()
        binding = resolve_policy_binding(self.root, "policy-s1", self.doc_version,
                                         enabled["candidate_digest"])
        self.assertEqual(binding["policy_id"], "policy-s1")
        result = search_policy_binding(self.root, binding, "HTS 28046100 50 percent",
                                       hts8="28046100")
        self.assertTrue(all(hit["doc_version"] == self.doc_version for hit in result["hits"]))
        self.assertEqual(result["policy_binding"]["candidate_digest"],
                         enabled["candidate_digest"])
        with self.assertRaisesRegex(ValueError, "客户端公告摘要"):
            resolve_policy_binding(self.root, "policy-s1", self.doc_version, "wrong")

    def test_session_binds_policy_and_task_carries_binding(self):
        enabled = self._enable()
        session = create_session(self.root)
        request = {"policy_id": "policy-s1", "month": "2025-01",
                   "product": "all", "focus": "contrast"}
        set_request(self.root, session, request,
                    policy_version=self.doc_version, data_version=None,
                    policy_binding=enabled["policy_binding"])
        stored = load_session(self.root, session["session_id"])
        self.assertEqual(stored["policy_binding"], enabled["policy_binding"])
        task = start_task(self.root, stored, model="deterministic", prompt_digest="s1",
                          request=request)
        self.assertEqual(task["task"]["policy_binding"], enabled["policy_binding"])

    def test_web_confirmation_requires_server_binding_for_unknown_policy(self):
        enabled = self._enable()
        session = create_session(self.root)
        result = _handle_session_post(
            self.root, "/api/session/request",
            {"session_id": session["session_id"],
             "request": {"policy_id": "policy-s1", "month": "2025-01",
                         "product": "all", "focus": "contrast"},
             "policy_binding": enabled["policy_binding"]}, _Repository())
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["policy_binding"], enabled["policy_binding"])
        self.assertEqual(result["session"]["data_version"], None)

    def test_parallel_submit_does_not_lose_candidate_record(self):
        # Two callers submit identical content; the locked read-modify-write
        # must leave one complete server-side record, never a partial JSON file.
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda _: submit_candidates(self.root, "policy-s1", self.doc_version, self.fields),
                range(2)))
        self.assertEqual(results[0]["candidate_digest"], results[1]["candidate_digest"])
        store = load_announcement_store(self.root, "policy-s1")
        record = store["announcement_candidates"][self.doc_version]
        self.assertEqual(record["candidate_digest"], results[0]["candidate_digest"])


if __name__ == "__main__":
    unittest.main()
