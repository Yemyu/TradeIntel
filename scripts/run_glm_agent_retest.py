"""Prepare or run the selected GLM models on the existing twelve questions.

Preparation is offline. A run needs its own frozen package and finite permit;
neither the old DeepSeek permit nor a successful smoke test grants that permit.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from scripts.glm_retest_transport import (MODELS, BASE_URL, ENDPOINT, GLMToolModel,
    GLMSendLedger, create_model, load_key, profile)
from scripts.run_us_agent_retest import (AgentCaseExecutor, GateError, copy_new_bytes,
    execute_cases, file_hash, snapshot_files, verify_snapshot, write_new)
from scripts.us_retest_transport import canonical_hash
from tradeintel_ai.model_adapter import OpenAICompatibleConfig, safe_error_details

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = PROJECT / "tmp/handoff-runs/us-agent-final-regression-20261002-v3b"
DEFAULT_DATA = PROJECT / "tmp/handoff-runs/trade-demo-data-20260925"
CREDENTIALS = PROJECT / ".local/model-tests-20261002.credentials.json"
POLICY_FILE = "us_301_review2025_tungsten_solar.json"
TESTS = ("tests.test_glm_agent_retest", "tests.test_us_agent_retest",
         "tests.test_us_retest_final", "tests.test_trade_agent_catalog_contract",
         "tests.test_trade_agent_policy_merge_contract", "tests.test_trade_agent_mainline",
         "tests.test_trade_agent_boundaries", "tests.test_trade_agent_policy_evidence",
         "tests.test_trade_agent_pilot", "tests.test_tradeintel_ai_model_adapter")


def prepare(root, model, template, data_root):
    effective = profile(model)
    if root.exists():
        raise GateError("New GLM package already exists; refusing overwrite")
    baseline = verify_snapshot(template / "FROZEN_MANIFEST.json")
    if baseline.get("ready_for_permit") is not True or str((data_root / "BUNDLE_MANIFEST.json").absolute()) not in baseline["files"]:
        raise GateError("Verified original data/package required")
    plan = json.loads((template / "inputs/plan.json").read_text())
    if (plan != json.loads((PROJECT / "evals/us_agent_retest_v1/scenarios.json").read_text())
            or len(plan["cases"]) != 12 or plan["as_of"] != "2026-10-01"):
        raise GateError("Original questions/clock changed")
    policy_source = template / "runtime/.local/announcement-docs" / POLICY_FILE
    store = json.loads(policy_source.read_text())
    if not store.get("documents") or any(d.get("status") != "enabled" for d in store["documents"]):
        raise GateError("Already confirmed enabled policy required")
    if str(policy_source.absolute()) not in baseline["files"]:
        raise GateError("Policy not bound to original freeze")
    root.mkdir(parents=True)
    for name in ("inputs", "runtime", "reference", "results", "ledgers"):
        (root / name).mkdir()
    copy_new_bytes(template / "inputs/plan.json", root / "inputs/plan.json")
    copy_new_bytes(template / "reference/trade.json", root / "reference/trade.json")
    copy_new_bytes(policy_source, root / "runtime/.local/announcement-docs" / POLICY_FILE)
    sessions, turns = {}, []
    for case in plan["cases"]:
        ident = uuid.uuid4().hex
        sessions.setdefault(case["session"], ident)
        turns.append({"case_id": case["id"], "question": case["question"],
                      "request_id": ident, "session_id": sessions[case["session"]],
                      "requires": case.get("requires")})
    write_new(root / "runtime/turns.json", turns)
    write_new(root / "inputs/effective-config.json", effective)
    write_new(root / "inputs/environment.json", {"executable": sys.executable,
        "version": sys.version, "interpreter_sha256": file_hash(Path(sys.executable).resolve())})
    write_new(root / "inputs/original-package.json", {
        "template": str(template.absolute()), "freeze_sha256": file_hash(template / "FROZEN_MANIFEST.json"),
        "data_root": str(data_root.absolute()), "data_manifest_sha256": file_hash(data_root / "BUNDLE_MANIFEST.json"),
        "policy_sha256": file_hash(policy_source), "reference_sha256": file_hash(root / "reference/trade.json")})
    dependencies = [Path(name) for name in baseline["files"]]
    dependencies.extend(PROJECT / name for name in (
        "scripts/glm_retest_transport.py", "scripts/run_glm_agent_retest.py", "tests/test_glm_agent_retest.py"))
    dependencies.extend((root / "inputs").glob("*.json"))
    dependencies.extend([root / "runtime/turns.json", root / "reference/trade.json",
                         root / "runtime/.local/announcement-docs" / POLICY_FILE])
    snapshot_files(sorted(set(dependencies)), root / "OFFLINE_SNAPSHOT.json")
    write_new(root / "STATUS.json", {"status": "offline_prepared", "model": model,
        "api_calls": 0, "formal_questions_run": 0, "pending": ["offline acceptance", "finite user permit"]})
    return {"status": "offline_prepared", "model": model, "api_calls": 0, "root": str(root)}


def acceptance(root):
    snapshot = verify_snapshot(root / "OFFLINE_SNAPSHOT.json")
    command = [sys.executable, "-m", "unittest", *TESTS]
    completed = subprocess.run(command, cwd=PROJECT, env={**os.environ, "PYTHONPATH": "src:.:tests"},
                               capture_output=True, text=True, timeout=600)
    receipt = {"command": command, "passed": completed.returncode == 0,
        "returncode": completed.returncode, "output": completed.stdout + completed.stderr,
        "api_calls": 0, "source_snapshot_sha256": file_hash(root / "OFFLINE_SNAPSHOT.json")}
    write_new(root / "inputs/OFFLINE_ACCEPTANCE.json", receipt)
    if completed.returncode:
        raise GateError("GLM offline acceptance failed; receipt retained")
    verify_snapshot(root / "OFFLINE_SNAPSHOT.json")
    dependencies = [Path(name) for name in snapshot["files"]]
    dependencies.append(root / "inputs/OFFLINE_ACCEPTANCE.json")
    snapshot_files(dependencies, root / "FROZEN_MANIFEST.json", ready_for_permit=True)
    effective = json.loads((root / "inputs/effective-config.json").read_text())
    write_new(root / "inputs/PERMISSION_REQUEST.json", {
        "schema": "glm-resource-pack-retest-permit-v1", "approved": False,
        "approver_role": "user", "freeze_sha256": file_hash(root / "FROZEN_MANIFEST.json"),
        "profile_sha256": canonical_hash(effective), "model": effective["model"], "endpoint": ENDPOINT,
        "authorization_message_sha256": None, "expires_at": None,
        "max_requests": 48, "max_rounds": 6, "max_tools": 12, "max_tokens": 8192,
        "max_body_bytes": 65536, "timeout_seconds": 90, "wall_seconds": 7200,
        "user_turns": 12, "retry_allowed": False, "max_total_tokens": 2500000,
        "billing": "resource_pack_expected_not_verified"})
    return {"status": "offline_accepted", "api_calls": 0,
            "freeze_sha256": file_hash(root / "FROZEN_MANIFEST.json"), "passed": True}


def verify_package(root, data_root):
    manifest = verify_snapshot(root / "FROZEN_MANIFEST.json")
    if manifest.get("ready_for_permit") is not True:
        raise GateError("GLM package not accepted")
    source = json.loads((root / "inputs/original-package.json").read_text())
    if source["data_root"] != str(data_root.absolute()):
        raise GateError("Wrong GLM evaluation data root")
    environment = json.loads((root / "inputs/environment.json").read_text())
    if (environment["executable"] != sys.executable or environment["version"] != sys.version
            or environment["interpreter_sha256"] != file_hash(Path(sys.executable).resolve())):
        raise GateError("Frozen GLM interpreter changed")
    return file_hash(root / "FROZEN_MANIFEST.json")


def run(root, data_root, permit_path, *, credential_path=CREDENTIALS):
    effective = json.loads((root / "inputs/effective-config.json").read_text())
    turns = json.loads((root / "runtime/turns.json").read_text())
    permit = json.loads(permit_path.read_text())
    verify = lambda: verify_package(root, data_root)
    ledger = GLMSendLedger(root / "ledgers/live", permit, effective, verify, turns=turns)
    # A rejected or expired permit must never cause credential loading.
    with ledger.batch():
        key = load_key(credential_path)
        def model_factory(case_id):
            return create_model(effective, key, ledger, next(t for t in turns if t["case_id"] == case_id))
        def review(case, result):
            write_new(root / "results" / (case["id"] + "-REVIEW_NEEDED.json"), {
                "case_id": case["id"], "result": result, "result_sha256": canonical_hash(result),
                "instruction": "Review saved public/tool evidence; do not call another model API to judge."})
            path = root / "results" / (case["id"] + "-SAFETY_REVIEW.json")
            while not path.exists():
                ledger.check_time()
                time.sleep(1)
            return json.loads(path.read_text())
        plan = json.loads((root / "inputs/plan.json").read_text())
        reference = json.loads((root / "reference/trade.json").read_text())
        executor = AgentCaseExecutor(plan, reference, data_root, root / "runtime",
                                     root / "results/evidence", model_factory)
        return execute_cases(plan, turns, root / "results/batch", executor,
                             verify_inputs=verify, review=review)


def smoke(model, output, *, credential_path=CREDENTIALS, transport=None):
    """At most two short, synthetic tool turns; never part of twelve-question scores."""
    from scripts.us_retest_transport import official_transport
    if output.exists():
        raise GateError("GLM smoke directory exists; no retry")
    effective = profile(model)
    source_files = [Path(__file__), PROJECT / "scripts/glm_retest_transport.py",
                    PROJECT / "src/tradeintel_ai/model_adapter.py"]
    code_hashes = {str(p.absolute()): file_hash(p) for p in source_files}
    output.mkdir(parents=True)
    write_new(output / "started.json", {"model": model, "max_requests": 2,
        "max_tokens_per_request": 1024, "timeout_seconds": 30,
        "automatic_retry": False, "purpose": "synthetic_tool_protocol_check_not_accuracy",
        "code_sha256": code_hashes, "thinking": {"type": "enabled"},
        "hypothesis": "The selected model can return a function call and consume its tool result.",
        "control": "The same two-turn protocol passes with offline HTTP fixtures.",
        "data": "Synthetic ping echo; no trade data or twelve-question answers.",
        "acceptance": "One connection_check(value=ping), then OK; valid reported usage; no retry."})
    key = load_key(credential_path)
    actual_transport = transport or official_transport
    sent = 0
    def bounded(request, *, timeout):
        nonlocal sent
        payload = json.loads(request.data)
        if sent >= 2 or request.full_url != ENDPOINT or len(request.data) > 65536 or timeout > 30 or payload.get("max_tokens") != 1024:
            raise GateError("Smoke request limit exceeded")
        sent += 1
        write_new(output / f"send-{sent:03d}.json", {"request_number": sent,
            "body_sha256": hashlib.sha256(request.data).hexdigest(), "body_bytes": len(request.data)})
        return actual_transport(request, timeout=timeout)
    adapter = GLMToolModel(OpenAICompatibleConfig(BASE_URL, model, key, 30, 0),
                          opener=bounded, request_params={"thinking": {"type": "enabled"}, "max_tokens": 1024})
    tools = [{"type": "function", "name": "connection_check", "description": "Echo the supplied string.",
              "parameters": {"type": "object", "properties": {"value": {"type": "string"}},
                             "required": ["value"], "additionalProperties": False}}]
    messages = [{"role": "user", "content": "Call connection_check once with value ping. After its result, reply OK only."}]
    replies = []
    result = {"model": model, "status": "started", "formal_questions": 0, "api_requests": 0,
              "accuracy_measured": False, "billing": "not_verified"}
    def check_usage(answer):
        usage = answer.metadata.get("usage", {})
        values = [usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")]
        if (any(type(v) is not int or v < 0 for v in values) or values[2] != values[0] + values[1]
                or values[0] > 1048576 or values[1] > 1048576 or answer.metadata.get("model") != model):
            raise GateError("Smoke response identity/usage unavailable")
    try:
        answer = adapter.complete(messages=messages, tools=tools)
        replies.append({"text": answer.text, "tool_calls": [vars(c) for c in answer.tool_calls], "metadata": answer.metadata})
        check_usage(answer)
        if len(answer.tool_calls) != 1 or answer.tool_calls[0].name != "connection_check" or answer.tool_calls[0].arguments != {"value": "ping"}:
            raise GateError("Smoke did not return the requested tool call")
        call = answer.tool_calls[0]
        assistant = {"role": "assistant", "content": answer.wire_content,
                     "tool_calls": [{"call_id": call.call_id, "name": call.name, "arguments": call.arguments}]}
        if answer.reasoning_present:
            assistant["reasoning_content"] = answer.reasoning_content
        messages += [assistant, {"role": "tool", "tool_call_id": call.call_id,
                                 "name": call.name, "content": '{"value":"ping"}'}]
        final = adapter.complete(messages=messages, tools=tools)
        replies.append({"text": final.text, "tool_calls": [vars(c) for c in final.tool_calls], "metadata": final.metadata})
        check_usage(final)
        if final.tool_calls or final.text.strip() != "OK":
            raise GateError("Smoke final response is not OK")
        result["status"] = "tool_roundtrip_passed"
    except Exception as error:
        result.update(status="stopped_without_retry", error=safe_error_details(error))
    finally:
        result.update(api_requests=sent if transport is None else 0, attempted_requests=sent,
                      origin="api" if transport is None else "offline_fixture", responses=replies,
                      code_unchanged=all(file_hash(Path(p)) == digest for p, digest in code_hashes.items()))
        # No reasoning or headers go to the evidence files.
        encoded = json.dumps(result, ensure_ascii=False).replace(key, "[REDACTED]")
        write_new(output / "result.json", json.loads(encoded))
    return {k: v for k, v in result.items() if k != "responses"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "accept", "verify", "run", "smoke"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", choices=MODELS)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--permit", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.action in {"run", "smoke"} and not args.execute:
        raise GateError("Explicit --execute required for a network action")
    if args.action in {"prepare", "smoke"} and not args.model:
        parser.error("--model is required")
    if args.action == "run" and not args.permit:
        parser.error("--permit is required")
    if args.action == "prepare":
        result = prepare(args.output.absolute(), args.model, args.template.absolute(), args.data_root.absolute())
    elif args.action == "accept":
        result = acceptance(args.output.absolute())
    elif args.action == "verify":
        result = {"freeze_sha256": verify_package(args.output.absolute(), args.data_root.absolute()), "api_calls": 0}
    elif args.action == "run":
        result = run(args.output.absolute(), args.data_root.absolute(), args.permit.absolute())
    else:
        result = smoke(args.model, args.output.absolute())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (GateError, OSError, ValueError, KeyError) as error:
        print(json.dumps({"status": "stopped", "error": safe_error_details(error)}))
        raise SystemExit(2)
