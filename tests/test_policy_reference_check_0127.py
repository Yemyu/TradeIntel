"""The policy reference check is source-bound but never self-certifies a human review."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.verify_policy_reference import DEFAULT_FACTS, DEFAULT_PDF, run_check


class PolicyReferenceCheck0127Tests(unittest.TestCase):
    def test_official_pdf_and_frozen_facts_match_pending_human_review(self):
        report = run_check(pdf_path=DEFAULT_PDF, facts_path=DEFAULT_FACTS)
        self.assertEqual(report["status"], "ai_assisted_check_passed_pending_human_review")
        self.assertTrue(all(report["checks"].values()))
        self.assertEqual(report["human_review"]["status"], "pending_independent_human_review")

    def test_approved_label_without_review_is_blocked(self):
        facts = json.loads(DEFAULT_FACTS.read_text(encoding="utf-8"))
        facts = deepcopy(facts)
        facts["review_status"] = "approved"
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "facts.json"
            path.write_text(json.dumps(facts, ensure_ascii=False), encoding="utf-8")
            report = run_check(pdf_path=DEFAULT_PDF, facts_path=path)
        self.assertEqual(report["status"], "blocked_before_human_review")
        self.assertFalse(report["checks"]["facts_review_status_is_pending"])

