import copy
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
import unittest

from scripts.prepare_public_policy_candidate import build_candidate
from scripts.run_public_policy_eval import (
    build_freeze_spec, preflight, run_injected, verify_freeze,
)
from scripts.run_public_brief_eval import DEFAULT_PACKAGE


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "evals/public_brief_v1/provider_matrix_high_v2.json"
SOURCE = DEFAULT_PACKAGE


class PublicPolicyEvalRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="policy-q3-eval-")
        self.root = Path(self.temp.name)
        self.package = self.root / "candidate"
        build_candidate(source_package=SOURCE, output=self.package)
        self.provider = json.loads(MATRIX.read_text(encoding="utf-8"))["candidates"][0]
        self.freeze = build_freeze_spec(provider=self.provider, package_path=self.package,
                                        matrix_path=MATRIX)
        self.messages = json.loads(
            (self.package / "requests/q3/messages.json").read_text(encoding="utf-8"))

    def tearDown(self):
        self.temp.cleanup()

    def _answer(self):
        payload = json.loads(self.messages[1]["content"])
        return {
            "schema_version": "public-policy-explanation-prototype-v2",
            "binding_sha256": payload["binding_sha256"],
            "policy_explanations": [
                {"topic": "change", "source_ids": ["p1"],
                 "text": "公告列示相关商品的附加关税安排，附加税不等于全部税负。"},
                {"topic": "applicability", "source_ids": ["p1"],
                 "text": "商品范围、原产地和入境条件需要结合登记内容核对。"},
                {"topic": "limits", "source_ids": ["p2"],
                 "text": "这是存档政策事实，不能直接代表现行完整税则，未知条件仍需核对。"},
            ],
            "interpretations": [{"observation_id": "o1", "kind": "meaning",
                                 "text": "这是一项贸易金额观察，不能单独证明政策造成了变化。"}],
            "watchlist": [],
        }

    def _call(self, answer=None, **metadata):
        raw = json.dumps(answer or self._answer(), ensure_ascii=False)
        return lambda **kwargs: (raw, {"finish_reason": "stop",
                                       "usage": {"completion_tokens": 100},
                                       "model": "offline-stub", **metadata})

    def test_preflight_and_freeze_are_independent_from_old_q1_to_q4(self):
        plan = preflight(provider_id=self.provider["id"], package_path=self.package,
                         matrix_path=MATRIX)
        self.assertEqual(plan["protocol"], "public-policy-explanation-prototype-v2")
        self.assertEqual(plan["question"], "q3")
        self.assertEqual(verify_freeze(freeze=self.freeze, provider=self.provider,
                                       package_path=self.package, matrix_path=MATRIX,
                                       allow_candidate=True),
                         __import__("scripts.run_public_policy_eval",
                                    fromlist=["canonical_sha"]).canonical_sha(self.freeze))

    def test_stub_closed_loop_records_zero_api_calls_and_budget(self):
        result = run_injected(provider=self.provider, package_path=self.package,
                              output=self.root / "run", provider_call=self._call(),
                              freeze=self.freeze, matrix_path=MATRIX,
                              ledger_root=self.root / "ledger")
        self.assertEqual(result["status"], "awaiting_semantic_review")
        self.assertEqual(result["api_calls"], 0)
        self.assertTrue(result["run"]["output_budget"]["within_gate"])
        self.assertEqual(result["run"]["validation"]["policy_explanation_count"], 3)

    def test_malformed_policy_answer_is_saved_as_invalid_response(self):
        answer = self._answer()
        answer.pop("policy_explanations")
        result = run_injected(provider=self.provider, package_path=self.package,
                              output=self.root / "bad", provider_call=self._call(answer),
                              freeze=self.freeze, matrix_path=MATRIX,
                              ledger_root=self.root / "ledger")
        self.assertEqual(result["status"], "invalid_response")
        self.assertEqual(result["api_calls"], 0)
        self.assertTrue((self.root / "bad/q3/raw-response.txt").is_file())

    def test_duplicate_attempt_is_refused_before_provider_call(self):
        calls = {"count": 0}
        def provider_call(**kwargs):
            calls["count"] += 1
            return self._call()(**kwargs)
        ledger = self.root / "ledger"
        first = run_injected(provider=self.provider, package_path=self.package,
                             output=self.root / "first", provider_call=provider_call,
                             freeze=self.freeze, matrix_path=MATRIX, ledger_root=ledger)
        self.assertEqual(first["status"], "awaiting_semantic_review")
        with self.assertRaisesRegex(ValueError, "已有运行记录"):
            run_injected(provider=self.provider, package_path=self.package,
                         output=self.root / "second", provider_call=provider_call,
                         freeze=self.freeze, matrix_path=MATRIX, ledger_root=ledger)
        self.assertEqual(calls["count"], 1)

    def test_wrong_source_or_freeze_change_is_rejected_before_call(self):
        answer = self._answer()
        answer["policy_explanations"][0]["source_ids"] = ["p999"]
        result = run_injected(provider=self.provider, package_path=self.package,
                              output=self.root / "wrong", provider_call=self._call(answer),
                              freeze=self.freeze, matrix_path=MATRIX,
                              ledger_root=self.root / "ledger")
        self.assertEqual(result["status"], "invalid_response")
        changed = copy.deepcopy(self.freeze)
        changed["params"]["body_max_chars"] = 1999
        with self.assertRaisesRegex(ValueError, "字符门"):
            verify_freeze(freeze=changed, provider=self.provider, package_path=self.package,
                          matrix_path=MATRIX, allow_candidate=True)

    def test_rehashed_report_mismatch_is_rejected(self):
        relative = "host_artifacts/q3/response.json"
        path = self.package / relative
        response = json.loads(path.read_text())
        response["report"]["title"] = "different report"
        path.write_text(json.dumps(response))
        manifest_path = self.package / "MANIFEST.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files_sha256"][relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "绑定不一致"):
            preflight(provider_id=self.provider["id"], package_path=self.package,
                      matrix_path=MATRIX)

    def test_ledger_payload_cannot_override_identity(self):
        from tradeintel_ai.public_policy_eval_ledger import claim, append, load
        started = claim(self.root, base_key="a" * 64, metadata={"question_id": "q3"})
        for key in ("event", "run_id", "base_key", "question_id", "at_utc"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "身份字段"):
                append(self.root, run_id=started["run_id"], event="awaiting_semantic_review",
                       payload={key: "override"})
        self.assertEqual(len(load(self.root)["events"]), 1)

    def test_invalid_matrix_schema_and_duplicate_ids_rejected(self):
        matrix = json.loads(MATRIX.read_text())
        path = self.root / "matrix.json"
        for changed in ({**matrix, "schema_version": "wrong"},
                        {**matrix, "candidates": [self.provider, self.provider]}):
            path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "matrix"):
                preflight(provider_id=self.provider["id"], package_path=self.package,
                          matrix_path=path)


if __name__ == "__main__":
    unittest.main()
