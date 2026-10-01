import json
from pathlib import Path
import tempfile
import unittest
import uuid

from tradeintel_ai.trade_agent_metrics import response_metrics, summarize_metrics, request_configuration
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from tradeintel_ai.trade_agent_store import begin_turn, finish_turn, read_session, record_attempt


class MetricsTests(unittest.TestCase):
    def test_request_config_does_not_copy_credentials_or_arbitrary_params(self):
        model = SimpleNamespace(config=SimpleNamespace(model="requested", api_key="TEST-SECRET"),
            request_params={"thinking": {"type": "enabled", "secret": "TEST-SECRET"},
                            "reasoning_effort": "high", "endpoint": "TEST-SECRET"})
        self.assertEqual(request_configuration(model), {"requested_model": "requested",
            "thinking": {"type": "enabled"}, "reasoning_effort": "high"})
        model.request_params = {"reasoning_effort": {}, "thinking": {"type": []}}
        self.assertEqual(request_configuration(model), {"requested_model": "requested"})

    def test_concurrent_attempt_claim_and_failure_persist(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); request = uuid.uuid4().hex
            begin_turn(root, None, request, "test")
            def claim(_):
                try: record_attempt(root, request, request); return True
                except ValueError: return False
            with ThreadPoolExecutor(max_workers=4) as pool:
                self.assertEqual(sum(pool.map(claim, range(4))), 1)
            record_attempt(root, request, request, failure={"failure_kind": "timeout", "usage_status": "unknown"})
            result = finish_turn(root, request, request, {"status": "unknown_outcome"})
            metrics = result["turns"][-1]["execution_metrics"]
            self.assertEqual((metrics["complete_attempts"], metrics["responses_received"]), (1, 0))
            self.assertEqual(metrics["attempts"][0]["failure_kind"], "timeout")
    def test_allowlist_and_invalid_usage(self):
        metadata = {"api_key": "TEST-SECRET", "reasoning": "TEST-THOUGHT",
                    "model": "returned-model", "usage": {"prompt_tokens": True,
                    "completion_tokens": -1, "total_tokens": 10**20}}
        result = response_metrics(metadata, 1)
        self.assertEqual(result["usage_status"], "unknown")
        self.assertNotIn("TEST-", json.dumps(result))
        self.assertEqual(result["model"], "returned-model")

    def test_partial_usage_not_double_counted_or_filled(self):
        event = {"status": "response_received", **response_metrics({"usage": {
            "prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13,
            "completion_tokens_details": {"reasoning_tokens": 2}}}, 5)}
        second = {"status": "response_received", **response_metrics({}, 6)}
        result = summarize_metrics({"attempts": [event, second]})
        self.assertEqual(result["complete_attempts"], 2)
        self.assertEqual(result["token_totals"]["total_tokens"], {"reported_sum": 13, "reporting_responses": 1})
        self.assertIsNone(result["token_totals"]["input_tokens"]["reported_sum"])
        self.assertEqual(result["cost_status"], "unknown")

    def test_persist_before_call_interruption_and_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); request = uuid.uuid4().hex
            state, fresh = begin_turn(root, None, request, "test")
            record_attempt(root, state["session_id"], request)
            saved = read_session(root, request)
            self.assertEqual(saved["turns"][-1]["execution_metrics"]["attempts"], [{"status": "started"}])
            with self.assertRaises(ValueError): record_attempt(root, request, request)
            replay, fresh = begin_turn(root, None, request, "test")
            self.assertFalse(fresh)
            self.assertEqual(saved, replay)
            finished = finish_turn(root, request, request, {"status": "unknown_outcome"})
            metrics = finished["turns"][-1]["execution_metrics"]
            self.assertEqual((metrics["complete_attempts"], metrics["responses_received"]), (1, 0))

    def test_preflight_rejection_records_zero_attempts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); request = uuid.uuid4().hex
            begin_turn(root, None, request, "unsupported")
            result = finish_turn(root, request, request, {"status": "needs_clarification"})
            metrics = result["turns"][-1]["execution_metrics"]
            self.assertEqual(metrics["complete_attempts"], 0)
            self.assertIsNone(metrics["token_totals"]["total_tokens"]["reported_sum"])
