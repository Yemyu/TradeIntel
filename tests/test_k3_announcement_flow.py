"""K3 offline acceptance: disabled announcement -> confirmed candidate -> enable.

The tests use synthetic notice text on purpose.  They verify the workflow
boundaries and are not a claim that a real R2 announcement was migrated.
"""
from pathlib import Path
import tempfile
import unittest

from src.tradeintel_ai.announcement_flow import (REQUIRED_FIELDS,
                                                  candidate_template,
                                                  confirm_and_enable,
                                                  coverage_report,
                                                  load_announcement_store,
                                                  save_announcement_store,
                                                  submit_candidates)
from src.tradeintel_ai.policy_documents import build_document
from src.tradeintel_ai.web_app import _handle_announcement_import


NOTICE = """Official Trade Notice 2025-A
Published December 20, 2024.
Effective January 1, 2025 at 00:00 UTC.
Products of China are covered; HTS 28046100 has an additional 50 percent rate.
The notice contains no other exceptions.
"""


class K3AnnouncementFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="k3-announcement-")
        self.root = Path(self.tmp.name)
        result = _handle_announcement_import(self.root, {
            "policy_id": "policy-k3",
            "source_id": "notice:p1",
            "url": "https://official.example/notice-a",
            "text": NOTICE,
        })
        self.doc_version = result["doc_version"]
        self.store = load_announcement_store(self.root, "policy-k3")

    def tearDown(self):
        self.tmp.cleanup()

    def fields(self, *, title_quote="Official Trade Notice 2025-A",
               title_status="known", include_last=True):
        fields = []
        for name in REQUIRED_FIELDS:
            if name == "title" and title_status == "known":
                fields.append({"field": name, "status": "known",
                               "value": "Official Trade Notice 2025-A",
                               "evidence": [{"doc_version": self.doc_version,
                                             "section_id": self.store["documents"][0]["sections"][0]["id"],
                                             "quote": title_quote}]})
            elif name == "effective_date":
                fields.append({"field": name, "status": "known", "value": "2025-01-01",
                               "evidence": [{"doc_version": self.doc_version,
                                             "section_id": self.store["documents"][0]["sections"][2]["id"],
                                             "quote": "Effective January 1, 2025 at 00:00 UTC."}]})
            else:
                fields.append({"field": name, "status": "unknown", "value": None,
                               "reason": "合成验收材料没有提供该字段"})
        return fields if include_last else fields[:-1]

    def enable(self, fields):
        ready = submit_candidates(self.root, "policy-k3", self.doc_version, fields)
        return confirm_and_enable(self.root, "policy-k3", self.doc_version, fields,
                                  confirmed_by="tester",
                                  expected_candidate_digest=ready["candidate_digest"])

    def test_template_only_disabled_and_enable_returns_rebind(self):
        template = candidate_template(self.store, self.doc_version)
        self.assertEqual(len(template["fields"]), 13)
        self.assertTrue(all(field["status"] == "unknown" for field in template["fields"]))
        self.assertEqual(template["source_provenance"], "user_supplied_unverified")
        self.assertEqual(template["source_url"], "https://official.example/notice-a")
        self.assertEqual(template["sections"][0], {
            "section_id": "notice:p1:para1", "text": "Official Trade Notice 2025-A\n"})
        self.assertEqual(self.store["documents"][0]["publication_time_status"], "unknown")
        result = self.enable(self.fields())
        self.assertEqual(result["status"], "enabled")
        self.assertTrue(result["rebind_required"])
        self.assertEqual(result["coverage"]["trade_coverage"], "not_checked")
        stored = load_announcement_store(self.root, "policy-k3")
        self.assertEqual(stored["documents"][0]["status"], "enabled")
        self.assertIn(self.doc_version, stored["announcement_candidates"])
        with self.assertRaises(ValueError):
            candidate_template(stored, self.doc_version)

    def test_reimport_preserves_unverified_source_marker(self):
        result = _handle_announcement_import(self.root, {
            "policy_id": "policy-k3", "source_id": "notice:p1",
            "url": "https://official.example/notice-a", "text": NOTICE,
        })
        self.assertTrue(result["idempotent"])
        self.assertEqual(result["source_provenance"], "user_supplied_unverified")

    def test_submit_rejects_non_verbatim_quote(self):
        fields = self.fields(title_quote="this text is not in the notice")
        with self.assertRaises(ValueError):
            submit_candidates(self.root, "policy-k3", self.doc_version, fields)

    def test_missing_field_or_unknown_without_reason_cannot_enable(self):
        with self.assertRaises(ValueError):
            confirm_and_enable(self.root, "policy-k3", self.doc_version,
                               self.fields(include_last=False), confirmed_by="tester",
                               expected_candidate_digest="missing")
        fields = self.fields()
        fields[-1]["reason"] = ""
        with self.assertRaises(ValueError):
            confirm_and_enable(self.root, "policy-k3", self.doc_version,
                               fields, confirmed_by="tester",
                               expected_candidate_digest="missing")

    def test_citation_from_another_document_is_rejected(self):
        second = _handle_announcement_import(self.root, {
            "policy_id": "policy-k3",
            "source_id": "notice:p2",
            "url": "https://official.example/notice-b",
            "text": NOTICE,
        })
        second_store = load_announcement_store(self.root, "policy-k3")
        second_document = next(doc for doc in second_store["documents"]
                               if doc["doc_version"] == second["doc_version"])
        fields = self.fields()
        fields[0]["evidence"][0]["doc_version"] = second["doc_version"]
        fields[0]["evidence"][0]["section_id"] = second_document["sections"][0]["id"]
        with self.assertRaises(ValueError):
            submit_candidates(self.root, "policy-k3", self.doc_version, fields)

    def test_document_change_invalidates_original_fields(self):
        fields = self.fields()
        changed = build_document({"policy_id": "policy-k3",
                                  "sources": [{"id": "notice:p1",
                                                "url": "https://official.example/notice-a",
                                                "text": NOTICE.replace("2025-A", "2025-B")}]},
                                 doc_id="notice:p1", status="disabled")
        store = load_announcement_store(self.root, "policy-k3")
        store["documents"][0] = changed
        save_announcement_store(self.root, "policy-k3", store)
        with self.assertRaises(ValueError):
            confirm_and_enable(self.root, "policy-k3", self.doc_version,
                               fields, confirmed_by="tester",
                               expected_candidate_digest="missing")

    def test_coverage_is_read_only_and_stays_not_checked(self):
        self.enable(self.fields())
        result = coverage_report(self.root, "policy-k3", self.doc_version)
        self.assertEqual(result["coverage"]["trade_coverage"], "not_checked")
        self.assertTrue(result["rebind_required"])


if __name__ == "__main__":
    unittest.main()
