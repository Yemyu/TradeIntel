"""Boundary tests for review-only model field suggestions."""
from copy import deepcopy
from pathlib import Path
import unittest

from tradeintel_ai.announcement_extraction_pilot import (
    D2_SOURCE_SHA256, D2_SOURCE_URL, adapt_suggestion, extract_d2_text,
    make_disabled_store, prepare_request,
)
from tradeintel_ai.policy_candidates import REQUIRED_FIELDS, build_candidates

ROOT = Path(__file__).resolve().parents[1]


def unknown_answer(version):
    return {"doc_version": version,
            "fields": [{"field": name, "status": "unknown", "value": None,
                        "reason": "正文不足以确定", "evidence": []}
                       for name in REQUIRED_FIELDS]}


class AnnouncementExtractionPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = (ROOT / "evals/policy_extraction_v1/sources/csms-65794272.html").read_bytes()
        cls.text, cls.attachments = extract_d2_text(raw)
        cls.store = make_disabled_store("d2_copper_2025", "csms65794272", cls.text,
                                        url=D2_SOURCE_URL, source_sha256=D2_SOURCE_SHA256)
        cls.version = cls.store["documents"][0]["doc_version"]

    def test_official_text_has_both_rate_bases_and_unsupplied_attachment(self):
        self.assertIn("50 percent additional ad valorem rate of duty", self.text)
        self.assertIn("0 percent additional ad valorem rate of duty", self.text)
        self.assertIn("eastern daylight time", self.text)
        self.assertIn("CopperHTSlist073125.docx", self.text)
        self.assertEqual(len(self.attachments), 1)
        self.assertNotIn("subscriberhelp", self.text)
        request = prepare_request(self.store, self.version)
        self.assertLess(request["request_bytes"], 24_000)

    def test_all_unknown_is_well_formed_but_review_only(self):
        adapted = adapt_suggestion(unknown_answer(self.version), self.store, self.version)
        self.assertEqual(adapted["status"], "review_only")
        self.assertEqual(len(adapted["candidate"]["fields"]), 13)

    def test_quote_is_mapped_only_to_saved_document(self):
        answer = unknown_answer(self.version)
        origin = next(f for f in answer["fields"] if f["field"] == "origin")
        origin.update(status="known", value="all countries", reason=None,
                      evidence=[{"quote": "from all countries, as provided for in headings 9903.78.01"}])
        adapted = adapt_suggestion(answer, self.store, self.version)
        source = next(f for f in adapted["candidate"]["fields"] if f["field"] == "origin")
        self.assertEqual(source["evidence"][0]["doc_version"], self.version)
        wrong = deepcopy(answer)
        next(f for f in wrong["fields"] if f["field"] == "origin")["evidence"] = [
            {"quote": "from all countries, as provided for in headings 9903.78.09"}]
        with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
            adapt_suggestion(wrong, self.store, self.version)
        with self.assertRaisesRegex(ValueError, "identity"):
            adapt_suggestion(answer, self.store, "docver-other")

    def test_reporting_heading_rejected_even_if_it_is_quoted(self):
        answer = unknown_answer(self.version)
        hts = next(f for f in answer["fields"] if f["field"] == "hts_codes")
        hts.update(status="known", value=[{"code": "99037801", "precision": "whole_hts8"}],
                   reason=None, evidence=[{"quote": "Heading 9903.78.01:"}])
        with self.assertRaisesRegex(ValueError, "Chapter 98/99"):
            adapt_suggestion(answer, self.store, self.version)
        with self.assertRaisesRegex(ValueError, "Chapter 98/99"):
            build_candidates([{"field": f["field"], "status": f["status"],
                               "value": f["value"], "reason": f["reason"],
                               "evidence": ([{"doc_version": self.version,
                                              "section_id": self.store["documents"][0]["sections"][0]["id"],
                                              "quote": "CSMS # 65794272"}]
                                            if f["field"] == "hts_codes" else [])}
                              for f in answer["fields"]], self.store,
                             allowed_statuses=("disabled",))

    def test_conditional_copper_rate_keeps_both_bases(self):
        answer = unknown_answer(self.version)
        rates = next(f for f in answer["fields"] if f["field"] == "rates")
        rates.update(status="known", reason=None,
                     value={"kind": "conditional_rates_v1", "rules": [
                         {"reporting_heading": "99037801", "rate_percent": 50,
                          "basis": "value of copper content"},
                         {"reporting_heading": "99037802", "rate_percent": 0,
                          "basis": "value of non-copper content"},
                     ]}, evidence=[
                         {"quote": "Heading 9903.78.01: 50 percent additional ad valorem rate of duty"},
                         {"quote": "Heading 9903.78.02: 0 percent additional ad valorem rate of duty"},
                     ])
        adapted = adapt_suggestion(answer, self.store, self.version)
        saved = next(f for f in adapted["candidate"]["fields"] if f["field"] == "rates")
        self.assertEqual(len(saved["value"]["rules"]), 2)
        broken = deepcopy(answer)
        next(f for f in broken["fields"] if f["field"] == "rates")["value"]["rules"][1]["basis"] = ""
        with self.assertRaisesRegex(ValueError, "invalid heading, percent or basis"):
            adapt_suggestion(broken, self.store, self.version)

    def test_oversize_input_and_enabled_document_stop_preparation(self):
        long_store = make_disabled_store("large", "large-source", "Policy details " * 2400,
                                         url=D2_SOURCE_URL, source_sha256="fixture")
        with self.assertRaisesRegex(ValueError, "exceeds"):
            prepare_request(long_store, long_store["documents"][0]["doc_version"])
        enabled = deepcopy(self.store)
        enabled["documents"][0]["status"] = "enabled"
        with self.assertRaisesRegex(ValueError, "no longer disabled"):
            adapt_suggestion(unknown_answer(self.version), enabled, self.version)

    def test_unknown_with_claim_and_duplicate_fields_are_rejected(self):
        answer = unknown_answer(self.version)
        # The response shape is checked before any semantic review.
        answer["fields"][0]["value"] = "made-up"
        with self.assertRaisesRegex(ValueError, "unknown field"):
            adapt_suggestion(answer, self.store, self.version)
        answer = unknown_answer(self.version)
        answer["fields"][1]["field"] = answer["fields"][0]["field"]
        with self.assertRaisesRegex(ValueError, "duplicated"):
            adapt_suggestion(answer, self.store, self.version)


if __name__ == "__main__":
    unittest.main()
