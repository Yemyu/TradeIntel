import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.tradeintel_ai.agent import ModelResponse, ModelToolCall
from scripts.run_live_evaluation import (
    _safe_endpoint,
    load_question_set,
    run_direct,
    run_evaluation, replay_context,
)


class FakeModel:
    def __init__(self, response):
        self.response = response

    def complete(self, *, messages, tools):
        return self.response


class LiveEvaluationRunnerTests(unittest.TestCase):
    def test_development_questions_require_explicit_opt_in(self):
        with self.assertRaises(ValueError):
            load_question_set(Path("evals/questions.jsonl"))
        questions, dataset_type = load_question_set(
            Path("evals/questions.jsonl"), allow_development_set=True, smoke=True
        )
        self.assertEqual(dataset_type, "development_smoke")
        self.assertEqual(len(questions), 60)

    def test_question_set_rejects_gold_fields(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "questions.jsonl"
            path.write_text(
                json.dumps({"id": "F01", "category": "policy", "question": "问什么？", "gold": {}})
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_question_set(path, smoke=True)

    def test_final_question_set_requires_at_least_forty_questions(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "questions.jsonl"
            path.write_text(
                json.dumps({"id": "F01", "category": "policy", "question": "问什么？"}) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_question_set(path)

    def test_direct_runner_records_tool_attempt_as_invalid(self):
        response = ModelResponse(
            text="",
            tool_calls=(ModelToolCall("x", "get_policy_event", {}),),
            metadata={"model": "test-model", "finish_reason": "tool_calls"},
        )
        result = run_direct(FakeModel(response), "政策是什么？")
        self.assertEqual(result["status"], "invalid_generation")
        self.assertEqual(result["model_run"]["model"], "test-model")
        self.assertEqual(result["tool_calls"][0]["name"], "get_policy_event")

    def test_endpoint_redaction_drops_userinfo_query_and_fragment(self):
        self.assertEqual(
            _safe_endpoint("https://user:secret@example.test/v1?key=hidden#fragment"),
            "https://example.test/v1",
        )

    def test_renamed_development_file_is_not_final(self):
        with TemporaryDirectory() as d:
            copied = Path(d) / "renamed.jsonl"
            copied.write_bytes(Path("evals/questions.jsonl").read_bytes())
            with self.assertRaises(ValueError):
                load_question_set(copied, smoke=True)

    def test_smoke_never_certifies_final_and_needs_no_credentials(self):
        plan = run_evaluation(questions_path=Path("evals/questions.jsonl"),
                              smoke=True, allow_development_set=True, limit=2, repeats=1)
        self.assertEqual(plan["dataset_type"], "development_smoke")
        self.assertEqual(plan["maximum_requests"], 12)
        self.assertIsNone(plan["metrics"])

    def test_length_terminated_text_remains_invalid(self):
        result = run_direct(FakeModel(ModelResponse(text="2018年", metadata={"finish_reason": "length"})), "日期")
        self.assertFalse(result["generation_complete"])

    def test_replay_uses_seen_messages_excluding_host_and_answers(self):
        trace = [{"messages": [{"role": "user", "content": "Q"}]},
                 {"messages": [{"role": "user", "content": "Q"},
                               {"role": "assistant", "content": "draft"},
                               {"role": "tool", "name": "get_policy_event", "content": "evidence"}]}]
        self.assertEqual(replay_context(trace), [{"name": "get_policy_event", "content": "evidence"}])

    def test_offline_three_arm_run_and_interruption_preserve_journal(self):
        from src.tradeintel_ai.model_adapter import OpenAICompatibleModel
        env = {"TRADEINTEL_MODEL_NAME": "fixture", "TRADEINTEL_MODEL_API_KEY": "fixture-secret"}
        def reply(model, *, messages, tools):
            if tools and len(messages) == 1:
                return ModelResponse(tool_calls=(ModelToolCall("p", "get_policy_event", {}),),
                                     metadata={"finish_reason": "tool_calls", "usage": {"total_tokens": 4}})
            return ModelResponse(text="2018年7月6日", metadata={"finish_reason": "stop"})
        with TemporaryDirectory() as d, patch.dict("os.environ", env), patch.object(OpenAICompatibleModel, "complete", reply):
            output = Path(d) / "run.json"
            kwargs = dict(questions_path=Path("evals/questions.jsonl"), smoke=True,
                          allow_development_set=True, limit=1, repeats=1, execute=True)
            report = run_evaluation(output_path=output, **kwargs)
            self.assertEqual(report["request_count"], 4)
            arms = report["questions"][0]["systems"]
            self.assertEqual(arms["direct_evidence"]["evidence_context"][0]["name"], "get_policy_event")
            self.assertFalse(report["model_adopted"])
            self.assertNotIn("fixture-secret", output.read_text() + output.with_suffix(".jsonl").read_text())
            with self.assertRaises(ValueError):
                run_evaluation(output_path=output, **kwargs)
            with patch.object(OpenAICompatibleModel, "complete", side_effect=KeyboardInterrupt):
                interrupted = run_evaluation(output_path=Path(d) / "interrupted.json", **kwargs)
            self.assertEqual(interrupted["status"], "interrupted")
            self.assertIn("request_started", (Path(d) / "interrupted.jsonl").read_text())

    def test_api_failure_stops_after_three_attempts_without_losing_answers(self):
        from src.tradeintel_ai.model_adapter import OpenAICompatibleModel, ModelAdapterError
        with TemporaryDirectory() as d, patch.dict("os.environ", {"TRADEINTEL_MODEL_NAME": "fixture"}), patch.object(
                OpenAICompatibleModel, "complete", side_effect=ModelAdapterError("HTTP 401")):
            report = run_evaluation(questions_path=Path("evals/questions.jsonl"),
                output_path=Path(d) / "failed.json", smoke=True, allow_development_set=True,
                repeats=1, limit=2, execute=True)
            self.assertEqual(report["status"], "stopped")
            self.assertEqual(report["request_count"], 3)
            self.assertEqual(len(report["questions"][0]["systems"]), 3)


if __name__ == "__main__":
    unittest.main()
