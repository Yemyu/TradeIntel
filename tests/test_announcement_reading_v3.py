"""Offline v3 checks; the synthetic notice is not observed policy evidence."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.prepare_announcement_reading_v3_offline import prepare, verify
from scripts.run_announcement_reading_v3_fake import run_fake
from tradeintel_ai.announcement_extraction_pilot import make_disabled_store
from tradeintel_ai.announcement_reading_v3 import (
    CHECKS, CHECK_IDS, FIELDS, MAX_ANSWER_BYTES, MAX_MESSAGE_BYTES,
    SCHEMA, build_reading_package, parse_reading_answer, verify_reading_package,
)


def synthetic_notice(country: str = "Orion", first_date: str = "2026-01-10") -> str:
    """54 dispersed passages, with dates/footnotes deliberately far apart."""
    parts = [f"Administrative record line {number}; not a rate rule."
             for number in range(1, 55)]
    updates = {
        2: "The agency amends two different trade measures, Alpha and Beta.",
        3: "Alpha is an additional duty, not the complete tariff burden.",
        4: "Eligible Alpha deposits may be reassessed and refunded after review.",
        5: "Ordinary customs duties remain independently applicable.",
        7: f"Alpha applies to goods originating in {country}.",
        8: "The additional Alpha duty does not replace other duties.",
        12: "This action does not set an aggregate tariff rate.",
        13: f"Beta applies to goods originating in Lyra, not {country}.",
        16: "The covered product is alloy plate under code 88001100, subject to its description.",
        23: "The amendment becomes effective on 2026-07-01.",
        31: f"Alpha: {country} group I entries from {first_date} are within the review period.",
        32: f"Alpha: {country} group II entries from 2026-02-12 are within the review period.",
        38: "Beta: Lyra group I entries from 2026-03-14 are within the review period.",
        41: "Beta: Lyra group II entries from 2026-04-16 are within the review period.",
        45: "The event is entry for consumption or withdrawal from warehouse for consumption.",
        49: "Exclusion requires both certification and the specified end use.",
        50: "Certification alone is insufficient for the exclusion.",
        54: "Footnote: code 88001100 and the written alloy-plate description both control exclusion.",
    }
    for number, text in updates.items():
        parts[number - 1] = text
    return "\n\n".join(parts) + "\n"


def fixture(text: str | None = None):
    text = synthetic_notice() if text is None else text
    store = make_disabled_store("synthetic-policy", "synthetic-source", text,
                                url="https://example.gov/synthetic-notice",
                                source_sha256=hashlib.sha256(text.encode()).hexdigest())
    version = store["documents"][0]["doc_version"]
    return store, version, build_reading_package(store, version)


def complete_answer(package, country: str = "Orion",
                    first_date: str = "2026-01-10"):
    rows = [
        ("policy_action", "The agency amends Alpha and Beta.", ["P2"]),
        ("measure_nature", "Alpha is additional; ordinary duties remain.",
         ["P3", "P5", "P8", "P12"]),
        ("assessment_effect", "Eligible deposits may be reassessed and refunded.", ["P4"]),
        ("origin_by_measure", f"Alpha covers {country} origin.", ["P7"]),
        ("origin_by_measure", f"Beta covers Lyra origin, not {country}.", ["P13"]),
        ("product_scope", "Alloy plate code 88001100 is subject to its description.", ["P16"]),
        ("effective_date", "The effective date is 2026-07-01.", ["P23"]),
        ("retroactive_starts", f"Alpha {country} group I starts {first_date}.", ["P31"]),
        ("retroactive_starts", f"Alpha {country} group II starts 2026-02-12.", ["P32"]),
        ("retroactive_starts", "Beta Lyra group I starts 2026-03-14.", ["P38"]),
        ("retroactive_starts", "Beta Lyra group II starts 2026-04-16.", ["P41"]),
        ("entry_event", "Entry or withdrawal from warehouse for consumption matters.", ["P45"]),
        ("exclusion_conditions", "Certification and specified end use are both needed.",
         ["P49", "P50"]),
        ("code_description", "The code and written description both control exclusion.",
         ["P54"]),
    ]
    claims_by_field = {field: [] for field in FIELDS}
    checks_by_field = {field: [] for field in FIELDS}
    for number, (check_id, text, refs) in enumerate(rows, 1):
        field = next(owner for cid, owner, _ in CHECKS if cid == check_id)
        claims_by_field[field].append({
            "claim_id": f"C{number}", "text": text, "anchors": refs,
            "check_ids": [check_id],
        })
    for check_id, field, _ in CHECKS:
        checks_by_field[field].append({
            "check_id": check_id, "status": "addressed",
            "claim_ids": [claim["claim_id"] for claim in claims_by_field[field]
                          if check_id in claim["check_ids"]],
            "note": "",
        })
    return {
        "schema_version": SCHEMA, "doc_version": package["doc_version"],
        "source_sha256": package["source_sha256"],
        "items": [{"field": field, "claims": claims_by_field[field],
                   "checks": checks_by_field[field]} for field in FIELDS],
    }


def reference_gap(answer: dict, expected_phrase: str) -> bool:
    """Test-only stand-in for a human reference sheet, never a production validator."""
    return not any(expected_phrase in claim["text"]
                   for item in answer["items"] for claim in item["claims"])


class AnnouncementReadingV3Test(unittest.TestCase):
    def setUp(self):
        self.store, self.version, self.package = fixture()

    def parse(self, answer):
        return parse_reading_answer(json.dumps(answer, ensure_ascii=False),
                                    self.package, self.store)

    def test_54_dispersed_passages_reconstruct_source_and_14_claims_parse(self):
        self.assertEqual(len(self.package["anchors"]), 54)
        self.assertEqual("".join(a["text"] for a in self.package["anchors"].values()),
                         synthetic_notice())
        self.assertLessEqual(self.package["request_bytes"], MAX_MESSAGE_BYTES)
        answer = complete_answer(self.package)
        self.assertLessEqual(len(json.dumps(answer, ensure_ascii=False).encode()), MAX_ANSWER_BYTES)
        result = self.parse(answer)
        self.assertEqual(result["status"], "review_only")
        self.assertTrue(result["ready_for_review"])
        self.assertEqual(len(result["items"][1]["claims"]), 9)  # old v2 capped at six
        self.assertEqual(len(result["items"][0]["claims"][1]["source_passages"]), 4)
        self.assertEqual([check["check_id"] for item in result["items"]
                          for check in item["checks"]], list(CHECK_IDS))
        self.assertNotIn("candidate", result)
        self.assertNotIn("enabled", result)

    def test_prompt_is_generic_and_not_hardcoded_to_seen_notice(self):
        prompt = self.package["messages"][0]["content"]
        self.assertIn("retroactive_starts", prompt)
        self.assertNotIn("FR2026-19516", prompt)
        self.assertNotIn("2026-01-10", prompt)
        self.assertNotIn("Orion", prompt)

    def test_identity_and_mutated_country_date(self):
        old_answer = complete_answer(self.package)
        changed_store, _, changed_package = fixture(
            synthetic_notice(country="Vega", first_date="2026-05-20"))
        with self.assertRaisesRegex(ValueError, "not bound"):
            parse_reading_answer(json.dumps(old_answer), changed_package, changed_store)
        with self.assertRaises(ValueError):
            verify_reading_package(changed_store, self.package)
        changed_answer = complete_answer(changed_package, country="Vega",
                                         first_date="2026-05-20")
        self.assertEqual(parse_reading_answer(json.dumps(changed_answer),
                                              changed_package, changed_store)["status"],
                         "review_only")

    def test_missing_duplicate_and_wrong_field_checks_are_rejected(self):
        base = complete_answer(self.package)
        cases = []
        changed = deepcopy(base); changed["items"][1]["checks"].pop(); cases.append(changed)
        changed = deepcopy(base); changed["items"][1]["checks"][0]["check_id"] = "policy_action"; cases.append(changed)
        changed = deepcopy(base); changed["items"][1]["checks"].append(changed["items"][1]["checks"][0]); cases.append(changed)
        changed = deepcopy(base); changed["items"][1]["field"] = "rate_meaning"; cases.append(changed)
        for answer in cases:
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                self.parse(answer)

    def test_claim_and_source_link_malformations_are_rejected(self):
        base = complete_answer(self.package)
        cases = []
        changed = deepcopy(base); changed["items"][1]["claims"][0]["anchors"] = ["P999"]; cases.append(changed)
        changed = deepcopy(base); changed["items"][1]["claims"][0]["anchors"] = ["P7", "P7"]; cases.append(changed)
        changed = deepcopy(base); changed["items"][1]["claims"][0]["check_ids"] = ["policy_action"]; cases.append(changed)
        changed = deepcopy(base); changed["items"][1]["claims"][0]["claim_id"] = "C1"; cases.append(changed)
        changed = deepcopy(base); changed["items"][1]["checks"][0]["claim_ids"] = []; cases.append(changed)
        changed = deepcopy(base); changed["items"][1]["claims"][0]["text"] = " "; cases.append(changed)
        for answer in cases:
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                self.parse(answer)

    def test_partial_unknown_conflict_and_incomplete_have_distinct_gates(self):
        answer = complete_answer(self.package)
        check = answer["items"][1]["checks"][3]  # retroactive_starts
        check.update(status="partial", note="只核得两组；其余来源组仍待人工查证")
        self.assertEqual(self.parse(answer)["status"], "review_only")
        check["note"] = ""
        with self.assertRaisesRegex(ValueError, "partial"):
            self.parse(answer)

        answer = complete_answer(self.package)
        check = answer["items"][0]["checks"][0]
        answer["items"][0]["claims"] = [claim for claim in answer["items"][0]["claims"]
                                           if claim["claim_id"] not in check["claim_ids"]]
        check.update(status="incomplete", claim_ids=[], note="这部分未完成")
        result = self.parse(answer)
        self.assertEqual(result["status"], "incomplete_not_ready")
        self.assertFalse(result["ready_for_review"])
        check.update(status="not_stated", note="公告未提及")
        self.assertEqual(self.parse(answer)["status"], "review_only")
        check.update(status="not_applicable", note="本公告不涉及")
        self.assertEqual(self.parse(answer)["status"], "review_only")
        check.update(status="conflict", note="两处矛盾")
        with self.assertRaisesRegex(ValueError, "conflict"):
            self.parse(answer)

    def test_bad_json_output_budget_and_unsupported_meaning_remain_visible(self):
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            parse_reading_answer('{"x":1,"x":2}', self.package, self.store)
        with self.assertRaisesRegex(ValueError, "byte limit"):
            parse_reading_answer("x" * (MAX_ANSWER_BYTES + 1), self.package, self.store)
        answer = complete_answer(self.package)
        answer["items"][1]["claims"][0]["text"] = "Alpha applies to every country."
        # A valid passage ID does not make a false legal claim true.
        self.assertEqual(self.parse(answer)["status"], "review_only")
        self.assertTrue(reference_gap(answer, "Alpha covers Orion origin."))

    def test_source_and_package_capacity_do_not_truncate(self):
        with self.assertRaisesRegex(ValueError, "do not truncate"):
            fixture("X" * 33_000)
        with self.assertRaisesRegex(ValueError, "do not truncate"):
            fixture(("Two lines of source.\n\n" * 2_000))

    def test_offline_pack_verify_and_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "document-store.json"
            source.write_text(json.dumps(self.store), encoding="utf-8")
            output = root / "pack"
            manifest = prepare(source, output)
            self.assertEqual(manifest["api_calls"], 0)
            self.assertEqual(manifest["post_body_status"], "not_built_or_verified")
            self.assertEqual(verify(source, output)["status"], "verified_offline")
            (output / "anchor-map.json").write_bytes(
                (output / "anchor-map.json").read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "differs from its manifest"):
                verify(source, output)

    def test_fake_answer_runs_same_parser_without_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "document-store.json"
            source.write_text(json.dumps(self.store), encoding="utf-8")
            pack = root / "pack"
            prepare(source, pack)
            answer_file = root / "answer.json"
            answer_file.write_text(json.dumps(complete_answer(self.package),
                                              ensure_ascii=False), encoding="utf-8")
            output = root / "run"
            manifest = run_fake(source, pack, answer_file, output)
            self.assertEqual(manifest["api_calls"], 0)
            self.assertFalse(manifest["provider_used"])
            review = json.loads((output / "review.json").read_text(encoding="utf-8"))
            self.assertEqual(review["status"], "review_only")
            self.assertEqual(len(review["items"][1]["checks"]), 5)
            self.assertEqual((output / "answer.json").read_bytes(), answer_file.read_bytes())


if __name__ == "__main__":
    unittest.main()
