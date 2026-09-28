"""E2 contract regressions: saved text, field shapes and package readback."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.audit_policy_extraction_e2 import probe
from scripts.prepare_policy_extraction_pilot import prepare, verify_package
from tradeintel_ai.announcement_extraction_pilot import (
    _has_code, adapt_suggestion, encode_provider_request, make_disabled_store, prepare_request,
    validate_provider_request,
)
from tradeintel_ai.policy_candidates import REQUIRED_FIELDS


def answer_for(text: str):
    store = make_disabled_store("e2", "e2", text, url="https://example.invalid/e2",
                                source_sha256="fixture")
    version = store["documents"][0]["doc_version"]
    answer = {"doc_version": version,
              "fields": [{"field": name, "status": "unknown", "value": None,
                          "reason": "未见相关原文", "evidence": []} for name in REQUIRED_FIELDS]}
    return store, version, answer


def known(answer, name, value, quote, *, occurrence=None):
    item = next(field for field in answer["fields"] if field["field"] == name)
    cite = {"quote": quote}
    if occurrence is not None:
        cite["occurrence"] = occurrence
    item.update(status="known", value=value, reason=None, evidence=[cite])


class E2ContractTests(unittest.TestCase):
    def test_hts10_standard_dotted_form_and_full_boundaries(self):
        code = "9401614011"
        for quote in ("9401614011", "9401.61.40.11", "9401.61.4011"):
            with self.subTest(quote=quote):
                self.assertTrue(_has_code(quote, code))
        for quote in ("9401.61.40", "9401.61.401", "9401.61.40112",
                      "19401.61.4011", "9401.61.4011.7", "9401 61 4011"):
            with self.subTest(quote=quote):
                self.assertFalse(_has_code(quote, code))
        self.assertFalse(_has_code("9401.61.4011", "94016140"))
        store, version, answer = answer_for("Furniture code 9401.61.4011 applies.")
        known(answer, "hts_codes", [{"code": code, "precision": "hts10_partial"}],
              "Furniture code 9401.61.4011 applies.")
        self.assertEqual(adapt_suggestion(answer, store, version)["status"], "review_only")

    def test_undotted_hts8_with_federal_register_leader_dots(self):
        self.assertTrue(_has_code(
            "28046100.............................  Silicon containing by weight", "28046100"))
        self.assertFalse(_has_code("2804610000........................  longer code", "28046100"))
        self.assertFalse(_has_code("28046100.7", "28046100"))

    def test_seven_reproduced_cases_have_correct_outcomes(self):
        bad = [
            ("50 percent duty", "rates", {"kind": "conditional_rates_v1", "rules": [
                {"reporting_heading": None, "rate_percent": 0, "basis": "content"}]}, "50 percent duty"),
            ("Effective August 1, 2025", "effective_date", {"wrong": "type"}, "Effective August 1, 2025"),
            ("Only HTS 2804.61.00.10 applies", "hts_codes",
             [{"code": "28046100", "precision": "whole_hts8"}], "Only HTS 2804.61.00.10 applies"),
            ("parts 28 batch 04 size 61 revision 00", "hts_codes",
             [{"code": "28046100", "precision": "whole_hts8"}],
             "parts 28 batch 04 size 61 revision 00"),
        ]
        for text, field, value, quote in bad:
            with self.subTest(field=field, text=text):
                self.assertEqual(probe("e2", text, field, value, [quote])["result"], "rejected")
        self.assertEqual(probe("wrapped", "The rate is based on\ncopper content value.",
                               "rate_meaning", "copper content value",
                               ["The rate is based on\ncopper content value."])["result"], "accepted")
        self.assertEqual(probe("decimal", "50 percent duty", "rates",
                               {"kind": "conditional_rates_v1", "rules": [
                                   {"reporting_heading": None, "rate_percent": 50.0, "basis": "content"}]},
                               ["50 percent duty"])["result"], "accepted")
        store, version, _ = answer_for("Original saved source.")
        store["documents"][0]["sections"][0]["text"] = "Changed without new digest."
        with self.assertRaisesRegex(ValueError, "digest"):
            prepare_request(store, version)

    def test_field_types_and_unknowns(self):
        store, version, answer = answer_for("Title. 2025-02-28 24:00 Some conditions.")
        invalid = {"title": {}, "publication_date": "2025-02-30", "effective_date": {},
                   "clock_24h": "24:00", "timezone": [], "entry_events": [""],
                   "origin": {}, "rate_meaning": "", "conditions": [],
                   "exceptions": [1], "revisions": "text"}
        for name, value in invalid.items():
            candidate = deepcopy(answer)
            known(candidate, name, value, "Title.")
            with self.subTest(name=name), self.assertRaises(ValueError):
                adapt_suggestion(candidate, store, version)
        bad_unknown = deepcopy(answer)
        bad_unknown["fields"][0]["reason"] = ""
        with self.assertRaisesRegex(ValueError, "unknown"):
            adapt_suggestion(bad_unknown, store, version)

    def test_code_precision_duplicates_and_simple_rate_scope(self):
        text = "HTS 2804.61.00: 50 percent duty."
        store, version, answer = answer_for(text)
        known(answer, "hts_codes", [{"code": "28046100", "precision": "whole_hts8"}], text)
        known(answer, "rates", {"28046100": 50}, text)
        self.assertEqual(adapt_suggestion(answer, store, version)["status"], "review_only")
        bad = deepcopy(answer)
        next(field for field in bad["fields"] if field["field"] == "hts_codes")["value"].append(
            {"code": "28046100", "precision": "whole_hts8"})
        with self.assertRaisesRegex(ValueError, "duplicate"):
            adapt_suggestion(bad, store, version)
        bad = deepcopy(answer)
        next(field for field in bad["fields"] if field["field"] == "rates")["value"] = {"28046100": True}
        with self.assertRaisesRegex(ValueError, "finite"):
            adapt_suggestion(bad, store, version)
        bad = deepcopy(answer)
        next(field for field in bad["fields"] if field["field"] == "rates")["value"] = {"28046101": 50}
        with self.assertRaisesRegex(ValueError, "known HTS8"):
            adapt_suggestion(bad, store, version)

    def test_repeated_and_cross_section_quotes_keep_original_location(self):
        store, version, answer = answer_for("First line\nSecond line\nFirst line\n")
        known(answer, "title", "First line", "First line")
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            adapt_suggestion(answer, store, version)
        known(answer, "title", "First line", "First line", occurrence=2)
        result = adapt_suggestion(answer, store, version)
        self.assertEqual(result["original_evidence"]["title"][0]["occurrence"], 2)
        known(answer, "title", "First line Second line", "First line\nSecond line")
        result = adapt_suggestion(answer, store, version)
        self.assertEqual(len(next(f for f in result["candidate"]["fields"]
                                  if f["field"] == "title")["evidence"]), 2)
        self.assertEqual(len(result["original_evidence"]["title"][0]["section_ids"]), 2)

    def test_prompt_and_final_request_budget(self):
        store, version, _ = answer_for("Unrelated test notice.")
        prepared = prepare_request(store, version)
        prompt = prepared["messages"][0]["content"]
        self.assertNotIn("99037801", prompt)
        self.assertNotIn("copper content value", prompt)
        self.assertIn("hts10_partial", prompt)
        self.assertGreater(validate_provider_request({"model": "test", "messages": prepared["messages"]},
                                                     prepared), prepared["request_bytes"])
        self.assertEqual(validate_provider_request({"model": "test", "messages": prepared["messages"]},
                                                   prepared),
                         len(encode_provider_request({"model": "test", "messages": prepared["messages"]},
                                                     prepared)))
        with self.assertRaisesRegex(ValueError, "exceeds"):
            validate_provider_request({"model": "test", "messages": prepared["messages"],
                                       "extra": "x" * 24_000}, prepared)

    def test_package_verify_rejects_tampered_request_even_with_updated_file_hash(self):
        with TemporaryDirectory() as temp:
            package = Path(temp) / "d2"
            prepare("d2", package)
            self.assertEqual(verify_package(package)["status"], "verified")
            request_path = package / "request.json"
            manifest_path = package / "manifest.json"
            request = json.loads(request_path.read_text(encoding="utf-8"))
            request["messages"][0]["content"] += " Altered prompt."
            encoded = json.dumps(request["messages"], ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":")).encode()
            request["request_bytes"] = len(encoded)
            request["request_sha256"] = hashlib.sha256(encoded).hexdigest()
            request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files_sha256"]["request.json"] = hashlib.sha256(request_path.read_bytes()).hexdigest()
            manifest["request_bytes"] = request["request_bytes"]
            manifest["request_sha256"] = request["request_sha256"]
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "request differs"):
                verify_package(package)

    def test_package_verify_rejects_interrupted_and_stale_code(self):
        with TemporaryDirectory() as temp:
            incomplete = Path(temp) / "incomplete"
            incomplete.mkdir()
            with self.assertRaisesRegex(ValueError, "manifest"):
                verify_package(incomplete)
            package = Path(temp) / "d2"
            prepare("d2", package)
            manifest_path = package / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["code_sha256"]["src/tradeintel_ai/announcement_extraction_pilot.py"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "code changed"):
                verify_package(package)

    def test_acceptance_packages_keep_reference_out_of_provider_request(self):
        with TemporaryDirectory() as temp:
            for case, critical, ordinary in (("h1", 46, 5), ("h2", 25, 4)):
                with self.subTest(case=case):
                    package = Path(temp) / case
                    prepare(case, package)
                    self.assertEqual(verify_package(package)["status"], "verified")
                    scorecard = json.loads((package / "scorecard.json").read_text(encoding="utf-8"))
                    request = json.loads((package / "request.json").read_text(encoding="utf-8"))
                    source = (package / "source.txt").read_text(encoding="utf-8")
                    self.assertEqual((scorecard["critical_facts"], scorecard["ordinary_facts"]),
                                     (critical, ordinary))
                    self.assertEqual(len(scorecard["facts"]), critical + ordinary)
                    self.assertLess(request["request_bytes"], 24_000)
                    self.assertNotIn("H1-CODE-", json.dumps(request))
                    self.assertNotIn("H2-CODE-", json.dumps(request))
                    for fact in scorecard["facts"]:
                        self.assertIsNone(fact["model_score"])
                        for cite in fact["evidence"]:
                            self.assertEqual(source[cite["start"]:cite["end"]], cite["quote"])
                            self.assertTrue(cite["section_ids"])

    def test_acceptance_package_missing_or_tampered_scorecard_is_rejected(self):
        with TemporaryDirectory() as temp:
            package = Path(temp) / "h2"
            prepare("h2", package)
            scorecard_path = package / "scorecard.json"
            scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
            scorecard["facts"][0]["evidence"][0]["quote"] = "wrong"
            scorecard_path.write_text(json.dumps(scorecard), encoding="utf-8")
            manifest_path = package / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files_sha256"]["scorecard.json"] = hashlib.sha256(scorecard_path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "scorecard differs"):
                verify_package(package)
            scorecard_path.unlink()
            with self.assertRaisesRegex(ValueError, "scorecard.json"):
                verify_package(package)


if __name__ == "__main__":
    unittest.main()
