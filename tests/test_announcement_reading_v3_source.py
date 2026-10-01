"""Source-extraction guards for the offline v3 notice path."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.prepare_announcement_reading_v3_source import prepare
from tradeintel_ai.policy_documents import validate_document_store


NUMBER = "2026-19517"
URL = "https://www.federalregister.gov/documents/full_text/text/2026/09/24/2026-19517.txt"


class V3SourcePreparationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.raw = root / "source.html"
        self.metadata = root / "metadata.json"
        self.reading = root / "source.reading.txt"
        self.store = root / "source-store.json"
        self.raw.write_text(
            "<html><body>neighbor notice<pre>\n[Notices]\n"
            f"[FR Doc No: {NUMBER}]\nOne &amp; two <a href='x'>linked</a>.\n"
            f"\\1\\ Footnote.\n[FR Doc. {NUMBER} Filed 9-23-26; 8:45 am]\n"
            "</pre>another neighbor</body></html>", encoding="utf-8")
        self.metadata.write_text(json.dumps({
            "document_number": NUMBER, "publication_date": "2026-09-24",
            "raw_text_url": URL,
        }), encoding="utf-8")

    def test_extracts_whole_notice_without_adjacent_text_and_keeps_disabled(self) -> None:
        result = prepare(self.raw, self.metadata, self.reading, self.store)
        text = self.reading.read_text(encoding="utf-8")
        store = json.loads(self.store.read_text(encoding="utf-8"))
        self.assertEqual(result["reading_sha256"], hashlib.sha256(text.encode()).hexdigest())
        self.assertIn("One & two linked.", text)
        self.assertIn("\\1\\ Footnote.", text)
        self.assertNotIn("neighbor", text)
        self.assertEqual(store["documents"][0]["status"], "disabled")
        self.assertEqual(store["documents"][0]["publication_time"], "2026-09-24")
        self.assertEqual("".join(section["text"] for section in store["documents"][0]["sections"]), text)
        self.assertEqual(validate_document_store(store)["status"], "valid")

    def test_wrong_identity_and_partial_wrapper_do_not_write(self) -> None:
        self.raw.write_text("<pre>[Notices]\n[FR Doc No: other]</pre>", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "identity"):
            prepare(self.raw, self.metadata, self.reading, self.store)
        self.assertFalse(self.reading.exists())
        self.assertFalse(self.store.exists())

    def test_existing_output_is_not_overwritten(self) -> None:
        self.reading.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            prepare(self.raw, self.metadata, self.reading, self.store)
        self.assertEqual(self.reading.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
