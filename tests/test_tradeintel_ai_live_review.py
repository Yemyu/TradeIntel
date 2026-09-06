import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.review_live_evaluation import make_form, summarise


ROOT = Path(__file__).resolve().parents[1]
QUESTION_SHA = json.loads((ROOT / "evals/final_gold.json").read_text())["questions_sha256"]


class LiveReviewTests(unittest.TestCase):
    def _run(self):
        common = {"status": "needs_review", "response": "2018-06-15宣布，2018-07-06生效，2018-07为过渡月。",
                  "generation_complete": True, "trace": []}
        agent = {**common, "trace": [{"response": {"text": common["response"], "metadata": {"finish_reason": "stop"}}}]}
        return {"question_sha256": QUESTION_SHA, "planned_answers": 3, "dataset_type": "development_smoke",
                "status": "collected_not_scored", "repeats": 1,
                "systems": ["agent", "direct", "direct_evidence"], "question_count": 1,
                "questions": [{"id": "F01", "category": "policy_timeline_scope",
                    "template_id": "policy_timeline_scope_v1", "question": "时间线？", "repeat": 1,
                    "systems": {"agent": agent, "direct": dict(common), "direct_evidence": dict(common)}}]}

    def _complete(self, form):
        for row in form["entries"]:
            row["facts"] = {key: True for key in row["facts"]}
            row["citations"] = {key: True for key in row["citations"]}
            row["all_claims_checked"] = True
            row["task_completed"] = True
            row["unsupported_causal_claim"] = False
            row["fabricated_evidence"] = False
            if row["arm"] == "agent":
                row["tool_selection_correct"] = True
            row["reviewer"] = "reviewer-a"
            row["review_method"] = "human"
            row["evidence_notes"] = "逐项对照政策事件文件。"

    def test_form_separates_agent_raw_and_visible(self):
        with TemporaryDirectory() as directory:
            run_path = Path(directory) / "run.json"
            run_path.write_text(json.dumps(self._run()), encoding="utf-8")
            form = make_form(run_path)
            surfaces = {(row["arm"], row["surface"]) for row in form["entries"]}
            self.assertEqual(surfaces, {("agent", "raw"), ("agent", "visible"),
                                        ("direct", "visible"), ("direct_evidence", "visible")})
            self.assertIn("policy_event", form["source_catalog"])

    def test_completed_review_stays_nonadopted_and_agent_harm_blocks(self):
        with TemporaryDirectory() as directory:
            run_path, form_path = Path(directory) / "run.json", Path(directory) / "review.json"
            run_path.write_text(json.dumps(self._run()), encoding="utf-8")
            form = make_form(run_path)
            self._complete(form)
            form_path.write_text(json.dumps(form), encoding="utf-8")
            result = summarise(run_path, form_path)
            self.assertEqual(result["decision"], "awaiting_review")
            self.assertFalse(result["model_adopted"])
            raw = next(row for row in form["entries"] if row["arm"] == "agent" and row["surface"] == "raw")
            raw["unsupported_causal_claim"] = True
            raw["task_completed"] = False
            form_path.write_text(json.dumps(form), encoding="utf-8")
            result = summarise(run_path, form_path)
            self.assertEqual(result["decision"], "blocked_unsafe_or_fabricated")


if __name__ == "__main__":
    unittest.main()
