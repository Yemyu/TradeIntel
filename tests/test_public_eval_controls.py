"""Offline acceptance tests for the public evaluation freeze and ledger."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.run_public_brief_eval import (
    DEFAULT_PACKAGE,
    build_freeze_spec,
    preflight,
    run_injected,
    verify_freeze,
)
from src.tradeintel_ai.public_eval_ledger import (
    DuplicatePublicRun,
    LedgerStateError,
    append,
    canonical_sha,
    claim,
    file_sha256,
    make_base_key,
    require_previous_review,
)
from tests.public_eval_test_helpers import record_review


class PublicEvalControlsTests(unittest.TestCase):
    def _provider_and_freeze(self):
        plan = preflight(provider_id="glm-46v", package_path=DEFAULT_PACKAGE)
        freeze = build_freeze_spec(provider=plan["provider"], package_path=DEFAULT_PACKAGE)
        return plan["provider"], freeze

    def test_concurrent_claim_has_one_winner_and_output_dir_does_not_matter(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = make_base_key("a" * 64, "b" * 64, "q1")

            def attempt(index):
                try:
                    return claim(root, base_key=base, metadata={
                        "question_id": "q1", "output_dir": f"/tmp/out-{index}"})["run_id"]
                except DuplicatePublicRun:
                    return None

            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(attempt, range(4)))
            self.assertEqual(sum(item is not None for item in results), 1)
            with self.assertRaises(DuplicatePublicRun):
                claim(root, base_key=base, metadata={"question_id": "q1", "output_dir": "/other"})

    def test_freeze_requires_all_budget_and_hash_bindings(self):
        provider, freeze = self._provider_and_freeze()
        self.assertEqual(verify_freeze(freeze=freeze, provider=provider,
                                       package_path=DEFAULT_PACKAGE,
                                       allow_candidate=True), canonical_sha(freeze))
        formal = json.loads(json.dumps(freeze))
        formal["status"] = "ready_for_formal"
        formal["provider"]["status"] = "not_reviewed"
        with self.assertRaisesRegex(ValueError, "冻结中的 provider"):
            verify_freeze(freeze=formal, provider=provider,
                          package_path=DEFAULT_PACKAGE, allow_candidate=False)
        broken = json.loads(json.dumps(freeze))
        broken["params"].pop("timeout_seconds")
        with self.assertRaisesRegex(ValueError, "字段与正文预算协议不匹配"):
            verify_freeze(freeze=broken, provider=provider, package_path=DEFAULT_PACKAGE,
                          allow_candidate=True)
        broken = json.loads(json.dumps(freeze))
        broken["runtime_sha256"]["scripts/run_public_brief_eval.py"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "运行时"):
            verify_freeze(freeze=broken, provider=provider, package_path=DEFAULT_PACKAGE,
                          allow_candidate=True)
        changed_provider = dict(provider)
        changed_provider["model_id"] = "glm-4.5-air"
        with self.assertRaisesRegex(ValueError, "provider"):
            verify_freeze(freeze=freeze, provider=changed_provider,
                          package_path=DEFAULT_PACKAGE, allow_candidate=True)

    def test_injected_run_saves_usage_then_waits_for_review_and_opens_q2(self):
        provider, freeze = self._provider_and_freeze()
        answer = json.dumps({
            "schema_version": "public-brief-explanation-v1",
            "interpretations": [{"observation_id": "o1", "kind": "meaning",
                                  "text": "这条观察说明公开数据存在变化，仍需后续核对。"}],
            "watchlist": [{"watch_id": "next_trade_release",
                            "rationale": "后续发布有助于核对变化是否延续。"}],
        }, ensure_ascii=False)

        def provider_call(**_kwargs):
            return answer, {"model": "glm-4.6v", "finish_reason": "stop",
                            "usage": {"prompt_tokens": 10, "completion_tokens": 20}}

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = run_injected(provider=provider, package_path=DEFAULT_PACKAGE,
                                 output=root / "q1-run", question_id="q1",
                                 provider_call=provider_call, freeze=freeze,
                                 ledger_root=root)
            self.assertEqual(first["status"], "awaiting_semantic_review")
            self.assertEqual(first["response_metadata"]["usage"]["completion_tokens"], 20)
            raw = root / "q1-run" / "q1" / "raw-response.txt"
            self.assertTrue(raw.is_file())
            self.assertEqual(file_sha256(raw), first["raw_sha256"])
            with self.assertRaises(DuplicatePublicRun):
                run_injected(provider=provider, package_path=DEFAULT_PACKAGE,
                             output=root / "different-output", question_id="q1",
                             provider_call=provider_call, freeze=freeze,
                             ledger_root=root)
            record_review(root, run_id=first["run_id"], raw_sha256=file_sha256(raw),
                          verdict="pass", reviewer="human")
            second = run_injected(provider=provider, package_path=DEFAULT_PACKAGE,
                                  output=root / "q2-run", question_id="q2",
                                  provider_call=provider_call, freeze=freeze,
                                  ledger_root=root)
            self.assertEqual(second["status"], "awaiting_semantic_review")

    def test_q2_is_blocked_until_q1_review_and_major_error_stops(self):
        provider, freeze = self._provider_and_freeze()
        answer = (json.dumps({"schema_version": "public-brief-explanation-v1",
                              "interpretations": [{"observation_id": "o1", "kind": "meaning",
                                                   "text": "这些变化仍需后续核对。"}], "watchlist": []}))
        provider_call = lambda **_: (answer, {"finish_reason": "stop",
                                               "usage": {"completion_tokens": 1}})
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(LedgerStateError):
                run_injected(provider=provider, package_path=DEFAULT_PACKAGE,
                             output=root / "q2", question_id="q2",
                             provider_call=provider_call, freeze=freeze,
                             ledger_root=root)
            first = run_injected(provider=provider, package_path=DEFAULT_PACKAGE,
                                 output=root / "q1", question_id="q1",
                                 provider_call=provider_call, freeze=freeze,
                                 ledger_root=root)
            raw = root / "q1" / "q1" / "raw-response.txt"
            record_review(root, run_id=first["run_id"], raw_sha256=file_sha256(raw),
                          verdict="major_error", reviewer="human", note="事实解释错误")
            with self.assertRaises(LedgerStateError):
                require_previous_review(root, base_key=make_base_key(
                    file_sha256(DEFAULT_PACKAGE / "MANIFEST.json"),
                    canonical_sha({"provider": "glm-4.6v"}), "q2"))

    def test_non_normal_finish_reason_is_not_structural_success(self):
        provider, freeze = self._provider_and_freeze()
        answer = json.dumps({"schema_version": "public-brief-explanation-v1",
                             "interpretations": [], "watchlist": []})
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = run_injected(
                provider=provider, package_path=DEFAULT_PACKAGE,
                output=root / "q1", question_id="q1",
                provider_call=lambda **_: (answer, {
                    "finish_reason": "length",
                    "usage": {"completion_tokens": 2},
                }), freeze=freeze, ledger_root=root)
            self.assertEqual(result["status"], "invalid_response")
            self.assertTrue((root / "q1" / "q1" / "raw-response.txt").is_file())

    def test_invalid_json_keeps_usage_before_parser_rejection(self):
        provider, freeze = self._provider_and_freeze()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = run_injected(
                provider=provider, package_path=DEFAULT_PACKAGE,
                output=root / "q1", question_id="q1",
                provider_call=lambda **_: ("not-json", {
                    "finish_reason": "stop",
                    "usage": {"prompt_tokens": 4, "completion_tokens": 5},
                }), freeze=freeze, ledger_root=root)
            self.assertEqual(result["status"], "invalid_response")
            self.assertEqual(result["response_metadata"]["usage"]["completion_tokens"], 5)
            self.assertTrue((root / "q1" / "q1" / "response-metadata.json").is_file())

    def test_timeout_is_unknown_and_raw_save_failure_keeps_claim(self):
        provider, freeze = self._provider_and_freeze()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            timed_out = run_injected(
                provider=provider, package_path=DEFAULT_PACKAGE,
                output=root / "timeout", question_id="q1",
                provider_call=lambda **_: (_ for _ in ()).throw(TimeoutError()),
                freeze=freeze, ledger_root=root)
            self.assertEqual(timed_out["status"], "unknown_outcome")
            with self.assertRaises(DuplicatePublicRun):
                run_injected(provider=provider, package_path=DEFAULT_PACKAGE,
                             output=root / "timeout-retry", question_id="q1",
                             provider_call=lambda **_: ("", {}), freeze=freeze,
                             ledger_root=root)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            answer = json.dumps({"schema_version": "public-brief-explanation-v1",
                                 "interpretations": [], "watchlist": []})
            original = __import__("scripts.run_public_brief_eval", fromlist=["_atomic_write_text"])._atomic_write_text

            def fail_raw(path, value):
                if Path(path).name == "raw-response.txt":
                    raise OSError("simulated disk failure")
                return original(path, value)

            with patch("scripts.run_public_brief_eval._atomic_write_text", side_effect=fail_raw):
                failed = run_injected(
                    provider=provider, package_path=DEFAULT_PACKAGE,
                    output=root / "save-fail", question_id="q1",
                    provider_call=lambda **_: (answer, {"usage": {"completion_tokens": 1}}),
                    freeze=freeze, ledger_root=root)
            self.assertEqual(failed["status"], "raw_save_failed")
            with self.assertRaises(DuplicatePublicRun):
                run_injected(provider=provider, package_path=DEFAULT_PACKAGE,
                             output=root / "save-fail-retry", question_id="q1",
                             provider_call=lambda **_: (answer, {}), freeze=freeze,
                             ledger_root=root)


if __name__ == "__main__":
    unittest.main()
