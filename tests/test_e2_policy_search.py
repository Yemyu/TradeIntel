"""E2 offline tests: document store, policy search contract, candidate fields.

Covers the Astra E2 contract points that are checkable without a provider:
version/status filtering order, exact-HTS priority, dependency completion
with ``incomplete_required_context``, no truncation of qualifiers, stable
citation ids, enabled re-check, digest-bound candidate confirmation and the
layered coverage rules.
"""
from copy import deepcopy
import json
import unittest

from src.tradeintel_ai.policy_candidates import (build_candidates, build_coverage,
                                                 candidate_digest, confirm_candidate,
                                                 parse_code_precision)
from src.tradeintel_ai.policy_documents import (build_document, build_document_store,
                                                citation_id, compute_doc_version,
                                                get_section, set_document_status,
                                                validate_document_store)
from src.tradeintel_ai.policy_search import PolicySearch, normalize_hts8, set_required_dependencies

CURRENT_TEXTS = [
    {"id": "cbpx:p8", "url": "https://example.test/cbp",
     "text": "The tariff increases take effect on January 1, 2025, with respect to goods "
             "entered for consumption, or withdrawn from warehouse for consumption, on or "
             "after 12:01 a.m. eastern standard time."},
    {"id": "cbpx:p9", "url": "https://example.test/cbp",
     "text": "For certain polysilicon products of China classified in 2804.61.00, importers "
             "shall submit heading 9903.91.05 to pay the additional 50 percent rate of duty.\n"
             "(1) 2804.61.00 (Silicon containing by weight not less than 99.99 percent of silicon)"},
    {"id": "cbpx:p12", "url": "https://example.test/cbp",
     "text": "For certain tungsten products of China classified in 8101.99.10, importers shall "
             "pay the additional 25 percent rate of duty."},
]
OLD_TEXT = "Notice of Action Pursuant to Section 301: the trade measure announced on August 16, 2018 " \
           "clarifies the first batch list of China origin products."


def make_store(*, old_status: str = "superseded"):
    current = build_document({"policy_id": "fixture", "data_version": "v1",
                              "sources": deepcopy(CURRENT_TEXTS)},
                             doc_id="cbpx", publication_time="2024-12-31", status="enabled")
    set_required_dependencies(current, {
        "effective_date": {"status": "known", "section_ids": ["cbpx:p8:para1"]},
        "origin": {"status": "known", "section_ids": ["cbpx:p9:para1", "cbpx:p12:para1"]},
        "conditions": {"status": "known", "section_ids": ["cbpx:p9:para2"]},
        "exceptions": {"status": "verified_absent",
                       "note": "已核验三个已索引段落，均无例外条款。"},
    })
    old = build_document({"policy_id": "fixture", "data_version": "old",
                          "sources": [{"id": "ustrold:p1", "url": "https://example.test/old",
                                       "text": OLD_TEXT}]},
                         doc_id="ustrold", publication_time="2018-08-16", status=old_status)
    return build_document_store([current, old], policy_id="fixture", data_version="v1")


class DocumentStoreTests(unittest.TestCase):
    def test_sections_reconstruct_source_text_exactly(self):
        store = make_store()
        validate_document_store(store)
        for document in store["documents"]:
            for source in document["sources"]:
                import hashlib
                sections = [s for s in document["sections"] if s["source_id"] == source["source_id"]]
                joined = "".join(s["text"] for s in sections)
                self.assertEqual(hashlib.sha256(joined.encode()).hexdigest(), source["text_sha256"])

    def test_citation_ids_are_stable_when_documents_are_added(self):
        store = make_store()
        search = PolicySearch(store)
        first = search.search("多晶硅的加征税率是多少？")["hits"][0]["citation_id"]
        extra = build_document({"policy_id": "fixture2", "sources": deepcopy(CURRENT_TEXTS[:1])},
                               doc_id="extra", status="disabled")
        store["documents"].append(extra)
        second = search.search("多晶硅的加征税率是多少？")["hits"][0]["citation_id"]
        self.assertEqual(first, second)
        self.assertEqual(citation_id("docver-1", "s"), "docver-1:s")

    def test_disabled_document_never_returns(self):
        store = make_store()
        version = store["documents"][0]["doc_version"]
        search = PolicySearch(store)
        self.assertEqual(search.search("多晶硅的加征税率是多少？")["status"], "candidate_evidence")
        set_document_status(store, version, "disabled")
        outcome = search.search("多晶硅的加征税率是多少？")
        self.assertEqual(outcome["status"], "no_evidence")
        self.assertFalse(any(hit["doc_version"] == version for hit in outcome["hits"]))

    def test_unknown_publication_time_is_excluded_under_cutoff(self):
        store = make_store()
        for document in store["documents"]:
            if document["status"] == "enabled":
                document["publication_time"] = None
                document["publication_time_status"] = "unknown"
        outcome = PolicySearch(store).search("多晶硅的加征税率是多少？", as_of="2025-01-01")
        self.assertEqual(outcome["status"], "no_evidence")
        self.assertTrue(outcome["excluded_fragments"])


class SearchContractTests(unittest.TestCase):
    def setUp(self):
        self.search = PolicySearch(make_store())

    def test_superseded_version_is_filtered_by_default(self):
        outcome = self.search.search("2018年的301清单修订了什么？")
        self.assertEqual(outcome["status"], "no_evidence")
        self.assertTrue(outcome["excluded_fragments"])

    def test_superseded_content_needs_explicit_opt_in(self):
        outcome = self.search.search("2018年的301清单修订了什么？", include_superseded=True)
        self.assertEqual(outcome["status"], "candidate_evidence")
        self.assertIn("August 16, 2018", "\n".join(hit["text"] for hit in outcome["hits"]))

    def test_rate_hit_completes_common_clauses(self):
        outcome = self.search.search("多晶硅的加征税率是多少？")
        self.assertEqual(outcome["status"], "candidate_evidence")
        labels = {item["dependency"] for item in outcome["required_context"]}
        self.assertIn("effective_date", labels)
        self.assertIn("origin", labels)
        self.assertIn("12:01 a.m. eastern standard time",
                      "\n".join(item["text"] for item in outcome["required_context"]
                                if item.get("text")))

    def test_missing_dependency_reports_incomplete(self):
        store = make_store()
        for document in store["documents"]:
            if document["status"] == "enabled":
                document["sections"] = [s for s in document["sections"]
                                        if "take effect" not in s["text"]]
                document["sources"] = [s for s in document["sources"]
                                       if "p8" not in s["source_id"]]
                document["doc_version"] = compute_doc_version(document)
        outcome = PolicySearch(store).search("多晶硅的加征税率是多少？")
        self.assertEqual(outcome["status"], "incomplete_required_context")
        self.assertIn("effective_date", str(outcome["missing_dependencies"]))

    def test_qualifier_text_is_never_truncated(self):
        outcome = self.search.search("28046100 纯度不足99.99%的硅也加征吗？")
        blob = "\n".join(hit["text"] for hit in outcome["hits"])
        self.assertIn("2804.61.00", blob)
        self.assertIn("not less than 99.99 percent", blob)

    def test_explicit_code_without_match_gets_no_substitute(self):
        outcome = self.search.search("8541.42.00 的加征税率是多少？")
        self.assertEqual(outcome["status"], "no_evidence")
        self.assertIn("不以其他商品的命中替代", outcome["reason"])

    def test_exact_recall_leads_and_is_not_crowded_out(self):
        outcome = self.search.search("8101.99.10 钨制品从仓库提取消费是否适用？")
        blob = "\n".join(hit["text"] for hit in outcome["hits"])
        self.assertIn("8101.99.10", blob)
        self.assertIn("withdrawn from warehouse for consumption",
                      "\n".join(ctx["text"] for ctx in outcome["required_context"]
                                if ctx.get("text")))

    def test_normalize_hts8_handles_plain_and_dotted(self):
        self.assertEqual(normalize_hts8("2804.61.00 和 81019910"), ["28046100", "81019910"])


class CandidateTests(unittest.TestCase):
    def make_fields(self, store):
        version = next(d["doc_version"] for d in store["documents"] if d["status"] == "enabled")
        return [{"field": "effective_date", "status": "known", "value": "2025-01-01",
                 "evidence": [{"doc_version": version, "section_id": "cbpx:p8:para1",
                               "quote": "January 1, 2025"}]},
                {"field": "origin", "status": "known", "value": "中国原产",
                 "evidence": [{"doc_version": version, "section_id": "cbpx:p9:para1",
                               "quote": "products of China"}]},
                {"field": "hts_codes", "status": "known",
                 "value": [{"code": "28046100", "precision": "whole_hts8"},
                           {"code": "81019910", "precision": "whole_hts8"}],
                 "evidence": [{"doc_version": version, "section_id": "cbpx:p9:para1",
                               "quote": "2804.61.00"},
                              {"doc_version": version, "section_id": "cbpx:p12:para1",
                               "quote": "8101.99.10"}]},
                {"field": "exceptions", "status": "unknown", "value": None,
                 "reason": "本版公告未载明例外条款；未核全章98与排除清单，未知不代表没有例外。"}]

    def test_build_verify_confirm_roundtrip(self):
        store = make_store()
        candidate = build_candidates(self.make_fields(store), store)
        self.assertIn("candidate_digest", candidate)
        self.assertEqual(candidate["candidate_digest"],
                         candidate_digest({k: v for k, v in candidate.items()
                                           if k != "candidate_digest"}))
        confirmation = confirm_candidate(candidate, store, confirmed_by="human")
        self.assertTrue(confirmation["evidence_reverified"])
        # Any field change invalidates the recorded digest.
        changed = deepcopy(candidate)
        changed["fields"][0]["value"] = "2025-01-02"
        with self.assertRaises(ValueError):
            confirm_candidate(changed, store, confirmed_by="human",
                              digest=candidate["candidate_digest"])

    def test_quote_must_match_saved_original_text(self):
        store = make_store()
        fields = self.make_fields(store)
        fields[0]["evidence"][0]["quote"] = "January 2, 2025"
        with self.assertRaises(ValueError):
            build_candidates(fields, store)

    def test_disabled_document_breaks_confirmation(self):
        store = make_store()
        candidate = build_candidates(self.make_fields(store), store)
        set_document_status(store, store["documents"][0]["doc_version"], "disabled")
        with self.assertRaises(ValueError):
            confirm_candidate(candidate, store, confirmed_by="human")

    def test_conflict_needs_two_evidence_and_unknown_needs_reason(self):
        store = make_store()
        fields = self.make_fields(store)
        conflict = {"field": "effective_date", "status": "conflict", "value": None,
                    "evidence": fields[0]["evidence"]}
        with self.assertRaises(ValueError):
            build_candidates(fields + [conflict], store)
        no_reason = {"field": "revisions", "status": "unknown", "value": None, "reason": None}
        with self.assertRaises(ValueError):
            build_candidates(fields + [no_reason], store)

    def test_coverage_layering(self):
        store = make_store()
        candidate = build_candidates(self.make_fields(store), store)
        # Without a trusted trade query the trade layer stays not_checked.
        unchecked = build_coverage(candidate)
        self.assertEqual(unchecked["trade_coverage"], "not_checked")
        # With trusted trade evidence matching the candidate codes: exact.
        evidence = {"codes": ["28046100", "81019910"], "month": "2026-07",
                    "data_version": "v1", "availability": "exact"}
        coverage = build_coverage(candidate, trade_evidence=evidence)
        self.assertEqual(coverage["code_precision"], "exact_hts8")
        self.assertEqual(coverage["policy_scope_match"], "whole_hts8")
        self.assertEqual(coverage["trade_coverage"], "exact")
        partial = deepcopy(candidate)
        partial["fields"][2]["value"][0]["precision"] = "partial_ex"
        partial["candidate_digest"] = candidate_digest(
            {k: v for k, v in partial.items() if k != "candidate_digest"})
        layered = build_coverage(partial, trade_evidence={**evidence, "availability": "partial"})
        self.assertEqual(layered["code_precision"], "partial")
        self.assertEqual(layered["policy_scope_match"], "partial")
        self.assertEqual(layered["trade_coverage"], "partial")
        self.assertIn("HS6不可扩成HTS8", layered["boundary"])
        # partial policy scope must never be reported as exact exposure.
        with self.assertRaises(ValueError):
            build_coverage(partial, trade_evidence=evidence)

    def test_parse_code_precision_rejects_mismatched_length(self):
        with self.assertRaises(ValueError):
            parse_code_precision([{"code": "280461", "precision": "whole_hts8"}])
        # Real HS6 stays 6-digit and must never be extended to HTS8.
        entries = parse_code_precision([{"code": "280461", "precision": "hs6_only"}])
        self.assertEqual(entries[0]["code"], "280461")
        # A 10-digit partial line is expressed explicitly.
        self.assertEqual(parse_code_precision(
            [{"code": "8101991050", "precision": "hts10_partial"}])[0]["code"], "8101991050")

    def test_empty_quote_is_rejected(self):
        store = make_store()
        fields = self.make_fields(store)
        fields[0]["evidence"][0]["quote"] = ""
        with self.assertRaises(ValueError):
            build_candidates(fields, store)

    def test_confirmation_rechecks_policy_identity(self):
        store = make_store()
        candidate = build_candidates(self.make_fields(store), store)
        drifted = dict(store, policy_id="other-policy")
        with self.assertRaises(ValueError):
            confirm_candidate(candidate, drifted, confirmed_by="human")
        stale_fields = deepcopy(candidate)
        stale_fields["missing_required_fields"] = ["title"]
        with self.assertRaises(ValueError):
            confirm_candidate(stale_fields, store, confirmed_by="human")


if __name__ == "__main__":
    unittest.main()
