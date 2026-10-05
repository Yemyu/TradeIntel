"""Finite, offline acceptance of the static four-case export."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts import build_public_showcase as s


class PublicShowcaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = s.make_cases(s.ROOT)

    def test_frozen_sources_and_all_saved_months_are_unchanged(self):
        self.assertEqual({name: s.sha(s.ROOT / name) for name in s.SOURCES}, s.SOURCES)
        for case in self.cases:
            for exported, rid in zip(case["reports"], s.REPORTS.get(case["id"], [])):
                original = s.read_json(s.ROOT / f".local/trade-reports/{rid}.json")["report"]
                self.assertEqual(exported["series"], [{k: row[k] for k in ("month", "status", "value_usd")} for row in original["series"]])
                self.assertEqual(exported["summary"], original["summary"])
            s.validate_case(case)

    def test_case_types_and_guard_are_not_model_success_claims(self):
        policy, guard = self.cases[2:]
        self.assertEqual(policy["turns"], [])
        self.assertEqual(policy["reports"], [])
        self.assertEqual(guard["reports"], [])
        self.assertEqual(guard["guard"]["model_month_selection"], "rejected")
        self.assertEqual(guard["guard"]["requested_month"], "2026-08")
        self.assertEqual(guard["turns"][1]["steps"][-1]["status"], "unavailable")

    def test_saved_reply_translation_excludes_comparisons_present_only_in_report_facts(self):
        for case, deltas in ((self.cases[0], ("13,163,460", "19,416", "3,500,150")),
                             (self.cases[1], ("3,340,380",))):
            source = s.read_json(s.ROOT / f".local/trade-agent-sessions/{s.SESSIONS[case['id']]}.json")
            replies = [turn["text"] for turn in case["turns"] if turn["role"] == "assistant"]
            facts = " ".join(fact["text_en"] for fact in case["reader_view"]["facts"])
            for delta in deltas:
                self.assertIn(delta, facts)
                self.assertTrue(all(delta not in reply["en"] for reply in replies))
            for reply, original in zip(replies, source["turns"]):
                self.assertEqual(reply["zh"], original["message"])
                self.assertIn("2025-08 to 2026-07", reply["en"])
                self.assertEqual(reply["en"], s.translate_saved_answer(original["message"]))

    def test_unknown_saved_replies_and_extra_english_facts_are_refused(self):
        with self.assertRaisesRegex(ValueError, "no verified English translation"):
            s.translate_saved_answer("Unknown saved reply")
        changed = copy.deepcopy(self.cases[0])
        changed["turns"][1]["text"]["en"] += " Increased by 13,163,460 USD."
        with self.assertRaisesRegex(ValueError, "translation mismatch"):
            s.validate_case(changed)

    def test_private_fields_at_each_contract_level_are_rejected(self):
        for layer in ("case", "report", "scope", "row", "fact", "method", "evidence", "step"):
            with self.subTest(layer=layer):
                case = copy.deepcopy(self.cases[0])
                target = {"case": case, "report": case["reports"][0], "scope": case["reports"][0]["scope"],
                          "row": case["reports"][0]["series"][0], "fact": case["reader_view"]["facts"][0],
                          "method": case["reader_view"]["method"], "evidence": case["evidence_meta"],
                          "step": case["turns"][1]["steps"][0]}[layer]
                target["raw"] = "not publishable"
                with self.assertRaises(ValueError):
                    s.validate_case(case)

    def test_private_paths_and_credential_shapes_anywhere_are_rejected(self):
        for text in ("/Users/test/private", ".local/ledger", "tmp/handoff/runs", "sk-not-a-real-secret-value",
                     "a" * 32 + ".not_a_real_secret", "http://localhost:8000", "file:///private", "javascript:alert(1)"):
            case = copy.deepcopy(self.cases[0]); case["turns"][0]["text"]["en"] = text
            with self.subTest(text=text), self.assertRaises(ValueError):
                s.validate_case(case)

    def test_urls_only_allow_official_uncredentialed_sources(self):
        for value in ("https://www.census.gov.evil.test/a", "https://me:password@www.census.gov/a",
                      "https://www.census.gov:443/a", "https://content.govdelivery.com/accounts/OTHER/a",
                      "https://api.deepseek.com/chat", "https://www.census.gov/a?api_key=abc"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                s.url(value)
        s.url("https://www.census.gov/trade/downloads/2026/Merch/ex_m/EXDB2607.ZIP")

    def test_amounts_aliases_and_statistics_cannot_drift(self):
        for layer in ("amount", "partner", "metric", "alias"):
            case = copy.deepcopy(self.cases[0])
            if layer == "amount": case["reports"][0]["series"][-1]["value_usd"] += 1
            if layer == "partner": case["reports"][0]["scope"]["partner"] = "OTHER"
            if layer == "metric": case["reports"][0]["scope"]["metric"] = "net_exports"
            if layer == "alias": case["turns"][1]["reports"] = ["r999"]
            with self.subTest(layer=layer), self.assertRaises(ValueError):
                s.validate_case(case)

    def test_build_is_whitelisted_and_verify_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory) / "site"
            before = {name: s.sha(s.ROOT / name) for name in s.SOURCES}
            result = s.build(s.ROOT, site)
            self.assertEqual(result, {"case_count": 4, "asset_count": 14, "status": "verified"})
            html = (site / "index.html").read_text()
            for forbidden in ('src="live.js"', 'id="question-form"', 'id="open-model-settings"'):
                self.assertNotIn(forbidden, html)
            self.assertNotIn("source", s.read_json(site / "data.json"))
            self.assertIn("source", s.read_json(s.WEB / "data.json"))
            self.assertEqual(before, {name: s.sha(s.ROOT / name) for name in s.SOURCES})
            audit_hash = s.sha(site.parent / "audit/manifest.json")
            s.verify(site)
            self.assertEqual(audit_hash, s.sha(site.parent / "audit/manifest.json"))
            self.assertFalse((site / "audit").exists())
            with self.assertRaises(ValueError): s.build(s.ROOT, site)

    def test_modified_or_interrupted_candidates_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory) / "site"; s.build(s.ROOT, site)
            data = s.read_json(site / "cases/soybean-trade.json")
            data["reader_view"]["facts"][0]["text"] = "新增的无据说法"
            s.save_json(site / "cases/soybean-trade.json", data)
            with self.assertRaises(ValueError): s.verify(site)
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory) / "site"; site.mkdir()
            with self.assertRaises(ValueError): s.verify(site)
            with self.assertRaises(ValueError): s.build(s.ROOT, site)

    def test_duplicate_keys_nan_and_symlinks_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x.json"
            for invalid in ('{"x":1,"x":2}', '{"x":NaN}'):
                path.write_text(invalid)
                with self.assertRaises(ValueError): s.read_json(path)
            site = Path(directory) / "site"; s.build(s.ROOT, site)
            (site / "extra").symlink_to(path)
            with self.assertRaises(ValueError): s.verify(site)

    def test_manifest_identity_and_extra_fields_are_refused(self):
        data = s.catalog(); s.validate_catalog(data)
        for mutate in (lambda x: x.update({"config": {}}),
                       lambda x: x["cases"][0].update({"asset": "../../config.json"}),
                       lambda x: x["cases"][2].update({"model": {"request_name": "fake", "reasoning": "high"}})):
            changed = copy.deepcopy(data); mutate(changed)
            with self.assertRaises(ValueError): s.validate_catalog(changed)

    def test_malformed_identifier_and_nested_value_types_fail_controlled(self):
        for value in ({}, [], True, None, 12):
            for field in ("id", "report_id", "product_label", "primary_report", "month"):
                case = copy.deepcopy(self.cases[0])
                if field == "id": case[field] = value
                elif field == "primary_report":
                    if value is None: continue  # Explicitly allowed.
                    case["turns"][1][field] = value
                elif field == "month": case["reports"][0]["series"][0][field] = value
                elif field == "product_label": case["reports"][0]["scope"][field] = value
                else: case["reports"][0][field] = value
                with self.subTest(value=value, field=field), self.assertRaises(ValueError): s.validate_case(case)


if __name__ == "__main__":
    unittest.main()
