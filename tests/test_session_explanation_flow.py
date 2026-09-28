import json
import shutil
import tempfile
import unittest
from pathlib import Path

from src.tradeintel_ai.brief_fact_catalog import render_fact_catalog
from src.tradeintel_ai.session_store import (create_session, load_session,
                                             set_request, start_task, transition_task)
from src.tradeintel_ai.session_explanation import prepare
from src.tradeintel_ai.web_app import _handle_session_post, _program_draft_gate
from tests.test_evidence_linked_brief import catalog


class SessionExplanationFlowTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="session-explanation-"))
        self.addCleanup(shutil.rmtree, self.root)
        self.session = create_session(self.root)
        self.catalog = catalog()
        self.request = {"policy_id": self.catalog["policy_id"], "month": self.catalog["request"]["month"],
                        "product": self.catalog["request"].get("product", "all"),
                        "focus": self.catalog["request"]["focus"]}
        set_request(self.root, self.session, self.request, policy_version="p", data_version="d")
        self.task = start_task(self.root, self.session, model="deterministic", prompt_digest="q")["task"]
        transition_task(self.root, self.session, self.task["task_id"], "evidence_ready")
        transition_task(self.root, self.session, self.task["task_id"], "generation_started")
        response = {"kind": "program-report-a3", "question": "解释这份结果",
                    "data_version": self.catalog["data_version"],
                    "catalog_sha256": self.catalog["catalog_sha256"],
                    "catalog": self.catalog,
                    "a3_markdown": render_fact_catalog(self.catalog)}
        transition_task(self.root, self.session, self.task["task_id"], "response_saved",
                        response=response)
        transition_task(self.root, self.session, self.task["task_id"], "needs_review")
        self.task_id = self.task["task_id"]

    def _post(self, path, payload):
        return _handle_session_post(self.root, path,
                                    {"session_id": self.session["session_id"],
                                     "task_id": self.task_id, **payload}, repository=None)

    def test_prepare_submit_review_and_export_gate(self):
        prepared = self._post("/api/session/task/explanation/prepare", {})
        self.assertEqual(prepared["status"], "ready_for_provider")
        self.assertEqual(prepared["protocol"], "host-bound-explanation-v1")
        bindings = prepared["host_bindings"]
        answer = {"interpretations": {key: "这项观察需要结合统计口径和政策范围理解。"
                                       for key in bindings},
                  "missing_evidence": "还需要人工核对其他来源和适用条件。",
                  "question": "下一步应核对哪些证据？"}
        submitted = self._post("/api/session/task/explanation/submit",
                               {"answer": answer, "channel": "chat_simulation", "model": "Luna最高"})
        self.assertEqual(submitted["status"], "manual_review_required")
        current = load_session(self.root, self.session["session_id"])
        explanation = next(iter(current["tasks"].values()))["explanation"]
        parsed = explanation["parsed"]
        count = len(parsed["findings"]) + len(parsed["followups"])
        decisions = []
        for index in range(count):
            kind = "finding" if index < len(parsed["findings"]) else "followup"
            decisions.append({"index": index, "kind": kind, "verdict": "accept",
                              "reason": "已核对事实范围和证据绑定。"})
        reviewed = self._post("/api/session/task/explanation/review",
                              {"reviewer": "fixture-reviewer", "facts_checked": True,
                               "decisions": decisions})
        self.assertTrue(reviewed["eligible_for_export"])
        transitioned = self._post("/api/session/task/transition",
                                  {"state": "reviewed", "operator": "fixture-reviewer"})
        self.assertEqual(transitioned["status"], "reviewed")
        self._post("/api/session/task/transition", {"state": "exportable"})
        state = load_session(self.root, self.session["session_id"])
        task = next(iter(state["tasks"].values()))
        self.assertIn("final_markdown", task["response"])
        self.assertIsNone(_program_draft_gate(task))

    def test_bad_answer_cannot_become_exportable(self):
        self._post("/api/session/task/explanation/prepare", {})
        with self.assertRaises(Exception):
            self._post("/api/session/task/explanation/submit",
                       {"raw_text": json.dumps({"interpretations": {}})})


if __name__ == "__main__":
    unittest.main()
