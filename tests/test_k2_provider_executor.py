"""K2 acceptance: actual provider executor with persistent event ledger.

All acceptance runs through injected stub providers -- no network, no real
model call, and the real path must refuse while no frozen-model marker
exists.  Ledger is a fresh append-only event log; the old G2 ledger is
never touched.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "tmp/handoff-runs/20260916-r1-fix/real-dev-package"

from src.tradeintel_ai.provider_executor import (ledger_remaining_slots,
                                                 load_ledger, resolve_unknown_run,
                                                 run_experiment)
from scripts.prepare_brief_v3_offline import estimate_input_tokens


def _ok_provider(calls):
    def provider(messages, timeout):
        calls.append(1)
        view = json.loads(messages[1]["content"])
        from scripts.run_fake_experiment import _fake_answer_from_view
        raw = json.dumps(_fake_answer_from_view(view, "stub回答，需人工审阅。"), ensure_ascii=False)
        return raw, {"prompt_tokens": 100, "completion_tokens": 50, "stub": True}
    provider.model_name = "stub-ok"
    return provider


def _timeout_provider(calls):
    def provider(messages, timeout):
        calls.append(1)
        raise TimeoutError("no answer in time")
    provider.model_name = "stub-timeout"
    return provider


def _free_provider(calls):
    def provider(messages, timeout):
        calls.append(1)
        return "这是B合同的自由中文回答：依据视图事实解释两个排序的区别，需人工审阅。", \
            {"prompt_tokens": 90, "completion_tokens": 40, "stub": True}
    provider.model_name = "stub-free"
    return provider


@unittest.skipUnless(PACKAGE.is_dir(), "real dev package not present")
class K2ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="k2-exec-"))
        # Isolate the ledger: every call resolves to ONE fixed temp dir per test.
        led_root = Path(tempfile.mkdtemp(prefix="k2-led-"))
        patcher = mock.patch("src.tradeintel_ai.provider_executor.experiments_dir",
                             side_effect=lambda r: led_root)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_real_path_refused_without_frozen_marker(self):
        result = run_experiment(self.root, package=PACKAGE, contract="C",
                                output=self.root / "run-x", provider=None,
                                authorize_real_call=True)
        self.assertEqual(result["status"], "real_call_not_authorized")
        self.assertFalse((self.root / "run-x").exists())

    def test_stub_c_run_completes_with_raw_first_and_usage(self):
        calls = []
        parse_calls = []
        from src.tradeintel_ai.evidence_linked_brief import parse_response as real_parse

        def spy_parse(answer, catalog):
            # RAW must already be on disk when parsing starts.
            parse_calls.append((self.root / "run-c" / "raw-response.json").exists())
            return real_parse(answer, catalog)

        with mock.patch("src.tradeintel_ai.provider_executor.parse_response", spy_parse):
            result = run_experiment(self.root, package=PACKAGE, contract="C",
                                    output=self.root / "run-c",
                                    provider=_ok_provider(calls))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(calls), 1)
        self.assertEqual(parse_calls, [True], "raw answer must hit disk before parsing")
        run = json.loads((self.root / "run-c" / "run-manifest.json").read_text())
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["api_calls"], 1)
        self.assertEqual(run["usage"]["stub"], True, "usage recorded verbatim")
        self.assertEqual(run["validation_status"], "manual_review_required")
        self.assertLessEqual(run["output_estimate"]["tokens"], 2000)
        # Ledger events: started then completed for the same run.
        ledger = load_ledger(self.root)
        events = [e for e in ledger["events"] if e.get("run_id") == result["run_id"]]
        self.assertEqual([e["event"] for e in events], ["started", "completed"])

    def test_duplicate_request_is_refused_without_second_call(self):
        calls = []
        first = run_experiment(self.root, package=PACKAGE, contract="C",
                               output=self.root / "run-1", provider=_ok_provider(calls))
        self.assertEqual(first["status"], "completed")
        second = run_experiment(self.root, package=PACKAGE, contract="C",
                                output=self.root / "run-2", provider=_ok_provider(calls))
        self.assertEqual(second["status"], "refused_duplicate_run")
        self.assertEqual(len(calls), 1, "duplicate request must not call the provider again")

    def test_timeout_yields_unknown_outcome_without_retry(self):
        calls = []
        result = run_experiment(self.root, package=PACKAGE, contract="C",
                                output=self.root / "run-t", provider=_timeout_provider(calls))
        self.assertEqual(result["status"], "unknown_outcome")
        self.assertEqual(len(calls), 1, "unknown outcome must never be auto-retried")
        run = json.loads((self.root / "run-t" / "run-manifest.json").read_text())
        self.assertEqual(run["status"], "unknown_outcome")
        self.assertEqual(run["api_calls"], 1)
        resolved = resolve_unknown_run(self.root, result["run_id"],
                                       resolution="resolved_mark_failed",
                                       decided_by="user", note="结果确认丢失")
        self.assertEqual(resolved["status"], "resolved_mark_failed")
        with self.assertRaises(ValueError):
            resolve_unknown_run(self.root, result["run_id"],
                                resolution="resolved_retry_authorized", decided_by="user")

    def test_b_contract_same_view_free_answer(self):
        calls = []
        c_view = json.loads((PACKAGE / "business-view.json").read_text(encoding="utf-8"))
        result = run_experiment(self.root, package=PACKAGE, contract="B",
                                output=self.root / "run-b", provider=_free_provider(calls))
        self.assertEqual(result["status"], "completed")
        manifest = json.loads((self.root / "run-b" / "run-manifest.json").read_text())
        # B and C share the same view: identical view hash for the same package.
        self.assertEqual(manifest["view_sha256"],
                         hashlib.sha256(json.dumps(
                             c_view, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")).hexdigest())
        self.assertEqual(manifest["validation_status"], "free_form_manual_review_required")
        self.assertTrue((self.root / "run-b" / "raw-response.json").is_file())

    def test_ledger_slots_decrement_and_blocked_budget_does_not_consume(self):
        before = ledger_remaining_slots(self.root)
        run_experiment(self.root, package=PACKAGE, contract="C",
                       output=self.root / "run-s", provider=_ok_provider([]))
        after_one = ledger_remaining_slots(self.root)
        self.assertEqual(after_one, before - 1)
        overlong = PACKAGE  # use a huge fake answer via overlong stub on B contract
        result = run_experiment(self.root, package=overlong, contract="B",
                                output=self.root / "run-o",
                                provider=_overlong_provider())
        self.assertEqual(result["status"], "blocked_output_budget")
        self.assertEqual(ledger_remaining_slots(self.root), after_one - 1,
                         "an over-output run still billed the call (consumes a slot)")
        # blocked_budget event does not consume: simulate via direct ledger append
        from src.tradeintel_ai.provider_executor import append_ledger_event
        append_ledger_event(self.root, {"run_id": "n/a", "event": "blocked_budget",
                                        "contract": "B", "request_digest": "x"})
        self.assertEqual(ledger_remaining_slots(self.root), after_one - 1)

    def test_old_g2_ledger_untouched(self):
        g2 = ROOT / "docs/experiments/g2-development-c-review-packet-20260915.zh-CN.md"
        self.assertTrue(g2.is_file(), "old G2 record must remain in place")


def _overlong_provider():
    def provider(messages, timeout):
        return json.dumps({"text": "长" * 4000}, ensure_ascii=False), {"stub": True}
    provider.model_name = "stub-overlong"
    return provider


if __name__ == "__main__":
    unittest.main()
