"""Offline plumbing tests; synthetic answers/reviews are never model scores."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.run_public_brief_eval import (
    DEFAULT_MATRIX, DEFAULT_PACKAGE, _output_budget, _sha_bytes, build_freeze_spec,
    preflight, run_injected,
)
from scripts.score_public_brief_eval import collect_results
from src.tradeintel_ai.public_eval_ledger import file_sha256, record_review
from src.tradeintel_ai.public_eval_protocols import QUESTION_PROTOCOLS


def _offline_answer(messages: list[dict[str, str]], qid: str) -> str:
    payload = json.loads(messages[1]["content"])
    if QUESTION_PROTOCOLS[qid]["mode"] == "policy":
        policy_rows = payload["view"]["policy"]["sources"]["rows"]
        source_ids = [row[0] for row in policy_rows[:3]]
        answer = {
            "schema_version": QUESTION_PROTOCOLS[qid]["protocol"],
            "binding_sha256": payload["binding_sha256"],
            "policy_explanations": [
                {"topic": "change", "source_ids": [source_ids[0]],
                 "text": "公告列出相关商品的附加税安排，但这不等于完整税则。"},
                {"topic": "applicability", "source_ids": [source_ids[1]],
                 "text": "商品范围、原产地和入境条件仍须核对原文。"},
                {"topic": "limits", "source_ids": [source_ids[2]],
                 "text": "这是存档政策信息，未知条件不能当作不存在。"},
            ],
            "interpretations": [{"observation_id": "o1", "kind": "meaning",
                                 "text": "贸易金额变化不能单独证明关税造成了变化。"}],
            "watchlist": [],
        }
    else:
        watch_ids = payload["watchlist_catalog"]
        answer = {
            "schema_version": QUESTION_PROTOCOLS[qid]["protocol"],
            "interpretations": [{"observation_id": "o1", "kind": "meaning",
                                 "text": "这项变化值得继续观察，但不能据此认定政策造成了结果。"}],
            "watchlist": ([{"watch_id": watch_ids[0],
                            "rationale": "继续查看后续官方月度贸易数据。"}]
                          if watch_ids else []),
        }
    return json.dumps(answer, ensure_ascii=False)


class UnifiedPublicFourQuestionEvalTests(unittest.TestCase):
    def setUp(self):
        self.plan = preflight(provider_id="glm-46v", package_path=DEFAULT_PACKAGE,
                              matrix_path=DEFAULT_MATRIX)
        self.freeze = build_freeze_spec(provider=self.plan["provider"],
                                        package_path=DEFAULT_PACKAGE,
                                        matrix_path=DEFAULT_MATRIX)
        self.temp = tempfile.TemporaryDirectory(prefix="unified-public-eval-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_fixed_modes_are_trade_policy_trade_and_trade(self):
        self.assertEqual(self.plan["experiment_id"], "public-brief-unified-v2")
        self.assertEqual([item["mode"] for item in self.plan["questions"]],
                         ["trade", "trade", "policy", "trade"])
        self.assertEqual([item["protocol"] for item in self.plan["questions"]],
                         ["public-brief-explanation-v1",
                          "public-brief-explanation-v1",
                          "public-policy-explanation-prototype-v2",
                          "public-brief-explanation-v1"])
        self.assertEqual(self.freeze["question_protocols"], QUESTION_PROTOCOLS)
        self.assertEqual(self.freeze["params"]["budget_protocol"], "v3")

    def test_protocol_mismatch_and_policy_source_tampering_fail_preflight(self):
        package = self.root / "bad-package"
        shutil.copytree(DEFAULT_PACKAGE, package)
        relative = "host_artifacts/q3/snapshot.json"
        path = package / relative
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        snapshot["mode"] = "trade"
        path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        manifest_path = package / "MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files_sha256"][relative] = _sha_bytes(path)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "快照"):
            preflight(provider_id="glm-46v", package_path=package,
                      matrix_path=DEFAULT_MATRIX)

        changed = self.root / "changed-policy-source"
        shutil.copytree(DEFAULT_PACKAGE, changed)
        snapshot_path = changed / "host_artifacts/q3/snapshot.json"
        response_path = changed / "host_artifacts/q3/response.json"
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        response = json.loads(response_path.read_text(encoding="utf-8"))
        snapshot["policy_context"]["limitations"][0] = "替换后的政策限制文字。"
        response["policy_context"]["limitations"][0] = "替换后的政策限制文字。"
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        response_path.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
        manifest_path = changed / "MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for relative, path in (("host_artifacts/q3/snapshot.json", snapshot_path),
                               ("host_artifacts/q3/response.json", response_path)):
            manifest["files_sha256"][relative] = _sha_bytes(path)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "重建"):
            preflight(provider_id="glm-46v", package_path=changed,
                      matrix_path=DEFAULT_MATRIX)

    def test_policy_reader_text_is_in_combined_character_gate(self):
        parsed = {
            "interpretations": [{"text": "贸" * 250} for _ in range(4)],
            "watchlist": [{"rationale": "观" * 50}],
            "policy_explanations": [{"text": "政" * 350} for _ in range(3)],
        }
        budget = _output_budget("短JSON", {"completion_tokens": 100},
                                budget_protocol="v3", parsed=parsed)
        self.assertEqual(budget["body_chars"], 2100)
        self.assertFalse(budget["within_gate"])
        self.assertEqual(budget["reason"], "body_characters_exceeded")

    def test_policy_text_over_budget_is_blocked_after_trade_body_alone_fits(self):
        ledger = self.root / "budget-ledger"
        results = self.root / "budget-results"
        for qid in ("q1", "q2"):
            output = results / f"budget-{qid}"
            result = run_injected(
                provider=self.plan["provider"], package_path=DEFAULT_PACKAGE,
                output=output, question_id=qid,
                provider_call=lambda messages, tools, qid=qid: (
                    _offline_answer(messages, qid),
                    {"finish_reason": "stop", "usage": {"completion_tokens": 100}}),
                freeze=self.freeze, matrix_path=DEFAULT_MATRIX, ledger_root=ledger)
            self.assertEqual(result["status"], "awaiting_semantic_review")
            record_review(
                ledger, run_id=result["run_id"],
                raw_sha256=file_sha256(output / qid / "raw-response.txt"),
                verdict="pass", reviewer="synthetic-test-only",
                note="仅为执行Q3预算反例，不评价模型。",
                checks={name: {"passed": True, "reason": "离线顺序控制夹具。"}
                        for name in ("structure", "facts", "relevance", "usefulness")})

        def over_budget_policy(messages, tools):
            payload = json.loads(messages[1]["content"])
            source_ids = [row[0] for row in payload["view"]["policy"]["sources"]["rows"][:3]]
            answer = {
                "schema_version": "public-policy-explanation-prototype-v2",
                "binding_sha256": payload["binding_sha256"],
                "policy_explanations": [
                    {"topic": topic, "source_ids": [source_ids[i]], "text": "政" * 350}
                    for i, topic in enumerate(("change", "applicability", "limits"))],
                "interpretations": [
                    {"observation_id": f"o{i}", "kind": "meaning", "text": "贸" * 250}
                    for i in range(1, 5)],
                "watchlist": [],
            }
            return json.dumps(answer, ensure_ascii=False), {
                "finish_reason": "stop", "usage": {"completion_tokens": 100}}

        result = run_injected(
            provider=self.plan["provider"], package_path=DEFAULT_PACKAGE,
            output=results / "budget-q3", question_id="q3",
            provider_call=over_budget_policy, freeze=self.freeze,
            matrix_path=DEFAULT_MATRIX, ledger_root=ledger)
        self.assertEqual(result["status"], "blocked_output_budget")
        self.assertEqual(result["output_budget"]["body_chars"], 2050)
        self.assertEqual(result["output_budget"]["reason"], "body_characters_exceeded")
        self.assertEqual(result["api_calls"], 0)

    def test_all_four_offline_routes_parse_and_keep_legacy_q3_separate(self):
        results = self.root / "results"
        ledger = self.root / "ledger"
        for qid in ("q1", "q2", "q3", "q4"):
            output = results / f"offline-{qid}"
            result = run_injected(
                provider=self.plan["provider"], package_path=DEFAULT_PACKAGE,
                output=output, question_id=qid,
                provider_call=lambda messages, tools, qid=qid: (
                    _offline_answer(messages, qid),
                    {"finish_reason": "stop", "usage": {"completion_tokens": 100},
                     "model": "offline-plumbing-stub"}),
                freeze=self.freeze, matrix_path=DEFAULT_MATRIX, ledger_root=ledger)
            self.assertEqual(result["status"], "awaiting_semantic_review")
            self.assertEqual(result["api_calls"], 0)
            self.assertEqual(result["mode"], QUESTION_PROTOCOLS[qid]["mode"])
            if qid == "q3":
                self.assertEqual(result["protocol"], "public-policy-explanation-prototype-v2")
                self.assertEqual(result["validation"]["policy_explanation_count"], 3)
            raw = output / qid / "raw-response.txt"
            record_review(
                ledger, run_id=result["run_id"], raw_sha256=file_sha256(raw),
                verdict="pass", reviewer="synthetic-test-only",
                note="仅验证离线接线；不构成模型质量审阅。",
                checks={name: {"passed": True, "reason": "仅验证执行与审阅流程，不评价模型质量。"}
                        for name in ("structure", "facts", "relevance", "usefulness")})

        # An old independent single-question Q3 artifact is deliberately not
        # admitted into this new four-question comparison.
        old_q3 = results / "old-policy-only" / "q3"
        old_q3.mkdir(parents=True)
        (old_q3 / "run.json").write_text(json.dumps({
            "schema_version": "public-policy-provider-run-v1", "question_id": "q3",
            "provider": {"id": "glm-46v", "model_id": "glm-4.6v"},
        }), encoding="utf-8")
        (old_q3 / "raw-response.txt").write_text("旧Q3", encoding="utf-8")
        report = collect_results(results_root=results, ledger_root=ledger)
        self.assertEqual(len(report["rows"]), 1)
        row = report["rows"][0]
        self.assertEqual(row["experiment_id"], "public-brief-unified-v2")
        self.assertEqual(row["run_questions"], 4)
        self.assertEqual([item["mode"] for item in row["questions"]],
                         ["trade", "trade", "policy", "trade"])
        # These synthetic passes validate wiring only and are not presented as
        # a real model score outside this test fixture.
        self.assertEqual(row["whole_pass"], 4)
        self.assertEqual(row["api_calls"], 0)


if __name__ == "__main__":
    unittest.main()
