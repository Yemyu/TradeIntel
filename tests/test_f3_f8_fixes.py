"""F3-F8 fix tests: document versioning, isolation, dependency completion,
coverage honesty, session concurrency and follow-up confirmation.

Each test maps to an acceptance item in ASTRA_R1_REVIEW_20260915 (F1-F9).
Everything runs offline with no provider access.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest

from src.tradeintel_ai.policy_candidates import build_candidates, build_coverage
from src.tradeintel_ai.policy_documents import (build_document, build_document_store,
                                                citation_id, compute_doc_version,
                                                get_section, set_document_status,
                                                validate_document_store)
from src.tradeintel_ai.policy_search import (PolicySearch, normalize_hts8,
                                             set_required_dependencies)
from src.tradeintel_ai.session_store import (StaleSessionError, append_message,
                                             create_session, load_session,
                                             resolve_followup, resolve_unknown_outcome,
                                             save_session, set_request, start_task,
                                             transition_task)

RATE_TEXTS = [
    {"id": "case:p1", "url": "https://example.test/a",
     "text": "For products of China classified in 8101.94.00, importers shall pay the "
             "additional 50 percent rate of duty."},
    {"id": "case:p2", "url": "https://example.test/a",
     "text": "For products of China classified in 8101.94.00, importers shall pay the "
             "additional 50 percent rate of duty, and the new text adds a clarified note."},
]


def _dep_mapping(section_ids):
    return {
        "effective_date": {"status": "known", "section_ids": [section_ids[0]]},
        "origin": {"status": "known", "section_ids": [section_ids[1]]},
        "exceptions": {"status": "verified_absent", "note": "已核验全文无例外条款。"},
    }


def _store_with_docs(documents, *, policy_id="case"):
    return build_document_store(documents, policy_id=policy_id)


class F3DocumentVersionTests(unittest.TestCase):
    def _doc(self, texts=None):
        return build_document(
            {"policy_id": "case", "data_version": "v1",
             "sources": deepcopy(texts or RATE_TEXTS)},
            doc_id="bulletin", publication_time="2025-01-01", status="enabled")

    def test_same_input_is_version_stable(self):
        self.assertEqual(self._doc()["doc_version"], self._doc()["doc_version"])

    def test_text_change_produces_new_version(self):
        v1 = self._doc()
        v2 = self._doc(RATE_TEXTS[:-1] + [dict(RATE_TEXTS[-1], text=RATE_TEXTS[-1]["text"] + " extra")])
        self.assertNotEqual(v1["doc_version"], v2["doc_version"])

    def test_two_versions_coexist_with_same_local_ids(self):
        v1 = self._doc()
        v2 = self._doc(RATE_TEXTS[:-1] + [dict(RATE_TEXTS[-1], text=RATE_TEXTS[-1]["text"] + " extra")])
        store = _store_with_docs([v1, v2])
        validate_document_store(store)
        self.assertIn((v1["doc_version"], "case:p1:para1"),
                      [(d["doc_version"], s["id"]) for d in store["documents"]
                       for s in d["sections"]])
        self.assertIn((v2["doc_version"], "case:p1:para1"),
                      [(d["doc_version"], s["id"]) for d in store["documents"]
                       for s in d["sections"]])

    def test_old_citation_still_points_to_old_text(self):
        v1 = self._doc()
        v2 = self._doc(RATE_TEXTS[:-1] + [dict(RATE_TEXTS[-1], text=RATE_TEXTS[-1]["text"] + " extra")])
        store = _store_with_docs([v1, v2])
        old = get_section(store, v1["doc_version"], "case:p2:para1")
        new = get_section(store, v2["doc_version"], "case:p2:para1")
        self.assertNotIn("extra", old["section"]["text"])
        self.assertIn("extra", new["section"]["text"])

    def test_tampered_text_or_version_is_rejected(self):
        v1 = self._doc()
        tampered_text = deepcopy(v1)
        tampered_text["sections"][0]["text"] += " injected"
        with self.assertRaises(ValueError):
            _store_with_docs([tampered_text])
        tampered_version = deepcopy(v1)
        tampered_version["doc_version"] = "docver-" + "0" * 16
        with self.assertRaises(ValueError):
            _store_with_docs([tampered_version])

    def test_offsets_are_character_positions(self):
        self.assertEqual(self._doc()["offset_unit"], "character")


class F5IsolationTests(unittest.TestCase):
    def _mixed_store(self, *, other_status="enabled"):
        mine = build_document({"policy_id": "mine", "data_version": "v1",
                               "sources": deepcopy(RATE_TEXTS)},
                              doc_id="mine-bulletin", status="enabled")
        set_required_dependencies(mine, _dep_mapping(["case:p1:para1", "case:p2:para1"]))
        other = build_document({"policy_id": "other", "data_version": "v1",
                                "sources": [{"id": "other:p1", "url": "https://e.test/o",
                                             "text": "For products of China in 8101.94.00 the "
                                                     "additional 90 percent rate of duty applies."}]},
                               doc_id="other-bulletin", status=other_status)
        return _store_with_docs([mine, other], policy_id="mine")

    def test_other_policy_document_never_enters_results(self):
        store = self._mixed_store()
        outcome = PolicySearch(store, policy_id="mine").search("8101.94.00 的税率是多少？")
        self.assertEqual(outcome["status"], "candidate_evidence")
        self.assertTrue(all(hit["policy_id"] == "mine" for hit in outcome["hits"]))
        self.assertFalse(any("90 percent" in hit["text"] for hit in outcome["hits"]))
        self.assertTrue(any("policy_id=other" in fragment
                            for fragment in outcome["excluded_fragments"]))

    def test_disabled_never_returns_even_with_superseded_opt_in(self):
        store = self._mixed_store(other_status="disabled")
        outcome = PolicySearch(store, policy_id="mine").search(
            "8101.94.00 的税率是多少？", include_superseded=True)
        self.assertFalse(any(hit["document_status"] == "disabled" for hit in outcome["hits"]))
        # And a superseded doc of another policy stays isolated too.
        store2 = self._mixed_store(other_status="superseded")
        outcome2 = PolicySearch(store2, policy_id="mine").search(
            "8101.94.00 的税率是多少？", include_superseded=True)
        self.assertTrue(all(hit["policy_id"] == "mine" for hit in outcome2["hits"]))

    def test_hit_status_is_visible(self):
        outcome = PolicySearch(self._mixed_store(), policy_id="mine").search("8101.94.00 的税率是多少？")
        self.assertTrue(all(hit["document_status"] == "enabled" for hit in outcome["hits"]))


class F6DependencyTests(unittest.TestCase):
    def _doc(self, extra_paragraph=None, *, undetermined=False):
        texts = [
            {"id": "case:p1", "url": "https://example.test/a",
             "text": "The measures take effect on March 1, 2025 for goods of China."},
            {"id": "case:p2", "url": "https://example.test/a",
             "text": "For products of China classified in 8101.94.00, the additional "
                     "25 percent rate of duty applies."},
        ]
        if extra_paragraph:
            texts.append({"id": "case:p3", "url": "https://example.test/a",
                          "text": extra_paragraph})
        doc = build_document({"policy_id": "case", "data_version": "v1", "sources": texts},
                             doc_id="b", status="enabled")
        mapping = {
            "effective_date": {"status": "known", "section_ids": ["case:p1:para1"]},
            "origin": {"status": "known", "section_ids": ["case:p2:para1"]},
        }
        if extra_paragraph:
            mapping["exceptions"] = {"status": "known", "section_ids": ["case:p3:para1"]}
        elif undetermined:
            mapping["exceptions"] = {"status": "undetermined"}
        else:
            mapping["exceptions"] = {"status": "verified_absent", "note": "已核验无例外。"}
        set_required_dependencies(doc, mapping)
        return doc

    def test_independent_exception_paragraph_is_attached(self):
        exception_text = ("Exclusions: products classified in 8101.94.00 that enter under "
                          "heading 9903.88.03 are excluded from the additional duty.")
        store = _store_with_docs([self._doc(extra_paragraph=exception_text)])
        outcome = PolicySearch(store).search("8101.94.00 的例外是什么？")
        self.assertEqual(outcome["status"], "candidate_evidence")
        blob = "\n".join(hit["text"] for hit in outcome["hits"]) + "\n" + \
               "\n".join(ctx["text"] for ctx in outcome["required_context"] if ctx.get("text"))
        self.assertIn("9903.88.03", blob)

    def test_qualifier_after_500_characters_stays_complete(self):
        long_line = ("For products of China classified in 8101.94.00, the additional "
                     "25 percent rate of duty applies. " + "filler sentence. " * 40 +
                     "Except: goods entered for forging use are excluded.")
        store = _store_with_docs([self._doc(extra_paragraph=long_line)])
        outcome = PolicySearch(store).search("8101.94.00 的例外和限制是什么？")
        blob = "\n".join(hit["text"] for hit in outcome["hits"]) + "\n" + \
               "\n".join(ctx["text"] for ctx in outcome["required_context"] if ctx.get("text"))
        self.assertGreater(len(long_line), 500)
        self.assertIn("goods entered for forging use are excluded", blob)

    def test_undetermined_dependency_blocks_success(self):
        store = _store_with_docs([self._doc(undetermined=True)])
        outcome = PolicySearch(store).search("8101.94.00 的税率是多少？")
        self.assertEqual(outcome["status"], "incomplete_required_context")
        self.assertIn("undetermined", str(outcome["missing_dependencies"]))

    def test_two_codes_with_top_k_one_are_both_reported(self):
        texts = [
            {"id": "case:p1", "url": "https://example.test/a",
             "text": "The measures take effect on March 1, 2025 for goods of China."},
            {"id": "case:p2", "url": "https://example.test/a",
             "text": "For products of China classified in 8101.94.00, the additional "
                     "25 percent rate of duty applies.\n(1) 8101.99.10 tungsten bars: "
                     "additional 25 percent rate of duty."},
        ]
        doc = build_document({"policy_id": "case", "data_version": "v1", "sources": texts},
                             doc_id="b", status="enabled")
        set_required_dependencies(doc, {
            "effective_date": {"status": "known", "section_ids": ["case:p1:para1"]},
            "origin": {"status": "known", "section_ids": ["case:p2:para1"]},
            "exceptions": {"status": "verified_absent", "note": "已核验无例外。"},
        })
        store = _store_with_docs([doc])
        outcome = PolicySearch(store).search("8101.94.00 和 8101.99.10 的税率？", top_k=1)
        self.assertEqual(outcome["status"], "candidate_evidence")
        blob = "\n".join(hit["text"] for hit in outcome["hits"])
        self.assertIn("8101.94.00", blob)
        self.assertIn("8101.99.10", blob)
        self.assertEqual(outcome["uncovered_codes"], [])

    def test_two_versions_of_same_policy_can_be_addressed(self):
        v1 = self._doc()
        changed = deepcopy(RATE_TEXTS)
        changed[1] = dict(changed[1], text=changed[1]["text"] + " Revised February 2025.")
        v2 = build_document({"policy_id": "case", "data_version": "v2", "sources": changed},
                            doc_id="b", status="enabled")
        set_required_dependencies(v2, {
            "effective_date": {"status": "known", "section_ids": ["case:p1:para1"]},
            "origin": {"status": "known", "section_ids": ["case:p2:para1"]},
            "exceptions": {"status": "verified_absent", "note": "已核验无例外。"},
        })
        store = _store_with_docs([v1, v2])
        outcome = PolicySearch(store).search("8101.94.00 的税率是多少？",
                                             doc_versions=[v2["doc_version"]])
        self.assertEqual(outcome["status"], "candidate_evidence")
        self.assertTrue(all(hit["doc_version"] == v2["doc_version"] for hit in outcome["hits"]))
        self.assertTrue(any("Revised February 2025" in hit["text"] for hit in outcome["hits"]))


class F4CoverageTests(unittest.TestCase):
    def test_no_trade_evidence_is_never_exact(self):
        store = build_document_store(
            [build_document({"policy_id": "case", "data_version": "v1",
                             "sources": deepcopy(RATE_TEXTS)}, doc_id="b", status="enabled")],
            policy_id="case")
        version = store["documents"][0]["doc_version"]
        fields = [
            {"field": "hts_codes", "status": "known",
             "value": [{"code": "81019400", "precision": "whole_hts8"}],
             "evidence": [{"doc_version": version, "section_id": "case:p1:para1",
                           "quote": "8101.94.00"}]},
        ]
        candidate = build_candidates(fields, store)
        coverage = build_coverage(candidate)
        self.assertEqual(coverage["trade_coverage"], "not_checked")

    def test_hs6_is_recorded_but_never_extended(self):
        entries = build_coverage.__globals__  # placeholder to avoid lint noise
        from src.tradeintel_ai.policy_candidates import parse_code_precision
        parsed = parse_code_precision([{"code": "810194", "precision": "hs6_only"}])
        self.assertEqual(parsed[0]["precision"], "hs6_only")
        self.assertEqual(len(parsed[0]["code"]), 6)


class F7SessionConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="f7-session-"))

    def test_same_second_creates_are_distinct_and_lossless(self):
        first = create_session(self.root, title="同时创建")
        second = create_session(self.root, title="同时创建")
        self.assertNotEqual(first["session_id"], second["session_id"])
        append_message(self.root, first, "user", "第一条")
        reloaded = load_session(self.root, first["session_id"])
        self.assertEqual(reloaded["messages"][0]["content"], "第一条")

    def test_stale_revision_is_rejected_not_overwritten(self):
        session = create_session(self.root)
        append_message(self.root, session, "user", "消息A")
        stale = load_session(self.root, session["session_id"])
        append_message(self.root, session, "user", "消息B")  # disk moves ahead
        stale["messages"].append({"role": "user", "content": "迟到的并发写入", "at": "x"})
        stale["revision"] += 1
        with self.assertRaises(StaleSessionError):
            save_session(self.root, stale)
        reloaded = load_session(self.root, session["session_id"])
        self.assertIn("消息B", [m["content"] for m in reloaded["messages"]])
        self.assertNotIn("迟到的并发写入", [m["content"] for m in reloaded["messages"]])

    def test_session_id_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            load_session(self.root, "../../etc/passwd")
        with self.assertRaises(ValueError):
            load_session(self.root, "session-ZZZZ")

    def test_repeated_click_claims_generation_once(self):
        session = create_session(self.root)
        set_request(self.root, session, {"policy_id": "case", "month": "2026-07",
                                         "product": "all", "focus": "contrast"},
                    policy_version="pv1", data_version="v1")
        results = []
        for _ in range(2):
            results.append(start_task(self.root, session, model="m", prompt_digest="p"))
        actions = sorted(item["action"] for item in results)
        self.assertEqual(actions, ["create", "in_progress"])
        self.assertEqual(results[0]["task_id"], results[1]["task_id"])


class F8FollowupTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="f8-session-"))
        self.session = create_session(self.root)
        set_request(self.root, self.session, {"policy_id": "case", "month": "2026-07",
                                              "product": "all", "focus": "contrast"},
                    policy_version="pv1", data_version="v1")

    def test_followup_does_not_write_confirmed_request(self):
        outcome = resolve_followup(self.session, "换成81019400呢？")
        self.assertTrue(outcome["confirmation_required"])
        self.assertTrue(outcome["scope_reconfirm_required"])
        self.assertEqual(outcome["candidate_request"]["product"], "81019400")
        reloaded = load_session(self.root, self.session["session_id"])
        self.assertEqual(reloaded["current_request"]["product"], "all")

    def test_switch_pattern_excludes_old_product(self):
        set_request(self.root, self.session, {"policy_id": "case", "month": "2026-07",
                                              "product": "81019910", "focus": "contrast"})
        outcome = resolve_followup(self.session, "把81019910换成81019400")
        self.assertFalse(outcome["needs_clarification"])
        self.assertEqual(outcome["candidate_request"]["product"], "81019400")

    def test_multi_month_is_preserved_and_clarified(self):
        outcome = resolve_followup(self.session, "帮我分别看2026-05和2026-06")
        self.assertIn("2026-05", outcome["needs_clarification"][0])
        self.assertEqual(outcome["multi_request"]["months"], ["2026-05", "2026-06"])
        self.assertIsNone(outcome["candidate_request"].get("month")
                          if outcome.get("changed") else None)

    def test_task_key_includes_policy_version(self):
        start_task(self.root, self.session, model="m", prompt_digest="p")
        reloaded = load_session(self.root, self.session["session_id"])
        task = next(iter(reloaded["tasks"].values()))
        self.assertEqual(task["policy_version"], "pv1")

    def test_unknown_outcome_mark_failed_needs_human_and_records(self):
        created = start_task(self.root, self.session, model="m", prompt_digest="p")["task"]
        transition_task(self.root, self.session, created["task_id"], "evidence_ready")
        transition_task(self.root, self.session, created["task_id"], "generation_started")
        transition_task(self.root, self.session, created["task_id"], "unknown_outcome",
                        reason="中断")
        # The transition map itself must never allow this edge.
        with self.assertRaises(ValueError):
            transition_task(self.root, self.session, created["task_id"], "failed")
        outcome = resolve_unknown_outcome(self.root, self.session, created["task_id"],
                                          resolution="mark_failed", decided_by="user",
                                          note="结果确认丢失")
        self.assertEqual(outcome["action"], "mark_failed")
        reloaded = load_session(self.root, self.session["session_id"])
        stored = next(t for t in reloaded["tasks"].values()
                      if t["task_id"] == created["task_id"])
        self.assertEqual(stored["state"], "failed")
        self.assertIn("decided_by", json.dumps(stored["history"], ensure_ascii=False))

    def test_retry_binds_original_request_snapshot(self):
        created = start_task(self.root, self.session, model="m", prompt_digest="p")["task"]
        transition_task(self.root, self.session, created["task_id"], "evidence_ready")
        transition_task(self.root, self.session, created["task_id"], "generation_started")
        transition_task(self.root, self.session, created["task_id"], "unknown_outcome")
        # The session's request changes before the human retry decision.
        set_request(self.root, self.session, {"policy_id": "case", "month": "2026-06",
                                              "product": "81019400", "focus": "china_amount"})
        outcome = resolve_unknown_outcome(self.root, self.session, created["task_id"],
                                          resolution="retry_authorized", decided_by="user")
        self.assertEqual(outcome["action"], "create")
        reloaded = load_session(self.root, self.session["session_id"])
        new_task = next(t for t in reloaded["tasks"].values()
                        if t["task_id"] == outcome["task_id"])
        self.assertEqual(new_task["request_digest"], created["request_digest"])
        self.assertEqual(new_task["request_snapshot"]["month"], "2026-07")
        self.assertIn("绑定原任务请求", new_task["request_note"] or "")


if __name__ == "__main__":
    unittest.main()
