"""Offline checks for the GLM comparison; no real provider calls."""
import io
import json
import os
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request

from scripts.glm_retest_transport import (BASE_URL, ENDPOINT, CAPACITY_BOUND, MODELS,
    GLMToolModel, GLMSendLedger, GLMAccountedOpener, create_model, load_key, profile)
from scripts.run_glm_agent_retest import smoke, run, prepare
from scripts.run_us_agent_retest import GateError, RecordingModel, AgentCaseExecutor, verify_snapshot
from scripts.us_retest_transport import canonical_hash, validate_permit as validate_deepseek
from tradeintel_ai.model_adapter import OpenAICompatibleConfig, ModelAdapterError


def turn(case="R01"):
    ident = uuid.uuid4().hex
    return {"case_id": case, "request_id": ident, "session_id": ident}


def permit(model="glm-4.5-air", **changes):
    p = {"schema": "glm-resource-pack-retest-permit-v1", "approved": True, "approver_role": "user",
         "freeze_sha256": "a" * 64, "profile_sha256": canonical_hash(profile(model)),
         "model": model, "endpoint": ENDPOINT, "authorization_message_sha256": "b" * 64,
         "expires_at": 10000, "max_requests": 48, "max_rounds": 6, "max_tools": 12,
         "max_tokens": 8192, "max_body_bytes": 65536, "timeout_seconds": 90,
         "wall_seconds": 7200, "user_turns": 12, "retry_allowed": False,
         "max_total_tokens": 2500000, "billing": "resource_pack_expected_not_verified"}
    return {**p, **changes}


def wire(model="glm-4.5-air", **changes):
    payload = {"model": model, "temperature": 0, "stream": False,
               "thinking": {"type": "enabled"}, "max_tokens": 8192,
               "messages": [{"role": "user", "content": "fixture"}]}
    payload.update(changes)
    return Request(ENDPOINT, data=json.dumps(payload).encode(), method="POST")


def reply(model="glm-4.5-air", *, reasoning="private-thinking", usage=None, arguments='{"value":"ping"}'):
    message = {"role": "assistant", "content": None, "tool_calls": [{"id": "call-1", "type": "function",
        "function": {"name": "connection_check", "arguments": arguments}}]}
    if reasoning != "ABSENT":
        message["reasoning_content"] = reasoning
    return io.BytesIO(json.dumps({"model": model, "choices": [{"finish_reason": "tool_calls", "message": message}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15} if usage is None else usage}).encode())


class GLMAdapterTests(unittest.TestCase):
    def test_selected_profiles_have_no_guessed_high_parameter(self):
        for model in MODELS:
            self.assertEqual(profile(model)["request_params"], {"thinking": {"type": "enabled"}, "max_tokens": 8192})
        for model in ("glm-5.3-flash", "qwen3.8-max", "deepseek-flash"):
            with self.assertRaises(GateError):
                profile(model)

    def test_reasoning_absent_null_and_text_are_replayed_without_metadata(self):
        for reasoning in ("ABSENT", None, "private-thinking"):
            with self.subTest(reasoning=reasoning):
                captured = []
                def http(request, **kwargs):
                    captured.append(json.loads(request.data))
                    return reply(reasoning=reasoning)
                adapter = GLMToolModel(OpenAICompatibleConfig(BASE_URL, "glm-4.5-air", "test-key"),
                                      opener=http, request_params=profile("glm-4.5-air")["request_params"])
                first = adapter.complete(messages=[{"role": "user", "content": "fixture"}], tools=[])
                message = {"role": "assistant", "content": first.wire_content,
                    "tool_calls": [{"call_id": "call-1", "name": "connection_check", "arguments": {"value": "ping"}}]}
                if first.reasoning_present:
                    message["reasoning_content"] = first.reasoning_content
                adapter.complete(messages=[message], tools=[])
                forwarded = captured[1]["messages"][0]
                self.assertEqual("reasoning_content" in forwarded, reasoning != "ABSENT")
                if reasoning != "ABSENT":
                    self.assertEqual(forwarded["reasoning_content"], reasoning)
                self.assertIsNone(forwarded["content"])
                self.assertNotIn("reasoning_content", first.metadata)
                self.assertFalse(captured[0]["stream"])

    def test_invalid_reasoning_and_wrong_host_are_rejected(self):
        with self.assertRaises(GateError):
            GLMToolModel(OpenAICompatibleConfig("https://other.invalid", "glm-4.5-air"),
                         request_params=profile("glm-4.5-air")["request_params"])
        adapter = GLMToolModel(OpenAICompatibleConfig(BASE_URL, "glm-4.5-air"),
                              opener=lambda *a, **k: reply(reasoning={"bad": True}),
                              request_params=profile("glm-4.5-air")["request_params"])
        with self.assertRaises(ModelAdapterError):
            adapter.complete(messages=[{"role": "user", "content": "fixture"}], tools=[])

    def test_private_credentials_reject_permissions_and_symlink(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "credentials.json"
            path.write_text(json.dumps({"glm": {"base_url": BASE_URL, "api_key": "fixture-secret-key"}}))
            os.chmod(path, 0o600)
            self.assertEqual(load_key(path), "fixture-secret-key")
            os.chmod(path, 0o644)
            with self.assertRaises(GateError):
                load_key(path)
            alias = Path(name) / "alias.json"
            alias.symlink_to(path)
            with self.assertRaises(GateError):
                load_key(alias)


class GLMLedgerTests(unittest.TestCase):
    def ledger(self, root, turns, model="glm-4.5-air", **changes):
        return GLMSendLedger(root, permit(model, **changes), profile(model), lambda: "a" * 64,
                             turns=turns, clock=lambda: 1, monotonic=lambda: 1)

    def test_unapproved_expired_cross_model_and_invalid_limits_rejected(self):
        for changes in ({"approved": False}, {"expires_at": 0}, {"max_requests": True},
                        {"profile_sha256": canonical_hash(profile("glm-4.6v"))}, {"max_total_tokens": 1}, {"retry_allowed": True},
                        {"authorization_message_sha256": None}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as name:
                with self.assertRaises(GateError):
                    self.ledger(name, [turn()], **changes)

    def test_deepseek_permit_validator_still_rejects_glm(self):
        with self.assertRaises(GateError):
            validate_deepseek(permit(), "a" * 64, 1)

    def test_concurrent_reservation_is_single_and_existing_batch_cannot_restart(self):
        with tempfile.TemporaryDirectory() as name:
            t = turn()
            ledger = self.ledger(name, [t])
            with ledger.batch():
                def reserve(_):
                    try:
                        return ledger.reserve(wire(), t)
                    except GateError:
                        return None
                with ThreadPoolExecutor(max_workers=4) as pool:
                    self.assertEqual(sum(v is not None for v in pool.map(reserve, range(4))), 1)
                self.assertEqual(ledger.records()[0]["reserved_tokens"], 2 * CAPACITY_BOUND)
            with self.assertRaises(GateError):
                with self.ledger(name, [t]).batch():
                    pass

    def test_six_per_turn_and_forty_eight_batch_cap(self):
        with tempfile.TemporaryDirectory() as name:
            turns = [turn("R" + str(i)) for i in range(9)]
            ledger = self.ledger(name, turns)
            with ledger.batch():
                for t in turns[:8]:
                    opener = GLMAccountedOpener(ledger, t, transport=lambda *a, **k: reply())
                    for _ in range(6):
                        opener(wire(), timeout=90)
                        opener.settle()
                    with self.assertRaises(GateError):
                        opener(wire(), timeout=90)
                with self.assertRaises(GateError):
                    GLMAccountedOpener(ledger, turns[-1])(wire(), timeout=90)
                self.assertEqual(len(ledger.records()), 48)

    def test_bad_config_body_timeout_and_turn_do_not_send(self):
        with tempfile.TemporaryDirectory() as name:
            t = turn()
            ledger = self.ledger(name, [t])
            with ledger.batch():
                calls = []
                opener = GLMAccountedOpener(ledger, t, transport=lambda *a, **k: calls.append(1))
                bads = [wire(model="glm-4.6v"), wire(reasoning_effort="high"), wire(stream=True),
                        wire(messages=[{"role": "user", "content": "x" * 65536}]),
                        Request("https://other.invalid", data=b"{}", method="POST")]
                for request in bads:
                    with self.assertRaises(GateError):
                        opener(request, timeout=90)
                with self.assertRaises(GateError):
                    opener(wire(), timeout=91)
                with self.assertRaises(GateError):
                    ledger.reserve(wire(), turn())
                self.assertFalse(calls)
                self.assertFalse(ledger.records())

    def test_response_model_mismatch_stops_before_another_send(self):
        with tempfile.TemporaryDirectory() as name:
            t = turn()
            ledger = self.ledger(name, [t])
            with ledger.batch():
                opener = GLMAccountedOpener(ledger, t, transport=lambda *a, **k: reply("glm-4.6v"))
                with self.assertRaises(GateError):
                    opener(wire(), timeout=90)
                self.assertFalse(opener.accounting_complete())
                with self.assertRaises(GateError):
                    opener(wire(), timeout=90)

    def test_bad_usage_keeps_reservation_and_stops(self):
        for usage in ({}, {"prompt_tokens": True, "completion_tokens": 1, "total_tokens": 2},
                      {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 3},
                      {"prompt_tokens": 1048577, "completion_tokens": 0, "total_tokens": 1048577}):
            with self.subTest(usage=usage), tempfile.TemporaryDirectory() as name:
                t = turn()
                ledger = self.ledger(name, [t])
                with ledger.batch():
                    opener = GLMAccountedOpener(ledger, t, transport=lambda *a, **k: reply(usage=usage))
                    opener(wire(), timeout=90)
                    with self.assertRaises(GateError):
                        opener.settle()
                    self.assertFalse(list(Path(name).glob("*-settled.json")))
                    self.assertTrue((Path(name) / "STOP.json").exists())

    def test_token_ceiling_rejects_before_another_send(self):
        with tempfile.TemporaryDirectory() as name:
            t = turn()
            ledger = self.ledger(name, [t])
            with ledger.batch():
                usage = {"prompt_tokens": 450000, "completion_tokens": 0, "total_tokens": 450000}
                opener = GLMAccountedOpener(ledger, t, transport=lambda *a, **k: reply(usage=usage))
                opener(wire(), timeout=90)
                opener.settle()
                with self.assertRaises(GateError):
                    opener(wire(), timeout=90)
                self.assertEqual(len(ledger.records()), 1)

    def test_accounted_adapter_records_no_key_or_private_reasoning(self):
        with tempfile.TemporaryDirectory() as name:
            t = turn()
            ledger = self.ledger(Path(name) / "ledger", [t])
            with ledger.batch():
                adapter = create_model(profile("glm-4.5-air"), "fixture-secret-key", ledger, t,
                                       transport=lambda *a, **k: reply())
                model = RecordingModel(adapter, Path(name) / "responses", accounting=adapter.retest_accounting)
                answer = model.complete(messages=[{"role": "user", "content": "fixture"}], tools=[])
                self.assertEqual(answer.reasoning_content, "private-thinking")
                self.assertTrue(adapter.retest_accounting.accounting_complete())
                disk = "".join(p.read_text() for p in Path(name).rglob("*.json"))
                self.assertNotIn("fixture-secret-key", disk)
                self.assertNotIn("private-thinking", disk)
                self.assertEqual(adapter.retest_origin, "offline_fixture")

    def test_clock_backwards_and_profile_mutation_reject(self):
        with tempfile.TemporaryDirectory() as name:
            now = [1]
            ledger = GLMSendLedger(name, permit(), profile("glm-4.5-air"), lambda: "a" * 64,
                                 turns=[turn()], clock=lambda: now[0], monotonic=lambda: now[0])
            with ledger.batch():
                now[0] = 0
                with self.assertRaises(GateError):
                    ledger.check_time()
        with tempfile.TemporaryDirectory() as name:
            ledger = self.ledger(name, [turn()])
            with ledger.batch():
                ledger.effective["model"] = "glm-4.6v"
                with self.assertRaises(GateError):
                    ledger.check_time()

    def test_timeout_keeps_dispatched_record_and_never_retries(self):
        with tempfile.TemporaryDirectory() as name:
            t = turn()
            ledger = self.ledger(name, [t])
            calls = []
            def timeout(*args, **kwargs):
                calls.append(1)
                raise TimeoutError("fixture timeout")
            with ledger.batch():
                opener = GLMAccountedOpener(ledger, t, transport=timeout)
                with self.assertRaises(TimeoutError):
                    opener(wire(), timeout=90)
                with self.assertRaises(GateError):
                    opener(wire(), timeout=90)
                self.assertEqual(calls, [1])
                self.assertTrue((Path(name) / "send-001-dispatched.json").exists())


class GLMRunnerTests(unittest.TestCase):
    def test_smoke_two_turns_offline_no_private_fields_and_no_restart(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            credentials = root / "credentials.json"
            credentials.write_text(json.dumps({"glm": {"base_url": BASE_URL, "api_key": "fixture-secret-key"}}))
            os.chmod(credentials, 0o600)
            sent = []
            def fake(request, **kwargs):
                payload = json.loads(request.data)
                sent.append(payload)
                if len(sent) == 1:
                    return reply()
                self.assertEqual(payload["messages"][-2]["reasoning_content"], "private-thinking")
                return io.BytesIO(json.dumps({"model": "glm-4.5-air", "choices": [{"message": {"content": "OK"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}).encode())
            result = smoke("glm-4.5-air", root / "smoke", credential_path=credentials, transport=fake)
            self.assertEqual(result["status"], "tool_roundtrip_passed")
            self.assertEqual(result["api_requests"], 0)
            self.assertEqual(result["attempted_requests"], 2)
            self.assertFalse(result["accuracy_measured"])
            disk = (root / "smoke/result.json").read_text()
            self.assertNotIn("private-thinking", disk)
            self.assertNotIn("fixture-secret-key", disk)
            with self.assertRaises(GateError):
                smoke("glm-4.5-air", root / "smoke", credential_path=credentials, transport=fake)

    def test_rejected_permit_never_loads_key_or_constructs_model(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "inputs").mkdir()
            (root / "runtime").mkdir()
            (root / "inputs/effective-config.json").write_text(json.dumps(profile("glm-4.5-air")))
            (root / "runtime/turns.json").write_text(json.dumps([turn()]))
            approval = root / "permit.json"
            approval.write_text(json.dumps(permit(approved=False)))
            with patch("scripts.run_glm_agent_retest.verify_package", return_value="a" * 64), \
                 patch("scripts.run_glm_agent_retest.load_key") as key, \
                 patch("scripts.run_glm_agent_retest.create_model") as model:
                with self.assertRaises(GateError):
                    run(root, root / "data", approval)
                key.assert_not_called()
                model.assert_not_called()

    def test_real_agent_two_turns_with_glm_http_fixture(self):
        from tests.test_trade_agent_mainline import DATA_ROOT
        from tests.test_trade_agent_pilot import FakeToolHTTP
        project = Path(__file__).resolve().parents[1]
        reference_file = project / "tmp/handoff-runs/us-agent-final-regression-20261002-v3b/reference/trade.json"
        if not DATA_ROOT.exists() or not reference_file.exists():
            self.skipTest("Local verified data not installed")
        plan = json.loads((project / "evals/us_agent_retest_v1/scenarios.json").read_text())
        reference = json.loads(reference_file.read_text())
        for model_name in MODELS:
            with self.subTest(model=model_name), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                first = turn()
                turns = [{**first, "question": plan["cases"][0]["question"], "requires": None},
                         {"case_id": "R02", "question": plan["cases"][1]["question"],
                          "requires": "R01", "request_id": uuid.uuid4().hex, "session_id": first["session_id"]}]
                ledger = GLMSendLedger(root / "ledger", permit(model_name), profile(model_name), lambda: "a" * 64,
                                       turns=turns, clock=lambda: 1, monotonic=lambda: 1)
                def factory(case_id):
                    fake = FakeToolHTTP()
                    def transport(request, **kwargs):
                        body = json.loads(fake(request, **kwargs).read())
                        body["model"] = model_name
                        for call in body["choices"][0]["message"].get("tool_calls", []):
                            function = call["function"]
                            if function["name"] in {"search_products", "query_trade"}:
                                args = json.loads(function["arguments"])
                                args["flow"] = "export" if case_id == "R02" else "import"
                                function["arguments"] = json.dumps(args)
                        return io.BytesIO(json.dumps(body).encode())
                    return create_model(profile(model_name), "fixture-secret-key", ledger,
                                        next(t for t in turns if t["case_id"] == case_id), transport=transport)
                executor = AgentCaseExecutor(plan, reference, DATA_ROOT, root / "runtime", root / "evidence", factory)
                with ledger.batch():
                    for t in turns:
                        result = executor(t)
                        self.assertTrue(result["numeric_complete"])
                        self.assertTrue(result["request_accounting_complete"])
                        self.assertEqual(result["origin"], "offline_fixture")
                    self.assertEqual(len(ledger.records()), 6)


if __name__ == "__main__":
    unittest.main()
