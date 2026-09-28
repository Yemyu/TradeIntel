from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.export_codex_eval_prompts import export_prompt_pack
from scripts.run_public_brief_eval import DEFAULT_PACKAGE


class CodexEvalPromptExportTests(unittest.TestCase):
    def test_exports_four_independent_prompts_without_model_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "luna"
            result = export_prompt_pack(provider_id="codex-luna-highest", output=output)
            self.assertEqual(result["status"], "exported")
            self.assertEqual(result["question_count"], 4)
            self.assertEqual(result["api_calls"], 0)
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["provider"]["model_id"], "gpt-5.6-luna")
            self.assertEqual(manifest["provider"]["reasoning_effort"], "max")
            self.assertEqual([row["question_id"] for row in manifest["questions"]],
                             ["q1", "q2", "q3", "q4"])
            for row in manifest["questions"]:
                path = output / row["prompt_file"]
                prompt = path.read_text(encoding="utf-8")
                self.assertIn("【系统要求】", prompt)
                self.assertIn("【本题问题与材料】", prompt)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                                 row["prompt_sha256"])
            readme = (output / "README.zh-CN.md").read_text(encoding="utf-8")
            self.assertIn("新开一个空白会话", readme)
            self.assertIn("每次只复制一份文件", readme)
            self.assertFalse(any(output.rglob("*answer*")))

    def test_api_provider_is_not_exported_as_codex(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "api"
            with self.assertRaisesRegex(ValueError, "仅供 Codex 手动会话"):
                export_prompt_pack(provider_id="glm-46v", output=output)
            self.assertFalse(output.exists())

    def test_existing_packet_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "existing"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("保留", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "不覆盖"):
                export_prompt_pack(provider_id="codex-sol-high", output=output)
            self.assertEqual(marker.read_text(encoding="utf-8"), "保留")


if __name__ == "__main__":
    unittest.main()
