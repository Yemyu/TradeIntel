from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tradeintel_ai.host_review import HostReviewPending, HostReviewStore
from tradeintel_ai.prospective_acceptance import AcceptanceGuardError, digest


class HostReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "reviews"
        self.snapshot = {"configuration": {"model": "offline-test"}, "questions": ["q"]}
        self.store = self.reopen()
        self.packet = {
            "case_id": "q", "expected_kind": "clarification", "expected_tasks": [],
            "preview": {"status": "needs_clarification"},
            "checklist": [{"id": "scope", "kind": "fact"}],
        }
        self.submission = {
            "packet_sha256": digest(self.packet),
            "overall": {"status": "fail", "reason": "Test reviewer rejects missing explanation"},
            "items": [{"id": "scope", "status": "fail", "reason": "Explanation absent"}],
        }

    def reopen(self):
        return HostReviewStore(self.path, snapshot=self.snapshot, reviewer="test-host")

    def test_pending_then_explicit_rejection_survives_reopen(self):
        path = self.store.request("q:plan", self.packet, kind="plan")
        self.assertTrue(path.is_file())
        with self.assertRaises(HostReviewPending):
            self.reopen().receive("q:plan")
        decision = self.reopen().submit("q:plan", self.submission)
        self.assertFalse(decision["approved"])
        self.assertEqual(self.reopen().receive("q:plan"), self.submission)

    def test_changed_snapshot_or_reviewer_rejected(self):
        for snapshot, reviewer in (({"changed": True}, "test-host"), (self.snapshot, "other-host")):
            with self.assertRaises(AcceptanceGuardError):
                HostReviewStore(self.path, snapshot=snapshot, reviewer=reviewer)

    def test_slot_cannot_be_rebound_to_new_packet(self):
        self.store.request("q:plan", self.packet, kind="plan")
        changed = {**self.packet, "case_id": "another-question"}
        with self.assertRaises(AcceptanceGuardError):
            self.reopen().request("q:plan", changed, kind="plan")

    def test_stale_or_empty_submission_not_published(self):
        self.store.request("q:plan", self.packet, kind="plan")
        for submission in ({}, {**self.submission, "packet_sha256": "old-answer"}):
            with self.assertRaises(AcceptanceGuardError):
                self.store.submit("q:plan", submission)
        with self.assertRaises(HostReviewPending):
            self.store.receive("q:plan")

    def test_duplicate_identical_submission_idempotent_conflict_rejected(self):
        self.store.request("q:plan", self.packet, kind="plan")
        self.store.submit("q:plan", self.submission)
        self.reopen().submit("q:plan", self.submission)
        changed = deepcopy(self.submission)
        changed["overall"]["reason"] = "different decision"
        with self.assertRaises(AcceptanceGuardError):
            self.reopen().submit("q:plan", changed)
        self.assertEqual(self.store.receive("q:plan"), self.submission)

    def test_corrupt_packet_and_submission_fail_closed(self):
        packet_path = self.store.request("q:plan", self.packet, kind="plan")
        self.store.submit("q:plan", self.submission)
        receipt = next(self.path.glob("*.submission.json"))
        original = receipt.read_text()
        value = json.loads(original)
        value["validation"]["approved"] = True
        receipt.write_text(json.dumps(value))
        with self.assertRaises(AcceptanceGuardError):
            self.reopen().receive("q:plan")
        receipt.write_text(original)
        packet_path.write_text('{"incomplete":')
        with self.assertRaises(AcceptanceGuardError):
            self.reopen().receive("q:plan")

    def test_unpublished_temporary_file_does_not_become_a_decision(self):
        self.store.request("q:plan", self.packet, kind="plan")
        (self.path / ".review-interrupted").write_text('{"partial":')
        with self.assertRaises(HostReviewPending):
            self.reopen().receive("q:plan")

    def test_callback_persists_then_receives_only_explicit_submission(self):
        callback = self.store.callback(kind="plan")
        with self.assertRaises(HostReviewPending):
            callback(self.packet)
        self.reopen().submit("q:plan:", self.submission)
        self.assertEqual(self.reopen().callback(kind="plan")(self.packet), self.submission)

    def test_path_like_slot_cannot_escape_store(self):
        path = self.store.request("../../outside", self.packet, kind="plan")
        self.assertEqual(path.parent, self.path)

    def test_explicit_fact_review_accepts_correct_uncited_baseline_and_rejects_negation(self):
        # Test-only judgements: the store itself never generates these labels.
        for contradicted in (False, True):
            packet = {
                "version": "fact-review-packet-0119", "case_id": "policy",
                "arm": "without_evidence", "policy_question": "额外税率？",
                "policy_as_of": "2018-07-06", "reference_sha256": "a" * 64,
                "facts": [{"id": "rate", "evidence_ids": ["source"]}],
                "evidence": {"source": {"text": "additional duty of 25 percent"}},
                "answer": {"claims": [{"text": "不是25%" if contradicted else "25%", "citations": []}]},
            }
            label = "contradicted" if contradicted else "supported"
            submission = {
                "case_id": "policy", "arm": "without_evidence", "reviewer": "test-host",
                "reviewed_at": "2026-09-13T00:00:00Z", "packet_sha256": digest(packet),
                "facts": [{"id": "rate", "status": label, "reason": "Explicit test judgement",
                           "claim_indices": [0], "source_id": "source",
                           "evidence_excerpt": "additional duty of 25 percent"}],
                "claims": [{"index": 0, "status": label, "reason": "Explicit test judgement", "fact_ids": ["rate"]}],
                "citation_review": {"status": "not_applicable"},
            }
            slot = f"baseline-{contradicted}"
            self.store.request(slot, packet, kind="facts")
            decision = self.reopen().submit(slot, submission)
            self.assertEqual(decision["approved"], not contradicted)
            self.assertEqual(self.reopen().receive(slot), submission)


if __name__ == "__main__":
    unittest.main()
