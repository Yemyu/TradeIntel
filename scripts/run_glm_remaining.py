"""Continue independent, previously unexecuted GLM evaluation cases only."""
import argparse
import json
import time
from pathlib import Path

from scripts.run_glm_agent_retest import (AgentCaseExecutor, DEFAULT_DATA, CREDENTIALS,
    GLMSendLedger, create_model, load_key, verify_package)
from scripts.run_us_agent_retest import GateError, file_hash, snapshot_files, verify_snapshot, write_new
from scripts.us_retest_transport import canonical_hash


def remaining_cases(plan, prior):
    ids = [c["id"] for c in plan["cases"]]
    if set(prior) != set(ids):
        raise GateError("Incomplete parent results")
    return [c for c in plan["cases"] if prior[c["id"]].get("executed") is False]


def execute_remaining(plan, turns, prior, output, execute, *, verify=lambda: None, review=None):
    if output.exists():
        raise GateError("Supplement exists; do not replay")
    selected = remaining_cases(plan, prior)
    turn_map = {t["case_id"]: t for t in turns}
    if len(turn_map) != len(turns):
        raise GateError("Duplicate turns")
    for case in selected:
        t = turn_map[case["id"]]
        if t["question"] != case["question"] or t.get("requires") != case.get("requires"):
            raise GateError("Question/dependency changed")
    output.mkdir(parents=True)
    results, stopped = dict(prior), False
    for case in selected:
        ident, dependency = case["id"], case.get("requires")
        if stopped or (dependency and not results[dependency].get("continuation_ready")):
            result = {"case_id": ident, "executed": False, "responses": 0,
                      "status": "not_run_infrastructure_stop" if stopped else "not_run_prerequisite"}
        else:
            verify()
            write_new(output / "claims" / (ident + ".json"), turn_map[ident])
            result = execute(dict(turn_map[ident]))
            if result.get("case_id") != ident:
                raise GateError("Result identity mismatch")
            result = {**result, "executed": True, "kind": case["kind"]}
            # Content/protocol failure is a per-case result, not a network stop.
            if result.get("public_safety") == "review_required":
                if review is None:
                    raise GateError("Saved evidence needs review")
                decision = review(case, dict(result))
                if (decision.get("case_id") != ident or not decision.get("reason")
                        or decision.get("result_sha256") != canonical_hash(result)):
                    raise GateError("Review evidence mismatch")
                write_new(output / (ident + "-review.json"), decision)
                result["unsafe"] = decision.get("public_safe") is False
                result["semantic_review"] = decision
            stopped = (result.get("request_accounting_complete") is not True
                       or result.get("agent_status") == "unknown_outcome"
                       or result.get("evaluation_reference_gap") is True)
            result["supplement_batch_stop"] = stopped
        write_new(output / (ident + ".json"), result)
        results[ident] = result
    write_new(output / "combined.json", [results[c["id"]] for c in plan["cases"]])
    return [results[c["id"]] for c in plan["cases"]]


def prepare(parent, root):
    verify_package(parent, DEFAULT_DATA)
    if root.exists():
        raise GateError("Supplement already exists")
    plan = json.loads((parent / "inputs/plan.json").read_text())
    prior = {c["id"]: json.loads((parent / "results/batch" / (c["id"] + ".json")).read_text())
             for c in plan["cases"]}
    selected = remaining_cases(plan, prior)
    sends = list((parent / "ledgers/live").glob("send-[0-9][0-9][0-9].json"))
    settled = list((parent / "ledgers/live").glob("send-*-settled.json"))
    if len(sends) != len(settled):
        raise GateError("Unaccounted parent send; no continuation")
    used = sum(json.loads(p.read_text())["total_tokens"] for p in settled)
    root.mkdir(parents=True)
    info = {"parent": str(parent), "selected": [c["id"] for c in selected],
            "prior": prior, "parent_requests": len(sends), "parent_tokens": used,
            "remaining_requests": 48 - len(sends), "remaining_tokens": 2500000 - used,
            "policy": "Continue independent cases after answer failure; never replay executed cases."}
    write_new(root / "continuation.json", info)
    original = verify_snapshot(parent / "FROZEN_MANIFEST.json")
    paths = [Path(p) for p in original["files"]]
    paths += list((parent / "results").rglob("*.json")) + list((parent / "ledgers").rglob("*.json"))
    paths += [root / "continuation.json", Path(__file__).resolve(),
              Path(__file__).resolve().parents[1] / "tests/test_glm_remaining.py"]
    snapshot_files(sorted(set(paths)), root / "FROZEN_MANIFEST.json", ready_for_permit=True)
    permit = json.loads((parent / "APPROVED_PERMIT.json").read_text())
    permit.update(approved=False, expires_at=None, authorization_message_sha256=None,
                  freeze_sha256=file_hash(root / "FROZEN_MANIFEST.json"),
                  max_total_tokens=info["remaining_tokens"])
    write_new(root / "PERMISSION_REQUEST.json", permit)
    return info


class RemainingLedger(GLMSendLedger):
    def __init__(self, *args, remaining_requests, **kwargs):
        super().__init__(*args, **kwargs)
        self.remaining_requests = remaining_requests

    def reserve(self, request, turn):
        if len(self.records()) >= self.remaining_requests:
            self.stop("combined_request_budget")
            raise GateError("Parent plus supplement request limit reached")
        return super().reserve(request, turn)


def run(root, permit_path):
    info = json.loads((root / "continuation.json").read_text())
    parent = Path(info["parent"])
    def verify():
        verify_snapshot(root / "FROZEN_MANIFEST.json")
        verify_package(parent, DEFAULT_DATA)
        return file_hash(root / "FROZEN_MANIFEST.json")
    effective = json.loads((parent / "inputs/effective-config.json").read_text())
    turns = json.loads((parent / "runtime/turns.json").read_text())
    permit = json.loads(permit_path.read_text())
    if permit.get("max_total_tokens") != info["remaining_tokens"]:
        raise GateError("Combined token ceiling changed")
    ledger = RemainingLedger(root / "ledgers", permit, effective, verify, turns=turns,
                             remaining_requests=info["remaining_requests"])
    with ledger.batch():
        key = load_key(CREDENTIALS)
        factory = lambda ident: create_model(effective, key, ledger, next(t for t in turns if t["case_id"] == ident))
        plan = json.loads((parent / "inputs/plan.json").read_text())
        executor = AgentCaseExecutor(plan, json.loads((parent / "reference/trade.json").read_text()),
                                    DEFAULT_DATA, parent / "runtime", root / "evidence", factory)
        def review(case, result):
            write_new(root / "reviews" / (case["id"] + "-NEEDED.json"),
                      {"result": result, "result_sha256": canonical_hash(result)})
            path = root / "reviews" / (case["id"] + "-DECISION.json")
            while not path.exists():
                ledger.check_time()
                time.sleep(1)
            return json.loads(path.read_text())
        return execute_remaining(plan, turns, info["prior"], root / "batch", executor,
                                 verify=verify, review=review)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--permit", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.action == "prepare":
        if not args.parent:
            parser.error("--parent required")
        print(json.dumps(prepare(args.parent.absolute(), args.output.absolute()), ensure_ascii=False))
    else:
        if not args.execute or not args.permit:
            parser.error("--execute and --permit required")
        print(json.dumps(run(args.output.absolute(), args.permit.absolute()), ensure_ascii=False))
