import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.live_development import (
    LIVE_REVIEWER_ID,
    ai_assisted_fact_review,
    ai_assisted_review,
    live_preflight,
    run_live_development,
    build_live_runner,
    runtime_configuration,
)
from tradeintel_ai.model_adapter import OpenAICompatibleConfig
from tradeintel_ai.prospective_acceptance import AcceptanceGuardError, digest, validate_fact_review
from tradeintel_ai.prospective_runner import (
    _model_pair_settings,
    _model_transport_settings,
    ProspectiveSyntheticRunner,
    SyntheticCase,
    development_cases,
)
from tradeintel_ai.policy_facts import load_frozen_policy_reference, reference_evidence


class StaticModel:
    def __init__(self, payload):
        self.payload = payload
        self.config = SimpleNamespace(
            model="fake-live-model", base_url="https://example.test/v1",
            temperature=0.0, timeout_seconds=10.0, api_key="",
        )

    def effective_request_settings(self):
        return {
            "model": self.config.model, "temperature": 0.0, "max_tokens": 1536,
            "thinking": {"type": "disabled"}, "stream": False,
        }

    def complete(self, *, messages, tools):
        return ModelResponse(
            text=json.dumps(self.payload, ensure_ascii=False),
            metadata={"finish_reason": "stop", "usage": {"total_tokens": 5}},
        )


def clarification_case():
    question = "我想分析关税影响，但没有说明商品、月份和金额口径。"
    payload = {
        "status": "clarify", "policy_question": None, "policy_as_of": None,
        "trade": None, "comparison": None, "policy_search_query": None,
        "tasks": [], "evidence": {}, "missing": ["商品、月份和金额口径"],
        "request_units": [{"quote": question, "kind": "request", "target": "trade"}],
    }
    return SyntheticCase(
        id="LIVE-CLARIFY-01", question=question, expected_kind="clarification",
        expected_tasks=(), checklist=({"id": "clarification", "kind": "fact"},),
        reference={"gold_marker": "not-in-model"},
    ), payload


class LiveDevelopment0128Tests(unittest.TestCase):
    def test_development_cases_freeze_four_known_scenes(self):
        cases = development_cases()
        self.assertEqual(len(cases), 4)
        self.assertEqual(cases[-1].expected_tasks, ("policy", "trade"))
        self.assertIsNotNone(cases[-1].policy_reference)
        self.assertIsNotNone(cases[-1].independent_request)

    def test_live_constructor_rejects_fixture_reviewer_and_unstrict_mode(self):
        with self.assertRaisesRegex(AcceptanceGuardError, "fixture reviewer"):
            ProspectiveSyntheticRunner(
                "/tmp/never-created-live-fixture", model_factory=lambda *_: None,
                run_mode="live_development", strict_protocol=True,
            )
        with self.assertRaisesRegex(AcceptanceGuardError, "strict_protocol"):
            ProspectiveSyntheticRunner(
                "/tmp/never-created-live-unstrict", model_factory=lambda *_: None,
                run_mode="live_development", strict_protocol=False,
                reviewer=lambda _packet: {}, reviewer_type="ai_assisted",
            )

    def test_live_clarification_uses_live_label_without_network(self):
        case, payload = clarification_case()
        with TemporaryDirectory() as tmp:
            runner = ProspectiveSyntheticRunner(
                Path(tmp) / "batch", cases=[case],
                model_factory=lambda *_: StaticModel(payload),
                reviewer=ai_assisted_review,
                strict_protocol=True,
                reviewer_id=LIVE_REVIEWER_ID,
                run_mode="live_development",
                external_calls=True,
                reviewer_type="ai_assisted",
            )
            summary = runner.run()
            self.assertEqual(summary["status"], "stopped")
            self.assertEqual(summary["run_mode"], "live_development")
            self.assertTrue(summary["external_calls"])
            self.assertFalse(summary["live_development_completed"])
            self.assertFalse(summary["synthetic_protocol_completed"])
            snapshot = json.loads((Path(tmp) / "batch" / "frozen-snapshot.json").read_text())
            self.assertEqual(snapshot["configuration"]["run_mode"], "live_development")
            self.assertEqual(snapshot["configuration"]["external_calls"], True)

    def test_live_review_packet_is_saved_before_reviewer_returns(self):
        case, payload = clarification_case()
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "batch"
            seen = []

            def reviewer(packet):
                path = output / "reviews" / f"{case.id}-planning-pending-packet.json"
                seen.append(path.is_file())
                raise RuntimeError("pause for host review")

            runner = ProspectiveSyntheticRunner(
                output, cases=[case], model_factory=lambda *_: StaticModel(payload),
                reviewer=reviewer, strict_protocol=True,
                reviewer_id=LIVE_REVIEWER_ID, run_mode="live_development",
                external_calls=True, reviewer_type="ai_assisted",
            )
            summary = runner.run()
            self.assertEqual(summary["status"], "stopped")
            self.assertEqual(seen, [True])
            self.assertIn(f"{case.id}:planning", summary["pending_review_packets"])

    def test_preflight_is_zero_network_and_redacts_key(self):
        config = OpenAICompatibleConfig(
            "https://example.test/v1?token=should-not-persist", "glm-test",
            api_key="secret-value", timeout_seconds=12, temperature=0,
        )
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "new-batch"
            report = live_preflight(output, config)
            self.assertEqual(report["network_calls"], 0)
            self.assertFalse(report["ready_for_bounded_run"])
            self.assertFalse(report["resume_supported"])
            self.assertTrue(report["blocking_reasons"])
            self.assertTrue(report["configuration"]["provider"]["api_key_present"])
            self.assertNotIn("secret-value", json.dumps(report, ensure_ascii=False))
            self.assertFalse(output.exists())

    def test_fact_review_is_source_bound_and_not_claimed_as_human_accuracy(self):
        reference = load_frozen_policy_reference(Path(__file__).resolve().parents[1])
        evidence = reference_evidence(reference)
        facts = reference["facts"]
        claims = [
            {"text": "相关商品自2018-07-06起适用，额外税率为25%。",
             "citations": ["initial_notice:p1:c4668", "initial_notice:p2:c5100"]}
        ]
        packet = {
            "version": "fact-review-packet-0119", "case_id": "LIVE-POLICY-01",
            "arm": "with_evidence", "policy_question": reference["question"],
            "policy_as_of": reference["as_of"],
            "answer": {"text": claims[0]["text"], "claims": claims},
            "facts": facts, "evidence": evidence, "citation_evidence": {},
            "reference_sha256": reference["reference_sha256"],
        }
        # Even correct facts cannot be certified without an actual host judgement.
        for arm in ("with_evidence", "no_evidence"):
            packet["arm"] = arm
            for text in (
                "相关商品自2018-07-06起适用，额外税率为25%。",
                "生效日期不是2018-07-06，额外税率不是25%。",
                "2018-07-06，25%，因此关税导致所有进口减少一半。",
            ):
                for citations in ([], ["initial_notice:p1:c4668", "initial_notice:p2:c5100"]):
                    with self.subTest(arm=arm, text=text, citations=citations):
                        packet["answer"] = {"text": text, "claims": [{"text": text, "citations": citations}]}
                        with self.assertRaisesRegex(AcceptanceGuardError, "actual host fact review"):
                            ai_assisted_fact_review(packet)

    def test_fact_review_maps_retrieval_window_id_back_to_frozen_source(self):
        reference = load_frozen_policy_reference(Path(__file__).resolve().parents[1])
        frozen = reference_evidence(reference)
        window_id = "initial_notice:p1:w4000-5200"
        window = {
            **frozen["initial_notice:p1:c4668"],
            "id": window_id,
            "text": frozen["initial_notice:p1:c4668"]["text"],
        }
        packet = {
            "version": "fact-review-packet-0119", "case_id": "LIVE-POLICY-WINDOW",
            "arm": "with_evidence", "policy_question": reference["question"],
            "policy_as_of": reference["as_of"],
            "answer": {"text": "2018-07-06", "claims": [{
                "text": "相关商品自2018-07-06起适用。",
                "citations": [window_id],
            }]},
            "facts": [reference["facts"][0]],
            "evidence": frozen,
            "citation_evidence": {window_id: window},
            "reference_sha256": reference["reference_sha256"],
        }
        with self.assertRaisesRegex(AcceptanceGuardError, "actual host fact review"):
            ai_assisted_fact_review(packet)

    def test_live_entry_blocks_before_model_construction_or_output_creation(self):
        config = OpenAICompatibleConfig("https://example.test/v1", "glm-test", api_key="secret")
        with TemporaryDirectory() as tmp, patch("tradeintel_ai.live_development.model_factory") as factory:
            output = Path(tmp) / "batch"
            for entry in (build_live_runner, run_live_development):
                with self.assertRaisesRegex(AcceptanceGuardError, "live development blocked"):
                    entry(output, config)
            factory.assert_not_called()
            self.assertFalse(output.exists())

    def test_plan_and_report_cannot_be_automatically_approved(self):
        for packet in ({}, {"checklist": [{"id": "scope", "kind": "fact"}]},
                       {"report_document": {"sha256": "unread-report"}}):
            with self.assertRaisesRegex(AcceptanceGuardError, "actual host review required"):
                ai_assisted_review(packet)

    def test_runtime_configuration_has_only_secret_free_provider_identity(self):
        config = OpenAICompatibleConfig("https://example.test/v1", "glm-test", api_key="secret")
        snapshot = runtime_configuration(config)
        self.assertEqual(snapshot["provider"]["base_url"], "https://example.test/v1")
        self.assertEqual(snapshot["provider"]["api_key_present"], True)
        self.assertNotIn("secret", json.dumps(snapshot, ensure_ascii=False))

    def test_transport_and_pair_snapshots_strip_url_credentials_and_queries(self):
        model = StaticModel({})
        model.config = SimpleNamespace(
            model="glm-test", base_url="https://example.test/v1?token=secret",
            temperature=0.0, timeout_seconds=10.0, api_key="secret",
        )
        transport = _model_transport_settings(model)
        pair = _model_pair_settings(model, question="问题", as_of="2018-07-06")
        self.assertEqual(transport["base_url"], "https://example.test/v1")
        self.assertEqual(pair["base_url"], "https://example.test/v1")
        serialized = json.dumps({"transport": transport, "pair": pair})
        self.assertNotIn("token=secret", serialized)


if __name__ == "__main__":
    unittest.main()
