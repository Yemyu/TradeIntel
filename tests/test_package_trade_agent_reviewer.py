"""The local review package must be explicit and must not overwrite an older ZIP."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from scripts import package_trade_agent_reviewer as package


class PackageTradeAgentReviewerTests(unittest.TestCase):
    def test_manifest_includes_agent_but_no_local_or_course_material(self):
        names = [name for name, _ in package._members()]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(names[0], "README.md")
        for required in package.EXTRA:
            self.assertIn(required, names)
        for name in names:
            self.assertFalse(any(name.startswith(prefix) for prefix in package.DENIED))
            self.assertFalse(name.endswith((".pyc", ".pyo")))

    def test_build_is_valid_and_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as holder:
            target = Path(holder) / "agent-candidate.zip"
            result = package.build(target)
            self.assertGreater(result["files"], 4)
            with ZipFile(target) as archive:
                self.assertIsNone(archive.testzip())
                self.assertIn("src/tradeintel_ai/trade_agent.py", archive.namelist())
                self.assertIn("web/design-preview/vendor/COBE-LICENSE", archive.namelist())
            with self.assertRaises(FileExistsError):
                package.build(target)


if __name__ == "__main__":
    unittest.main()
