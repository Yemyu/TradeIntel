import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tradeintel_ai.session_brief import build_temporal_session_brief
from src.tradeintel_ai.session_store import (
    create_session,
    load_session,
    set_request,
    start_task,
    transition_task,
)
from src.tradeintel_ai.web_app import _handle_session_post, _temporal_draft_gate


VERSION = "91c2ed45f937392ea4473cd156ca05d3c7566e333ff9d50be90f5cbeccba4e1b"


def _request():
    return {
        "schema_version": "analysis-request-v1",
        "original_question": "请说明最近几个月国际贸易变化",
        "policy_id": "us_301_review2025_tungsten_solar",
        "policy_binding": None,
        "products": ["38180000"],
        "window": {"start": "2026-01", "end": "2026-07",
                   "anchor_month": "2026-07", "mode": "explicit",
                   "selection_reason": "回归测试固定窗口"},
        "comparisons": ["series", "mom", "yoy", "origins"],
        "data_version": VERSION,
        "policy_view": "archived_event",
        "policy_verified_at": None,
        "requested_as_of": None,
    }


class PublicExplanationFlowTests(unittest.TestCase):
    """Regression coverage for the new temporal public explanation path."""

    def test_policy_context_rejects_wrong_data_version(self):
        from copy import deepcopy
        from src.tradeintel_ai.session_explanation import build_public_snapshot
        bad = deepcopy(self.brief)
        bad["policy_context"]["data_version"] = "0" * 64
        with self.assertRaises(ValueError):
            build_public_snapshot(bad, question="这项政策改了什么？")

    def test_policy_context_rejects_non_object(self):
        from src.tradeintel_ai.session_explanation import build_public_snapshot
        for bad in ([], False, "", None):
            with self.subTest(context=bad), self.assertRaises(ValueError):
                build_public_snapshot({**self.brief, "policy_context": bad}, question="政策是什么？")

    def setUp(self):
        self.repo_root = Path(__file__).resolve().parents[1]
        self.root = Path(tempfile.mkdtemp(prefix="public-explanation-flow-"))
        self.addCleanup(shutil.rmtree, self.root)
        self.session = create_session(self.root)
        request = _request()
        set_request(self.root, self.session, request, data_version=VERSION)
        task = start_task(self.root, self.session, model="deterministic",
                          prompt_digest="public-flow-test")["task"]
        self.task_id = task["task_id"]
        brief = build_temporal_session_brief(self.repo_root, request,
                                             data_version=VERSION)
        evidence = {
            "kind": brief["kind"],
            "request_digest": brief["evidence"]["request_digest"],
            "query_plan": brief["query_plan"],
            "data_version": brief["data_version"],
            "evidence": brief["evidence"],
            "report": brief["report"],
            "report_sha256": brief["report_sha256"],
            "evidence_sha256": brief["evidence_sha256"],
        }
        transition_task(self.root, self.session, self.task_id,
                        "evidence_ready", evidence=evidence)
        transition_task(self.root, self.session, self.task_id, "generation_started")
        transition_task(self.root, self.session, self.task_id,
                        "response_saved", response=brief)
        transition_task(self.root, self.session, self.task_id, "needs_review")
        self.brief = brief

    def _post(self, path, **payload):
        return _handle_session_post(
            self.root, path,
            {"session_id": self.session["session_id"],
             "task_id": self.task_id, **payload},
            repository=None,
        )

    def test_server_model_call_is_single_claim_and_keeps_review_pending(self):
        import json
        from types import SimpleNamespace
        from src.tradeintel_ai.agent import ModelResponse
        from src.tradeintel_ai.web_app import WebRequestError
        self._post("/api/session/task/explanation/prepare")
        raw = json.dumps({
            "schema_version": "public-brief-explanation-v1",
            "interpretations": [{"observation_id": "o1", "kind": "meaning",
                                 "text": "这项观察需要结合商品范围理解。"}],
            "watchlist": [{"watch_id": "next_trade_release",
                           "rationale": "等待下一期官方数据后核对。"}],
        }, ensure_ascii=False)
        config = SimpleNamespace(api_key="stub-only", model="offline-stub")
        with patch("src.tradeintel_ai.web_app.load_product_config", return_value=config), \
             patch("src.tradeintel_ai.model_adapter.OpenAICompatibleModel") as model:
            model.return_value.complete.return_value = ModelResponse(text=raw)
            result = self._post("/api/session/task/explanation/call")
            self.assertEqual(result["status"], "manual_review_required")
            self.assertEqual(model.return_value.complete.call_count, 1)
            with self.assertRaises(WebRequestError):
                self._post("/api/session/task/explanation/call")
            self.assertEqual(model.return_value.complete.call_count, 1)
        task = next(iter(load_session(self.root, self.session["session_id"])["tasks"].values()))
        self.assertEqual(task["explanation"]["channel"], "api")
        self.assertIsNone(task["explanation"]["review"])

    def test_rejected_key_is_recorded_without_retry(self):
        from types import SimpleNamespace
        from src.tradeintel_ai.model_adapter import ModelAdapterError
        from src.tradeintel_ai.web_app import WebRequestError
        self._post("/api/session/task/explanation/prepare")
        config = SimpleNamespace(api_key="stub-only", model="offline-stub")
        with patch("src.tradeintel_ai.web_app.load_product_config", return_value=config), \
             patch("src.tradeintel_ai.model_adapter.OpenAICompatibleModel") as model:
            model.return_value.complete.side_effect = ModelAdapterError("模型服务返回 HTTP 401")
            with self.assertRaisesRegex(WebRequestError, "凭证或权限未通过验证"):
                self._post("/api/session/task/explanation/call")
            with self.assertRaises(WebRequestError):
                self._post("/api/session/task/explanation/call")
            self.assertEqual(model.return_value.complete.call_count, 1)
        task = next(iter(load_session(self.root, self.session["session_id"])["tasks"].values()))
        self.assertEqual(task["explanation"]["status"], "failed")

    def test_http_400_is_definite_rejection(self):
        from types import SimpleNamespace
        from src.tradeintel_ai.model_adapter import ModelAdapterError
        from src.tradeintel_ai.web_app import WebRequestError
        self._post("/api/session/task/explanation/prepare")
        config = SimpleNamespace(api_key="stub-only", model="offline-stub")
        with patch("src.tradeintel_ai.web_app.load_product_config", return_value=config), \
             patch("src.tradeintel_ai.model_adapter.OpenAICompatibleModel") as model:
            model.return_value.complete.side_effect = ModelAdapterError(
                "模型服务返回 HTTP 400", details={"http_status": 400, "param": "model"})
            with self.assertRaisesRegex(WebRequestError, "请求参数被拒绝"):
                self._post("/api/session/task/explanation/call")
            self.assertEqual(model.return_value.complete.call_count, 1)
        task = next(iter(load_session(self.root, self.session["session_id"])["tasks"].values()))
        self.assertEqual(task["explanation"]["status"], "failed")
        self.assertEqual(task["explanation"]["error_details"]["param"], "model")

    def test_temporal_prepare_submit_review_and_export(self):
        prepared = self._post("/api/session/task/explanation/prepare")
        self.assertEqual(prepared["protocol"], "public-brief-explanation-v1")
        self.assertIn("report_sha256", prepared)
        self.assertNotIn("catalog_sha256", prepared)
        self.assertNotIn("host_bindings", prepared)
        user_payload = __import__("json").loads(prepared["messages"][1]["content"])
        from src.tradeintel_ai.public_input_view import decode_view
        decoded = decode_view(user_payload["view"])
        original_policy = self.brief["policy_context"]
        self.assertEqual(decoded["policy_context"]["sources"], original_policy["sources"])
        self.assertTrue(decoded["policy_context"]["sources"])
        for actual, original in zip(decoded["policy_context"]["product_rates"],
                                    original_policy["product_rates"]):
            self.assertEqual(actual["hts8"], original["hts8"])
            self.assertEqual(actual["additional_duty_percent"], original["additional_duty_percent"])
            for field, value in original["details"].items():
                if field != "field_refs":
                    self.assertEqual(actual["details"][field], value)
        self.assertEqual(decoded["evidence"]["observations"],
                         self.brief["report"]["evidence"]["observations"])
        self.assertTrue(any(item["kind"] == "comparison"
                         for item in decoded["evidence"]["observations"]))

        observation_id = self.brief["report"]["evidence"]["observations"][0]["id"]
        answer = {
            "schema_version": "public-brief-explanation-v1",
            "interpretations": [{
                "observation_id": "o1",
                "kind": "meaning",
                "text": "这项观察表示相关统计需要结合已列出的范围来阅读。",
            }],
            "watchlist": [{
                "watch_id": "next_trade_release",
                "rationale": "等待下一期官方统计后继续核对。",
            }],
        }
        submitted = self._post("/api/session/task/explanation/submit",
                               answer=answer, channel="chat_simulation",
                               model="Luna最高")
        self.assertEqual(submitted["status"], "manual_review_required")
        reviewed = self._post(
            "/api/session/task/explanation/review", reviewer="local",
            facts_checked=True,
            decisions=[
                {"index": 0, "kind": "interpretation", "verdict": "accept",
                 "reason": "已核对程序观察。"},
                {"index": 0, "kind": "watchlist", "verdict": "accept",
                 "reason": "作为非建议性观察项。"},
            ],
        )
        self.assertTrue(reviewed["eligible_for_export"])
        self.assertEqual(self._post("/api/session/task/transition",
                                    state="reviewed")["status"], "reviewed")
        self.assertEqual(self._post("/api/session/task/transition",
                                    state="exportable")["status"], "exportable")
        saved = load_session(self.root, self.session["session_id"])
        task = next(iter(saved["tasks"].values()))
        self.assertEqual(task["response"]["final_kind"],
                         "temporal-report-v1-with-reviewed-explanation")
        self.assertIsNone(_temporal_draft_gate(task))

    def test_policy_mode_has_separate_policy_items_and_requires_their_review(self):
        prepared = self._post("/api/session/task/explanation/prepare", mode="policy")
        self.assertEqual(prepared["protocol"], "public-policy-explanation-prototype-v2")
        self.assertEqual(prepared["mode"], "policy")
        payload = __import__("json").loads(prepared["messages"][1]["content"])
        answer = {
            "schema_version": "public-policy-explanation-prototype-v2",
            "binding_sha256": payload["binding_sha256"],
            "policy_explanations": [
                {"topic": "change", "source_ids": ["p2"],
                 "text": "该公告列示相关商品的附加关税安排，不能将附加税理解为全部税负。"},
                {"topic": "applicability", "source_ids": ["p1", "p2"],
                 "text": "原产地、商品限定和入境条件均需核对，不能仅凭商品名称判定。"},
                {"topic": "limits", "source_ids": ["p1"],
                 "text": "这是存档政策事实，不代表现行完整税则，例外尚未核全。"},
            ],
            "interpretations": [{"observation_id": "o1", "kind": "meaning",
                                 "text": "这项观察是贸易金额变化，不代表政策造成的损失。"}],
            "watchlist": [],
        }
        submitted = self._post("/api/session/task/explanation/submit", answer=answer,
                               channel="stub", model="fixture")
        self.assertEqual(submitted["status"], "manual_review_required")
        review = self._post("/api/session/task/explanation/review", reviewer="local",
                            facts_checked=True,
                            decisions=[
                                {"index": 0, "kind": "interpretation", "verdict": "accept",
                                 "reason": "贸易观察已核对。"},
                                {"index": 0, "kind": "policy_explanation", "verdict": "accept",
                                 "reason": "政策变更来源已核对。"},
                                {"index": 1, "kind": "policy_explanation", "verdict": "accept",
                                 "reason": "适用范围来源已核对。"},
                                {"index": 2, "kind": "policy_explanation", "verdict": "accept",
                                 "reason": "局限说明来源已核对。"},
                            ])
        self.assertEqual(review["status"], "reviewed")
        self.assertTrue(review["eligible_for_export"])
        task = next(item for item in load_session(self.root, self.session["session_id"])["tasks"].values()
                    if item["task_id"] == self.task_id)
        final_report = task["explanation"]["review"]["final_report"]
        self.assertEqual(len(final_report["policy_explanations"]), 3)
        self.assertIn("## 政策说明", task["explanation"]["review"]["rendered_markdown"])
        self.assertEqual(self._post("/api/session/task/transition", state="reviewed")["status"],
                         "reviewed")
        self.assertEqual(self._post("/api/session/task/transition", state="exportable")["status"],
                         "exportable")

    def test_policy_mode_cannot_export_without_policy_acceptance(self):
        prepared = self._post("/api/session/task/explanation/prepare", mode="policy")
        payload = __import__("json").loads(prepared["messages"][1]["content"])
        answer = {
            "schema_version": "public-policy-explanation-prototype-v2",
            "binding_sha256": payload["binding_sha256"],
            "policy_explanations": [
                {"topic": topic, "source_ids": ["p1"], "text": "这项政策说明需要按原文核对。"}
                for topic in ("change", "applicability", "limits")
            ],
            "interpretations": [{"observation_id": "o1", "kind": "meaning",
                                 "text": "这项观察是贸易金额变化，不代表政策造成的损失。"}],
            "watchlist": [],
        }
        self._post("/api/session/task/explanation/submit", answer=answer,
                   channel="stub", model="fixture")
        review = self._post("/api/session/task/explanation/review", reviewer="local",
                            facts_checked=True,
                            decisions=[
                                {"index": 0, "kind": "interpretation", "verdict": "accept", "reason": "已核对。"},
                                {"index": 0, "kind": "policy_explanation", "verdict": "reject", "reason": "未采纳。"},
                                {"index": 1, "kind": "policy_explanation", "verdict": "reject", "reason": "未采纳。"},
                                {"index": 2, "kind": "policy_explanation", "verdict": "reject", "reason": "未采纳。"},
                            ])
        self.assertEqual(review["status"], "needs_review")
        self.assertFalse(review["eligible_for_export"])

    def test_public_snapshot_rejects_bad_task_digest_and_channel(self):
        prepared = self._post("/api/session/task/explanation/prepare")
        current = load_session(self.root, self.session["session_id"])["tasks"]
        explanation = next(iter(current.values()))["explanation"]
        from src.tradeintel_ai.session_explanation import submit_public

        with self.assertRaises(ValueError):
            submit_public(self.root, self.session["session_id"], self.task_id,
                          explanation, "{}", channel="untrusted")

        tampered = dict(explanation)
        tampered["evidence_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            submit_public(self.root, self.session["session_id"], self.task_id,
                          tampered, "{}", channel="chat_simulation")

    def test_wire_semantics_and_order_cannot_be_rehashed_away(self):
        from copy import deepcopy
        from src.tradeintel_ai.public_input_view import build_view, restore_view, _sha
        packet = build_view(self.brief["report"], self.brief["policy_context"])
        for change in ("denominator", "order", "value"):
            bad = deepcopy(packet)
            metrics = bad["view"]["evidence"]["metrics"]
            if change == "denominator":
                metrics["semantics"]["level"]["share"]["denominator_definition"] = "中国全部出口"
            elif change == "order":
                metrics["levels"]["measures"].reverse()
            else:
                metrics["levels"]["rows"][0][4][0] = -999
            bad["sidecar"]["view_sha256"] = _sha(bad["view"])
            with self.subTest(change=change), self.assertRaises(ValueError):
                restore_view(bad)

    def test_policy_revision_is_present_when_statistics_have_gaps(self):
        ids = [x["watch_id"] for x in self.brief["report"]["watchlist"]]
        self.assertEqual(ids, ["next_trade_release", "policy_revision", "coverage_gap"])

    def test_projection_does_not_silently_discard_new_metric_fields(self):
        from copy import deepcopy
        from src.tradeintel_ai.public_input_view import _normal_metric
        metric = deepcopy(self.brief["report"]["evidence"]["metrics"][0])
        metric["new_business_qualification"] = "仅限特定商品"
        with self.assertRaisesRegex(ValueError, "未声明"):
            _normal_metric(metric)

    def test_registration_dedup_requires_equal_values_and_known_columns(self):
        from copy import deepcopy
        from src.tradeintel_ai.public_input_view import _normal_policy
        policy = deepcopy(self.brief["policy_context"])
        _normal_policy(policy)
        policy["product_rates"][0]["details"]["registered_name"] = "不同的商品名称"
        with self.assertRaisesRegex(ValueError, "被去重字段"):
            _normal_policy(policy)
        policy = deepcopy(self.brief["policy_context"])
        policy["registration"]["csv_text"] = policy["registration"]["csv_text"].replace(
            "product_description_zh", "new_legal_qualification", 1)
        with self.assertRaisesRegex(ValueError, "登记列变化"):
            _normal_policy(policy)

    def test_old_snapshot_requires_migration_without_rewriting_file(self):
        import json
        from src.tradeintel_ai.session_explanation import (
            build_public_snapshot, save_public_snapshot, load_public_snapshot,
            HistoricalPublicSnapshotNeedsMigration, PUBLIC_SNAPSHOT_SCHEMA_V1, _sha,
        )
        snapshot = build_public_snapshot(self.brief, question="最近有什么变化？",
                    identity={"session_id": self.session["session_id"], "task_id": self.task_id})
        saved = save_public_snapshot(self.root, self.session["session_id"], self.task_id, snapshot)
        path = self.root / saved["path"]
        historical = json.loads(path.read_text())
        historical["schema_version"] = PUBLIC_SNAPSHOT_SCHEMA_V1
        historical.pop("snapshot_sha256")
        historical["snapshot_sha256"] = _sha(historical)
        raw = json.dumps(historical, ensure_ascii=False)
        path.write_text(raw)
        with self.assertRaises(HistoricalPublicSnapshotNeedsMigration):
            load_public_snapshot(self.root, self.session["session_id"], self.task_id)
        self.assertEqual(path.read_text(), raw)


if __name__ == "__main__":
    unittest.main()
