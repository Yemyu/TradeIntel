"""High-value offline gates for the unseen notice's one-attempt runner."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime
import json
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import freeze_announcement_reading_unseen as freeze
from scripts import run_announcement_reading_unseen_once as runner


class UnseenOneAttemptTests(unittest.TestCase):
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
            patch.object(runner, "_config", return_value=(
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

    def _response(self, *, content=None, finish="stop") -> bytes:
        answer = {
            "schema_version": self.request["schema_version"],
            "doc_version": self.request["doc_version"],
            "source_sha256": self.request["source_sha256"],
            "items": [
                {"field": field, "status": "known", "reason": "",
                 "claims": [{"text": "Fake transport answer for contract testing",
                             "anchors": ["P7"]}]}
                for field in ("rate_meaning", "conditions", "exceptions")
            ],
        }
        return json.dumps({
            "model": "deepseek-flash",
            "choices": [{"finish_reason": finish, "message": {
                "content": json.dumps(answer) if content is None else content}}],
            "usage": {"prompt_tokens": 7000, "completion_tokens": 1000},
        }).encode()

    def test_default_is_offline_and_live_release_is_closed(self):
        with patch.object(runner, "_post", side_effect=AssertionError("HTTP attempted")):
            self.assertEqual(runner.check()["attempt_status"], "not_started")
            with self.assertRaisesRegex(ValueError, "no live release"):
                self._call()
        self.assertFalse(self.ledger.exists())

    def test_frozen_body_excludes_reference_and_old_r2_answer(self):
        body = json.loads((self.frozen / "provider-body.json").read_text())
        self.assertEqual(set(body), {"model", "messages", *freeze.PARAMS})
        self.assertEqual(body["messages"], self.request["messages"])
        self.assertEqual([entry["role"] for entry in body["messages"]],
                         ["system", "user"])
        self.assertNotIn("13项", json.dumps(body, ensure_ascii=False))
        self.assertNotIn("r2-reading-dev", json.dumps(body))
        self.assertEqual(freeze.verify_frozen(self.frozen)["body_bytes"], 27_784)

    def test_one_fake_call_writes_private_ledger_before_http_and_never_retries(self):
        seen = []
        def fake_post(body, key):
            self.assertEqual(body, (self.frozen / "provider-body.json").read_bytes())
            self.assertEqual(key, "FAKE_KEY")
            state = runner._ledger(runner._paths()[0])
            self.assertEqual(state["status"], "provider_call_started")
            self.assertEqual(state["case_id"], freeze.CASE_ID)
            seen.append(1)
            return self._response()
        with patch.object(runner, "LIVE_RELEASED", True), patch.object(
                runner, "_post", side_effect=fake_post):
            self.assertEqual(self._call()["status"], "needs_human_review")
            with self.assertRaisesRegex(ValueError, "already started"):
                self._call()
        self.assertEqual(seen, [1])
        ledger, raw, review, lock = runner._paths()
        for path in (self.ledger, ledger, raw, review, lock):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o077, 0)
        self.assertNotIn("FAKE_KEY", ledger.read_text())
        self.assertEqual(json.loads(review.read_text())["status"], "review_only")

    def test_four_concurrent_calls_only_one_reaches_fake_provider(self):
        calls = []
        def fake_post(_body, _key):
            calls.append(1)
            return self._response()
        with patch.object(runner, "LIVE_RELEASED", True), patch.object(
                runner, "_post", side_effect=fake_post):
            with ThreadPoolExecutor(max_workers=4) as pool:
                outcomes = []
                for future in [pool.submit(self._call) for _ in range(4)]:
                    try:
                        outcomes.append(future.result())
                    except ValueError:
                        outcomes.append("refused")
        self.assertEqual(len(calls), 1)
        self.assertEqual(sum(isinstance(item, dict) for item in outcomes), 1)

    def test_timeout_is_unknown_and_is_not_sent_again(self):
        with patch.object(runner, "LIVE_RELEASED", True), patch.object(
                runner, "_post", side_effect=TimeoutError("secret detail")) as provider:
            self.assertEqual(self._call()["status"], "unknown_outcome")
            with self.assertRaises(ValueError):
                self._call()
        self.assertEqual(provider.call_count, 1)
        self.assertNotIn("secret detail", runner._paths()[0].read_text())

    def test_reference_source_request_or_body_change_refused_before_http(self):
        with patch.object(runner, "LIVE_RELEASED", True), patch.object(
                runner, "_post", side_effect=AssertionError("HTTP attempted")):
            with patch.object(freeze, "REFERENCE_MANIFEST_SHA256", "0" * 64):
                with self.assertRaises(ValueError):
                    self._call()
            for name in ("source-store.json", "offline/request.json",
                         "provider-body.json"):
                with self.subTest(name=name):
                    target = self.frozen / name
                    original = target.read_bytes()
                    try:
                        target.write_bytes(original + b" ")
                        with self.assertRaises(ValueError):
                            self._call()
                    finally:
                        target.write_bytes(original)
        self.assertFalse(self.ledger.exists())

    def test_invalid_provider_content_saved_but_not_reviewed(self):
        with patch.object(runner, "LIVE_RELEASED", True), patch.object(
                runner, "_post", return_value=self._response(content="")):
            self.assertEqual(self._call()["status"], "invalid_response")
        _, raw, review, _ = runner._paths()
        self.assertTrue(raw.is_file())
        self.assertFalse(review.exists())


if __name__ == "__main__":
    unittest.main()
