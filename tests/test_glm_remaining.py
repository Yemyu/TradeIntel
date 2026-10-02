import tempfile
import unittest
from pathlib import Path
from scripts.run_glm_remaining import execute_remaining
from scripts.run_us_agent_retest import GateError
from scripts.us_retest_transport import canonical_hash


class RemainingTests(unittest.TestCase):
    def exercise(self, *, broken_accounting=False):
        cases = [{"id": "A", "question": "first", "kind": "normal"},
                 {"id": "B", "question": "follow", "requires": "A", "kind": "normal"},
                 {"id": "C", "question": "independent", "kind": "normal"},
                 {"id": "D", "question": "another", "kind": "normal"}]
        prior = {c["id"]: {"case_id": c["id"], "executed": c["id"] == "A",
                            "continuation_ready": False} for c in cases}
        turns = [{"case_id": c["id"], "question": c["question"], "requires": c.get("requires")} for c in cases]
        called = []
        def execute(turn):
            called.append(turn["case_id"])
            return {"case_id": turn["case_id"], "agent_status": "failed",
                    "request_accounting_complete": not broken_accounting,
                    "public_safety": "review_required", "stop_batch": True}
        def review(case, result):
            return {"case_id": case["id"], "result_sha256": canonical_hash(result),
                    "public_safe": False, "reason": "fixture answer unsupported"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "batch"
            rows = execute_remaining({"cases": cases}, turns, prior, path, execute, review=review)
            with self.assertRaises(GateError):
                execute_remaining({"cases": cases}, turns, prior, path, execute, review=review)
        return rows, called

    def test_content_failure_does_not_stop_independent_cases(self):
        rows, calls = self.exercise()
        self.assertEqual(calls, ["C", "D"])
        self.assertEqual(rows[1]["status"], "not_run_prerequisite")
        self.assertTrue(rows[2]["unsafe"])
        self.assertFalse(rows[2]["supplement_batch_stop"])

    def test_unknown_accounting_stops_batch(self):
        rows, calls = self.exercise(broken_accounting=True)
        self.assertEqual(calls, ["C"])
        self.assertEqual(rows[3]["status"], "not_run_infrastructure_stop")
