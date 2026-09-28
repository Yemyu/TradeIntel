"""Offline tests for the one-call R2 runner; _post is always a fake."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime
import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from threading import Lock
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from scripts import freeze_announcement_reading_dev as freeze
from scripts import run_announcement_reading_dev_once as runner


class ReadingOneCallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack_tmp = TemporaryDirectory()
        cls.pack = Path(cls.pack_tmp.name) / "frozen"
        freeze.prepare_frozen(cls.pack)
        request = json.loads((cls.pack / "offline/request.json").read_text())
        cls.answer = {
            "schema_version": request["schema_version"],
            "doc_version": request["doc_version"],
            "source_sha256": request["source_sha256"],
            "items": [{"field": field, "status": "unknown", "claims": [],
                       "reason": "Needs manual source review."}
                      for field in ("rate_meaning", "conditions", "exceptions")],
        }

    @classmethod
    def tearDownClass(cls):
        cls.pack_tmp.cleanup()

    def setUp(self):
        self.temp = TemporaryDirectory(dir=runner.ROOT / ".local/experiments")
        self.folder = Path(self.temp.name) / "one-call"
        self.patches = (
            patch.object(runner, "FROZEN", self.pack),
            patch.object(runner, "verify_frozen",
                         side_effect=lambda: freeze.verify_frozen(freeze.ROOT, self.pack)),
            patch.object(runner, "_config",
                         return_value=(SimpleNamespace(api_key="FAKE_TEST_KEY"), "test-id")),
            patch.object(runner, "_deadline", side_effect=lambda _: nullcontext()),
            patch.object(runner, "product_status",
                         return_value={"provider": "deepseek", "model": "deepseek-flash"}),
        )
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(self.temp.cleanup)

    def _call(self):
        return runner.run_once(authorized=True,
                               price_confirmed_date=datetime.now().astimezone().date().isoformat(),
                               folder=self.folder)

    def _response(self, answer=None, *, finish="stop", content=None, usage=None):
        if answer is None:
            answer = self.answer
        return json.dumps({
            "model": "deepseek-flash",
            "choices": [{"finish_reason": finish,
                         "message": {"content": json.dumps(answer) if content is None else content}}],
            "usage": usage if usage is not None else
                     {"prompt_tokens": 6000, "completion_tokens": 2000},
        }).encode()

    def test_preflight_does_not_create_ledger_or_call_provider(self):
        with patch.object(runner, "_post", side_effect=AssertionError("must not call")):
            status = runner.check(folder=self.folder)
        self.assertEqual(status["attempt_status"], "not_started")
        self.assertEqual(status["provider_calls_by_check"], 0)
        self.assertFalse(self.folder.exists())

    def test_requires_authorization_and_same_day_price_check(self):
        with patch.object(runner, "_post", side_effect=AssertionError("must not call")):
            with self.assertRaises(ValueError):
                runner.run_once(authorized=False, price_confirmed_date="", folder=self.folder)
            with self.assertRaises(ValueError):
                runner.run_once(authorized=True, price_confirmed_date="2020-01-01",
                                folder=self.folder)
        self.assertFalse(self.folder.exists())

    def test_exact_body_prior_ledger_private_outputs_and_no_retry(self):
        seen = []
        def fake_post(body, key):
            self.assertEqual(body, (self.pack / "provider-body.json").read_bytes())
            self.assertEqual(key, "FAKE_TEST_KEY")
            ledger = runner._ledger(runner._paths(self.folder)[0])
            self.assertEqual(ledger["status"], "provider_call_started")
            seen.append(1)
            return self._response()
        with patch.object(runner, "_post", side_effect=fake_post):
            result = self._call()
            with self.assertRaises(ValueError):
                self._call()
        self.assertEqual(seen, [1])
        self.assertEqual(result["status"], "needs_human_review")
        ledger, raw, review, lock = runner._paths(self.folder)
        self.assertEqual(runner._ledger(ledger)["automatic_retries"], 0)
        self.assertEqual(json.loads(review.read_text())["status"], "review_only")
        for path in (self.folder, ledger, raw, review, lock):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o077, 0)
        self.assertNotIn("FAKE_TEST_KEY", ledger.read_text())

    def test_concurrent_requests_one_provider_call(self):
        calls = []
        guard = Lock()
        def fake_post(body, key):
            with guard:
                calls.append(1)
            return self._response()
        with patch.object(runner, "_post", side_effect=fake_post):
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(self._call) for _ in range(4)]
                results = []
                for future in futures:
                    try:
                        results.append(future.result())
                    except ValueError:
                        results.append("refused")
        self.assertEqual(len(calls), 1)
        self.assertEqual(sum(isinstance(x, dict) for x in results), 1)

    def test_timeout_stays_unknown_and_is_not_retried(self):
        with patch.object(runner, "_post", side_effect=TimeoutError("secret in error")) as post:
            result = self._call()
            with self.assertRaises(ValueError):
                self._call()
        self.assertEqual(post.call_count, 1)
        self.assertEqual(result["status"], "unknown_outcome")
        self.assertNotIn("secret", runner._paths(self.folder)[0].read_text())

    def test_http_rejection_and_server_error_do_not_retry(self):
        self.folder.mkdir(mode=0o700)
        for code, expected in ((400, "provider_rejected"), (503, "unknown_outcome")):
            with self.subTest(code=code):
                folder = self.folder / str(code)
                error = HTTPError(runner.ENDPOINT, code, "private error", {}, None)
                with patch.object(runner, "_post", side_effect=error) as post:
                    result = runner.run_once(
                        authorized=True,
                        price_confirmed_date=datetime.now().astimezone().date().isoformat(),
                        folder=folder)
                    with self.assertRaises(ValueError):
                        runner.run_once(
                            authorized=True,
                            price_confirmed_date=datetime.now().astimezone().date().isoformat(),
                            folder=folder)
                self.assertEqual(post.call_count, 1)
                self.assertEqual(result["status"], expected)
                self.assertFalse(runner._paths(folder)[1].exists())

    def test_bad_answers_save_raw_but_never_review(self):
        cases = [
            self._response(finish="length"), self._response(content=""),
            self._response(content="not JSON"),
            self._response(answer={**self.answer, "doc_version": "wrong"}),
            self._response(answer={**self.answer, "items": [
                {"field": "rate_meaning", "status": "known", "reason": "",
                 "claims": [{"text": "Invented", "anchors": ["P999"]}]},
                *self.answer["items"][1:]]}),
            self._response(usage={"prompt_tokens": 30001, "completion_tokens": 1}),
            self._response().replace(b'"model": "deepseek-flash"', b'"model": "other"'),
        ]
        for response in cases:
            with self.subTest(response=response[:20]):
                folder = self.folder / str(len(os.listdir(self.folder))) if self.folder.exists() else self.folder
                with patch.object(runner, "_post", return_value=response):
                    result = runner.run_once(
                        authorized=True,
                        price_confirmed_date=datetime.now().astimezone().date().isoformat(),
                        folder=folder)
                self.assertEqual(result["status"], "invalid_response")
                self.assertTrue(runner._paths(folder)[1].exists())
                self.assertFalse(runner._paths(folder)[2].exists())

    def test_modified_source_reference_or_body_refused_before_http(self):
        with patch.object(runner, "_post", side_effect=AssertionError("must not call")):
            body = self.pack / "provider-body.json"
            original = body.read_bytes()
            try:
                body.write_bytes(original + b" ")
                with self.assertRaises(ValueError):
                    self._call()
            finally:
                body.write_bytes(original)
        self.assertFalse(self.folder.exists())

    def test_oversized_provider_response_is_refused_without_claiming_raw_saved(self):
        with patch.object(runner, "_post", return_value=b"x" * (runner.MAX_RESPONSE_BYTES + 1)):
            result = self._call()
        self.assertEqual(result["status"], "invalid_response")
        self.assertFalse(runner._paths(self.folder)[1].exists())


if __name__ == "__main__":
    unittest.main()
