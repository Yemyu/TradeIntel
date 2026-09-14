import json
import tempfile
from pathlib import Path
import unittest

from scripts.package_live_demo_0140 import package


class LivePackageTests(unittest.TestCase):
    def test_rejects_incomplete_run_without_creating_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "run"
            run.mkdir()
            (run / "ledger.json").write_text(json.dumps({"status": "waiting_review", "questions": []}))
            output = root / "out"
            with self.assertRaises(ValueError):
                package(run, output)
            self.assertFalse(output.exists())

    def test_rejects_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "run"
            run.mkdir()
            output = root / "out"
            output.mkdir()
            with self.assertRaises(ValueError):
                package(run, output)


if __name__ == "__main__":
    unittest.main()
