"""Offline one-attempt tests. No test may contact the model provider."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from scripts import freeze_announcement_reading_v3_once as freeze
from scripts import run_announcement_reading_v3_once as runner
from tradeintel_ai.announcement_reading_v3 import CHECKS, FIELDS, SCHEMA


class ReadingV3OneAttemptTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=runner.ROOT / ".local/experiments")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.candidate = self.root / "candidate"
        self.live = self.root / "live"
        self.ledger_parent = self.root / "v3-ledger"
        self.ledger_root = self.ledger_parent / "case"
        freeze.prepare_frozen(self.candidate)
        self.patches = (
            patch.object(runner, "FROZEN_CANDIDATE", self.candidate),
            patch.object(runner, "FROZEN_LIVE", self.live),
            patch.object(runner, "LEDGER_PARENT", self.ledger_parent),
            patch.object(runner, "LEDGER_ROOT", self.ledger_root),
            patch.object(runner, "_deadline", side_effect=lambda _: nullcontext()),
            patch.object(runner, "_config", return_value=(
                type("FakeConfig", (), {"api_key": "FAKE_KEY"})(), "fake-identity")),
        )
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def release_fixture(self):
        freeze.prepare_frozen(self.live, live_release=True,
                              authorization_reference="test-fixture-only-not-user-authorization")

    def call(self):
        return runner.run_once(authorized=True, price_confirmed_date="2026-09-29")

    def valid_answer(self, *, incomplete=False):
        request = json.loads((self.candidate / "offline/request.json").read_text())
        facts = {
            "policy_action": ("商务部将中国 CBS 反倾销调查的初裁期限延长至 2026 年 10 月 28 日。", ["P17"]),
            "measure_nature": ("本公告调整初裁程序期限，不决定税率。", ["P17"]),
            "origin_by_measure": ("该 LTFV 调查针对中国来源 CBS。", ["P6", "P12"]),
            "product_scope": ("商品为 CBS；本公告没有给出 HTS 编码。", ["P6"]),
            "effective_date": ("公告适用日为 2026 年 9 月 24 日。", ["P8"]),
        }
        items = []
        number = 0
        for field in FIELDS:
            claims, checks = [], []
            for check_id, owner, _ in CHECKS:
                if owner != field:
                    continue
                if check_id in facts:
                    number += 1
                    cid = f"C{number}"
                    text, anchors = facts[check_id]
                    claims.append({"claim_id": cid, "text": text,
                                   "anchors": anchors, "check_ids": [check_id]})
                    checks.append({"check_id": check_id,
                                   "status": "partial" if check_id == "product_scope" else "addressed",
                                   "claim_ids": [cid],
                                   "note": "未载税号及详细排除范围" if check_id == "product_scope" else ""})
                else:
                    checks.append({"check_id": check_id,
                                   "status": "incomplete" if incomplete and check_id == "entry_event"
                                   else "not_applicable", "claim_ids": [],
                                   "note": "本次回答没有查完" if incomplete and check_id == "entry_event"
                                   else "本程序延期公告不涉及此项"})
            items.append({"field": field, "claims": claims, "checks": checks})
        return {"schema_version": SCHEMA, "doc_version": request["doc_version"],
                "source_sha256": request["source_sha256"], "items": items}

    def response(self, *, answer=None, finish="stop", model="deepseek-flash",
                 prompt_tokens=7011, completion_tokens=1000):
        if answer is None:
            answer = self.valid_answer()
        return json.dumps({
            "model": model,
            "choices": [{"finish_reason": finish,
                         "message": {"content": json.dumps(answer, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": prompt_tokens,
                      "completion_tokens": completion_tokens},
        }, ensure_ascii=False).encode()

    def test_candidate_is_not_released_and_post_excludes_reference(self):
        frozen = freeze.verify_frozen(self.candidate)
        self.assertEqual(frozen["status"], freeze.CANDIDATE_STATUS)
        self.assertEqual(frozen["body_bytes"], 7607)
        self.assertEqual(frozen["peak_reserve_estimate_usd"], "0.036")
        body = json.loads((self.candidate / "provider-body.json").read_text())
        request = json.loads((self.candidate / "offline/request.json").read_text())
        self.assertEqual(body["messages"], request["messages"])
        self.assertEqual(body["model"], "deepseek-flash")
        self.assertEqual(body["reasoning_effort"], "high")
        self.assertNotIn("F01", json.dumps(body, ensure_ascii=False))
        with patch.object(runner, "_post", side_effect=AssertionError("network")):
            self.assertEqual(runner.check()["status"], "not_released")
            with self.assertRaisesRegex(ValueError, "missing or unsafe"):
                self.call()
        self.assertFalse(self.ledger_parent.exists())

    def test_release_requires_separate_reference_and_tampering_refused(self):
        with self.assertRaisesRegex(ValueError, "separate authorization"):
            freeze.prepare_frozen(self.live, live_release=True)
        self.assertFalse(self.live.exists())
        self.release_fixture()
        self.assertEqual(runner.check()["attempt_status"], "not_started")
        with self.assertRaisesRegex(ValueError, "authorization"):
            runner.run_once(authorized=False, price_confirmed_date="2026-09-29")
        self.assertFalse(self.ledger_parent.exists())
        (self.live / "provider-body.json").write_bytes(b"{}")
        with patch.object(runner, "_post", side_effect=AssertionError("network")):
            with self.assertRaises(ValueError):
                self.call()
        self.assertFalse(self.ledger_parent.exists())

    def test_valid_answer_is_only_queued_for_review_and_no_retry(self):
        self.release_fixture()
        fake = self.response()
        with patch.object(runner, "_post", return_value=fake) as post:
            result = self.call()
            self.assertEqual(result["status"], "needs_human_review")
            self.assertEqual(post.call_count, 1)
            with self.assertRaisesRegex(ValueError, "already started"):
                self.call()
            self.assertEqual(post.call_count, 1)
        ledger, raw, review, _ = runner._paths()
        self.assertEqual(json.loads(ledger.read_text())["status"], "needs_human_review")
        self.assertEqual(raw.read_bytes(), fake)
        self.assertTrue(json.loads(review.read_text())["ready_for_review"])

    def test_concurrent_calls_share_one_consumption_slot(self):
        self.release_fixture()
        counts = []
        gate = threading.Lock()

        def fake_post(_body, _key):
            with gate:
                counts.append(1)
            time.sleep(0.03)
            return self.response()

        with patch.object(runner, "_post", side_effect=fake_post):
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(self.call) for _ in range(4)]
                results = []
                for future in futures:
                    try:
                        results.append(future.result())
                    except ValueError as exc:
                        results.append(str(exc))
        self.assertEqual(len(counts), 1)
        self.assertEqual(sum(isinstance(item, dict) for item in results), 1)
        self.assertEqual(sum("already started" in item for item in results
                             if isinstance(item, str)), 3)

    def test_transport_failures_never_retry(self):
        cases = (
            (HTTPError(runner.ENDPOINT, 400, "bad request", {}, None), "provider_rejected"),
            (HTTPError(runner.ENDPOINT, 503, "unavailable", {}, None), "unknown_outcome"),
            (TimeoutError("deadline"), "unknown_outcome"),
            (URLError("connection dropped"), "unknown_outcome"),
        )
        for error, expected in cases:
            with self.subTest(error=repr(error)), TemporaryDirectory(
                    dir=runner.ROOT / ".local/experiments") as directory:
                if not self.live.exists():
                    self.release_fixture()
                with patch.object(runner, "LEDGER_PARENT", Path(directory) / "parent"), \
                     patch.object(runner, "LEDGER_ROOT", Path(directory) / "parent/case"), \
                     patch.object(runner, "_post", side_effect=error) as post:
                    self.assertEqual(self.call()["status"], expected)
                    self.assertEqual(post.call_count, 1)
                    with self.assertRaisesRegex(ValueError, "already started"):
                        self.call()
                    self.assertEqual(post.call_count, 1)

    def test_invalid_results_and_incomplete_are_not_success(self):
        self.release_fixture()
        incomplete = self.valid_answer(incomplete=True)
        cases = (
            (self.response(finish="length"), "invalid_response", "answer_contract"),
            (self.response(model="another-model"), "invalid_response", "answer_contract"),
            (self.response(completion_tokens=20_001), "invalid_response", "answer_contract"),
            (b"not JSON", "invalid_response", "answer_contract"),
            (self.response(answer=incomplete), "invalid_response", "incomplete_check"),
            (self.response(answer={"wrong": "shape"}), "invalid_response", "answer_contract"),
            (self.response(answer="x" * 16_001), "invalid_response", "answer_contract"),
            (b"x" * (runner.MAX_RESPONSE_BYTES + 1), "invalid_response", "response_too_large"),
        )
        for raw, status, category in cases:
            with self.subTest(category=category), TemporaryDirectory(
                    dir=runner.ROOT / ".local/experiments") as directory:
                with patch.object(runner, "LEDGER_PARENT", Path(directory) / "parent"), \
                     patch.object(runner, "LEDGER_ROOT", Path(directory) / "parent/case"), \
                     patch.object(runner, "_post", return_value=raw) as post:
                    self.assertEqual(self.call()["status"], status)
                    ledger, _, _, _ = runner._paths()
                    self.assertEqual(json.loads(ledger.read_text())["error_category"], category)
                    with self.assertRaisesRegex(ValueError, "already started"):
                        self.call()
                    self.assertEqual(post.call_count, 1)

    def test_interruption_after_durable_reservation_cannot_restart(self):
        self.release_fixture()
        with patch.object(runner, "_post", side_effect=KeyboardInterrupt) as post:
            with self.assertRaises(KeyboardInterrupt):
                self.call()
            ledger, _, _, _ = runner._paths()
            self.assertEqual(json.loads(ledger.read_text())["status"],
                             "provider_call_started")
            with self.assertRaisesRegex(ValueError, "already started"):
                self.call()
            self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
