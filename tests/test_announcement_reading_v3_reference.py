"""Read-only integrity check for the FR2026-19517 pre-answer reference."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from tradeintel_ai.announcement_reading_v3 import CHECK_IDS


ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "evals/announcement_reading_v3/unseen-20260929-screen/2026-19517"


class V3ReferenceFreezeTest(unittest.TestCase):
    def test_source_reference_request_and_code_match_pre_answer_manifest(self) -> None:
        manifest = json.loads((CASE / "REFERENCE_MANIFEST.json").read_bytes())
        self.assertEqual(manifest["schema"], "announcement-reading-v3-pre-answer-reference-v1")
        self.assertEqual(manifest["case"], "FR2026-19517")
        self.assertEqual(manifest["check_ids"], list(CHECK_IDS))
        self.assertEqual(manifest["critical_fact_ids"], [f"F{i:02d}" for i in range(1, 12)])
        self.assertEqual(manifest["model_answer_status"], "not_generated_for_this_case")
        self.assertFalse(manifest["provider_authorized"])
        self.assertEqual(manifest["api_calls_this_phase"], 0)
        for name, digest in manifest["files"].items():
            path = ROOT / name
            self.assertTrue(path.is_file() and not path.is_symlink(), name)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest, name)

        source = (CASE / "source.reading.txt").read_bytes()
        request = json.loads((CASE / "offline-pack/request.json").read_bytes())
        store = json.loads((CASE / "source-store.json").read_bytes())
        self.assertEqual(manifest["source_sha256"], hashlib.sha256(source).hexdigest())
        self.assertEqual(request["source_sha256"], manifest["source_sha256"])
        self.assertEqual(request["doc_version"], manifest["doc_version"])
        self.assertEqual(store["documents"][0]["doc_version"], manifest["doc_version"])
        self.assertEqual(store["documents"][0]["status"], "disabled")
        self.assertEqual(request["request_sha256"], manifest["request_sha256"])
        self.assertEqual(request["request_bytes"], manifest["request_bytes"])
        messages = json.dumps(request["messages"], ensure_ascii=False)
        self.assertNotIn("答前开发者事实参考", messages)
        self.assertNotIn("F01", messages)


if __name__ == "__main__":
    unittest.main()
