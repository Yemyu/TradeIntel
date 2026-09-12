"""Fail-closed guards for the 0112 prospective acceptance protocol.

This module deliberately has no provider or network dependency.  It provides
the small pieces that must be true *before* an online batch can be considered
for release:

* hard terminal-state checks run before a human review can approve anything;
* a structured review has one decision and reason for every frozen item;
* execution inputs are fingerprinted and checked before every provider call;
* calls are reserved durably before provider code, and are never retried;
* unknown usage, failed calls, and token limits stop the batch while preserving
  a fixed ``not_run`` row for every question that was not reached.

The actual 0111 online runner remains disabled until an Astra review wires this
module into a new, semantically corrected question set.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import uuid
from typing import Any, Callable, Iterable, Mapping
from .answer_checklist import at


HARD_FAILURE_CATEGORIES = frozenset({
    "connection",
    "timeout",
    "http",
    "url",
    "dns",
    "certificate",
    "tls",
    "tls_eof",
    "connection_reset",
    "connection_refused",
    "os",
    "transport",
    "adapter_or_response_error",
    "structure",
    "transport_failure",
})

FAILURE_STATUSES = frozenset({
    "failed",
    "interrupted",
    "incomplete",
    "needs_review",
    "stopped_without_retry",
    "execution_failed",
    "trade_execution_failed",
    "planning_failed",
    "answer_rejected",
    "unsafe_execution_path",
})

EXECUTABLE_STATUSES = frozenset({
    "needs_confirmation",
    "research_draft",
    "trade_draft",
    "policy_draft",
})

SUPPORT_TERMINAL_STATUSES = frozenset({
    "research_draft",
    "trade_draft",
    "policy_draft",
})

NON_EXECUTABLE_TERMINAL_STATUSES = frozenset({
    "needs_clarification",
    "needs_scope_selection",
    "clarification",
    "scope_selection",
})

STAGES = ("planning", "policy_with_evidence", "policy_no_evidence")
DEFAULT_STAGE_BUDGETS = {
    "planning": 24,
    "policy_with_evidence": 8,
    "policy_no_evidence": 8,
}
DEFAULT_TOKEN_BUDGET = 80_000


class AcceptanceGuardError(ValueError):
    """A malformed or unsafe acceptance record."""


class FrozenInputChanged(AcceptanceGuardError):
    """A file or snapshot used by the batch changed after freezing."""


class AcceptanceStopped(RuntimeError):
    """The one-way prospective ledger has stopped and cannot be resumed."""


class ReferenceLeakage(AcceptanceGuardError):
    """Human-only reference material was found in a model message."""


def digest(value: Any) -> str:
    """Return a deterministic SHA-256 for JSON-compatible values."""

    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        .encode("utf-8")
    ).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compare_trade_scope(reference_request: Mapping[str, Any],
                        proposed_request: Mapping[str, Any]) -> dict[str, Any]:
    """Compare against a separately frozen request; never repair the proposal.

    This checks equality, not provenance: the runner must load the reference
    before any model call and keep it outside the model input boundary.
    """
    fields = {"policy_id", "operation", "metric", "origin", "granularity",
              "months", "hs6", "causal_effect"}
    def canonical(request):
        if not isinstance(request, Mapping) or set(request) != {"trade", "comparison"}:
            raise AcceptanceGuardError("trade comparison requires complete request")
        trade = request["trade"]
        if not isinstance(trade, Mapping) or set(trade) != fields:
            raise AcceptanceGuardError("trade comparison requires all scope fields")
        result = deepcopy(dict(request))
        months = trade["months"]
        if months is not None:
            if (not isinstance(months, list) or not months
                    or any(not isinstance(m, str) for m in months)
                    or len(set(months)) != len(months)):
                raise AcceptanceGuardError("invalid explicit month list")
            result["trade"]["months"] = sorted(months)
        spec = request["comparison"]
        schemas = {"sequence": {"kind"},
                   "endpoint": {"kind", "reference_month", "current_month"},
                   "registered": {"kind", "comparison_id"}}
        if not isinstance(spec, Mapping) or spec.get("kind") not in schemas or set(spec) != schemas[spec["kind"]]:
            raise AcceptanceGuardError("invalid comparison contract")
        if months is None and spec["kind"] != "registered":
            raise AcceptanceGuardError("explicit comparison requires months")
        return result
    reference, proposed = canonical(reference_request), canonical(proposed_request)
    differences = ["trade." + field for field in sorted(fields)
                   if digest(reference["trade"][field]) != digest(proposed["trade"][field])]
    if digest(reference["comparison"]) != digest(proposed["comparison"]):
        differences.append("comparison")
    return {"scope_equal": not differences, "differences": differences,
            "reference_sha256": digest(reference), "proposed_sha256": digest(proposed),
            "proposal_repaired": False, "provenance_verified": False}


def validate_policy_pair(with_evidence: Mapping[str, Any],
                         without_evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Validate declared paired-call configuration before either call.

    Payload capture at the adapter boundary is still required to prove that
    the actual calls used these settings. Neither arm is scored here.
    """
    keys = {"question", "as_of", "base_url", "model", "temperature", "max_tokens",
            "thinking", "stream", "timeout_seconds", "response_schema_sha256"}
    for arm in (with_evidence, without_evidence):
        if not isinstance(arm, Mapping) or set(arm) != keys:
            raise AcceptanceGuardError("paired configuration is incomplete or contains extra fields")
        for key in ("question", "as_of", "base_url", "model", "response_schema_sha256"):
            if not isinstance(arm[key], str) or not arm[key].strip():
                raise AcceptanceGuardError("paired configuration identity is missing")
        if type(arm["max_tokens"]) is not int or arm["max_tokens"] != 768:
            raise AcceptanceGuardError("policy pair requires the frozen 768 output limit")
        if arm["thinking"] != {"type": "disabled"} or arm["stream"] is not False:
            raise AcceptanceGuardError("policy pair requires disabled thinking and streaming")
        if (type(arm["temperature"]) not in (int, float) or not 0 <= arm["temperature"] <= 2
                or type(arm["timeout_seconds"]) not in (int, float)
                or not 0 < arm["timeout_seconds"] < float('inf')):
            raise AcceptanceGuardError("invalid paired numeric settings")
    if digest(with_evidence) != digest(without_evidence):
        raise AcceptanceGuardError("policy pair settings differ")
    return {"configuration_equal": True, "configuration_sha256": digest(with_evidence),
            "actual_calls_verified": False, "semantic_accuracy_measured": False}


FACT_REVIEW_STATUSES = frozenset({
    "supported", "missing", "contradicted", "unverifiable",
})
CLAIM_REVIEW_STATUSES = frozenset({
    "supported", "unsupported", "contradicted", "uncertainty",
})


def validate_fact_review(packet: Mapping[str, Any],
                         submission: Mapping[str, Any],
                         *, reviewer: str | None = None) -> dict[str, Any]:
    """Validate a human fact/claim review without deciding its truth.

    The packet contains the answer and frozen evidence; the reviewer supplies
    semantic labels.  This function checks identity, exhaustiveness and that
    every cited quote actually exists in the packet.  It deliberately does not
    infer ``supported`` from matching words, so a negation or an extra causal
    claim remains a human decision.
    """

    if not isinstance(packet, Mapping) or not isinstance(submission, Mapping):
        raise AcceptanceGuardError("fact review packet and submission must be objects")
    case_id, arm = packet.get("case_id"), packet.get("arm")
    if (not isinstance(case_id, str) or not case_id.strip()
            or arm not in {"with_evidence", "without_evidence"}):
        raise AcceptanceGuardError("fact review packet identity is invalid")
    if submission.get("case_id") != case_id or submission.get("arm") != arm:
        raise AcceptanceGuardError("fact review belongs to another case or arm")
    expected_reviewer = reviewer or submission.get("reviewer")
    if not isinstance(expected_reviewer, str) or not expected_reviewer.strip():
        raise AcceptanceGuardError("fact review reviewer is required")
    if submission.get("reviewer") != expected_reviewer:
        raise AcceptanceGuardError("fact review reviewer mismatch")
    if not isinstance(submission.get("reviewed_at"), str) or not submission["reviewed_at"].strip():
        raise AcceptanceGuardError("fact review timestamp is required")
    if submission.get("packet_sha256") != digest(packet):
        raise AcceptanceGuardError("fact review is not bound to its packet")

    facts = packet.get("facts")
    if not isinstance(facts, list) or not facts:
        raise AcceptanceGuardError("frozen facts are required")
    fact_ids = []
    for fact in facts:
        if (not isinstance(fact, Mapping) or not isinstance(fact.get("id"), str)
                or not fact["id"].strip()):
            raise AcceptanceGuardError("invalid frozen fact")
        fact_ids.append(fact["id"])
    if len(set(fact_ids)) != len(fact_ids):
        raise AcceptanceGuardError("duplicate frozen fact")

    reviewed_facts = submission.get("facts")
    if not isinstance(reviewed_facts, list) or len(reviewed_facts) != len(fact_ids):
        raise AcceptanceGuardError("each frozen fact needs exactly one review")
    fact_by_id = {row.get("id"): row for row in reviewed_facts if isinstance(row, Mapping)}
    if set(fact_by_id) != set(fact_ids) or len(fact_by_id) != len(fact_ids):
        raise AcceptanceGuardError("fact review IDs do not match the frozen facts")

    answer = packet.get("answer")
    if not isinstance(answer, Mapping) or not isinstance(answer.get("claims"), list):
        raise AcceptanceGuardError("fact review answer claims are missing")
    claims = answer["claims"]
    evidence = packet.get("evidence", {})
    if not isinstance(evidence, Mapping):
        raise AcceptanceGuardError("fact review evidence must be an object")
    citation_ids = set(evidence)
    fact_records = []
    fact_failures = {status: 0 for status in ("missing", "contradicted", "unverifiable")}
    for fact_id in fact_ids:
        row = fact_by_id[fact_id]
        status, reason = row.get("status"), row.get("reason")
        if status not in FACT_REVIEW_STATUSES or not isinstance(reason, str) or not reason.strip():
            raise AcceptanceGuardError("invalid fact review row")
        claim_indices = row.get("claim_indices", [])
        if not isinstance(claim_indices, list) or any(
                type(index) is not int or not 0 <= index < len(claims)
                for index in claim_indices):
            raise AcceptanceGuardError("fact claim index is outside the actual answer")
        if len(set(claim_indices)) != len(claim_indices):
            raise AcceptanceGuardError("duplicate fact claim index")
        if status in {"supported", "contradicted"}:
            if not claim_indices:
                raise AcceptanceGuardError("supported or contradicted facts need a claim")
            source_id = row.get("source_id")
            excerpt = row.get("evidence_excerpt")
            # The baseline model sees no evidence, but its reviewer still
            # needs the same frozen reference evidence as the main reviewer.
            if (not isinstance(source_id, str) or source_id not in citation_ids
                    or not isinstance(evidence[source_id], Mapping)
                    or not isinstance(excerpt, str) or not excerpt.strip()
                    or excerpt not in str(evidence[source_id].get("text", ""))):
                raise AcceptanceGuardError("fact evidence quote is not in the packet")
        elif claim_indices and status == "missing":
            raise AcceptanceGuardError("missing fact cannot cite an answer claim")
        if status in fact_failures:
            fact_failures[status] += 1
        fact_records.append({"id": fact_id, "status": status, "reason": reason,
                             "claim_indices": list(claim_indices)})

    reviewed_claims = submission.get("claims")
    if not isinstance(reviewed_claims, list) or len(reviewed_claims) != len(claims):
        raise AcceptanceGuardError("each actual claim needs exactly one review")
    claim_by_index = {}
    for row in reviewed_claims:
        if not isinstance(row, Mapping) or type(row.get("index")) is not int:
            raise AcceptanceGuardError("invalid claim review row")
        index = row["index"]
        if index in claim_by_index or not 0 <= index < len(claims):
            raise AcceptanceGuardError("claim review indices do not match the answer")
        if row.get("status") not in CLAIM_REVIEW_STATUSES:
            raise AcceptanceGuardError("invalid claim review status")
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            raise AcceptanceGuardError("claim review reason is required")
        fact_refs = row.get("fact_ids", [])
        if not isinstance(fact_refs, list) or any(item not in fact_ids for item in fact_refs):
            raise AcceptanceGuardError("claim review references an unknown fact")
        claim_by_index[index] = row
    if set(claim_by_index) != set(range(len(claims))):
        raise AcceptanceGuardError("claim review is not exhaustive")

    citation_review = submission.get("citation_review")
    if arm == "with_evidence":
        if not isinstance(citation_review, Mapping) or citation_review.get("status") not in {"pass", "fail"}:
            raise AcceptanceGuardError("evidence arm requires citation review")
        if not isinstance(citation_review.get("reason"), str) or not citation_review["reason"].strip():
            raise AcceptanceGuardError("citation review reason is required")
    elif citation_review is not None and (not isinstance(citation_review, Mapping)
                                        or citation_review.get("status") != "not_applicable"):
        raise AcceptanceGuardError("baseline citation review must be not_applicable")

    supported = sum(row["status"] == "supported" for row in fact_records)
    unsupported_claims = sum(row["status"] in {"unsupported", "contradicted"}
                             for row in claim_by_index.values())
    return {
        "version": "fact-review-0118",
        "case_id": case_id,
        "arm": arm,
        "reviewer": expected_reviewer,
        "packet_sha256": digest(packet),
        "approved": (supported == len(fact_ids) and not fact_failures["contradicted"]
                     and not fact_failures["unverifiable"] and unsupported_claims == 0
                     and (arm == "without_evidence"
                          or citation_review.get("status") == "pass")),
        "semantic_accuracy_measured": False,
        "review_structure_verified": True,
        "fact_counts": {"total": len(fact_ids), "supported": supported,
                        **fact_failures},
        "unsupported_claim_count": unsupported_claims,
    }


def _safe_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Keep only provider usage fields; never persist arbitrary response data."""

    if not isinstance(metadata, Mapping):
        return {}
    usage = metadata.get("usage")
    if not isinstance(usage, Mapping):
        usage = {}
    finish_reason = metadata.get("finish_reason")
    result: dict[str, Any] = {
        "finish_reason": finish_reason
        if isinstance(finish_reason, str)
        and finish_reason in {"stop", "length", "tool_calls", "content_filter"}
        else None,
        "usage": {},
    }
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if type(value) is int and value >= 0:
            result["usage"][key] = value
    return result


def total_tokens(metadata: Mapping[str, Any] | None) -> int | None:
    """Read an explicit provider total; missing totals remain unknown.

    We intentionally do not add prompt and completion fields ourselves.  Some
    providers report cached or reasoning tokens differently, so inferring a
    total would weaken the budget stop rule.
    """

    safe = _safe_metadata(metadata)
    value = safe.get("usage", {}).get("total_tokens")
    return value if type(value) is int and value >= 0 else None


def _iter_files(paths: Iterable[str | Path]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        path = Path(raw).resolve()
        if not path.is_file():
            raise FileNotFoundError(str(path))
        files.append(path)
    if len({str(path.resolve()) for path in files}) != len(files):
        raise AcceptanceGuardError("duplicate frozen dependency path")
    return sorted(files, key=lambda path: str(path))


def freeze_dependencies(
    paths: Iterable[str | Path],
    *,
    configuration: Mapping[str, Any] | None = None,
    labels: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Fingerprint all files and configuration used by a future batch.

    ``paths`` is intentionally explicit.  Callers must list the runner,
    adapter, prompts, questions, references, corpus and data files rather than
    relying on a broad directory glob whose contents could silently change.
    """

    files = _iter_files(paths)
    records = []
    for path in files:
        records.append({
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
            "label": (labels or {}).get(str(path)),
        })
    payload = {
        "version": "prospective-freeze-0112",
        "files": records,
        "configuration": deepcopy(dict(configuration or {})),
    }
    return {**payload, "snapshot_sha256": digest(payload)}


def verify_dependencies(snapshot: Mapping[str, Any]) -> None:
    """Fail closed if any frozen input, path, or snapshot body changed."""

    if not isinstance(snapshot, Mapping) or snapshot.get("version") != "prospective-freeze-0112":
        raise FrozenInputChanged("invalid dependency snapshot")
    body = {key: deepcopy(snapshot[key]) for key in ("version", "files", "configuration")
            if key in snapshot}
    if snapshot.get("snapshot_sha256") != digest(body):
        raise FrozenInputChanged("dependency snapshot fingerprint changed")
    records = snapshot.get("files")
    if not isinstance(records, list) or not records:
        raise FrozenInputChanged("dependency snapshot has no explicit files")
    for record in records:
        if not isinstance(record, Mapping) or not isinstance(record.get("path"), str):
            raise FrozenInputChanged("malformed frozen dependency record")
        path = Path(record["path"])
        if not path.is_file():
            raise FrozenInputChanged("frozen dependency is missing")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != record.get("sha256"):
            raise FrozenInputChanged("frozen dependency changed")


def assert_no_reference_leakage(
    messages: Iterable[Mapping[str, Any]],
    reference: Mapping[str, Any],
) -> None:
    """Reject human-only reference values copied into model messages.

    The full serialized reference is the strongest signal.  We additionally
    reject non-trivial scalar values (at least four characters) so a synthetic
    gold answer cannot be smuggled field by field.  Short labels such as an
    ID or ``USD`` are not sufficient evidence by themselves and are ignored.
    """

    if not isinstance(reference, Mapping):
        raise AcceptanceGuardError("reference must be an object")
    message_text = json.dumps(list(messages), ensure_ascii=False, sort_keys=True)
    reference_text = json.dumps(reference, ensure_ascii=False, sort_keys=True)
    if reference_text in message_text:
        raise ReferenceLeakage("完整的人类审查参考被放入模型消息")

    def scalars(value: Any) -> Iterable[str]:
        if isinstance(value, Mapping):
            for nested in value.values():
                yield from scalars(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                yield from scalars(nested)
        elif isinstance(value, str) and len(value.strip()) >= 4:
            yield value.strip()
        elif type(value) in (int, float) and abs(value) >= 1000:
            yield str(value)

    for scalar in scalars(reference):
        if scalar in message_text:
            raise ReferenceLeakage("人类审查参考值出现在模型消息")


def _collect_diagnostic_categories(value: Any) -> set[str]:
    categories: set[str] = set()
    if isinstance(value, Mapping):
        diagnostic = value.get("diagnostic")
        if isinstance(diagnostic, Mapping):
            category = diagnostic.get("category")
            if isinstance(category, str):
                categories.add(category)
        # A synthetic packet can put a category directly under an audit row.
        direct_category = value.get("category")
        if isinstance(direct_category, str) and direct_category in HARD_FAILURE_CATEGORIES:
            categories.add(direct_category)
        for nested in value.values():
            categories.update(_collect_diagnostic_categories(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            categories.update(_collect_diagnostic_categories(nested))
    return categories


def _actual_tasks(result: Mapping[str, Any]) -> list[str] | None:
    tasks = result.get("tasks")
    if tasks is None and isinstance(result.get("request"), Mapping):
        tasks = result["request"].get("tasks")
    if tasks is None and isinstance(result.get("plan"), Mapping):
        tasks = result["plan"].get("tasks")
    if not isinstance(tasks, list) or any(not isinstance(item, str) for item in tasks):
        return None
    return list(tasks)


def validate_terminal(
    *,
    preview: Mapping[str, Any] | None = None,
    result: Mapping[str, Any] | None = None,
    delivery: Mapping[str, Any] | None = None,
    review: Mapping[str, Any] | None = None,
    expected_kind: str = "support",
    expected_tasks: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Validate an execution terminal state before considering review.

    A reviewer can reject a good result, but cannot approve a hard failure.
    The returned record is JSON-safe and deliberately includes the reason for
    every hard rejection so it can be saved beside a future review submission.
    """

    if expected_kind not in {"support", "clarification", "boundary"}:
        raise AcceptanceGuardError("unknown terminal kind")
    preview = preview if isinstance(preview, Mapping) else {}
    result = result if isinstance(result, Mapping) else {}
    delivery = delivery if isinstance(delivery, Mapping) else None
    observed = [preview, result]
    if delivery is not None:
        observed.append(delivery)
    hard: list[str] = []
    categories = set().union(*(_collect_diagnostic_categories(item) for item in observed))
    for category in sorted(categories):
        if category in HARD_FAILURE_CATEGORIES:
            hard.append(f"diagnostic:{category}")

    statuses = {item.get("status") for item in observed if isinstance(item, Mapping)}
    bad_statuses = sorted(status for status in statuses if status in FAILURE_STATUSES)
    hard.extend(f"status:{status}" for status in bad_statuses)
    if delivery is not None and delivery.get("status") in {"failed", "interrupted", "incomplete"}:
        hard.append(f"delivery:{delivery.get('status')}")

    actual = _actual_tasks(result)
    if actual is None:
        actual = _actual_tasks(preview)
    if expected_tasks is not None and actual is None:
        hard.append("tasks:missing")
    elif expected_tasks is not None and sorted(actual or []) != sorted(set(expected_tasks)):
        hard.append("tasks:mismatch")

    final_status = result.get("status") or preview.get("status")
    if expected_kind == "support":
        if preview.get("status") != "needs_confirmation":
            hard.append("preview:not_confirmable")
        if final_status not in SUPPORT_TERMINAL_STATUSES:
            hard.append("result:not_delivered")
        if delivery is None:
            hard.append("delivery:missing")
        else:
            if delivery.get("verified") is not True:
                hard.append("delivery:not_verified")
            if delivery.get("missing_files"):
                hard.append("delivery:missing_files")
        policy = result.get("policy")
        if 'policy' in (actual or []):
            generation = policy.get('generation') if isinstance(policy, Mapping) else None
            if (not isinstance(generation, Mapping)
                    or generation.get('status') != 'draft_requires_semantic_review'):
                hard.append("policy:generation_failed")
    else:
        if (any(item.get('status') in EXECUTABLE_STATUSES or item.get('executed') is True
                or item.get('confirmation_token') for item in (preview, result))):
            hard.append("terminal:unsafe_execution")
        if final_status not in NON_EXECUTABLE_TERMINAL_STATUSES:
            hard.append("terminal:not_clarification_or_boundary")

    review_approved = bool(isinstance(review, Mapping) and review.get("approved") is True)
    unique_hard = list(dict.fromkeys(hard))
    return {
        "version": "terminal-guard-0112",
        "approved": bool(review_approved and not unique_hard),
        "reviewer_approved": review_approved,
        "hard_failures": unique_hard,
        "reviewer_cannot_override": bool(review_approved and unique_hard),
        "expected_kind": expected_kind,
        "observed_status": final_status,
        "actual_tasks": actual,
    }


def validate_structured_review(
    packet: Mapping[str, Any],
    submission: Mapping[str, Any],
    *,
    reviewer: str,
    expected_kind: str = "support",
    expected_tasks: Iterable[str] | None = None,
    stage: str = "answer",
) -> dict[str, Any]:
    """Validate a per-requirement review and combine it with hard gates.

    ``stage='plan'`` is intentionally a different gate from answer review:
    it can approve only a non-executed preview (usually ``needs_confirmation``
    or a deliberate clarification), never a delivery.  Keeping this branch
    here means the same frozen checklist and packet-hash rules apply to both
    halves of the workflow without pretending that a plan is an answer.
    """

    if not isinstance(reviewer, str) or not reviewer.strip():
        raise AcceptanceGuardError("explicit reviewer required")
    if stage not in {"plan", "answer"}:
        raise AcceptanceGuardError("unknown review stage")
    if expected_kind not in {"support", "clarification", "boundary"}:
        raise AcceptanceGuardError("unknown review kind")
    if not isinstance(packet, Mapping) or not isinstance(submission, Mapping):
        raise AcceptanceGuardError("review packet and submission must be objects")
    if submission.get("packet_sha256") != digest(packet):
        raise AcceptanceGuardError("review submission is not bound to this packet")
    checklist = packet.get("checklist")
    if not isinstance(checklist, list) or not checklist:
        raise AcceptanceGuardError("frozen checklist is required")
    specs = []
    for row in checklist:
        if not isinstance(row, Mapping) or not isinstance(row.get("id"), str) or not row["id"].strip():
            raise AcceptanceGuardError("invalid checklist item")
        specs.append(dict(row))
    ids = [row["id"] for row in specs]
    if len(set(ids)) != len(ids):
        raise AcceptanceGuardError("duplicate checklist item")
    overall = submission.get("overall")
    if (not isinstance(overall, Mapping) or overall.get("status") not in {"pass", "fail"}
            or not isinstance(overall.get("reason"), str) or not overall["reason"].strip()):
        raise AcceptanceGuardError("overall review status and reason are required")
    entries = submission.get("items")
    if not isinstance(entries, list) or len(entries) != len(ids):
        raise AcceptanceGuardError("one review decision is required for every checklist item")
    by_id = {row.get("id"): row for row in entries if isinstance(row, Mapping)}
    if set(by_id) != set(ids) or len(by_id) != len(ids):
        raise AcceptanceGuardError("review items do not match the frozen checklist")

    item_failures: list[str] = []
    item_records = []
    for spec in specs:
        row = by_id[spec["id"]]
        status = row.get("status")
        reason = row.get("reason")
        if status not in {"pass", "supported", "covered", "fail", "missing", "contradicted", "unverifiable"}:
            raise AcceptanceGuardError("unknown per-item review status")
        if not isinstance(reason, str) or not reason.strip():
            raise AcceptanceGuardError("per-item reason is required")
        passing = status in {"pass", "supported", "covered"}
        kind = spec.get("kind", "fact")
        if stage == "answer" and passing and kind in {"number", "policy", "citation"}:
            witnesses = row.get("witnesses")
            if not isinstance(witnesses, list) or not witnesses:
                raise AcceptanceGuardError("numeric/policy items require witnesses")
            for witness in witnesses:
                if not isinstance(witness, Mapping):
                    raise AcceptanceGuardError("invalid review witness")
                if kind in {"policy", "citation"} and (
                        not isinstance(witness.get("citation_id"), str)
                        or not isinstance(witness.get("evidence_excerpt"), str)
                        or not witness["evidence_excerpt"].strip()):
                    raise AcceptanceGuardError("policy witness requires citation and excerpt")
                if kind in {"policy", "citation"}:
                    artifact = packet.get("result", {})
                    claims = artifact.get("policy", {}).get("generation", {}).get("claims", [])
                    hits = artifact.get("policy_evidence", {}).get("hits", [])
                    index = witness.get("claim_index")
                    if type(index) is not int or not 0 <= index < len(claims):
                        raise AcceptanceGuardError("policy witness needs an actual claim")
                    claim = claims[index]
                    hit = next((h for h in hits if h.get("id") == witness["citation_id"]), None)
                    if (hit is None or witness["citation_id"] not in claim.get("citations", [])
                            or witness.get("claim_text") != claim.get("text")
                            or witness["evidence_excerpt"] not in hit.get("text", "")):
                        raise AcceptanceGuardError("policy witness differs from the actual evidence")
            if kind == "number":
                checks = spec.get("checks")
                if not isinstance(checks, list) or not checks or row.get("checks") != checks:
                    raise AcceptanceGuardError("all frozen numeric checks must be recorded")
                for check in checks:
                    try:
                        actual_value = at(packet["result"], check["path"])
                        expected_value = check["expected"]
                    except (ValueError, KeyError, TypeError) as exc:
                        raise AcceptanceGuardError("invalid numeric evidence path") from exc
                    if type(actual_value) is not type(expected_value) or actual_value != expected_value:
                        raise AcceptanceGuardError("number differs from frozen reference")
        if not passing:
            item_failures.append(spec["id"])
        item_records.append({
            "id": spec["id"],
            "status": status,
            "reason": reason,
            "witnesses": deepcopy(row.get("witnesses", [])),
        })

    if stage == "plan":
        preview = packet.get("preview")
        preview = preview if isinstance(preview, Mapping) else {}
        actual = _actual_tasks(preview)
        hard: list[str] = []
        categories = _collect_diagnostic_categories(preview)
        hard.extend(f"diagnostic:{category}" for category in sorted(categories)
                    if category in HARD_FAILURE_CATEGORIES)
        status = preview.get("status")
        if status in FAILURE_STATUSES:
            hard.append(f"status:{status}")
        if expected_tasks is not None and actual is None:
            hard.append("tasks:missing")
        elif expected_tasks is not None and sorted(actual or []) != sorted(set(expected_tasks)):
            hard.append("tasks:mismatch")
        if expected_kind == "support":
            if status != "needs_confirmation":
                hard.append("preview:not_confirmable")
            if preview.get("executed") is True or preview.get("confirmation_token") in {None, ""}:
                hard.append("preview:missing_confirmation_boundary")
        else:
            if status not in NON_EXECUTABLE_TERMINAL_STATUSES:
                hard.append("preview:not_clarification_or_boundary")
            if status in EXECUTABLE_STATUSES or preview.get("executed") is True:
                hard.append("preview:unsafe_execution")
        unique_hard = list(dict.fromkeys(hard))
        terminal = {
            "version": "plan-guard-0114",
            "approved": bool(overall["status"] == "pass" and not unique_hard),
            "reviewer_approved": overall["status"] == "pass",
            "hard_failures": unique_hard,
            "reviewer_cannot_override": bool(overall["status"] == "pass" and unique_hard),
            "expected_kind": expected_kind,
            "observed_status": status,
            "actual_tasks": actual,
        }
    else:
        terminal = validate_terminal(
            preview=packet.get("preview"), result=packet.get("result"),
            delivery=packet.get("delivery"), review={"approved": overall["status"] == "pass"},
            expected_kind=expected_kind, expected_tasks=expected_tasks,
        )
    approved = bool(overall["status"] == "pass" and not item_failures and terminal["approved"])
    return {
        "version": "structured-review-0114" if stage == "plan" else "structured-review-0112",
        "stage": stage,
        "reviewer": reviewer,
        "packet_sha256": digest(packet),
        "approved": approved,
        "overall": {"status": overall["status"], "reason": overall["reason"]},
        "items": item_records,
        "item_failures": item_failures,
        "terminal": terminal,
        "semantic_coverage_verified": False,
    }


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _secret_safe(value: Any, secret: str = "") -> Any:
    """Return JSON data with a provider credential removed from every field."""

    raw = json.dumps(value, ensure_ascii=False)
    if secret:
        raw = raw.replace(secret, "[REDACTED]")
    return json.loads(raw)


def persist_artifact(
    output: str | Path,
    name: str,
    value: Any,
    *,
    secret: str = "",
) -> dict[str, Any]:
    """Persist a redacted JSON artifact and return its content fingerprint.

    Artifact names are relative to ``output`` and cannot escape it.  The hash
    is calculated from the exact redacted bytes written to disk, so a later
    review can bind itself to what was actually saved rather than to an
    in-memory object.
    """

    relative = Path(name)
    if (relative.is_absolute() or relative == Path(".")
            or ".." in relative.parts or not str(relative)):
        raise AcceptanceGuardError("artifact path must stay inside the batch")
    safe = _secret_safe(value, secret)
    path = Path(output) / relative
    root = Path(output).resolve()
    if not path.resolve().is_relative_to(root):
        raise AcceptanceGuardError("artifact symlink escapes batch")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as file:
        file.write(json.dumps(safe, ensure_ascii=False, indent=2) + '\n')
    data = path.read_bytes()
    return {
        "path": str(relative),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }


class ProspectiveCallLedger:
    """Durable, at-most-once ledger for a future 24-question batch."""

    def __init__(
        self,
        question_ids: Iterable[str],
        output: str | Path,
        *,
        frozen_snapshot: Mapping[str, Any],
        stage_budgets: Mapping[str, int] | None = None,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        verify_snapshot_fn: Callable[[Mapping[str, Any]], None] = verify_dependencies,
    ) -> None:
        ids = list(question_ids)
        if not ids or any(not isinstance(item, str) or not item.strip() for item in ids):
            raise AcceptanceGuardError("question IDs must be non-empty")
        if len(set(ids)) != len(ids):
            raise AcceptanceGuardError("question IDs must be unique")
        if type(token_budget) is not int or token_budget <= 0:
            raise AcceptanceGuardError("positive token budget required")
        budgets = dict(DEFAULT_STAGE_BUDGETS)
        if stage_budgets is not None:
            budgets.update(stage_budgets)
        if set(budgets) != set(STAGES) or any(type(value) is not int or value < 0 for value in budgets.values()):
            raise AcceptanceGuardError("invalid stage budgets")
        self.question_ids = tuple(ids)
        self.output = Path(output)
        if self.output.exists():
            raise AcceptanceGuardError("prospective batches cannot be resumed or overwritten")
        self.output.mkdir(parents=True, exist_ok=False)
        self.ledger_path = self.output / "ledger.json"
        self.snapshot = deepcopy(dict(frozen_snapshot))
        self.verify_snapshot_fn = verify_snapshot_fn
        self.verify_snapshot_fn(self.snapshot)
        self.stage_budgets = budgets
        self.token_budget = token_budget
        self._active: dict[str, Any] | None = None
        self._started = {}
        self.state: dict[str, Any] = {
            "version": "prospective-call-ledger-0112",
            "status": "running",
            "question_ids": list(ids),
            "questions": [{"id": item, "status": "not_run", "stages": []} for item in ids],
            "calls": [],
            "artifacts": {},
            "stage_budgets": deepcopy(budgets),
            "reported_tokens": 0,
            "token_budget": token_budget,
            "usage_status": "none",
            "stop_reason": None,
            "controls": {},
            "reviews": {},
            "frozen_snapshot_sha256": self.snapshot.get("snapshot_sha256"),
            "automatic_retry": False,
            "resume_supported": False,
        }
        self._save()

    def _save(self) -> None:
        _atomic_json(self.ledger_path, self.state)
        self._ledger_sha256 = hashlib.sha256(self.ledger_path.read_bytes()).hexdigest()

    def _assert_running(self) -> None:
        if self.state.get("status") != "running":
            raise AcceptanceStopped(str(self.state.get("stop_reason") or "ledger_stopped"))
        try:
            self.verify_snapshot_fn(self.snapshot)
            if (not self.ledger_path.is_file()
                    or hashlib.sha256(self.ledger_path.read_bytes()).hexdigest() != self._ledger_sha256):
                raise FrozenInputChanged("ledger changed")
            for artifact in self.state['artifacts'].values():
                path = self.output / artifact['path']
                if (not path.is_file()
                        or hashlib.sha256(path.read_bytes()).hexdigest() != artifact['sha256']):
                    raise FrozenInputChanged("saved response or review changed")
        except FrozenInputChanged:
            # A changed dependency is itself a terminal batch event.  Persist
            # the stop before re-raising so a caller cannot mistake the failed
            # pre-call check for an unattempted, retryable call.
            self.state["status"] = "stopped"
            self.state["stop_reason"] = "frozen_inputs_changed"
            self._save()
            raise
        if self._active is not None:
            raise AcceptanceStopped("previous_call_not_completed; retry/resume is disabled")

    def _stage_count(self, stage: str) -> int:
        return sum(1 for row in self.state["calls"] if row.get("stage") == stage)

    def _question(self, question_id: str) -> dict[str, Any]:
        for row in self.state["questions"]:
            if row["id"] == question_id:
                return row
        raise AcceptanceGuardError("question is not in the frozen set")

    def stop(self, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise AcceptanceGuardError("stop reason is required")
        if self.state.get("status") == "running":
            self.state["status"] = "stopped"
            self.state["stop_reason"] = reason
            self._save()

    def reserve(self, question_id: str, stage: str) -> dict[str, Any]:
        """Persist an attempted call before entering provider code."""

        self._assert_running()
        if stage not in STAGES:
            raise AcceptanceGuardError("unknown call stage")
        question = self._question(question_id)
        if any(row.get("question_id") == question_id and row.get("stage") == stage
               for row in self.state["calls"]):
            raise AcceptanceStopped("duplicate stage call; retry is disabled")
        if self._stage_count(stage) >= self.stage_budgets[stage]:
            self.stop(f"budget_exceeded:{stage}")
            raise AcceptanceStopped(f"budget_exceeded:{stage}")
        if self.state["reported_tokens"] >= self.token_budget:
            self.stop("reported_token_budget_reached")
            raise AcceptanceStopped("reported_token_budget_reached")
        call_id = uuid.uuid4().hex
        record = {
            "call_id": call_id,
            "question_id": question_id,
            "stage": stage,
            "status": "reserved",
            "reserved_at_utc": _utc_now(),
            "total_tokens": None,
            "usage_status": "unknown",
        }
        self.state["calls"].append(record)
        question["status"] = "in_progress"
        question["current_call_id"] = call_id
        self._active = record
        self._started[call_id] = time.monotonic()
        self._save()
        return deepcopy(record)

    def _active_record(self, reservation: Mapping[str, Any]) -> dict[str, Any]:
        if self._active is None or reservation.get("call_id") != self._active.get("call_id"):
            raise AcceptanceStopped("unknown or already completed call reservation")
        record = self.state["calls"][-1]
        if record.get("call_id") != reservation.get("call_id"):
            raise AcceptanceStopped("call reservation is not the latest durable record")
        return record

    def complete(
        self,
        reservation: Mapping[str, Any],
        *,
        metadata: Mapping[str, Any] | None,
        response_status: str = "returned",
        raw_response: Any | None = None,
        secret: str = "",
    ) -> dict[str, Any]:
        """Persist provider metadata and stop on unknown or excessive usage."""

        record = self._active_record(reservation)
        safe = _safe_metadata(metadata)
        tokens = total_tokens(safe)
        if raw_response is not None:
            artifact_name = (
                f"responses/{record['question_id']}-{record['stage']}.json"
            )
            artifact = persist_artifact(self.output, artifact_name, raw_response, secret=secret)
            self.state["artifacts"][artifact_name] = artifact
            record["raw_response"] = artifact
        record.update({
            "status": response_status if response_status in {"returned", "completed"} else response_status,
            "completed_at_utc": _utc_now(),
            "duration_seconds": round(time.monotonic() - self._started.pop(record["call_id"], time.monotonic()), 3),
            "metadata": safe,
            "total_tokens": tokens,
            "usage_status": "reported" if tokens is not None else "unknown",
        })
        question = self._question(record["question_id"])
        # Returning a plan is not completion of a question or semantic review.
        question["status"] = "awaiting_review" if tokens is not None else "stopped"
        question['stages'].append(record['stage'])
        question.pop("current_call_id", None)
        self._active = None
        if tokens is None:
            self.state["usage_status"] = "unknown"
            self.state["status"] = "stopped"
            self.state["stop_reason"] = "unknown_usage"
        else:
            self.state["reported_tokens"] += tokens
            self.state["usage_status"] = "reported"
            if self.state["reported_tokens"] >= self.token_budget:
                self.state["status"] = "stopped"
                self.state["stop_reason"] = "reported_token_budget_reached"
        if response_status not in {'returned', 'completed'} or safe.get('finish_reason') != 'stop':
            record['status'] = 'failed'
            record['diagnostic'] = {'category': 'structure'}
            question['status'] = 'stopped'
            self.state['status'] = 'stopped'
            self.state['stop_reason'] = 'call_failed:structure'
        self._save()
        return deepcopy(record)

    def fail(
        self,
        reservation: Mapping[str, Any],
        *,
        category: str,
    ) -> dict[str, Any]:
        """Persist a failure and stop; no provider retry is allowed."""

        record = self._active_record(reservation)
        safe_category = category if category in HARD_FAILURE_CATEGORIES else "provider_failure"
        record.update({
            "status": "failed",
            "completed_at_utc": _utc_now(),
            "duration_seconds": round(time.monotonic() - self._started.pop(record["call_id"], time.monotonic()), 3),
            "diagnostic": {"category": safe_category},
        })
        question = self._question(record["question_id"])
        question["status"] = "stopped"
        question.pop("current_call_id", None)
        self._active = None
        self.state["status"] = "stopped"
        self.state["stop_reason"] = f"call_failed:{safe_category}"
        self.state['usage_status'] = 'unknown'
        self._save()
        return deepcopy(record)

    def record_review(
        self,
        question_id: str,
        stage: str,
        submission: Mapping[str, Any],
        *,
        packet: Mapping[str, Any] | None = None,
        validation: Mapping[str, Any] | None = None,
        secret: str = "",
    ) -> dict[str, Any]:
        """Save a redacted review submission and optional packet by hash.

        This method does not approve a review.  The structured validator must
        still be called by the runner; this method only preserves exactly what
        was submitted for later audit.
        """

        self._assert_running()
        self._question(question_id)
        if stage not in STAGES:
            raise AcceptanceGuardError("unknown review stage")
        if not isinstance(submission, Mapping):
            raise AcceptanceGuardError("review submission must be an object")
        if validation is not None:
            if not isinstance(validation, Mapping) or not isinstance(packet, Mapping):
                raise AcceptanceGuardError("validated review requires its packet")
            recomputed = validate_structured_review(
                packet, submission, reviewer=validation.get("reviewer"),
                expected_kind=packet.get("expected_kind", "support"),
                expected_tasks=packet.get("expected_tasks"),
                stage="plan" if stage == "planning" else "answer",
            )
            # Caller-supplied flags are not proof. An additional checklist can
            # reject a structural pass, but cannot turn a rejection into a pass.
            for key, value in recomputed.items():
                if key == "approved":
                    if type(validation.get(key)) is not bool or (validation[key] and not value):
                        raise AcceptanceGuardError("review approval differs from validation")
                elif validation.get(key) != value:
                    raise AcceptanceGuardError("review decision differs from validation")
        prefix = f"reviews/{question_id}-{stage}"
        review_key = f"{question_id}:{stage}"
        if review_key in self.state["reviews"]:
            raise AcceptanceGuardError("duplicate review stage")
        submission_name = prefix + "-submission.json"
        submission_artifact = persist_artifact(
            self.output, submission_name, submission, secret=secret
        )
        artifacts = {submission_name: submission_artifact}
        if packet is not None:
            packet_name = prefix + "-packet.json"
            artifacts[packet_name] = persist_artifact(
                self.output, packet_name, packet, secret=secret
            )
        validation_artifact = None
        if validation is not None:
            if not isinstance(validation, Mapping):
                raise AcceptanceGuardError("review validation must be an object")
            validation_name = prefix + "-decision.json"
            validation_artifact = persist_artifact(
                self.output, validation_name, validation, secret=secret
            )
            artifacts[validation_name] = validation_artifact
        self.state["artifacts"].update(artifacts)
        self.state["reviews"][review_key] = {
            "question_id": question_id,
            "stage": stage,
            "approved": (bool(validation.get("approved"))
                          if isinstance(validation, Mapping) else None),
            "packet_sha256": digest(packet) if packet is not None else None,
            "submission_artifact": submission_artifact,
            "packet_artifact": artifacts.get(prefix + "-packet.json"),
            "validation_artifact": validation_artifact,
        }
        self._save()
        return deepcopy(artifacts)

    def record_artifact(
        self,
        name: str,
        value: Any,
        *,
        secret: str = "",
    ) -> dict[str, Any]:
        """Persist a runner-owned artifact and bind its hash to the ledger.

        This is used for deterministic controls and summaries that are not a
        provider response.  It still goes through the same path and hash
        checks as model output, so a later edit cannot silently turn a failed
        control into a passing one.
        """

        if self.state.get("status") == "running":
            self._assert_running()
        else:
            # A terminal failure still needs a final diagnostic artifact.  It
            # may be appended only after the same frozen-input and hash checks
            # used before a provider call; it can never reopen the ledger.
            try:
                self.verify_snapshot_fn(self.snapshot)
                if (not self.ledger_path.is_file()
                        or hashlib.sha256(self.ledger_path.read_bytes()).hexdigest() != self._ledger_sha256):
                    raise FrozenInputChanged("ledger changed")
                for item in self.state["artifacts"].values():
                    path = self.output / item["path"]
                    if (not path.is_file()
                            or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]):
                        raise FrozenInputChanged("saved response or review changed")
            except FrozenInputChanged:
                self.state["status"] = "stopped"
                self.state["stop_reason"] = "frozen_inputs_changed"
                self._save()
                raise
            if self._active is not None:
                raise AcceptanceStopped("active call must be completed first")
        artifact = persist_artifact(self.output, name, value, secret=secret)
        self.state["artifacts"][name] = artifact
        self._save()
        return deepcopy(artifact)

    def record_control(
        self,
        control_id: str,
        payload: Mapping[str, Any],
        *,
        artifact_name: str | None = None,
        secret: str = "",
    ) -> dict[str, Any]:
        """Record one synthetic A/B control without changing the denominator."""

        if not isinstance(control_id, str) or not control_id.strip():
            raise AcceptanceGuardError("control ID is required")
        if not isinstance(payload, Mapping):
            raise AcceptanceGuardError("control payload must be an object")
        requested_status = payload.get("status", "recorded")
        if requested_status == "validated":
            control_kind = payload.get("control")
            if control_kind == "A":
                checks = payload.get("checks")
                if (payload.get("method") != "independent_csv_recomputation"
                        or not isinstance(payload.get("source"), Mapping)
                        or not isinstance(payload.get("actual"), Mapping)
                        or not isinstance(payload.get("independent"), Mapping)
                        or not isinstance(checks, Mapping)
                        or type(checks.get("passed")) is not bool):
                    raise AcceptanceGuardError("control A validation record is incomplete")
            elif control_kind == "B":
                if (payload.get("method") != "same_question_without_retrieved_evidence"
                        or not isinstance(payload.get("response"), Mapping)
                        or type(payload.get("fact_recall")) not in {float, int, type(None)}):
                    raise AcceptanceGuardError("control B validation record is incomplete")
            else:
                raise AcceptanceGuardError("validated control kind is unknown")
        name = artifact_name or f"controls/{control_id}.json"
        artifact = self.record_artifact(name, payload, secret=secret)
        self.state["controls"][control_id] = {
            "status": str(requested_status),
            "question_id": payload.get("question_id"),
            "artifact": artifact,
        }
        self._save()
        return deepcopy(self.state["controls"][control_id])

    def mark_question_status(
        self,
        question_id: str,
        status: str,
        *,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Move a reviewed row to an explicit terminal status."""

        if status not in {"accepted", "accepted_terminal", "stopped"}:
            raise AcceptanceGuardError("invalid terminal question status")
        self._assert_running()
        question = self._question(question_id)
        if question.get("current_call_id") or self._active is not None:
            raise AcceptanceStopped("active call must be completed first")
        question["status"] = status
        # A caller may leave a visible status label for diagnostics, but the
        # label itself is deliberately not an acceptance proof.  Only
        # ``approve_question`` creates a binding that finalization accepts.
        if status in {"accepted", "accepted_terminal"}:
            question.pop("acceptance_binding", None)
        if reason is not None:
            if not isinstance(reason, str) or not reason.strip():
                raise AcceptanceGuardError("status reason must be non-empty")
            question["terminal_reason"] = reason
        question["terminal_at_utc"] = _utc_now()
        self._save()
        return deepcopy(question)

    def approve_question(
        self,
        question_id: str,
        *,
        expected_kind: str,
        answer_stage: str | None = None,
        delivery_artifact_name: str | None = None,
        required_controls: Iterable[str] = (),
        reason: str = "reviewed_execution",
    ) -> dict[str, Any]:
        """Bind a question to validated reviews, delivery, and controls.

        This is the only ledger-owned path that turns a visible ``accepted``
        label into an acceptance proof.  Direct status labels remain useful in
        old diagnostic tests, but ``finalize_reviewed`` rejects them because
        they have no binding object.
        """

        if expected_kind not in {"support", "clarification", "boundary"}:
            raise AcceptanceGuardError("unknown acceptance kind")
        self._assert_running()
        if self._active is not None:
            raise AcceptanceStopped("active call must be completed first")
        question = self._question(question_id)
        plan_key = f"{question_id}:planning"
        plan = self.state["reviews"].get(plan_key)
        if not isinstance(plan, Mapping) or plan.get("approved") is not True:
            raise AcceptanceGuardError("accepted question requires an approved planning review")
        if not any(call.get("question_id") == question_id
                   and call.get("stage") == "planning"
                   and call.get("status") in {"returned", "completed"}
                   and call.get("raw_response")
                   for call in self.state["calls"]):
            raise AcceptanceGuardError("accepted question requires an actual planning response")
        plan_packet = json.loads((self.output / plan["packet_artifact"]["path"]).read_text())
        if plan_packet.get("expected_kind") != expected_kind:
            raise AcceptanceGuardError("acceptance kind differs from reviewed plan")
        if expected_kind == "support":
            if answer_stage != "policy_with_evidence":
                raise AcceptanceGuardError("support acceptance requires an answer review stage")
            answer_key = f"{question_id}:{answer_stage}"
            answer = self.state["reviews"].get(answer_key)
            if not isinstance(answer, Mapping) or answer.get("approved") is not True:
                raise AcceptanceGuardError("support acceptance requires an approved answer review")
            if not isinstance(delivery_artifact_name, str) or delivery_artifact_name not in self.state["artifacts"]:
                raise AcceptanceGuardError("support acceptance requires a saved delivery inspection")
            delivery_artifact = self.state["artifacts"][delivery_artifact_name]
            delivery_path = self.output / delivery_artifact["path"]
            try:
                delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError) as exc:
                raise AcceptanceGuardError("delivery inspection is unreadable") from exc
            if not isinstance(delivery, Mapping) or delivery.get("verified") is not True:
                raise AcceptanceGuardError("delivery inspection is not verified")
        else:
            if answer_stage is not None or delivery_artifact_name is not None:
                raise AcceptanceGuardError("non-support acceptance cannot bind an answer delivery")
            delivery_artifact = None

        control_ids = list(required_controls)
        if expected_kind == "support" and not control_ids:
            raise AcceptanceGuardError("support acceptance requires at least one validated control")
        if any(not isinstance(item, str) or not item.strip() for item in control_ids):
            raise AcceptanceGuardError("control IDs must be non-empty")
        control_refs = {}
        for control_id in control_ids:
            control = self.state["controls"].get(control_id)
            if not isinstance(control, Mapping) or control.get("status") != "validated":
                raise AcceptanceGuardError(f"validated control is missing: {control_id}")
            if control.get("question_id") not in {None, question_id}:
                raise AcceptanceGuardError(f"control is bound to another question: {control_id}")
            control_refs[control_id] = deepcopy(control)

        binding = {
            "version": "acceptance-binding-0116",
            "question_id": question_id,
            "expected_kind": expected_kind,
            "plan_review": deepcopy(plan),
            "answer_review": (deepcopy(self.state["reviews"].get(f"{question_id}:{answer_stage}"))
                              if answer_stage else None),
            "delivery_artifact": deepcopy(delivery_artifact),
            "controls": control_refs,
            "reason": reason,
        }
        binding["binding_sha256"] = digest(binding)
        question["status"] = "accepted" if expected_kind == "support" else "accepted_terminal"
        question["acceptance_binding"] = binding
        question["terminal_reason"] = reason
        question["terminal_at_utc"] = _utc_now()
        self._save()
        return deepcopy(question)

    def finalize_reviewed(
        self,
        *,
        required_controls: Iterable[str] = (),
    ) -> dict[str, Any]:
        """Close only when every row has a ledger-owned acceptance binding."""

        self._assert_running()
        if self._active is not None:
            raise AcceptanceStopped("active call must be completed first")
        required = list(required_controls)
        if any(not isinstance(item, str) or not item.strip() for item in required):
            raise AcceptanceGuardError("control IDs must be non-empty")
        for control_id in required:
            control = self.state["controls"].get(control_id)
            if not isinstance(control, Mapping) or control.get("status") != "validated":
                raise AcceptanceGuardError(f"validated control is missing: {control_id}")
        for question in self.state["questions"]:
            if question.get("status") not in {"accepted", "accepted_terminal"}:
                raise AcceptanceGuardError("every question must have an acceptance binding")
            binding = question.get("acceptance_binding")
            if not isinstance(binding, Mapping) or binding.get("question_id") != question.get("id"):
                raise AcceptanceGuardError("question status is not bound to reviewed execution")
            body = {key: deepcopy(value) for key, value in binding.items() if key != "binding_sha256"}
            if binding.get("binding_sha256") != digest(body):
                raise FrozenInputChanged("acceptance binding changed")
        self.state["status"] = "completed"
        self.state["completed_at_utc"] = _utc_now()
        self._save()
        return self.summary()

    def finalize(self) -> dict[str, Any]:
        """Close only when every fixed question row has reached a terminal row."""

        if self._active is not None:
            raise AcceptanceStopped("active call must be completed first")
        if self.state.get("status") == "running":
            # Online integration must bind actual execution, per-stage reviews,
            # and both controls before a batch can ever be accepted.
            raise AcceptanceGuardError("acceptance finalization requires reviewed runner integration")
        return self.summary()

    def summary(self) -> dict[str, Any]:
        counts = {}
        for row in self.state["questions"]:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        return {
            "version": self.state["version"],
            "status": self.state["status"],
            "question_count": len(self.question_ids),
            "question_status_counts": dict(sorted(counts.items())),
            "not_run": [row["id"] for row in self.state["questions"] if row["status"] == "not_run"],
            "call_count": len(self.state["calls"]),
            "stage_counts": {stage: self._stage_count(stage) for stage in STAGES},
            "reported_tokens": self.state["reported_tokens"],
            "usage_status": self.state["usage_status"],
            "stop_reason": self.state["stop_reason"],
            "automatic_retry": False,
            "resume_supported": False,
            "controls": deepcopy(self.state.get("controls", {})),
            "reviews": deepcopy(self.state.get("reviews", {})),
        }


__all__ = [
    "AcceptanceGuardError",
    "AcceptanceStopped",
    "DEFAULT_STAGE_BUDGETS",
    "DEFAULT_TOKEN_BUDGET",
    "FAILURE_STATUSES",
    "FrozenInputChanged",
    "HARD_FAILURE_CATEGORIES",
    "FACT_REVIEW_STATUSES",
    "CLAIM_REVIEW_STATUSES",
    "NON_EXECUTABLE_TERMINAL_STATUSES",
    "ProspectiveCallLedger",
    "ReferenceLeakage",
    "STAGES",
    "assert_no_reference_leakage",
    "digest",
    "freeze_dependencies",
    "persist_artifact",
    "total_tokens",
    "validate_structured_review",
    "validate_fact_review",
    "validate_terminal",
    "verify_dependencies",
]
