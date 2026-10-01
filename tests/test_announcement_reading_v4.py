"""Offline v4 contract tests; all notices and answers here are synthetic."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.prepare_announcement_reading_v4_offline import prepare, verify
from scripts.run_announcement_reading_v4_fake import run_fake
from tradeintel_ai.announcement_extraction_pilot import make_disabled_store
from tradeintel_ai.announcement_reading_v4 import (
    CHECK_IDS, SCHEMA, build_reading_package, parse_reading_answer,
    verify_reading_package,
)


def fixture(country: str = "Orion"):
    parts = [f"Administrative filler paragraph {number}." for number in range(1, 55)]
    parts[1] = "Agency amends Alpha and Beta; a separate investigation remains pending."
    parts[2] = "Alpha is an additional duty, not the aggregate tariff."
    parts[3] = "Eligible deposits may be reassessed and refunded."
    parts[6] = f"Alpha covers goods originating in {country}."
    parts[12] = "Beta covers goods originating in Lyra."
    parts[15] = "Alloy plate under 88001100 is limited by the written description."
    parts[22] = "The request was initiated on 2026-06-01; action takes effect 2026-07-01."
    parts[30] = "Alpha group I retrospective period starts 2026-01-10."
    parts[31] = "Alpha group II retrospective period starts 2026-02-12."
    parts[37] = "Beta group I retrospective period starts 2026-03-14."
    parts[40] = "Beta group II retrospective period starts 2026-04-16."
    parts[44] = "Entry for consumption or withdrawal from warehouse is the trigger."
    parts[48] = "Exclusion needs both certification and specified end use."
    parts[53] = "Footnote: code and written description jointly define the exception."
    text = "\n\n".join(parts) + "\n"
    store = make_disabled_store("synthetic-policy", "synthetic-source", text,
                                url="https://example.gov/notice",
                                source_sha256=hashlib.sha256(text.encode()).hexdigest())
    version = store["documents"][0]["doc_version"]
    return store, build_reading_package(store, version), text


def complete_answer(package):
    examples = {
        "policy_action": [("Alpha and Beta are amended; investigation remains separate.", ["P2"])],
        "measure_nature": [("Alpha is an additional duty, not aggregate tariff.", ["P3"])],
        "assessment_effect": [("Eligible deposits may be reassessed/refunded.", ["P4"])],
        "origin_by_measure": [("Alpha concerns Orion origin.", ["P7"]),
                              ("Beta concerns Lyra origin.", ["P13"])],
        "product_scope": [("Alloy plate 88001100 is text-limited.", ["P16"])],
        "effective_date": [("Request on June 1, action effective July 1.", ["P23"])],
        "retroactive_starts": [("Alpha I starts January 10.", ["P31"]),
                                 ("Alpha II starts February 12.", ["P32"]),
                                 ("Beta I starts March 14.", ["P38"]),
                                 ("Beta II starts April 16.", ["P41"])],
        "entry_event": [("Entry or warehouse withdrawal is the trigger.", ["P45"])],
        "exclusion_conditions": [("Certification and end use are both needed.", ["P49"])],
        "code_description": [("Code and description jointly define exception.", ["P54"])],
    }
    return {"schema_version": SCHEMA, "doc_version": package["doc_version"],
            "source_sha256": package["source_sha256"],
            "checks": {check_id: {"status": "addressed",
                                  "claims": [{"text": text, "anchors": refs}
                                             for text, refs in examples[check_id]],
                                  "note": ""} for check_id in CHECK_IDS}}


class ReadingV4Test(unittest.TestCase):
    def setUp(self):
        self.store, self.package, self.source = fixture()

    def parse(self, answer):
        return parse_reading_answer(json.dumps(answer, ensure_ascii=False),
                                    self.package, self.store)

    def test_complete_source_and_normalized_claims(self):
        self.assertEqual(len(self.package["anchors"]), 54)
        self.assertEqual("".join(item["text"] for item in self.package["anchors"].values()),
                         self.source)
        answer = complete_answer(self.package)
        answer["checks"]["policy_action"]["note"] = "人工核对并行调查是否另有决定。"
        result = self.parse(answer)
        self.assertEqual(result["status"], "review_only")
        self.assertEqual(result["items"][0]["claims"][0]["claim_id"], "C1")
        self.assertEqual(result["items"][0]["checks"][0]["note"],
                         "人工核对并行调查是否另有决定。")
        self.assertEqual(len(result["items"][1]["claims"]), 9)
        self.assertEqual([check["check_id"] for item in result["items"]
                          for check in item["checks"]], list(CHECK_IDS))
        self.assertNotIn("candidate", result)

    def test_prompt_discloses_exact_shape_and_generic_timeline(self):
        prompt = self.package["messages"][0]["content"]
        for fragment in ("checks 必须是对象", "不要生成 claim_id", "实际生效", "并行调查",
                         "addressed", "note 可为空"):
            self.assertIn(fragment, prompt)
        for case_detail in ("FR2026-19517", "Orion", "2026-07-01"):
            self.assertNotIn(case_detail, prompt)

    def test_partial_conflict_and_incomplete(self):
        answer = complete_answer(self.package)
        answer["checks"]["product_scope"]["status"] = "partial"
        answer["checks"]["product_scope"]["note"] = "附件尚待核对"
        answer["checks"]["origin_by_measure"]["status"] = "conflict"
        answer["checks"]["origin_by_measure"]["note"] = "两条原文存在冲突，待人工判断"
        self.assertTrue(self.parse(answer)["ready_for_review"])
        answer["checks"]["entry_event"] = {
            "status": "incomplete", "claims": [], "note": "本次未能检查该段"}
        self.assertEqual(self.parse(answer)["status"], "incomplete_not_ready")
        answer["checks"]["entry_event"] = {
            "status": "not_stated", "claims": [], "note": "在原文中未找到该项"}
        self.assertTrue(self.parse(answer)["ready_for_review"])
        answer["checks"]["entry_event"]["status"] = "not_applicable"
        self.assertTrue(self.parse(answer)["ready_for_review"])

    def test_invalid_status_claim_note_combinations(self):
        base = complete_answer(self.package)
        cases = []
        changed = deepcopy(base); changed["checks"]["entry_event"]["claims"] = []; cases.append(changed)
        changed = deepcopy(base); changed["checks"]["entry_event"]["status"] = "partial"; cases.append(changed)
        changed = deepcopy(base); changed["checks"]["entry_event"]["status"] = "conflict"; changed["checks"]["entry_event"]["note"] = "x"; cases.append(changed)
        changed = deepcopy(base); changed["checks"]["entry_event"]["status"] = "not_stated"; changed["checks"]["entry_event"]["note"] = "x"; cases.append(changed)
        changed = deepcopy(base); changed["checks"]["entry_event"]["note"] = "x" * 501; cases.append(changed)
        for answer in cases:
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                self.parse(answer)

    def test_identity_shape_and_anchor_fail_closed(self):
        base = complete_answer(self.package)
        cases = []
        changed = deepcopy(base); changed["checks"].pop("entry_event"); cases.append(changed)
        changed = deepcopy(base); changed["checks"]["invented"] = changed["checks"]["entry_event"]; cases.append(changed)
        changed = deepcopy(base); changed["checks"]["policy_action"]["claim_ids"] = ["C1"]; cases.append(changed)
        changed = deepcopy(base); changed["checks"]["entry_event"]["claims"][0]["anchors"] = ["P999"]; cases.append(changed)
        changed = deepcopy(base); changed["checks"]["entry_event"]["claims"][0]["anchors"] = ["P45", "P45"]; cases.append(changed)
        changed = deepcopy(base); changed["checks"]["entry_event"]["claims"][0]["text"] = " "; cases.append(changed)
        changed = deepcopy(base); changed["source_sha256"] = "0" * 64; cases.append(changed)
        for answer in cases:
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                self.parse(answer)
        other_store, other_pack, _ = fixture("Vega")
        with self.assertRaises(ValueError):
            parse_reading_answer(json.dumps(base), other_pack, other_store)
        with self.assertRaises(ValueError):
            verify_reading_package(other_store, self.package)

    def test_duplicate_keys_and_answer_budget(self):
        raw = json.dumps(complete_answer(self.package)).replace(
            '"checks": {', '"checks": {}, "checks": {', 1)
        with self.assertRaises(ValueError):
            parse_reading_answer(raw, self.package, self.store)
        with self.assertRaises(ValueError):
            parse_reading_answer("x" * 16001, self.package, self.store)

    def test_pack_fake_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store_path, answer_path = root / "store.json", root / "answer.json"
            store_path.write_text(json.dumps(self.store, ensure_ascii=False))
            answer_path.write_text(json.dumps(complete_answer(self.package), ensure_ascii=False))
            pack, output = root / "pack", root / "fake"
            self.assertEqual(prepare(store_path, pack)["api_calls"], 0)
            self.assertEqual(verify(store_path, pack)["status"], "verified_offline")
            result = run_fake(store_path, pack, answer_path, output)
            self.assertEqual(result["api_calls"], 0)
            self.assertFalse(result["provider_used"])
            self.assertEqual(json.loads((output / "review.json").read_text())["status"],
                             "review_only")
            request = pack / "request.json"
            request.write_text(request.read_text() + " ")
            with self.assertRaises(ValueError):
                verify(store_path, pack)


if __name__ == "__main__":
    unittest.main()
