"""Offline preparation and fail-closed request ledger for the US retest."""
import argparse
import fcntl
import hashlib
import json
import os
import time
import uuid
import tempfile
import sys
import subprocess
from contextlib import contextmanager
from pathlib import Path
from datetime import date
from decimal import Decimal, InvalidOperation
from tradeintel_ai.model_adapter import safe_error_details
from tradeintel_ai.trade_agent_metrics import response_metrics


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=".retest-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        # Same-directory hard link publishes the complete file without ever
        # overwriting an existing result or exposing half-written JSON.
        os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temporary)


def build_review_materials(plan):
    criteria = {
        "R05": ["用户上月是2026-09，不能改成7月", "正确请求缺月与错误月份被拦分别记", "缺数据不能补零"],
        "R06": ["巴西伙伴未接入，不得用全部目的地替代", "程序预检0响应记模型N/A"],
        "P02": ["25%是存档附加税，不是当前综合税率", "当前税率未知需明确", "不得新增无关贸易报告来冒充回答"],
    }
    return {"kind": "us-retest-human-review-template-v1", "model_context_allowed": False,
        "cases": [{"case_id": case["id"], "question": case["question"],
            "checks": criteria.get(case["id"], ["核对主范围及所有附加报告", "核对原始工具决策和被拦错误企图",
                "核对finish引用来自本轮", "核对政策命中、依赖和读回", "核对HTTP账本与usage未知状态"]),
            "decision": "pending", "reviewer": None, "evidence_paths": [],
            "model_raw_correct": None, "product_complete_or_safe": None} for case in plan["cases"]],
        "boundary": "Template only, no prefilled success or human approval"}


class GateError(RuntimeError):
    pass


class GuardedOpener:
    """Check actual adapter bytes, including replay, before invoking transport.

    Authorization here is injected only for offline tests. CLI live stays closed
    until frozen authorization and monetary reservation are implemented.
    """
    def __init__(self, ledger, transport, *, authorized=False, started_at=None):
        self.ledger = ledger
        self.transport = transport
        self.authorized = authorized
        self.started_at = started_at

    def __call__(self, request, *, timeout):
        if not isinstance(timeout, (float, int)) or isinstance(timeout, bool) or not 0 < timeout <= 90:
            raise GateError("HTTP timeout outside frozen limit")
        record = self.ledger.reserve_wire(request.data, authorized=self.authorized,
                                          started_at=self.started_at)
        # The reservation is retained even if transport raises or response parsing fails.
        # No request URL, headers, messages or reasoning are persisted.
        return self.transport(request, timeout=timeout)


class RecordingModel:
    """Retain the original response object so private thinking replay survives."""
    def __init__(self, inner, output, *, accounting=None):
        self.inner = inner
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        self.number = 0
        self.accounting = accounting
        self.tool_number = 0

    def record_tool(self, item):
        self.tool_number += 1
        write_new(self.output / f"tool-{self.tool_number:03d}.json", {"tools": [item]})

    @property
    def config(self):
        return self.inner.config

    @property
    def request_params(self):
        return self.inner.request_params

    def complete(self, *, messages, tools):
        self.number += 1
        number = self.number
        write_new(self.output / f"{number:03d}-started.json", {"status": "started"})
        # Tool feedback is necessary to distinguish wrong attempts from guard
        # corrections. Only tool messages are recorded, never private reasoning.
        write_new(self.output / f"{number:03d}-feedback.json", {
            "tools": [{"name": item.get("name"), "tool_call_id": item.get("tool_call_id"),
                       "content": item.get("content")} for item in messages if item.get("role") == "tool"]})
        started = time.monotonic()
        try:
            response = self.inner.complete(messages=messages, tools=tools)
        except Exception as error:
            if self.accounting is not None:
                self.accounting.fail("model_parse_or_transport_failure")
            write_new(self.output / f"{number:03d}-failed.json", {
                "status": "failed_or_unknown", "error": safe_error_details(error),
                "budget_rejection": isinstance(error, GateError)})
            raise
        if self.accounting is not None:
            self.accounting.settle()
        write_new(self.output / f"{number:03d}-response.json", {
            "status": "response_received", "text": response.text,
            "tool_calls": [{"call_id": call.call_id, "name": call.name,
                            "arguments": call.arguments} for call in response.tool_calls],
            "metrics": response_metrics(response.metadata, int((time.monotonic() - started) * 1000))})
        return response


class RequestLedger:
    """Reservations survive interruption; no implicit retry or authorization."""
    def __init__(self, root, *, clock=time.time):
        self.root = Path(root)
        self.clock = clock
        self.root.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def locked(self):
        with (self.root / "ledger.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def claim(self, case_id, *, request_id=None, session_id=None):
        if not isinstance(case_id, str) or not case_id.isalnum():
            raise GateError("Invalid case ID")
        with self.locked():
            path = self.root / (case_id + ".json")
            if path.exists():
                raise GateError("Case already claimed; reconcile existing record, do not retry")
            if request_id is not None and (not isinstance(request_id, str) or not request_id.isalnum()):
                raise GateError("Invalid frozen request ID")
            write_new(path, {"case_id": case_id, "status": "claimed",
                "request_id": request_id or uuid.uuid4().hex, "session_id": session_id})

    def reserve_wire(self, body, *, authorized=False, started_at=None, max_requests=48,
                     max_bytes=65536, wall_seconds=7200):
        if not authorized:
            raise GateError("Live requests not authorized")
        if not isinstance(body, bytes) or len(body) > max_bytes:
            raise GateError("Wire body exceeds limit or is not bytes")
        if started_at is None or self.clock() - started_at >= wall_seconds:
            raise GateError("Batch time budget unavailable or exhausted")
        with self.locked():
            records = list(self.root.glob("wire-*.json"))
            if len(records) >= max_requests:
                raise GateError("Batch request limit reached")
            number = len(records) + 1
            path = self.root / f"wire-{number:03d}.json"
            write_new(path, {"number": number, "status": "reserved_outcome_unknown",
                "body_bytes": len(body), "wire_sha256": hashlib.sha256(body).hexdigest()})
            return path

    def reserve_money(self, amount_usd, *, budget_usd="2", authorized=False):
        """Retain conservative explicit reserves, not an invented byte/token estimate.

        Caller must supply a separately justified bound. No CLI live caller
        exists yet, and this function alone cannot guarantee supplier billing.
        """
        if not authorized:
            raise GateError("Monetary reservation not authorized")
        def money(value):
            if not isinstance(value, str):
                raise GateError("Money must be explicit decimal text")
            try:
                number = Decimal(value)
            except InvalidOperation as error:
                raise GateError("Invalid money") from error
            if not number.is_finite() or number <= 0:
                raise GateError("Invalid monetary bound")
            return number
        amount, budget = money(amount_usd), money(budget_usd)
        with self.locked():
            paths = list(self.root.glob("money-*.json"))
            total = sum((money(json.loads(path.read_text())["reserved_usd"]) for path in paths), Decimal(0))
            if total + amount > budget:
                raise GateError("Monetary reservation budget exhausted")
            path = self.root / f"money-{len(paths) + 1:03d}.json"
            write_new(path, {"reserved_usd": str(amount), "budget_usd": str(budget),
                "status": "reserved_outcome_unknown", "billing": "not_verified"})
            return path


def prepare(root, scenarios, reference):
    if root.exists():
        raise GateError("Preparation root exists; refusing overwrite")
    plan = json.loads(scenarios.read_text())
    gold = json.loads(reference.read_text())
    core = {f"2025-{m:02d}" for m in range(8, 13)} | {f"2026-{m:02d}" for m in range(1, 8)}
    if (plan["limits"]["live_authorized"] or len(plan["cases"]) != 12
            or not core <= set(gold["months"]) or any(set(gold["months"][m]) != {"import", "export"} for m in core)):
        raise GateError("Unexpected plan or reference")
    root.mkdir(parents=True)
    for name in ("inputs", "runtime", "ledgers", "results", "reference"):
        (root / name).mkdir()
    write_new(root / "reference/trade.json", gold)
    # Evaluator-only fields remain outside runtime inputs.
    write_new(root / "inputs/plan.json", plan)
    sessions = {}
    runtime = []
    for case in plan["cases"]:
        request_id = uuid.uuid4().hex
        sessions.setdefault(case["session"], request_id)
        runtime.append({"case_id": case["id"], "question": case["question"],
            "request_id": request_id, "session_id": sessions[case["session"]],
            "requires": case.get("requires")})
    write_new(root / "runtime/turns.json", runtime)
    write_new(root / "STATUS.json", {"status": "offline_partial_not_live_ready",
        "api_calls": 0, "policy_confirmed": False, "freeze_ready": False,
        "pending": ["policy registration and confirmation", "recording adapter and scoring",
                    "full offline acceptance", "freeze and finite live authorization"]})


def file_hash(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def snapshot_files(paths, output, *, inventories=None, ready_for_permit=False):
    """Seal explicit offline inputs; not a live-ready authorization manifest."""
    if output.exists():
        raise GateError("Snapshot exists; refusing overwrite")
    entries = {}
    for path in paths:
        path = Path(path).absolute()
        if path.is_symlink() or not path.is_file():
            raise GateError("Snapshot input missing or unsafe")
        entries[str(path)] = {"sha256": file_hash(path), "bytes": path.stat().st_size}
    if not entries:
        raise GateError("Empty snapshot")
    inventory = []
    for directory, pattern in inventories or []:
        directory = Path(directory).absolute()
        if directory.is_symlink() or not directory.is_dir():
            raise GateError("Unsafe inventory directory")
        members = sorted(str(path.absolute()) for path in directory.glob(pattern))
        if any(name not in entries for name in members):
            raise GateError("Inventory member not hashed")
        inventory.append({"directory": str(directory), "pattern": pattern, "members": members})
    write_new(output, {"schema": "us-retest-offline-snapshot-v1", "live_ready": False,
                       "ready_for_permit": ready_for_permit, "files": entries, "inventory": inventory})


def collect_snapshot_inputs(project, package, data_root):
    """Include actual inputs and dependencies, excluding mutable sessions/secrets."""
    paths = list((project / "src/tradeintel_ai").glob("*.py"))
    paths.extend(project / "scripts" / name for name in (
        "run_us_agent_retest.py", "score_us_agent_retest.py",
        "build_us_agent_retest_reference.py", "prepare_us_retest_policy.py", "us_retest_transport.py"))
    paths.extend([project / "evals/us_agent_retest_v1/scenarios.json",
                  project / "docs/handoff/US_AGENT_RETEST_DESIGN_20261001.zh-CN.md",
                  project / "tests/test_us_agent_retest.py",
                  project / "tests/test_us_retest_final.py",
                  project / "docs/handoff/US_RETEST_FINAL_EXECUTION_PLAN_20261001.zh-CN.md",
                  project / "data/raw/policy/review2025/cbp-63577329.html",
                  project / "data/raw/policy/review2025/cbp-63577329.source.json",
                  project / "data/processed/policy_exposure/policy_corpus.json",
                  package / "inputs/plan.json", package / "runtime/turns.json",
                  package / "reference/trade.json", package / "runtime/policy-review.json"])
    paths.extend([package / "inputs/review-template.json", package / "runtime/policy-field-candidate.json",
                  package / "inputs/effective-config.json", package / "inputs/environment.json"])
    continuation = package / "inputs/continuation.json"
    if continuation.exists():
        paths.append(continuation)
        paths.extend((package / "bootstrap").rglob("*.json"))
        paths.extend(Path(name) for name in json.loads(continuation.read_text())["parent_files"])
        paths.append(project / "docs/handoff/US_RETEST_REFERENCE_AND_CONTINUATION_20261001.zh-CN.md")
    paths.extend((project / "tests").glob("test_trade_agent*.py"))
    paths.append(project / "tests/test_tradeintel_ai_model_adapter.py")
    for name in ("requirements.txt", "requirements.lock", "pyproject.toml", "uv.lock", "poetry.lock"):
        if (project / name).is_file():
            paths.append(project / name)
    stores = list((package / "runtime/.local/announcement-docs").glob("*.json"))
    if not stores:
        raise GateError("Isolated policy store missing")
    paths.extend(stores)
    bundle_path = data_root / "BUNDLE_MANIFEST.json"
    bundle = json.loads(bundle_path.read_text())
    paths.append(bundle_path)
    for entry in bundle["files"]:
        candidate = data_root / entry["path"]
        if not candidate.resolve().is_relative_to(data_root.resolve()):
            raise GateError("Unsafe bundle path")
        if candidate.stat().st_size != entry["bytes"] or file_hash(candidate) != entry["sha256"]:
            raise GateError("Bundle input mismatch")
        paths.append(candidate)
    return sorted(set(paths))


class AgentCaseExecutor:
    """Real Agent/session/report path with an injected model, no key loading.

    Verified public projections can advance the R01/R02 continuation gate.
    Final product/model scores remain pending until an evidence-bound review.
    """
    def __init__(self, plan, reference, data_root, runtime, output, model_factory):
        self.plan = plan
        self.reference = reference
        self.data_root = data_root
        self.runtime = runtime
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.output = output
        self.model_factory = model_factory

    def __call__(self, turn):
        from tradeintel_ai.trade_agent import TradeResearchAgent
        from scripts.score_us_agent_retest import check_saved_report
        case = next(case for case in self.plan["cases"] if case["id"] == turn["case_id"])
        recording = self.output / turn["case_id"] / "responses"
        inner = self.model_factory(turn["case_id"])
        accounting = getattr(inner, "retest_accounting", None)
        model = RecordingModel(inner, recording, accounting=accounting)
        tool_records = []
        def audit_tool(item):
            model.record_tool(item)
            tool_records.append(item)
        agent = TradeResearchAgent(self.data_root, self.runtime, model,
            today=date.fromisoformat(self.plan["as_of"]),
            max_rounds=self.plan["limits"]["max_rounds_per_turn"],
            max_tools=self.plan["limits"]["max_tools_per_turn"], audit_callback=audit_tool)
        # First request doubles as session ID; passing it as an existing SID
        # would cause the store to reject the first turn.
        existing = self.runtime / ".local/trade-agent-sessions" / (turn["session_id"] + ".json")
        if not existing.exists() and turn["request_id"] != turn["session_id"]:
            raise GateError("Prerequisite session missing; cannot start a replacement session")
        state = agent.turn(turn["question"], turn["request_id"],
                           session_id=turn["session_id"] if existing.exists() else None)
        current = next(item for item in state["turns"] if item["request_id"] == turn["request_id"])
        write_new(self.output / turn["case_id"] / "session-readback.json", state)
        from scripts.score_us_agent_retest import check_public_turn, audit_query_actions
        audit = {"passed": False, "checks": [], "errors": [], "public_safety": "review_required"}
        if case["kind"] == "normal":
            audit = check_public_turn(self.runtime, current, case, self.reference, tool_records)
            if case.get("policy_prerequisite") and audit["passed"]:
                from scripts.prepare_us_retest_policy import POLICY_ID
                from tradeintel_ai.announcement_flow import load_announcement_store
                from scripts.score_us_agent_retest import check_policy_bundles
                policy = check_policy_bundles(current.get("policy_evidence", {}).get("evidence_bundles", []),
                                             load_announcement_store(self.runtime, POLICY_ID))
                if not policy["passed"]:
                    audit.update(passed=False, public_safety="review_required", policy_check=policy)
        if current.get("request_id") != turn["request_id"] or current.get("question") != turn["question"]:
            audit.update(passed=False, public_safety="unsafe")
        responses = len(list(recording.glob("*-response.json")))
        if accounting is not None:
            responses = sum(json.loads(path.read_text()).get("model_response") is True
                for record in accounting.ledger.records() if record["case_id"] == turn["case_id"]
                for path in [accounting.ledger.root / (record["id"] + "-received.json")] if path.exists())
        response_records = [json.loads(path.read_text()) for path in sorted(recording.glob("*-response.json"))]
        query_audit = audit_query_actions(case, response_records, [{"tools": tool_records}])
        accounted = accounting.accounting_complete() if accounting is not None else True
        safety = audit["public_safety"]
        reference_gap = audit.get("verification_status") == "unverified_reference"
        if case["id"] == "R06" and responses == 0 and not tool_records and current["status"] == "needs_clarification":
            safety = "verified_program_output"
        return {"case_id": turn["case_id"], "responses": responses,
            "agent_status": current["status"], "report_checks": audit["checks"], "public_audit": audit,
            "origin": "program_precheck" if not responses and not tool_records else getattr(inner, "retest_origin", "offline_fixture"),
            "numeric_complete": audit["passed"], "public_safety": safety,
            "continuation_ready": audit["passed"] and safety == "verified_program_output" and accounted,
            "product_result": "pending_audit", "raw_decision_correct": None,
            "query_audit": query_audit, "request_accounting_complete": accounted,
            "accounting_complete": accounted, "unsafe": safety == "unsafe",
            "evaluation_reference_gap": reference_gap,
            "stop_reason": "evaluation_reference_gap" if reference_gap else None,
            "stop_batch": reference_gap or not accounted or current["status"] == "unknown_outcome",
            "boundary": "Continuation is not final scoring; offline fixtures are not API model results"}


def verify_snapshot(path):
    snapshot = json.loads(path.read_text())
    if snapshot.get("schema") != "us-retest-offline-snapshot-v1" or not snapshot.get("files"):
        raise GateError("Invalid snapshot")
    for name, expected in snapshot["files"].items():
        target = Path(name)
        if target.is_symlink() or not target.is_file() or target.stat().st_size != expected["bytes"] or file_hash(target) != expected["sha256"]:
            raise GateError("Frozen input changed")
    for item in snapshot.get("inventory", []):
        directory = Path(item["directory"])
        if directory.is_symlink() or not directory.is_dir() or sorted(str(path.absolute()) for path in directory.glob(item["pattern"])) != item["members"]:
            raise GateError("Frozen directory membership changed")
    return snapshot


def execute_cases(plan, turns, output, execute, *, verify_inputs=lambda: None, review=None, continuation=None):
    """Injected executor for offline acceptance; no provider/config construction.

    Claims precede execution. Existing claims/results block restart; failed
    prerequisites are not repaired by injecting context or changing IDs.
    """
    if output.exists():
        raise GateError("Batch output exists; inspect without rerunning")
    ids = [case["id"] for case in plan["cases"]]
    if len(set(ids)) != len(ids) or [turn["case_id"] for turn in turns] != ids:
        raise GateError("Case order or identity mismatch")
    for case, turn in zip(plan["cases"], turns):
        if turn["question"] != case["question"] or turn.get("requires") != case.get("requires"):
            raise GateError("Runtime question/dependency mismatch")
        if case.get("requires") and ids.index(case["requires"]) >= ids.index(case["id"]):
            raise GateError("Forward prerequisite")
    if any("request_id" in turn or "session_id" in turn for turn in turns):
        request_ids = [turn.get("request_id") for turn in turns]
        if (len(set(request_ids)) != len(request_ids) or
                any(not isinstance(value, str) or len(value) != 32 or any(c not in "0123456789abcdef" for c in value) for value in request_ids)):
            raise GateError("Invalid or duplicate frozen request IDs")
        sessions = {}
        for case, turn in zip(plan["cases"], turns):
            if "session" not in case:
                continue  # Minimal legacy/offline unit fixtures omit session labels.
            sessions.setdefault(case["session"], turn["request_id"])
            if turn.get("session_id") != sessions[case["session"]]:
                raise GateError("Frozen session grouping mismatch")
    output.mkdir(parents=True)
    ledger = RequestLedger(output / "claims")
    results = {}
    allowed = set(ids)
    if continuation is not None:
        expected = ids[1:]
        if (ids[0] != "R01" or continuation.get("allowlist") != expected
                or continuation.get("anchor", {}).get("continuation_ready") is not True
                or continuation.get("anchor", {}).get("case_id") != "R01"
                or not re_full_sha(continuation.get("anchor", {}).get("diagnostic_sha256"))):
            raise GateError("Invalid continuation schedule/anchor")
        allowed = set(expected)
        results["R01"] = continuation["anchor"]
    stopped = False
    for case, turn in zip(plan["cases"], turns):
        if case["id"] not in allowed:
            continue  # Ancestor is context only: no new claim, output or score.
        previous = results.get(case.get("requires"))
        if stopped or (case.get("requires") and not previous.get("continuation_ready")):
            result = {"case_id": case["id"], "executed": False, "responses": 0,
                      "status": "not_run_batch_stop" if stopped else "not_run_prerequisite"}
        else:
            verify_inputs()
            ledger.claim(case["id"], request_id=turn.get("request_id"), session_id=turn.get("session_id"))
            result = execute(dict(turn))  # No expected code/gold/scoring rules passed.
            if not isinstance(result, dict) or result.get("case_id") != case["id"]:
                raise GateError("Executor result identity mismatch")
            result = {**result, "executed": True, "kind": case["kind"]}
            if result.get("public_safety") == "review_required" and not result.get("evaluation_reference_gap"):
                if review is None:
                    result["stop_batch"] = True
                    result["pause_reason"] = "saved_evidence_semantic_review_required"
                else:
                    decision = review(case, dict(result))
                    from scripts.us_retest_transport import canonical_hash
                    if (not isinstance(decision, dict) or decision.get("case_id") != case["id"]
                            or decision.get("reviewer_role") not in {"user", "human_reviewer", "ai_reviewer"}
                            or not decision.get("reason") or decision.get("result_sha256") != canonical_hash(result)):
                        raise GateError("Incomplete semantic review evidence")
                    write_new(output / (case["id"] + "-review.json"), decision)
                    if decision.get("public_safe") is not True:
                        result.update(stop_batch=True, unsafe=decision.get("public_safe") is False)
                    elif (decision.get("continuation_ready") is True and result.get("request_accounting_complete") is True
                          and (case["kind"] == "boundary" or result.get("public_audit", {}).get("passed") is True)):
                        result["continuation_ready"] = True
            if result.get("unsafe") or result.get("stop_batch"):
                stopped = True
            if case["id"] in {"R01", "R02"} and (
                    result.get("continuation_ready") is not True or result.get("request_accounting_complete") is not True):
                stopped = True
        write_new(output / (case["id"] + ".json"), result)
        results[case["id"]] = result
    return [results[case_id] for case_id in ids if case_id in allowed]


ACCEPTANCE_TESTS = ("tests.test_us_agent_retest", "tests.test_us_retest_final",
    "tests.test_trade_agent_catalog_contract", "tests.test_trade_agent_policy_merge_contract",
    "tests.test_trade_agent_mainline", "tests.test_trade_agent_boundaries",
    "tests.test_trade_agent_request", "tests.test_trade_agent_language",
    "tests.test_trade_agent_report_view", "tests.test_trade_agent_metrics",
    "tests.test_tradeintel_ai_model_adapter", "tests.test_trade_agent_policy_evidence")


def prepare_final(root, project, scenarios, data_root):
    from scripts.build_us_agent_retest_reference import build_reference
    from scripts.prepare_us_retest_policy import prepare_policy, review_candidate, POLICY_ID
    from tradeintel_ai.announcement_flow import load_announcement_store
    if root.exists():
        raise GateError("Final package exists; no overwrite")
    # Follow-up queries may return an earlier registered month as an additional
    # report. Keep that reference evaluator-only, but cover the full manifest.
    reference = build_reference(data_root, coverage_profile="manifest_available")
    # Build outside the package only in memory, then publish new inputs.
    root.mkdir(parents=True)
    for name in ("inputs", "runtime", "ledgers", "results", "reference"):
        (root / name).mkdir()
    plan = json.loads(scenarios.read_text())
    if len(plan["cases"]) != 12 or plan["limits"]["live_authorized"]:
        raise GateError("Unexpected experiment plan")
    write_new(root / "reference/trade.json", reference)
    write_new(root / "inputs/plan.json", plan)
    sessions, turns = {}, []
    for case in plan["cases"]:
        rid = uuid.uuid4().hex
        sessions.setdefault(case["session"], rid)
        turns.append({"case_id": case["id"], "request_id": rid, "session_id": sessions[case["session"]],
                      "question": case["question"], "requires": case.get("requires")})
    write_new(root / "runtime/turns.json", turns)
    write_new(root / "inputs/review-template.json", build_review_materials(plan))
    prepare_policy(project, root / "runtime")
    store = load_announcement_store(root / "runtime", POLICY_ID)
    candidate = review_candidate(store)
    write_new(root / "runtime/policy-field-candidate.json", {"status": "proposed_not_confirmed", "candidate": candidate})
    write_new(root / "inputs/policy-confirmation-sheet.json", {
        "status": "user_confirmation_required", "candidate_digest": candidate["candidate_digest"],
        "summary_zh": "仅确认这份存档的字段：2025年1月1日00:01 EST生效、中国原产；硅类两个子目附加50%，钨类三个子目附加25%。商品限定按原文保留。25%不是现行全部税率，HS4贸易总额也不是政策税基。",
        "unknown_fields": [f["field"] for f in candidate["fields"] if f["status"] == "unknown"],
        "fields_with_quotes": candidate["fields"], "doc_version": store["documents"][0]["doc_version"],
        "approval_required": {"role": "user", "approved": True, "candidate_digest": candidate["candidate_digest"],
                              "confirmed_by": "真实确认者姓名，不能由AI代填", "authorization_message_sha256": "真实授权消息的SHA256"}})
    write_new(root / "inputs/effective-config.json", {"base_url": "https://api.deepseek.com",
        "model": "deepseek-flash", "temperature": 0, "timeout_ceiling_seconds": 90,
        "request_params": {"thinking": {"type": "enabled"}, "reasoning_effort": "high", "max_tokens": 8192}})
    write_new(root / "inputs/environment.json", {"executable": sys.executable, "version": sys.version,
        "resolved_executable": str(Path(sys.executable).resolve()),
        "interpreter_sha256": file_hash(Path(sys.executable).resolve())})
    write_new(root / "STATUS.json", {"status": "offline_prepared", "api_calls": 0,
        "old_records": "preserved", "source_dependency_fix": "includes cbp63577329:p9:para3",
        "pending": ["offline acceptance", "real user policy confirmation", "freeze and finite permit"]})


def acceptance(root, project, data_root):
    if (root / "inputs/continuation.json").exists():
        verify_continuation(root, initial=True)
    paths = collect_snapshot_inputs(project, root, data_root)
    source_hashes = {str(path.absolute()): file_hash(path) for path in paths
                     if path.suffix == ".py" or path == root / "reference/trade.json"}
    env = {**os.environ, "PYTHONPATH": "src:.:tests"}
    command = [sys.executable, "-m", "unittest", *ACCEPTANCE_TESTS]
    completed = subprocess.run(command, cwd=project, env=env, capture_output=True, text=True, timeout=600)
    write_new(root / "inputs/OFFLINE_ACCEPTANCE.json", {"command": command, "passed": completed.returncode == 0,
        "returncode": completed.returncode, "output": completed.stdout + completed.stderr,
        "source_hashes": source_hashes, "data_manifest_sha256": file_hash(data_root / "BUNDLE_MANIFEST.json"),
        "api_calls": 0, "boundary": "Scripted/offline engineering evidence, not model accuracy"})
    if completed.returncode:
        raise GateError("Offline acceptance failed; receipt retained")


def confirm_policy(root, approval_path):
    from scripts.prepare_us_retest_policy import POLICY_ID
    from tradeintel_ai.announcement_flow import submit_candidates, confirm_and_enable, load_announcement_store
    approval = json.loads(approval_path.read_text())
    candidate = json.loads((root / "runtime/policy-field-candidate.json").read_text())["candidate"]
    if approval.get("role") != "user" or approval.get("approved") is not True or approval.get("candidate_digest") != candidate["candidate_digest"]:
        raise GateError("Actual user policy approval missing/mismatched")
    digest = approval.get("authorization_message_sha256", "")
    if not isinstance(digest, str) or not re_full_sha(digest) or not isinstance(approval.get("confirmed_by"), str) or not approval["confirmed_by"].strip():
        raise GateError("Policy approval evidence missing")
    receipt_path = root / "runtime/policy-human-approval.json"
    if receipt_path.exists():
        raise GateError("Policy approval already recorded")
    store = load_announcement_store(root / "runtime", POLICY_ID)
    version = store["documents"][0]["doc_version"]
    submitted = submit_candidates(root / "runtime", POLICY_ID, version, candidate["fields"])
    confirmed = confirm_and_enable(root / "runtime", POLICY_ID, version, candidate["fields"],
        confirmed_by=approval["confirmed_by"], expected_candidate_digest=submitted["candidate_digest"])
    write_new(receipt_path, {"approval": approval, "confirmation": confirmed})


def re_full_sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def ancestor_facts(parent, project):
    """Reconcile the closed R01 segment without reopening or rewriting it."""
    from scripts.us_retest_transport import canonical_hash
    parent = parent.resolve()
    freeze = json.loads((parent / "FROZEN_MANIFEST.json").read_text())
    batch = json.loads((parent / "ledgers/live/batch.json").read_text())
    permit = batch["permit"]
    if (permit.get("freeze_sha256") != file_hash(parent / "FROZEN_MANIFEST.json")
            or canonical_hash(permit) != batch.get("permit_sha256")
            or permit.get("currency") != "CNY" or permit.get("budget") != "10"
            or permit.get("max_requests") != 48 or permit.get("model") != "deepseek-flash"
            or permit.get("approved") is not True or permit.get("approver_role") != "user"
            or permit.get("reasoning_effort") != "high" or permit.get("retry_allowed") is not False
            or permit.get("input_price_per_million") != "2" or permit.get("output_price_per_million") != "8"
            or permit.get("output_bound_route") != "capacity_fallback"
            or (parent / "ledgers/live/STOP.json").exists()):
        raise GateError("Ancestor permission/accounting identity invalid")
    price_evidence = parent / "inputs/CNY_PRICE_EVIDENCE.json"
    if price_evidence.is_symlink() or not price_evidence.is_file() or file_hash(price_evidence) != permit.get("price_source_sha256"):
        raise GateError("Ancestor price evidence changed/missing")
    allowed = {str((project / "scripts" / name).absolute()) for name in (
        "run_us_agent_retest.py", "score_us_agent_retest.py", "build_us_agent_retest_reference.py", "us_retest_transport.py")}
    allowed.update(str((project / "tests" / name).absolute()) for name in (
        "test_us_agent_retest.py", "test_us_retest_final.py"))
    files, changed = {}, []
    for name, expected in freeze["files"].items():
        path = Path(name)
        if path.is_symlink() or not path.is_file():
            raise GateError("Ancestor input missing/unsafe")
        actual = file_hash(path)
        if actual != expected["sha256"] or path.stat().st_size != expected["bytes"]:
            if name not in allowed:
                raise GateError("Ancestor product/data/input drift")
            changed.append(name)
        if name not in allowed:
            files[name] = actual
    for item in freeze.get("inventory", []):
        if sorted(str(p.absolute()) for p in Path(item["directory"]).glob(item["pattern"])) != item["members"]:
            raise GateError("Ancestor input inventory changed")
    plan = json.loads((parent / "inputs/plan.json").read_text())
    turns = json.loads((parent / "runtime/turns.json").read_text())
    records = sorted((parent / "ledgers/live").glob("send-[0-9][0-9][0-9].json"))
    if len(records) != 5:
        raise GateError("This continuation requires the reconciled five-send R01 segment")
    for suffix in ("dispatched", "received", "settled"):
        expected_names = {f"send-{i:03d}-{suffix}.json" for i in range(1, 6)}
        if {p.name for p in (parent / "ledgers/live").glob(f"send-*-{suffix}.json")} != expected_names:
            raise GateError("Ancestor has orphan/missing send evidence")
    cost = Decimal(0)
    for i, path in enumerate(records, 1):
        record = json.loads(path.read_text())
        prefix = path.with_suffix("")
        required = [Path(str(prefix) + suffix) for suffix in ("-dispatched.json", "-received.json", "-settled.json")]
        if any(not p.is_file() or p.is_symlink() for p in required):
            raise GateError("Ancestor has an unknown/unsettled send")
        received, settled = [json.loads(p.read_text()) for p in required[1:]]
        usage = received.get("usage", {})
        inputs, outputs = usage.get("prompt_tokens"), usage.get("completion_tokens")
        if (record.get("case_id") != "R01" or record.get("number") != i
                or record.get("request_id") != turns[0]["request_id"] or record.get("session_id") != turns[0]["session_id"]
                or record.get("permit_sha256") != canonical_hash(permit) or record.get("currency") != "CNY"
                or received.get("model_response") is not True
                or any(type(v) is not int or v < 0 for v in (inputs, outputs))
                or inputs > 1048576 or outputs > 393216
                or usage.get("total_tokens", inputs + outputs) != inputs + outputs
                or settled.get("id") != record["id"] or settled.get("currency") != "CNY"
                or settled.get("prompt_tokens") != inputs or settled.get("completion_tokens") != outputs):
            raise GateError("Ancestor usage/identity does not reconcile")
        expected_cost = (Decimal(inputs) * 2 + Decimal(outputs) * 8) / 1000000
        if Decimal(settled["estimated_cost"]) != expected_cost:
            raise GateError("Ancestor cost does not reconcile")
        cost += expected_cost
    for case in plan["cases"]:
        result = json.loads((parent / "results/batch" / (case["id"] + ".json")).read_text())
        if case["id"] == "R01":
            if (result.get("executed") is not True or result.get("agent_status") != "completed"
                    or result.get("request_accounting_complete") is not True):
                raise GateError("Ancestor R01 has no settled completed context")
        elif (result.get("executed") is not False or result.get("responses") != 0
                or (parent / "results/batch/claims" / (case["id"] + ".json")).exists()):
            raise GateError("Remaining turn already attempted")
    evidence, inventory = [parent / "FROZEN_MANIFEST.json", price_evidence], []
    for directory in ("results/batch", "results/evidence", "ledgers/live", "runtime/.local/trade-agent-sessions", "runtime/.local/trade-reports"):
        members = sorted((parent / directory).rglob("*.json"))
        evidence.extend(members)
        inventory.append({"directory": str(parent / directory), "members": [str(p.absolute()) for p in members]})
    for path in evidence:
        if path.is_symlink() or not path.resolve().is_relative_to(parent):
            raise GateError("Unsafe ancestor evidence")
        files[str(path.absolute())] = file_hash(path)
    return {"parent": str(parent), "parent_freeze_sha256": file_hash(parent / "FROZEN_MANIFEST.json"),
            "parent_files": files, "parent_inventory": inventory, "changed_evaluator_paths": sorted(changed),
            "consumed_requests": len(records), "consumed_cost": str(cost), "currency": "CNY"}


def copy_new_bytes(source, destination):
    """Only used with the explicit non-secret bootstrap whitelist."""
    if source.is_symlink() or not source.is_file():
        raise GateError("Bootstrap source unsafe")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream:
        os.chmod(destination, 0o600)
        stream.write(source.read_bytes())
        stream.flush()
        os.fsync(stream.fileno())


def prepare_continuation(root, parent, project, data_root):
    from scripts.build_us_agent_retest_reference import build_reference
    from scripts.score_us_agent_retest import check_public_turn
    if root.exists():
        raise GateError("Continuation package exists; refusing overwrite")
    facts = ancestor_facts(parent, project)
    parent = Path(facts["parent"])
    if str((data_root / "BUNDLE_MANIFEST.json").absolute()) not in facts["parent_files"]:
        raise GateError("Continuation data root differs from ancestor")
    reference = build_reference(data_root, coverage_profile="manifest_available")
    plan = json.loads((parent / "inputs/plan.json").read_text())
    turns = json.loads((parent / "runtime/turns.json").read_text())
    state = json.loads((parent / "results/evidence/R01/session-readback.json").read_text())
    current = next(t for t in state["turns"] if t["request_id"] == turns[0]["request_id"])
    tools = [item for path in sorted((parent / "results/evidence/R01/responses").glob("tool-*.json"))
             for item in json.loads(path.read_text())["tools"]]
    audit = check_public_turn(parent / "runtime", current, plan["cases"][0], reference, tools)
    if audit["passed"] is not True or audit["public_safety"] != "verified_program_output":
        raise GateError("Ancestor public context cannot be independently verified")
    raw_session = parent / "runtime/.local/trade-agent-sessions" / (turns[0]["session_id"] + ".json")
    raw = json.loads(raw_session.read_text())
    if (raw.get("session_id") != turns[0]["session_id"] or len(raw.get("turns", [])) != 1
            or raw["turns"][0].get("request_id") != turns[0]["request_id"]
            or raw["turns"][0].get("status") != "completed"):
        raise GateError("Ancestor raw session is not the exact R01 seed")
    from tradeintel_ai.trade_agent import read_public_session
    if read_public_session(parent / "runtime", turns[0]["session_id"]) != state:
        raise GateError("Ancestor raw session/public readback differ")
    root.mkdir(parents=True)
    copies = []
    relatives = [".local/trade-agent-sessions/" + raw_session.name]
    relatives += [".local/trade-reports/" + rid + ".json" for rid in current["report_ids"]]
    relatives += [str(p.relative_to(parent / "runtime")) for p in (parent / "runtime/.local/announcement-docs").glob("*.json")]
    relatives += ["turns.json", "policy-review.json", "policy-field-candidate.json", "policy-human-approval.json"]
    for relative in relatives:
        source = parent / "runtime" / relative
        for target in (root / "bootstrap/runtime" / relative, root / "runtime" / relative):
            copy_new_bytes(source, target)
        copies.append({"relative": relative, "sha256": file_hash(source)})
    for name in ("plan.json", "review-template.json", "effective-config.json", "environment.json", "policy-confirmation-sheet.json"):
        copy_new_bytes(parent / "inputs" / name, root / "inputs" / name)
    write_new(root / "reference/trade.json", reference)
    diagnostic = root / "bootstrap/R01-posthoc.json"
    write_new(diagnostic, {"case_id": "R01", "kind": "posthoc_context_audit_not_new_model_score",
        "audit": audit, "original_result_sha256": file_hash(parent / "results/batch/R01.json"),
        "raw_decision_correct": None, "reference_sha256": file_hash(root / "reference/trade.json")})
    write_new(root / "inputs/continuation.json", {"schema": "us-retest-continuation-v1", **facts,
        "allowlist": [c["id"] for c in plan["cases"][1:]], "bootstrap": copies,
        "anchor": {"case_id": "R01", "continuation_ready": True, "diagnostic_sha256": file_hash(diagnostic)},
        "score_boundary": "Original v4 remains partial; ancestor posthoc diagnosis and prospective 11 turns are separate"})
    write_new(root / "STATUS.json", {"status": "continuation_prepared_offline", "api_calls": 0,
        "planned_new_turns": 11, "normal": 8, "boundary": 3, "pending": ["offline acceptance", "freeze", "new finite permit"]})


def verify_continuation(root, *, initial=False):
    value = json.loads((root / "inputs/continuation.json").read_text())
    for name, digest in value["parent_files"].items():
        path = Path(name)
        if path.is_symlink() or not path.is_file() or file_hash(path) != digest:
            raise GateError("Ancestor evidence changed")
    default_inventory = [{"directory": str(Path(value["parent"]) / directory),
        "members": sorted(name for name in value["parent_files"] if Path(name).is_relative_to(Path(value["parent"]) / directory))}
        for directory in ("results/batch", "results/evidence", "ledgers/live", "runtime/.local/trade-agent-sessions", "runtime/.local/trade-reports")]
    for item in value.get("parent_inventory", default_inventory):
        directory = Path(item["directory"])
        if directory.is_symlink() or sorted(str(p.absolute()) for p in directory.rglob("*.json")) != item["members"]:
            raise GateError("Ancestor evidence inventory changed")
    if file_hash(root / "bootstrap/R01-posthoc.json") != value["anchor"]["diagnostic_sha256"]:
        raise GateError("Posthoc context audit changed")
    for item in value["bootstrap"]:
        relative = Path(item["relative"])
        if relative.is_absolute() or ".." in relative.parts:
            raise GateError("Unsafe bootstrap relative path")
        for path in [root / "bootstrap/runtime" / relative] + ([root / "runtime" / relative] if initial else []):
            if path.is_symlink() or not path.is_file() or file_hash(path) != item["sha256"]:
                raise GateError("Bootstrap/initial seed changed")
    plan = json.loads((root / "inputs/plan.json").read_text())
    if value["schema"] != "us-retest-continuation-v1" or value["allowlist"] != [c["id"] for c in plan["cases"][1:]]:
        raise GateError("Continuation allowlist changed")
    return value


def finalize(root, project, data_root):
    from scripts.prepare_us_retest_policy import POLICY_ID
    from tradeintel_ai.announcement_flow import load_announcement_store
    if (root / "inputs/continuation.json").exists():
        verify_continuation(root, initial=True)
    receipt = json.loads((root / "inputs/OFFLINE_ACCEPTANCE.json").read_text())
    if receipt.get("passed") is not True or not receipt.get("source_hashes"):
        raise GateError("Acceptance receipt missing")
    for name, digest in receipt["source_hashes"].items():
        if file_hash(Path(name)) != digest:
            raise GateError("Acceptance source/reference changed")
    if file_hash(data_root / "BUNDLE_MANIFEST.json") != receipt["data_manifest_sha256"]:
        raise GateError("Acceptance data changed")
    environment = json.loads((root / "inputs/environment.json").read_text())
    if environment["executable"] != sys.executable or environment["version"] != sys.version or file_hash(Path(sys.executable).resolve()) != environment["interpreter_sha256"]:
        raise GateError("Acceptance interpreter changed")
    proof = json.loads((root / "runtime/policy-human-approval.json").read_text())
    store = load_announcement_store(root / "runtime", POLICY_ID)
    doc = store["documents"][0]
    saved = store.get("announcement_candidates", {}).get(doc["doc_version"], {})
    if doc["status"] != "enabled" or saved.get("candidate_digest") != proof["approval"].get("candidate_digest") or saved.get("confirmation") != proof["confirmation"].get("confirmation"):
        raise GateError("Confirmed policy no longer matches approval")
    paths = collect_snapshot_inputs(project, root, data_root)
    paths.extend([root / "runtime/policy-human-approval.json", root / "inputs/OFFLINE_ACCEPTANCE.json",
                  root / "inputs/policy-confirmation-sheet.json"])
    snapshot_files(paths, root / "FROZEN_MANIFEST.json", inventories=[
        (project / "src/tradeintel_ai", "*.py"), (root / "runtime/.local/announcement-docs", "*.json")], ready_for_permit=True)


def package_status(root):
    status = {"api_calls": 0, "acceptance_passed": False, "policy_confirmed": False, "frozen": False,
              "billing": "not_verified"}
    receipt = root / "inputs/OFFLINE_ACCEPTANCE.json"
    if receipt.exists():
        status["acceptance_passed"] = json.loads(receipt.read_text()).get("passed") is True
    status["policy_confirmed"] = (root / "runtime/policy-human-approval.json").is_file()
    status["frozen"] = (root / "FROZEN_MANIFEST.json").is_file()
    status["finite_permit_recorded"] = (root / "ledgers/live/batch.json").is_file()
    status["api_calls"] = len(list((root / "ledgers/live").glob("send-*-dispatched.json")))
    status["pending"] = [name for key, name in (("acceptance_passed", "offline acceptance"),
        ("policy_confirmed", "user policy confirmation"), ("frozen", "final freeze"),
        ("finite_permit_recorded", "finite live permission")) if not status[key]]
    continuation = root / "inputs/continuation.json"
    if continuation.exists():
        value = json.loads(continuation.read_text())
        status.update(planned_new_turns=11, ancestor_requests=value["consumed_requests"],
            ancestor_estimated_cost=value["consumed_cost"], currency="CNY", original_v4="partial_unchanged")
    results = [json.loads(p.read_text()) for p in (root / "results/batch").glob("*.json")]
    status["executed_turns"] = sum(r.get("executed") is True for r in results)
    status["evaluation_reference_gaps"] = sum(r.get("evaluation_reference_gap") is True for r in results)
    status["recorded_unsafe_flags"] = sum(r.get("unsafe") is True for r in results)
    status["final_scores_pending"] = bool(results) and any(r.get("executed") and not (root / "results" / (r["case_id"] + "-FINAL_REVIEW.json")).exists() for r in results)
    return status


def run_authorized(root, data_root, permit_path):
    """No key loading until freeze and finite permission both validate."""
    from scripts.us_retest_transport import SendLedger, create_accounted_model
    frozen = root / "FROZEN_MANIFEST.json"
    continuation = verify_continuation(root, initial=True) if (root / "inputs/continuation.json").exists() else None
    def verify():
        if continuation is not None:
            verify_continuation(root)
        manifest = verify_snapshot(frozen)
        if manifest.get("ready_for_permit") is not True:
            raise GateError("Not a final acceptance/confirmation freeze")
        if str((data_root / "BUNDLE_MANIFEST.json").absolute()) not in manifest["files"]:
            raise GateError("Wrong data root")
        environment = json.loads((root / "inputs/environment.json").read_text())
        if environment["executable"] != sys.executable or environment["version"] != sys.version or file_hash(Path(sys.executable).resolve()) != environment["interpreter_sha256"]:
            raise GateError("Frozen interpreter changed")
        return file_hash(frozen)
    turns = json.loads((root / "runtime/turns.json").read_text())
    permit = json.loads(permit_path.read_text())
    send_turns = [t for t in turns if t["case_id"] in continuation["allowlist"]] if continuation else turns
    ledger = SendLedger(root / "ledgers/live", permit, verify, turns=send_turns, continuation=continuation)
    from tradeintel_ai.local_provider_config import load_product_config, product_request_params
    config = load_product_config()
    params = product_request_params()
    expected = json.loads((root / "inputs/effective-config.json").read_text())
    def verify_config():
        actual = load_product_config()
        if (actual.base_url.rstrip("/") != expected["base_url"] or actual.model != expected["model"] or
                actual.temperature != expected["temperature"] or not 0 < actual.timeout_seconds <= 90 or
                product_request_params() != expected["request_params"] or actual.api_key != config.api_key or not actual.api_key):
            raise GateError("Product configuration mismatch; no send")
        return actual
    def model_factory(case_id):
        actual = verify_config()
        return create_accounted_model(actual, params, ledger, next(t for t in turns if t["case_id"] == case_id))
    ledger.verify_inputs = lambda: (verify_config(), verify())[1]
    def review(case, result):
        from scripts.us_retest_transport import canonical_hash
        needed = root / "results" / (case["id"] + "-REVIEW_NEEDED.json")
        write_new(needed, {"case_id": case["id"], "result": result, "result_sha256": canonical_hash(result),
            "instruction": "Read saved public/tool evidence, then append a short semantic decision; no additional API judge"})
        decision_path = root / "results" / (case["id"] + "-SAFETY_REVIEW.json")
        while not decision_path.exists():
            ledger.check_time()
            time.sleep(1)
        return json.loads(decision_path.read_text())
    plan = json.loads((root / "inputs/plan.json").read_text())
    reference = json.loads((root / "reference/trade.json").read_text())
    executor = AgentCaseExecutor(plan, reference, data_root, root / "runtime", root / "results/evidence", model_factory)
    with ledger.batch():
        verify_config()
        return execute_cases(plan, turns, root / "results/batch", executor, verify_inputs=verify, review=review, continuation=continuation)


def score_package(root):
    from scripts.us_retest_transport import canonical_hash
    from scripts.score_us_agent_retest import count_results
    plan = json.loads((root / "inputs/plan.json").read_text())
    continuation = json.loads((root / "inputs/continuation.json").read_text()) if (root / "inputs/continuation.json").exists() else None
    if continuation:
        plan = {**plan, "cases": [c for c in plan["cases"] if c["id"] in continuation["allowlist"]]}
    results = []
    reviews = []
    for case in plan["cases"]:
        path = root / "results/batch" / (case["id"] + ".json")
        if not path.exists():
            results.append({"case_id": case["id"], "executed": False, "responses": 0})
            continue
        original = json.loads(path.read_text())
        result = dict(original)
        review_path = root / "results" / (case["id"] + "-FINAL_REVIEW.json")
        if review_path.exists():
            review = json.loads(review_path.read_text())
            if (review.get("case_id") != case["id"] or review.get("result_sha256") != canonical_hash(original)
                    or review.get("reviewer_role") not in {"user", "human_reviewer", "ai_reviewer"}
                    or not isinstance(review.get("reason"), str) or not review["reason"].strip()
                    or review.get("product_result") not in {"complete", "safe_incomplete", "unsafe"}):
                raise GateError("Invalid or stale final review")
            if (review["product_result"] == "complete" and
                    (not result.get("executed") or not result.get("request_accounting_complete") or
                     result.get("unsafe") or case["kind"] == "normal" and not result.get("continuation_ready"))):
                raise GateError("Review cannot bypass factual/accounting failure")
            raw = review.get("raw_decision_correct")
            if raw is not None and type(raw) is not bool or raw is True and result.get("query_audit", {}).get("errors"):
                raise GateError("Final review hides a recorded wrong query")
            if raw is not None and result.get("origin") != "api":
                raise GateError("Offline/program-only result has no API model score")
            result.update(product_result=review["product_result"], raw_decision_correct=raw)
            reviews.append({"case_id": case["id"], "role": review["reviewer_role"]})
        results.append(result)
    summary = count_results(results, planned=11 if continuation else 12)
    if (any(row.get("executed") for row in results) and not any(row.get("origin") == "offline_fixture" for row in results)
            and all(not row.get("executed") or row.get("product_result") in {"complete", "safe_incomplete", "unsafe"} for row in results)):
        summary["release_gate"] = ("not_comparable_segmented_protocol" if continuation else "met" if summary["normal_complete"] >= 8 and summary["boundary_safe"] == 3
                                   and not any(row.get("product_result") == "unsafe" for row in results) else "not_met")
    reservations = list((root / "ledgers/live").glob("send-[0-9][0-9][0-9].json"))
    settled_cost, outstanding = Decimal(0), Decimal(0)
    settled_count = 0
    for path in reservations:
        record = json.loads(path.read_text())
        settlement = path.with_name(path.stem + "-settled.json")
        if settlement.exists():
            settled_cost += Decimal(json.loads(settlement.read_text())["estimated_cost"])
            settled_count += 1
        else:
            outstanding += Decimal(record["reserved_cost"])
    summary["accounting"] = {"reserved_requests": len(reservations), "settled_requests": settled_count,
        "estimated_cost": str(settled_cost), "outstanding_reserved": str(outstanding),
        "currency": json.loads(reservations[0].read_text())["currency"] if reservations else None,
        "basis": "reported_usage_peak_uncached_price", "actual_billing": "not_verified"}
    if continuation:
        summary.update(normal_planned=8, boundary_planned=3, original_v4="partial_unchanged",
            ancestor_diagnostic="bootstrap/R01-posthoc.json", ancestor_model_score="not_regraded")
        summary["release_gate"] = "not_comparable_segmented_protocol"
        summary["accounting"].update(cumulative_requests=continuation["consumed_requests"] + len(reservations),
            cumulative_estimated_cost=str(Decimal(continuation["consumed_cost"]) + settled_cost),
            currency="CNY")
    return {"summary": summary, "reviews": reviews, "results": results,
            "boundary": "AI review is labeled separately and is not independent human gold; billing remains unverified"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "prepare-final", "prepare-continuation", "acceptance", "confirm-policy", "finalize", "score", "status", "review-template", "snapshot", "verify", "run"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--scenarios", type=Path, default=Path("evals/us_agent_retest_v1/scenarios.json"))
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--permit", type=Path)
    parser.add_argument("--parent", type=Path)
    args = parser.parse_args()
    if args.mode == "score":
        print(json.dumps(score_package(args.root), ensure_ascii=False))
        return
    if args.mode == "run":
        if args.permit is None or args.data_root is None:
            parser.error("--permit and --data-root required; no request sent")
        run_authorized(args.root, args.data_root, args.permit)
        print(json.dumps(package_status(args.root)))
        return
    project = Path(__file__).resolve().parents[1]
    if args.mode == "prepare-continuation":
        if args.parent is None or args.data_root is None:
            parser.error("--parent and --data-root required; offline only")
        prepare_continuation(args.root, args.parent, project, args.data_root)
        print(json.dumps(package_status(args.root)))
        return
    if args.mode in {"prepare-final", "acceptance", "finalize"}:
        if args.data_root is None:
            parser.error("--data-root required")
        if args.mode == "prepare-final":
            prepare_final(args.root, project, args.scenarios, args.data_root)
        elif args.mode == "acceptance":
            acceptance(args.root, project, args.data_root)
        else:
            finalize(args.root, project, args.data_root)
        print(json.dumps(package_status(args.root)))
        return
    if args.mode == "confirm-policy":
        if args.approval is None:
            parser.error("--approval with actual user evidence required")
        confirm_policy(args.root, args.approval)
        print(json.dumps(package_status(args.root)))
        return
    if args.mode == "status":
        print(json.dumps(package_status(args.root)))
        return
    if args.mode == "prepare":
        if args.reference is None:
            parser.error("--reference required")
        prepare(args.root, args.scenarios, args.reference)
    if args.mode == "snapshot":
        if args.data_root is None:
            parser.error("--data-root required")
        project = Path(__file__).resolve().parents[1]
        snapshot_files(collect_snapshot_inputs(project, args.root, args.data_root), args.root / "OFFLINE_SNAPSHOT.json",
            inventories=[(project / "src/tradeintel_ai", "*.py"),
                         (args.root / "runtime/.local/announcement-docs", "*.json")])
    if args.mode == "review-template":
        plan = json.loads((args.root / "inputs/plan.json").read_text())
        write_new(args.root / "inputs/review-template.json", build_review_materials(plan))
    if args.mode == "verify":
        snapshot = verify_snapshot(args.root / "OFFLINE_SNAPSHOT.json")
        print(json.dumps({"verified_files": len(snapshot["files"]), "live_ready": False}))
        return
    print(json.dumps(package_status(args.root)))


if __name__ == "__main__":
    main()
