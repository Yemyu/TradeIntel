import contextlib
import csv
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import run_v21_pilot as pilot
from src.tradeintel_ai.agent import ModelResponse, ModelToolCall
from src.tradeintel_ai.model_adapter import ModelAdapterError, OpenAICompatibleConfig


class PilotTests(unittest.TestCase):
    def config(self):
        return OpenAICompatibleConfig(pilot.BASE,pilot.MODEL,"fake-secret",60,0)

    def test_reference_monthly_values_match_independent_csv(self):
        refs = json.loads(pilot.REFERENCE.read_text())
        with (pilot.ROOT / "data/processed/analysis/policy_case_monthly.csv").open() as handle:
            rows = {r["month_label"]:r for r in csv.DictReader(handle)}
        fields = {"China":"target", "other_origins":"other_origins", "all_origins":"all_origins"}
        for key,ref in refs.items():
            if key == "purpose":
                continue
            for label,value,path in ref["facts"]:
                if " / " in label and path == "policy_case_monthly.csv":
                    month, origin = label.replace(" 进口额", "").split(" / ")
                    if month not in rows:
                        self.assertIsNone(value)
                        continue
                    self.assertEqual(value,int(rows[month][fields[origin]+"_import_value_consumption_usd"]))
            if key in {"V201","V202"}:
                expected = sum(int(rows[m][fields[o]+"_import_value_consumption_usd"]) for o,m in ref["trade_scope"])
                self.assertEqual(ref["facts"][-1][1],expected)

    def test_reference_is_only_structural_and_wrong_scope_fails(self):
        _,refs,baselines,_ = pilot.preflight()
        checks = pilot.structural_checks(baselines["V206"],refs["V206"])
        self.assertIsNone(checks["task_completed"])
        self.assertIsNone(checks["manual_semantic_review"])
        self.assertFalse(pilot.structural_checks(baselines["V201"],refs["V202"])["queried_trade_scope_matches"])

    def test_offline_preflight_never_calls_model(self):
        with patch.object(pilot.OpenAICompatibleModel,"complete",side_effect=AssertionError("network")):
            self.assertEqual(pilot.run()["maximum_api_requests"],32)

    def test_eight_task_simulation_journal_redaction_and_no_auto_scores(self):
        qs, refs, _, _ = pilot.preflight()
        routes = {q["question"]:refs[q["id"]]["calls"] for q in qs}
        def complete(model, *, messages, tools):
            # Fixture knows reference routes; the production model never sees them.
            if len(messages) == 1:
                self.assertEqual(set(messages[0]),{"role","content"})
                return ModelResponse(tool_calls=tuple(ModelToolCall(str(i),n,a) for i,(n,a) in enumerate(routes[messages[0]["content"]])), metadata={"finish_reason":"tool_calls"})
            return ModelResponse(text="fake-secret：未经核验模型文字",metadata={"finish_reason":"stop"})
        with TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            out=Path(d)/"run.json"
            with patch.object(pilot.OpenAICompatibleModel,"complete",complete):
                result=pilot.run(execute=True,config=self.config(),output=out)
            self.assertEqual(result["recorded"],8)
            self.assertEqual(result["api_requests"],16)
            self.assertNotIn("fake-secret",out.read_text()+out.with_suffix(".jsonl").read_text())
            saved=json.loads(out.read_text())
            self.assertFalse(saved["model_adopted"])
            for q in saved["questions"]:
                self.assertIsNone(q["structural_checks"]["task_completed"])
                self.assertTrue(q["generation_complete"])
                self.assertNotIn("未经核验模型文字",q["result"]["response"])
            with self.assertRaises(ValueError):
                pilot.run(execute=True,config=self.config(),output=out)

    def test_three_transport_failures_stop_and_preserve_plan(self):
        with TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()), patch.object(
                pilot.OpenAICompatibleModel,"complete",side_effect=ModelAdapterError("timeout")):
            out=Path(d)/"stopped.json"
            result=pilot.run(execute=True,config=self.config(),output=out)
            self.assertEqual(result["status"],"stopped")
            self.assertEqual(result["api_requests"],3)
            saved=json.loads(out.read_text())
            self.assertEqual(saved["question_count"],8)
            self.assertEqual(len(saved["questions"]),3)

    def test_interrupt_is_not_success(self):
        with TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()), patch.object(
                pilot.OpenAICompatibleModel,"complete",side_effect=KeyboardInterrupt):
            out=Path(d)/"interrupted.json"
            result=pilot.run(execute=True,config=self.config(),output=out)
            self.assertEqual(result["status"],"interrupted")
            self.assertFalse(json.loads(out.read_text())["questions"][0]["generation_complete"])

    def test_length_terminated_model_draft_is_incomplete_even_with_report(self):
        def reply(model, *, messages, tools):
            if len(messages) == 1:
                return ModelResponse(tool_calls=(ModelToolCall("p","get_policy_event",{}),), metadata={"finish_reason":"tool_calls"})
            return ModelResponse(text="截断文本",metadata={"finish_reason":"length"})
        with TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()), patch.object(pilot.OpenAICompatibleModel,"complete",reply):
            out=Path(d)/"length.json"
            pilot.run(execute=True,config=self.config(),output=out)
            saved=json.loads(out.read_text())
            self.assertTrue(all(q["result"].get("facts") for q in saved["questions"]))
            self.assertTrue(all(not q["generation_complete"] for q in saved["questions"]))


if __name__ == "__main__":
    unittest.main()
