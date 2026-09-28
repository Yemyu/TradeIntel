"""K4 deterministic CBP parser and parser -> K3 chain."""
import json
from pathlib import Path
import tempfile
import unittest

from src.tradeintel_ai.announcement_parser import parse_announcement_text, parse_saved_candidate
from src.tradeintel_ai.announcement_flow import confirm_and_enable, submit_candidates
from src.tradeintel_ai.policy_candidates import REQUIRED_FIELDS
from src.tradeintel_ai.source_registry import fetch_source, save_candidate
from src.tradeintel_ai.web_app import _handle_announcement_import

ROOT = Path(__file__).resolve().parents[1]


def corpus_text():
    corpus = json.loads((ROOT / "data/processed/policy_exposure/policy_corpus.json").read_text(encoding="utf-8"))
    wanted = {"cbp63577329:p8", "cbp63577329:p9", "cbp63577329:p12"}
    return "\n\n".join(chunk["text"] for chunk in corpus["chunks"] if chunk["id"] in wanted)


class K4AnnouncementParserTests(unittest.TestCase):
    def test_real_corpus_extracts_effective_date_rates_and_five_codes(self):
        parsed = parse_announcement_text("policy-k4", "cbp63577329:parsed", corpus_text())
        fields = {field["field"]: field for field in parsed["fields"]}
        self.assertEqual(fields["effective_date"]["value"], "2025-01-01")
        self.assertEqual(fields["origin"]["value"], "China")
        self.assertEqual({item["code"] for item in fields["hts_codes"]["value"]},
                         {"28046100", "38180000", "81019400", "81019910", "81019980"})
        self.assertEqual(fields["rates"]["value"], {
            "28046100": 50, "38180000": 50,
            "81019400": 25, "81019910": 25, "81019980": 25,
        })
        self.assertTrue(fields["exceptions"]["status"] == "unknown")
        for field in parsed["fields"]:
            for evidence in field.get("evidence", []):
                section = next(item for item in parsed["document"]["sections"]
                                if item["id"] == evidence["section_id"])
                self.assertIn(evidence["quote"], section["text"])

    def test_missing_rate_is_unknown_not_guessed(self):
        text = "The tariff increases take effect on January 1, 2025, with respect to goods entered for consumption, or withdrawn from warehouse for consumption, on or after 12:01 a.m. eastern standard time."
        parsed = parse_announcement_text("policy-k4", "notice:missing-rate", text)
        fields = {field["field"]: field for field in parsed["fields"]}
        self.assertEqual(fields["rates"]["status"], "unknown")
        self.assertEqual(fields["hts_codes"]["status"], "unknown")
        self.assertIn("未找到", fields["rates"]["reason"])

    def test_parser_output_reaches_k3_enable_without_network(self):
        text = corpus_text()
        parsed = parse_announcement_text("policy-k4", "cbp63577329:parsed", text)
        with tempfile.TemporaryDirectory(prefix="k4-chain-") as directory:
            root = Path(directory)
            imported = _handle_announcement_import(root, {
                "policy_id": "policy-k4", "source_id": "cbp63577329:parsed", "text": text,
            })
            self.assertEqual(imported["doc_version"], parsed["document"]["doc_version"])
            candidate = submit_candidates(root, "policy-k4", imported["doc_version"],
                                           parsed["fields"])
            self.assertEqual(candidate["status"], "candidate_ready")
            ready = submit_candidates(root, "policy-k4", imported["doc_version"], parsed["fields"])
            enabled = confirm_and_enable(root, "policy-k4", imported["doc_version"],
                                         parsed["fields"], confirmed_by="k4-test",
                                         expected_candidate_digest=ready["candidate_digest"])
            self.assertEqual(enabled["status"], "enabled")
            self.assertEqual(enabled["coverage"]["trade_coverage"], "not_checked")
            self.assertEqual(len(parsed["fields"]), len(REQUIRED_FIELDS))

    def test_hash_verified_fetch_save_reload_parse_chain(self):
        text = corpus_text().encode("utf-8")
        with tempfile.TemporaryDirectory(prefix="k4-source-chain-") as directory:
            root = Path(directory)
            fetched = fetch_source("cbp-csms-63577329",
                                  transport=lambda url, timeout: (text, url))
            saved = save_candidate(root, fetched, text)
            record = json.loads((root / saved["record_path"]).read_text(encoding="utf-8"))
            parsed = parse_saved_candidate(root, "policy-k4", record)
            fields = {field["field"]: field for field in parsed["fields"]}
            self.assertEqual(fields["effective_date"]["value"], "2025-01-01")
            self.assertEqual(parsed["document"]["url"], fetched["final_url"])


if __name__ == "__main__":
    unittest.main()
