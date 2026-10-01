"""No-network release and one-attempt tests for the final unseen notice."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from scripts import freeze_announcement_reading_dev as old_freeze
from scripts import freeze_announcement_reading_unseen as candidate_freeze
from scripts import freeze_announcement_reading_unseen_live as freeze
from scripts import run_announcement_reading_unseen_once as candidate_runner
from scripts import run_announcement_reading_unseen_live_once as runner


class UnseenLiveOneAttemptTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=runner.LEDGER_PARENT)
        self.base = Path(self.temp.name)
        self.frozen = self.base / "frozen"
        self.ledger = self.base / "private"
        freeze.prepare_frozen(self.frozen)
        self.request = json.loads((self.frozen / "offline/request.json").read_text())
        self.patches = (
            patch.object(runner, "FROZEN", self.frozen),
            patch.object(runner, "LEDGER_ROOT", self.ledger),
            patch.object(candidate_runner, "LEDGER_ROOT", self.ledger),
            patch.object(candidate_runner, "_config", return_value=(
                type("Config", (), {"api_key": "FAKE_KEY"})(), "fake-identity")),
            patch.object(runner, "product_status", return_value={
                "provider": "deepseek", "model": "deepseek-flash"}),
            patch.object(runner, "_deadline", side_effect=lambda _: nullcontext()),
        )
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(self.temp.cleanup)

    def _call(self):
        return runner.run_once(
            authorized=True,
            price_confirmed_date=datetime.now().astimezone().date().isoformat(),
        )

    def _response(self, *, content=None, finish="stop", model="deepseek-flash"):
        answer = {
            "schema_version": self.request["schema_version"],
            "doc_version": self.request["doc_version"],
            "source_sha256": self.request["source_sha256"],
            "items": [
                {"field": field, "status": "known", "reason": "",
                 "claims": [{"text": "Fake answer for transport contract",
                             "anchors": ["P7"]}]}
                for field in ("rate_meaning", "conditions", "exceptions")
            ],
        }
        return json.dumps({
            "model": model,
            "choices": [{"finish_reason": finish, "message": {
                "content": json.dumps(answer) if content is None else content}}],
            "usage": {"prompt_tokens": 7000, "completion_tokens": 1000},
        }).encode()

    def test_final_package_has_bound_price_and_no_reference_in_post(self):
        verified = freeze.verify_frozen(self.frozen)
        body = json.loads((self.frozen / "provider-body.json").read_text())
        self.assertEqual(verified["status"], "live_eligible_after_authorization")
        self.assertEqual(verified["peak_reserve_estimate_usd"], "0.036")
        self.assertEqual(verified["planned_usd_limit"], "0.04")
        self.assertEqual(body["model"], "deepseek-flash")
        self.assertEqual(body["max_tokens"], 20_000)
        self.assertEqual(body["messages"], self.request["messages"])
        self.assertEqual([entry["role"] for entry in body["messages"]],
                         ["system", "user"])
        self.assertNotIn("13项", json.dumps(body, ensure_ascii=False))
        self.assertFalse(self.ledger.exists())

    def test_default_preflight_and_missing_authorization_are_offline(self):
        with patch.object(runner, "_post", side_effect=AssertionError("HTTP attempted")):
            self.assertEqual(runner.check()["attempt_status"], "not_started")
            with self.assertRaisesRegex(ValueError, "authorization"):
                runner.run_once(authorized=False, price_confirmed_date="")
        self.assertFalse(self.ledger.exists())

    def test_candidate_status_or_budget_missing_cannot_be_sent(self):
        candidate = candidate_freeze.verify_frozen()
        with patch.object(runner, "verify_frozen", return_value=candidate), patch.object(
                runner, "_post", side_effect=AssertionError("HTTP attempted")):
            with self.assertRaisesRegex(ValueError, "release or cost gate"):
                self._call()
        self.assertFalse(self.ledger.exists())

    def test_manifest_price_budget_or_source_change_refused_before_http(self):
        manifest_path = self.frozen / "MANIFEST.json"
        original = manifest_path.read_bytes()
        with patch.object(runner, "_post", side_effect=AssertionError("HTTP attempted")):
            for field, bad in (("planned_usd_limit", None),
                               ("planned_usd_limit", "0.001"),
                               ("peak_input_cache_miss_usd_per_million", "9.00"),
                               ("status", "candidate_offline_no_live_release")):
                with self.subTest(field=field, bad=bad):
                    data = json.loads(original)
                    data[field] = bad
                    manifest_path.write_text(json.dumps(data))
                    with self.assertRaises(ValueError):
                        self._call()
            manifest_path.write_bytes(original)
            source = self.frozen / "source-store.json"
            saved = source.read_bytes()
            try:
                source.write_bytes(saved + b" ")
                with self.assertRaises(ValueError):
                    self._call()
            finally:
                source.write_bytes(saved)
        self.assertFalse(self.ledger.exists())

    def test_over_budget_plan_cannot_be_sent(self):
        with patch.object(runner, "peak_estimate_usd", return_value=Decimal("0.05")), \
                patch.object(runner, "_post", side_effect=AssertionError("HTTP attempted")):
            with self.assertRaisesRegex(ValueError, "release or cost gate"):
                self._call()
        self.assertFalse(self.ledger.exists())

    def test_ledger_and_directory_are_durable_before_one_fake_post(self):
        observed = []
        real_fsync = runner._fsync_directory

        def marked_fsync(path):
            real_fsync(path)
            observed.append(Path(path))

        def fake_post(body, api_key):
            self.assertEqual(body, (self.frozen / "provider-body.json").read_bytes())
            self.assertEqual(api_key, "FAKE_KEY")
            ledger = candidate_runner._ledger(candidate_runner._paths()[0])
            self.assertEqual(ledger["status"], "provider_call_started")
            self.assertIn(self.ledger, observed)
            return self._response()

        with patch.object(runner, "_fsync_directory", side_effect=marked_fsync), \
                patch.object(runner, "_post", side_effect=fake_post) as provider:
            self.assertEqual(self._call()["status"], "needs_human_review")
            with self.assertRaisesRegex(ValueError, "already started"):
                self._call()
        self.assertEqual(provider.call_count, 1)
        ledger, raw, review, lock = candidate_runner._paths()
        for path in (self.ledger, ledger, raw, review, lock):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o077, 0)
        self.assertNotIn("FAKE_KEY", ledger.read_text())
        self.assertEqual(json.loads(review.read_text())["status"], "review_only")
        self.assertEqual(json.loads(ledger.read_text())["response"][
            "peak_cache_miss_estimate_usd"], "0.0033")

    def test_concurrent_calls_reach_provider_once(self):
        with patch.object(runner, "_post", return_value=self._response()) as provider:
            with ThreadPoolExecutor(max_workers=4) as pool:
                outcomes = []
                for future in [pool.submit(self._call) for _ in range(4)]:
                    try:
                        outcomes.append(future.result())
                    except ValueError:
                        outcomes.append("refused")
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(sum(isinstance(item, dict) for item in outcomes), 1)

    def test_timeout_and_invalid_model_never_retry(self):
        with patch.object(runner, "_post", side_effect=TimeoutError("private detail")) as provider:
            self.assertEqual(self._call()["status"], "unknown_outcome")
            with self.assertRaises(ValueError):
                self._call()
        self.assertEqual(provider.call_count, 1)
        self.assertNotIn("private detail", candidate_runner._paths()[0].read_text())

    def test_wrong_model_response_saved_for_review_not_retried(self):
        with patch.object(runner, "_post", return_value=self._response(
                model="deepseek-v4-pro")) as provider:
            self.assertEqual(self._call()["status"], "invalid_response")
            with self.assertRaises(ValueError):
                self._call()
        self.assertEqual(provider.call_count, 1)
        _, raw, review, _ = candidate_runner._paths()
        self.assertTrue(raw.is_file())
        self.assertFalse(review.exists())

    def test_http_400_is_recorded_without_retry(self):
        error = HTTPError(runner.ENDPOINT, 400, "bad request", hdrs=None, fp=None)
        with patch.object(runner, "_post", side_effect=error) as provider:
            self.assertEqual(self._call()["status"], "provider_rejected")
            with self.assertRaises(ValueError):
                self._call()
        self.assertEqual(provider.call_count, 1)

    def test_empty_content_is_kept_as_invalid_response(self):
        with patch.object(runner, "_post", return_value=self._response(content="")) as provider:
            self.assertEqual(self._call()["status"], "invalid_response")
            with self.assertRaises(ValueError):
                self._call()
        self.assertEqual(provider.call_count, 1)

    def test_truncated_answer_is_not_reviewable(self):
        with patch.object(runner, "_post", return_value=self._response(finish="length")):
            self.assertEqual(self._call()["status"], "invalid_response")
        self.assertFalse(candidate_runner._paths()[2].exists())

    def test_wrong_anchor_is_not_a_reviewable_answer(self):
        raw = self._response().replace(b'P7', b'P999')
        with patch.object(runner, "_post", return_value=raw):
            self.assertEqual(self._call()["status"], "invalid_response")
        self.assertFalse(candidate_runner._paths()[2].exists())

    def test_old_and_candidate_freeze_stay_verifiable(self):
        self.assertEqual(candidate_freeze.verify_frozen()["manifest_sha256"],
                         "11221cda0918889971b887e607e85bef9ebcb8369bd446505ccd909983689fe0")
        self.assertEqual(old_freeze.verify_frozen()["manifest_sha256"],
                         "6abda1602eee589cbd81b3bb83fcd0d085bd77b09cf75bd2b5e4007af17debaa")


if __name__ == "__main__":
    unittest.main()
