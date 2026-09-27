"""Offline checks for source-bound, review-only announcement reading notes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.prepare_announcement_reading_offline import prepare, verify
from scripts.run_policy_extraction_schema_probe_once import _provider_metadata
from tradeintel_ai.announcement_extraction_pilot import make_disabled_store
from tradeintel_ai.announcement_reading_suggestions import (
    FOCUS_FIELDS, SCHEMA, build_reading_package, parse_reading_answer,
    verify_reading_package,
)


def fixture(text: str = "Rate: 50 percent additional duty.\n\nException: see annex.\n"):
    digest = hashlib.sha256(text.encode()).hexdigest()
    store = make_disabled_store("sample-policy", "sample-source", text,
                                url="https://example.gov/notice", source_sha256=digest)
    version = store["documents"][0]["doc_version"]
    return store, version


def answer(package):
    return {
        "schema_version": SCHEMA,
        "doc_version": package["doc_version"],
        "source_sha256": package["source_sha256"],
        "items": [
            {"field": "rate_meaning", "status": "known", "claims": [
                {"text": "公告提到额外税率，计税基础仍需人工核对。", "anchors": ["P1"]},
                {"text": "别将本次额外税率称为全部税负。", "anchors": ["P1"]}],
             "reason": ""},
            {"field": "conditions", "status": "unknown", "claims": [],
             "reason": "本段没有足够条件信息"},
            {"field": "exceptions", "status": "unknown", "claims": [],
             "reason": "附件未提供，不能补造例外"},
        ],
    }


class AnnouncementReadingSuggestionsTest(unittest.TestCase):
    def setUp(self):
        self.store, self.version = fixture()
        self.package = build_reading_package(self.store, self.version)

    def parse(self, value):
        return parse_reading_answer(json.dumps(value, ensure_ascii=False),
                                    self.package, self.store)

    def test_reading_package_and_three_field_answer_are_review_only(self):
        self.assertEqual(len(self.package["anchors"]), 2)
        self.assertLessEqual(self.package["request_bytes"], 28_000)
        result = self.parse(answer(self.package))
        self.assertEqual(result["status"], "review_only")
        self.assertEqual([item["field"] for item in result["items"]], list(FOCUS_FIELDS))
        self.assertEqual(result["items"][0]["claims"][0]["source_passages"][0]["text"],
                         "Rate: 50 percent additional duty.\n\n")
        self.assertEqual(len(result["items"][0]["claims"]), 2)
        self.assertNotIn("candidate", result)
        self.assertNotIn("enabled", result)

    def test_bad_json_and_duplicate_keys_are_rejected(self):
        for raw in ('{"doc_version":', '{"schema_version":"a","schema_version":"b"}',
                    '{"x":NaN}'):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, "valid JSON"):
                parse_reading_answer(raw, self.package, self.store)

    def test_wrong_version_or_source_hash_is_rejected(self):
        for key, value in (("doc_version", "another-version"),
                           ("source_sha256", "0" * 64)):
            changed = answer(self.package)
            changed[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "not bound"):
                self.parse(changed)

    def test_bad_or_duplicate_anchor_is_rejected(self):
        for refs in (["P999"], ["P1", "P1"], ["P0"]):
            changed = answer(self.package)
            changed["items"][0]["claims"][0]["anchors"] = refs
            with self.subTest(refs=refs), self.assertRaises(ValueError):
                self.parse(changed)

    def test_unknown_requires_reason_and_conflict_requires_two_sourced_claims(self):
        changed = answer(self.package)
        changed["items"][1]["reason"] = ""
        with self.assertRaisesRegex(ValueError, "unknown reading"):
            self.parse(changed)
        changed = answer(self.package)
        changed["items"][0].update(status="conflict", reason="两段冲突", claims=[
            {"text": "只有一个有出处的说法", "anchors": ["P1"]}])
        with self.assertRaisesRegex(ValueError, "conflict reading"):
            self.parse(changed)

    def test_each_claim_needs_real_passages_and_unknown_has_no_claims(self):
        changed = answer(self.package)
        changed["items"][0]["claims"][0]["anchors"] = []
        with self.assertRaisesRegex(ValueError, "claim or source"):
            self.parse(changed)
        changed = answer(self.package)
        changed["items"][1]["claims"] = [{"text": "臆测条件", "anchors": ["P2"]}]
        with self.assertRaisesRegex(ValueError, "unknown reading"):
            self.parse(changed)

    def test_passages_cover_exact_source_and_preserve_original_section_ids(self):
        source = ("Action: initial additional rate.\nExisting duty remains.\n\n"
                  "Exception applies only to a zone.\nNext line of same clause.\n")
        store, version = fixture(source)
        package = build_reading_package(store, version)
        self.assertEqual(len(package["anchors"]), 2)
        self.assertEqual("".join(p["text"] for p in package["anchors"].values()), source)
        self.assertEqual([p["start"] for p in package["anchors"].values()],
                         [0, len(package["anchors"]["P1"]["text"])])
        self.assertEqual(len(package["anchors"]["P1"]["section_ids"]), 2)
        self.assertEqual(len(package["anchors"]["P2"]["section_ids"]), 2)
        self.assertNotIn("50 percent", package["messages"][0]["content"])

    def test_missing_or_extra_field_is_rejected(self):
        changed = answer(self.package)
        changed["items"][2]["field"] = "conditions"
        with self.assertRaisesRegex(ValueError, "repeated"):
            self.parse(changed)
        changed = answer(self.package)
        changed["items"].pop()
        with self.assertRaisesRegex(ValueError, "exactly three"):
            self.parse(changed)

    def test_changed_source_invalidates_old_package(self):
        new_store, _ = fixture("Rate: 25 percent.\nException: see annex.\n")
        with self.assertRaises(ValueError):
            verify_reading_package(new_store, self.package)

    def test_legacy_v1_answer_and_package_are_explicitly_rejected(self):
        changed = answer(self.package)
        changed["schema_version"] = "announcement-reading-suggestions-v1"
        with self.assertRaisesRegex(ValueError, "not bound"):
            self.parse(changed)
        old_package = dict(self.package, schema_version="announcement-reading-suggestions-v1")
        with self.assertRaises(ValueError):
            verify_reading_package(self.store, old_package)

    def test_long_source_is_rejected_without_truncation(self):
        large_store, version = fixture("X" * 30_000)
        with self.assertRaisesRegex(ValueError, "do not truncate"):
            build_reading_package(large_store, version)

    def test_provider_metadata_survives_malformed_tool_arguments(self):
        raw = json.dumps({
            "model": "deepseek-flash", "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            "choices": [{"finish_reason": "tool_calls", "message": {
                "tool_calls": [{"function": {"arguments": "{not-json"}}]}}],
        }).encode()
        metadata = _provider_metadata(raw)
        self.assertEqual(metadata["usage"]["prompt_tokens"], 5)
        self.assertEqual(metadata["finish_reason"], "tool_calls")
        self.assertEqual(metadata["response_model"], "deepseek-flash")

    def test_offline_pack_readback_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "document-store.json"
            source.write_text(json.dumps(self.store), encoding="utf-8")
            output = root / "pack"
            manifest = prepare(source, output)
            self.assertEqual(manifest["api_calls"], 0)
            self.assertEqual(manifest["schema_version"], "announcement-reading-offline-pack-v2")
            self.assertEqual(verify(source, output)["status"], "verified_offline")
            with (output / "anchor-map.json").open("ab") as stream:
                stream.write(b" ")
            with self.assertRaisesRegex(ValueError, "differs from its manifest"):
                verify(source, output)

    def test_old_manifest_is_rejected_by_v2_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "document-store.json"
            source.write_text(json.dumps(self.store), encoding="utf-8")
            output = root / "pack"
            manifest = prepare(source, output)
            manifest["schema_version"] = "announcement-reading-offline-pack-v1"
            (output / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differs from its manifest"):
                verify(source, output)


if __name__ == "__main__":
    unittest.main()
