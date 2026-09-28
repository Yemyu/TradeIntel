import json
from pathlib import Path
import tempfile
import unittest

from scripts.run_public_brief_eval import DEFAULT_PACKAGE, build_freeze_spec, preflight, run_injected
from scripts.score_public_brief_eval import collect_results, render_markdown
from src.tradeintel_ai.public_eval_ledger import file_sha256
from tests.public_eval_test_helpers import record_review


class PublicEvalScoringTests(unittest.TestCase):
    def test_review_rechecks_disk_and_unlogged_output_is_not_a_score(self):
        plan = preflight(provider_id="glm-46v", package_path=DEFAULT_PACKAGE)
        freeze = build_freeze_spec(provider=plan["provider"], package_path=DEFAULT_PACKAGE)
        answer = json.dumps({"schema_version": "public-brief-explanation-v1",
                             "interpretations": [{"observation_id": "o1", "kind": "meaning",
                                                  "text": "这些变化仍需后续核对。"}], "watchlist": []})
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = run_injected(provider=plan["provider"], package_path=DEFAULT_PACKAGE,
                                  output=root / "results", question_id="q1", freeze=freeze,
                                  provider_call=lambda **_: (answer, {"finish_reason": "stop",
                                                                     "usage": {"completion_tokens": 100}}),
                                  ledger_root=root)
            unlogged = collect_results(results_root=root / "results", ledger_root=root / "empty-ledger")
            self.assertEqual(unlogged["rows"][0]["structural_pass"], 0)
            (root / "results/q1/raw-response.txt").write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "产物不一致"):
                record_review(root, run_id=result["run_id"], raw_sha256=result["raw_sha256"],
                              verdict="pass", reviewer="human")

    def test_unreviewed_and_unrun_questions_are_not_counted_as_passes(self):
        plan = preflight(provider_id="glm-46v", package_path=DEFAULT_PACKAGE)
        freeze = build_freeze_spec(provider=plan["provider"], package_path=DEFAULT_PACKAGE)
        answer = json.dumps({"schema_version": "public-brief-explanation-v1",
                             "interpretations": [{"observation_id": "o1", "kind": "meaning",
                                                  "text": "这些变化仍需后续核对。"}], "watchlist": []})

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            call = lambda **_: (answer, {"model": "glm-4.6v", "finish_reason": "stop",
                                         "usage": {"completion_tokens": 1}})
            q1 = run_injected(provider=plan["provider"], package_path=DEFAULT_PACKAGE,
                              output=root / "results" / "glm-q1", question_id="q1",
                              provider_call=call, freeze=freeze, ledger_root=root)
            raw1 = root / "results" / "glm-q1" / "q1" / "raw-response.txt"
            record_review(root, run_id=q1["run_id"], raw_sha256=file_sha256(raw1),
                          verdict="pass", reviewer="human")
            run_injected(provider=plan["provider"], package_path=DEFAULT_PACKAGE,
                         output=root / "results" / "glm-q2", question_id="q2",
                         provider_call=call, freeze=freeze, ledger_root=root)
            report = collect_results(results_root=root / "results", ledger_root=root)
            self.assertEqual(len(report["rows"]), 1)
            row = report["rows"][0]
            self.assertEqual(row["run_questions"], 2)
            self.assertEqual(row["answered_questions"], 2)
            self.assertEqual(row["structural_pass"], 2)
            self.assertEqual(row["semantic_pass"], 1)
            self.assertEqual(row["whole_pass"], 1)
            self.assertIsNone(row["whole_pass_rate"])
            self.assertEqual(row["execution_channel"], "offline_injected")
            self.assertEqual(q1["api_calls"], 0)
            markdown = render_markdown(report)
            self.assertIn("2/4", markdown)
            self.assertIn("q2: 尚未完成语义审阅", markdown)
            self.assertIn("q3: 未运行", markdown)
            raw1.write_text("changed", encoding="utf-8")
            changed = collect_results(results_root=root / "results", ledger_root=root)
            self.assertEqual(changed["rows"][0]["whole_pass"], 0)
            self.assertIn("原答文件摘要不一致", str(changed))

    def test_empty_answer_cannot_be_reviewed_as_pass(self):
        plan = preflight(provider_id="glm-46v", package_path=DEFAULT_PACKAGE)
        freeze = build_freeze_spec(provider=plan["provider"], package_path=DEFAULT_PACKAGE)
        answer = json.dumps({"schema_version": "public-brief-explanation-v1",
                             "interpretations": [], "watchlist": []})
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = run_injected(provider=plan["provider"], package_path=DEFAULT_PACKAGE,
                                  output=root / "results", question_id="q1", freeze=freeze,
                                  provider_call=lambda **_: (answer, {"finish_reason": "stop",
                                                                     "usage": {"completion_tokens": 10}}),
                                  ledger_root=root)
            self.assertEqual(result["status"], "needs_revision")
            with self.assertRaises(ValueError):
                record_review(root, run_id=result["run_id"], raw_sha256=result["raw_sha256"],
                              verdict="pass", reviewer="human")
            report = collect_results(results_root=root / "results", ledger_root=root)
            self.assertEqual(report["rows"][0]["structural_pass"], 0)

    def test_duplicate_local_output_is_exposed_without_picking_one(self):
        plan = preflight(provider_id="glm-46v", package_path=DEFAULT_PACKAGE)
        freeze = build_freeze_spec(provider=plan["provider"], package_path=DEFAULT_PACKAGE)
        answer = json.dumps({"schema_version": "public-brief-explanation-v1",
                             "interpretations": [], "watchlist": []})
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            call = lambda **_: (answer, {"finish_reason": "stop",
                                         "usage": {"completion_tokens": 10}})
            first = run_injected(provider=plan["provider"], package_path=DEFAULT_PACKAGE,
                                 output=root / "a" / "glm-q1", question_id="q1",
                                 provider_call=call, freeze=freeze, ledger_root=root)
            run_file = root / "a" / "glm-q1" / "q1" / "run.json"
            duplicate = root / "b" / "glm-q1" / "q1"
            duplicate.mkdir(parents=True)
            (duplicate / "run.json").write_text(run_file.read_text(), encoding="utf-8")
            (duplicate / "raw-response.txt").write_text(answer, encoding="utf-8")
            report = collect_results(results_root=root, ledger_root=root)
            row = report["rows"][0]
            self.assertEqual(row["attempt_count"], 2)
            self.assertEqual(row["duplicate_questions"], ["q1"])
            self.assertEqual(row["answered_questions"], 0)
            self.assertIn("多次运行记录", str(row["main_issues"]))


if __name__ == "__main__":
    unittest.main()
