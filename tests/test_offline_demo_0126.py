"""The strict offline demo remains deterministic and clearly non-accuracy."""

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import run_strict_offline_demo


class OfflineDemo0126Tests(unittest.TestCase):
    def test_demo_completes_without_accuracy_claim(self):
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "run"
            with redirect_stdout(StringIO()):
                exit_code = run_strict_offline_demo.main(["--output", str(output)])

            self.assertEqual(exit_code, 0)
            summary = json.loads((output / "run-summary.json").read_text())
            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["question_status_counts"], {
                "accepted": 2, "accepted_terminal": 1,
            })
            self.assertEqual(summary["call_count"], 5)
            self.assertFalse(summary["acceptance_ready"])
            self.assertFalse(summary["semantic_accuracy_measured"])
            self.assertTrue(summary["synthetic_protocol_completed"])

            public_summary = json.loads((output / "run-summary.json").read_text())
            self.assertNotIn("TRADEINTEL_MODEL_API_KEY", json.dumps(public_summary))

