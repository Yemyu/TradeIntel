"""Offline end-to-end runner for the 0114 prospective acceptance protocol.

This module is deliberately a *synthetic* runner.  It exercises the same
product workflow boundary, the durable at-most-once ledger, review packets,
delivery verification using caller-supplied test doubles, and the two 0116
controls. Control A independently recomputes trade values from the source
table; control B records the actual answer to the same policy question without
retrieved evidence. There is no default API client, but injected callables are
trusted test code, not a network sandbox.

The runner is not a semantic benchmark.  Its purpose is narrower and more
important at this stage: demonstrate that a model response, a reviewed plan,
an actually verified delivery, and a completed acceptance batch are four
different states that cannot be silently collapsed into one another.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, asdict
from decimal import Decimal
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .agent import ModelResponse, _normalise_response
from .prospective_acceptance import (
    AcceptanceGuardError,
    AcceptanceStopped,
    ProspectiveCallLedger,
    assert_no_reference_leakage,
    compare_trade_scope,
    digest,
    freeze_dependencies,
    requirement_names,
    runtime_environment,
    validate_fact_review,
    validate_policy_pair,
    validate_structured_review,
)
from .unified_research import build_product_workflow, inspect_delivery
from .structured_workflow import execute_request
from .research_brief import summary_with_comparison
from .evidence_v21 import EvidenceRegistryV21
from .answer_checklist import (
    at,
    digest as checklist_digest,
    validate_review as validate_legacy_checklist_review,
)
from .policy_workflow import safe_metadata
from .request_capture import complete_with_capture
from .policy_facts import REFERENCE_RELATIVE, load_frozen_policy_reference, reference_evidence


MODEL_STAGES = ("planning", "policy_with_evidence", "policy_no_evidence")


@dataclass(frozen=True)
class SyntheticCase:
    """One fixed denominator row for the synthetic batch."""

    id: str
    question: str
    expected_kind: str
    expected_tasks: tuple[str, ...]
    checklist: tuple[Mapping[str, Any], ...]
    reference: Mapping[str, Any]
    run_controls: bool = False
    control_facts: tuple[str, ...] = ()
    # These are host-owned evaluation inputs. They are deliberately separate
    # from ``reference`` and are never passed to the model factory.
    independent_request: Mapping[str, Any] | None = None
    facts: tuple[Mapping[str, Any], ...] = ()
    # Strict policy cases carry an independent, host-owned question/cutoff and
    # source facts.  Legacy synthetic fixtures may leave this unset.
    policy_reference: Mapping[str, Any] | None = None
    # A case may opt into the existing host separator-gap gate.  It is kept
    # off for historical fixtures so they retain their old compatibility
    # contract; strict cases must supply a separate human gap reviewer.
    allow_host_gap_review: bool = False


@dataclass(frozen=True)
class ModelInput:
    """Public factory input: no gold answers, expected tasks or checklist."""
    id: str
    question: str


POLICY_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["claims"],
    "properties": {
        "answer": {"type": "string"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["text", "citations"],
                "properties": {
                    "text": {"type": "string"},
                    "citations": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
        },
    },
}


def default_cases() -> tuple[SyntheticCase, ...]:
    """Return small, deterministic cases covering support and clarification."""

    policy_reference = load_frozen_policy_reference(_project_root())
    policy_facts = tuple(policy_reference["facts"])

    return (
        SyntheticCase(
            id="SYN-TRADE-01",
            question=("查询其他原产地整体2018-09和2018-10的美元消费进口额；"
                      "比较2018-10相对于2018-09；只做描述性比较，不做因果分析；"
                      "第一批关税，政策整体范围。"),
            expected_kind="support",
            expected_tasks=("trade",),
            checklist=({"id": "scope", "kind": "fact"},),
            reference={"gold_marker": "trade-gold-only-2018-window"},
            run_controls=True,
            independent_request={
                "trade": {
                    "policy_id": "us_301_list1_2018", "operation": "read",
                    "metric": "import_value_consumption_usd", "origin": "other_origins",
                    "granularity": "policy_aggregate",
                    "months": ["2018-09", "2018-10"], "hs6": None,
                    "causal_effect": False,
                },
                "comparison": {"kind": "endpoint", "reference_month": "2018-09",
                                "current_month": "2018-10"},
            },
        ),
        SyntheticCase(
            id="SYN-CLARIFY-01",
            question="我想分析关税影响，但没有说明商品、月份和金额口径。",
            expected_kind="clarification",
            expected_tasks=(),
            checklist=({"id": "clarification", "kind": "fact"},),
            reference={"gold_marker": "clarification-gold-only-scope"},
        ),
        SyntheticCase(
            id="SYN-POLICY-01",
            question="第一批关税何时生效，额外税率是多少？政策资料截止日是2018-07-06。",
            expected_kind="support",
            expected_tasks=("policy",),
            checklist=({"id": "policy_claim", "kind": "policy"},),
            reference={"gold_marker": "policy-gold-only-not-in-messages"},
            run_controls=True,
            control_facts=tuple(fact["expected_value"] for fact in policy_facts),
            facts=policy_facts,
            policy_reference=policy_reference,
        ),
    )


def _response_payload(response: ModelResponse, *, messages: Sequence[Mapping[str, Any]] | None = None,
                      tools: Sequence[Mapping[str, Any]] | None = None,
                      request_config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "text": response.text,
        "tool_calls": [
            {"call_id": call.call_id, "name": call.name, "arguments": call.arguments}
            for call in response.tool_calls
        ],
        "metadata": safe_metadata(response.metadata),
        "messages": deepcopy(list(messages or [])),
        "tools": deepcopy(list(tools or [])),
        # This is a provider-neutral boundary capture. A real adapter may add
        # its own HTTP payload fingerprint; the runner never stores API keys.
        "request_config": deepcopy(dict(request_config or {})),
    }


def _failure_category(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ConnectionError):
        return "connection"
    return "structure"


def _model_pair_settings(model: Any, *, question: str, as_of: str) -> dict[str, Any]:
    """Return the secret-free settings that must match across policy arms."""

    config = getattr(model, "config", None)
    effective = getattr(model, "effective_request_settings", None)
    declared = effective() if callable(effective) else {}
    if not isinstance(declared, Mapping):
        declared = {}
    model_name = declared.get("model") or getattr(config, "model", None) or type(model).__name__
    base_url = getattr(config, "base_url", None) or "fixture://provider"
    if not isinstance(base_url, str) or "@" in base_url:
        base_url = "[REDACTED_ENDPOINT]"
    temperature = declared.get("temperature", getattr(config, "temperature", 0.0))
    return {
        "question": question,
        "as_of": as_of,
        "base_url": base_url,
        "model": str(model_name),
        "temperature": temperature,
        "max_tokens": int(declared.get("max_tokens", 768)),
        "thinking": declared.get("thinking", {"type": "disabled"}),
        "stream": declared.get("stream", False),
        "timeout_seconds": float(getattr(config, "timeout_seconds", 60.0)),
        "response_schema_sha256": digest(POLICY_RESPONSE_SCHEMA),
    }


def _policy_pair_packet(case: SyntheticCase, preview: Mapping[str, Any],
                        with_model: Any, without_model: Any) -> dict[str, Any]:
    request = preview.get("request") if isinstance(preview.get("request"), Mapping) else {}
    policy_reference = case.policy_reference
    if isinstance(policy_reference, Mapping):
        policy_question = policy_reference.get("question")
        as_of = policy_reference.get("as_of")
        planned_question = request.get("policy_question")
        planned_as_of = request.get("policy_as_of")
        if planned_question != policy_question or planned_as_of != as_of:
            raise AcceptanceGuardError("policy_reference_scope_mismatch")
    else:
        # Compatibility path for historical synthetic fixtures.  The strict
        # default cases always carry the independent reference above.
        policy_question = request.get("policy_question") or preview.get("plan", {}).get("policy_question")
        as_of = request.get("policy_as_of") or preview.get("plan", {}).get("policy_as_of")
    if not isinstance(policy_question, str) or not isinstance(as_of, str):
        raise AcceptanceGuardError("policy pair needs a frozen question and cutoff")
    with_settings = _model_pair_settings(with_model, question=policy_question, as_of=as_of)
    without_settings = _model_pair_settings(without_model, question=policy_question, as_of=as_of)
    contract = validate_policy_pair(with_settings, without_settings)
    return {
        "version": "policy-pair-0118",
        "case_id": case.id,
        "question": policy_question,
        "as_of": as_of,
        "with_evidence": {"configuration": with_settings},
        "without_evidence": {"configuration": without_settings},
        "prompt_difference": "with_evidence receives retrieved policy evidence; without_evidence does not",
        "response_schema": deepcopy(POLICY_RESPONSE_SCHEMA),
        "policy_reference_sha256": (policy_reference.get("reference_sha256")
                                    if isinstance(policy_reference, Mapping) else None),
        "contract": contract,
        "actual_payloads_verified": False,
        "semantic_accuracy_measured": False,
    }


def _policy_claims_from_result(result: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    policy = result.get("policy") if isinstance(result, Mapping) else {}
    generation = policy.get("generation") if isinstance(policy, Mapping) else {}
    raw_claims = generation.get("claims", []) if isinstance(generation, Mapping) else []
    claims = [deepcopy(dict(item)) for item in raw_claims if isinstance(item, Mapping)]
    evidence = result.get("policy_evidence", {}) if isinstance(result, Mapping) else {}
    hits = evidence.get("hits", []) if isinstance(evidence, Mapping) else []
    evidence_by_id = {item.get("id"): deepcopy(dict(item)) for item in hits
                      if isinstance(item, Mapping) and isinstance(item.get("id"), str)}
    return claims, evidence_by_id


def _fact_review_packet(case: SyntheticCase, arm: str, *, answer: str,
                        claims: Sequence[Mapping[str, Any]],
                        evidence: Mapping[str, Any],
                        reference_sha256: str | None = None) -> dict[str, Any]:
    if arm not in {"with_evidence", "without_evidence"}:
        raise AcceptanceGuardError("unknown policy review arm")
    normalized_claims = []
    for claim in claims:
        normalized_claims.append({
            "text": claim.get("text", ""),
            "citations": list(claim.get("citations", []))
            if isinstance(claim.get("citations", []), list) else [],
        })
    return {
        "version": ("fact-review-packet-0119" if reference_sha256
                    else "fact-review-packet-0118"),
        "case_id": case.id,
        "arm": arm,
        "question": case.question,
        "policy_question": (case.policy_reference.get("question")
                             if isinstance(case.policy_reference, Mapping) else None),
        "policy_as_of": (case.policy_reference.get("as_of")
                          if isinstance(case.policy_reference, Mapping) else None),
        "answer": {"text": answer, "claims": normalized_claims},
        "facts": [deepcopy(dict(item)) for item in case.facts],
        "evidence": deepcopy(dict(evidence)),
        "reference_sha256": reference_sha256,
    }


def _independent_trade_baseline(case: SyntheticCase) -> dict[str, Any]:
    """Build the host-owned A baseline before the planner is called."""

    request = case.independent_request
    if not isinstance(request, Mapping):
        raise AcceptanceGuardError("independent trade request is required")
    request = deepcopy(dict(request))
    if not isinstance(request.get("trade"), Mapping) or not isinstance(request.get("comparison"), Mapping):
        raise AcceptanceGuardError("independent trade request is incomplete")
    # Self-validation catches an accidentally malformed fixture without using
    # the model-derived request as a repair source.
    compare_trade_scope(request, request)
    registry = EvidenceRegistryV21()
    execution_trade = deepcopy(dict(request["trade"]))
    comparison = request["comparison"]
    if execution_trade.get("months") is None:
        if not isinstance(comparison, Mapping) or comparison.get("kind") != "registered":
            raise AcceptanceGuardError("independent trade request needs explicit months")
        from .research_comparison import registered_windows
        windows = registered_windows(registry.repository)
        window = windows.get(comparison.get("comparison_id"))
        if not isinstance(window, Mapping):
            raise AcceptanceGuardError("independent registered window is missing")
        execution_trade["months"] = sorted(
            list(window.get("reference_months", [])) + list(window.get("current_months", []))
        )
    execution = execute_request({"task": "trade", "request": execution_trade}, registry)
    if execution.get("status") != "evidence_ready":
        raise AcceptanceGuardError("independent_trade_baseline_failed")
    data = next((row.get("data") for row in execution.get("tool_results", [])
                 if isinstance(row, Mapping) and row.get("tool_name") == "get_trade_series"), None)
    if not isinstance(data, Mapping):
        raise AcceptanceGuardError("independent trade result is missing")
    summary = summary_with_comparison(data, comparison, registry.repository)
    baseline_result = {"request": request, "summary": summary}
    recompute = _direct_trade_recompute(baseline_result)
    if recompute.get("checks", {}).get("passed") is not True:
        raise AcceptanceGuardError("baseline_recompute_failed")
    return {
        "version": "independent-trade-baseline-0118",
        "case_id": case.id,
        "question_sha256": digest(case.question),
        "request": request,
        "execution_request": {"trade": execution_trade, "comparison": comparison},
        "execution_status": execution.get("status"),
        "data": deepcopy(dict(data)),
        "source_hashes": deepcopy(execution.get("sources", {})),
        "independent_recompute": recompute,
        "reference_origin": "host_frozen_fixture_request_before_planning",
        "model_input_boundary": "not_sent_to_model",
    }


def _model_transport_settings(model: Any) -> dict[str, Any]:
    """Capture non-secret request settings at the provider-neutral seam."""

    config = getattr(model, "config", None)
    effective = getattr(model, "effective_request_settings", None)
    settings = effective() if callable(effective) else {}
    if not isinstance(settings, Mapping):
        settings = {}
    result = {
        "model": settings.get("model") or getattr(config, "model", type(model).__name__),
        "temperature": settings.get("temperature", getattr(config, "temperature", 0.0)),
        "max_tokens": settings.get("max_tokens", 768),
        "thinking": deepcopy(settings.get("thinking", {"type": "disabled"})),
        "stream": settings.get("stream", False),
        "base_url": getattr(config, "base_url", "fixture://provider"),
    }
    # Endpoint paths are not credentials, but the full URL can contain user
    # info. Keep the explicit marker only; pair equality uses the declared
    # config captured before the call.
    if not isinstance(result["base_url"], str) or "@" in result["base_url"]:
        result["base_url"] = "[REDACTED_ENDPOINT]"
    return result


class LedgerBoundModel:
    """Bind one provider-neutral model boundary to one ledger reservation."""

    def __init__(self, base: Any, ledger: ProspectiveCallLedger,
                 question_id: str, stage: str, reference: Mapping[str, Any]):
        if stage not in MODEL_STAGES:
            raise AcceptanceGuardError("unknown model stage")
        self.base = base
        self.ledger = ledger
        self.question_id = question_id
        self.stage = stage
        self.reference = deepcopy(dict(reference))
        # Preserve a fixture's configuration shape for the workflow manifest,
        # while never copying a credential into the ledger.
        self.config = getattr(base, "config", None)

    def complete(self, *, messages: Sequence[Mapping[str, Any]],
                 tools: Sequence[Mapping[str, Any]]) -> ModelResponse:
        assert_no_reference_leakage(messages, self.reference)
        reservation = self.ledger.reserve(self.question_id, self.stage)
        try:
            response = _normalise_response(
                complete_with_capture(self.base, messages=messages, tools=tools)
            )
            self.ledger.complete(
                reservation,
                metadata=response.metadata,
                raw_response=_response_payload(
                    response, messages=messages, tools=tools,
                    request_config=_model_transport_settings(self.base),
                ),
            )
            return response
        except (KeyboardInterrupt, Exception) as exc:
            # ``complete`` may already have closed the reservation while
            # rejecting an invalid finish reason.  In that case its durable
            # stop record is the authoritative one; do not write a second
            # failure or attempt a retry.
            if getattr(self.ledger, "_active", None) is not None:
                self.ledger.fail(reservation, category=_failure_category(exc))
            raise


def fixture_review(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Create a mechanical review for offline contract tests only.

    It is intentionally not a semantic judge.  Policy and numeric witnesses
    are copied from the *actual packet* so the structured validator can prove
    that a witness is bound to real evidence rather than an invented ID.
    """

    items = []
    result = packet.get("result") if isinstance(packet.get("result"), Mapping) else {}
    for spec in packet.get("checklist", []):
        spec = dict(spec)
        row: dict[str, Any] = {"id": spec["id"], "status": "pass", "reason": "fixture contract check"}
        kind = spec.get("kind", "fact")
        # Planning reviews check scope and boundaries only.  Witnesses are
        # required after execution, when the packet contains a result.
        if not isinstance(packet.get("result"), Mapping):
            items.append(row)
            continue
        if kind in {"policy", "citation"}:
            claims = result.get("policy", {}).get("generation", {}).get("claims", [])
            hits = result.get("policy_evidence", {}).get("hits", [])
            if not claims or not hits:
                row.update(status="fail", reason="no actual claim/evidence witness")
            else:
                claim = claims[0]
                citation_id = claim.get("citations", [None])[0]
                hit = next((item for item in hits if item.get("id") == citation_id), None)
                if not isinstance(hit, Mapping):
                    row.update(status="fail", reason="citation is not in the packet")
                else:
                    row["witnesses"] = [{
                        "claim_index": 0,
                        "claim_text": claim.get("text"),
                        "citation_id": citation_id,
                        "evidence_excerpt": hit.get("text", ""),
                    }]
        elif kind == "number":
            checks = spec.get("checks")
            if not isinstance(checks, list) or not checks:
                row.update(status="fail", reason="frozen numeric checks are absent")
            else:
                row["checks"] = deepcopy(checks)
                row["witnesses"] = [{"value": at(result, check["path"])} for check in checks]
        items.append(row)
    passed = all(item["status"] == "pass" for item in items)
    return {
        "packet_sha256": digest(packet),
        "overall": {"status": "pass" if passed else "fail",
                    "reason": "fixture review is not semantic acceptance"},
        "items": items,
    }


def _call_factory(factory: Callable[..., Any], stage: str, case: SyntheticCase) -> Any:
    """Call a two-argument fixture factory, with a small one-argument seam."""

    try:
        return factory(stage, ModelInput(case.id, case.question))
    except TypeError as exc:
        # Test seams from earlier smoke runners often accept only ``stage``.
        # Retry only when Python can prove the callable has one positional
        # parameter; provider errors inside a two-argument factory propagate.
        import inspect
        try:
            signature = inspect.signature(factory)
        except (TypeError, ValueError):
            raise exc
        positional = [p for p in signature.parameters.values()
                      if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        if len(positional) == 1:
            return factory(stage)
        raise


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _callable_descriptor(value: Any) -> dict[str, Any]:
    """Describe injected code without serializing its source or secrets."""

    import inspect

    if value is None:
        return {"kind": "none"}
    result: dict[str, Any] = {
        "kind": "callable",
        "module": getattr(value, "__module__", type(value).__module__),
        "qualname": getattr(value, "__qualname__", type(value).__qualname__),
    }
    try:
        source_path = inspect.getsourcefile(value) or inspect.getfile(value)
    except (OSError, TypeError):
        source_path = None
    if isinstance(source_path, str):
        path = Path(source_path).resolve()
        if path.is_file():
            result["source_path"] = str(path)
            result["source_sha256"] = _file_sha256(path)
    return result


def _validate_policy_case_reference(case: SyntheticCase) -> None:
    """Fail before planning if a strict policy case lost its independent facts."""

    reference = case.policy_reference
    if reference is None:
        return
    if not isinstance(reference, Mapping):
        raise AcceptanceGuardError("policy_reference must be an object")
    loaded = load_frozen_policy_reference(_project_root())
    if (reference.get("reference_sha256") != loaded.get("reference_sha256")
            or reference.get("corpus_sha256") != loaded.get("corpus_sha256")
            or reference.get("question") != loaded.get("question")
            or reference.get("as_of") != loaded.get("as_of")):
        raise AcceptanceGuardError("policy_reference_changed")
    if digest(reference.get("facts")) != digest(loaded.get("facts")):
        raise AcceptanceGuardError("policy_facts_changed")
    if not reference.get("source_catalog"):
        raise AcceptanceGuardError("policy_reference_sources_missing")


def _direct_trade_recompute(result: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute the delivered monthly values without calling project tools.

    Control A intentionally reads the declared CSV directly and performs only
    the small aggregation needed for this request.  It therefore checks the
    tool/workflow output against a separate implementation instead of feeding
    the same function's answer back to itself.
    """

    request = result.get("request", {}).get("trade", {})
    if not isinstance(request, Mapping):
        raise AcceptanceGuardError("control A needs the confirmed trade request")
    summary = result.get("summary")
    if not isinstance(summary, Mapping):
        raise AcceptanceGuardError("control A needs a delivered trade summary")
    comparison = result.get("request", {}).get("comparison", {})
    months = request.get("months")
    if months is None and comparison.get("kind") == "registered":
        months = [row.get("month") for row in summary.get("series", [])
                  if isinstance(row, Mapping)]
    if not isinstance(months, list) or not months or any(not isinstance(month, str) for month in months):
        raise AcceptanceGuardError("control A needs explicit or registered months")
    if len(months) != len(set(months)):
        raise AcceptanceGuardError("control A duplicate requested months")
    months = sorted(months)
    if comparison.get("kind") not in {"sequence", "endpoint", "registered"}:
        raise AcceptanceGuardError("control A has an unknown comparison kind")
    origin = request.get("origin")
    fields = {
        "China": "target_import_value_consumption_usd",
        "other_origins": "other_origins_import_value_consumption_usd",
        "all_origins": "all_origins_import_value_consumption_usd",
    }
    if origin not in fields:
        raise AcceptanceGuardError("control A has an unknown origin")
    hs6 = request.get("hs6")
    if hs6 is not None:
        path = _project_root() / "data/processed/causal/causal_trade_hs6_monthly.csv"
        field = {
            "China": "china_import_value_consumption_usd",
            "other_origins": "other_origins_import_value_consumption_usd",
            "all_origins": "all_origin_import_value_consumption_usd",
        }[origin]
        match_key = "hs6_2017"
    else:
        path = _project_root() / "data/processed/analysis/policy_case_monthly.csv"
        field = fields[origin]
        match_key = None
    if not path.is_file():
        raise AcceptanceGuardError("control A source table is missing")
    by_month: dict[str, int] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if match_key is not None and row.get(match_key, "").strip() != str(hs6):
                continue
            month = row.get("month_label") or (
                f"{int(row['year']):04d}-{int(row['month']):02d}")
            if month in by_month:
                raise AcceptanceGuardError(f"control A duplicate month: {month}")
            try:
                if hs6 is not None and origin == "other_origins":
                    value = int(row["all_origin_import_value_consumption_usd"]) - int(row["china_import_value_consumption_usd"])
                else:
                    value = int(row[field])
            except (KeyError, TypeError, ValueError) as exc:
                raise AcceptanceGuardError("control A source value is not an integer") from exc
            if value < 0:
                raise AcceptanceGuardError("control A source value is negative")
            by_month[month] = value
    independent_series = [
        {"month": month, "value_usd": by_month.get(month)} for month in months
    ]
    actual_series = [
        {"month": row.get("month"), "value_usd": row.get("value_usd")}
        for row in summary.get("series", []) if isinstance(row, Mapping)
    ]
    independent_total = (None if any(row["value_usd"] is None for row in independent_series)
                         else sum(row["value_usd"] for row in independent_series))
    actual_total = summary.get("total_usd")
    series_equal = actual_series == independent_series
    total_equal = actual_total == independent_total
    actual_comparison = summary.get("comparison", {})
    comparison_checks = {"kind": actual_comparison.get("kind") == comparison["kind"]}
    if comparison["kind"] == "endpoint":
        reference, current = comparison["reference_month"], comparison["current_month"]
        if reference not in months or current not in months:
            raise AcceptanceGuardError("control A endpoint outside requested months")
        base, target = by_month.get(reference), by_month.get(current)
        change = target - base if base is not None and target is not None else None
        rate = str((Decimal(change) * 100 / Decimal(base)).quantize(Decimal("0.01"))) if base and change is not None else None
        expected_comparison = {
            "reference_months": [reference], "current_months": [current],
            "change_usd": change, "change_percent": rate,
        }
        comparison_checks.update({key: actual_comparison.get(key) == value
                                  for key, value in expected_comparison.items()})
        comparison_checks["summary_delta"] = summary.get("endpoint_change_usd") == change
        comparison_checks["summary_percent"] = summary.get("endpoint_change_percent") == rate
    elif comparison["kind"] == "registered":
        actual_registered = summary.get("comparison", {})
        reference = actual_registered.get("reference_months")
        current = actual_registered.get("current_months")
        if (not isinstance(reference, list) or not isinstance(current, list)
                or set(reference) & set(current)
                or any(month not in by_month for month in reference + current)):
            raise AcceptanceGuardError("control A registered window is incomplete")
        base = sum(by_month[month] for month in reference)
        target = sum(by_month[month] for month in current)
        change = target - base
        rate = (str((Decimal(change) * 100 / Decimal(base)).quantize(Decimal("0.01")))
                if base else None)
        comparison_checks.update({
            "reference_months": actual_registered.get("reference_months") == reference,
            "current_months": actual_registered.get("current_months") == current,
            "change_usd": actual_registered.get("change_usd") == change,
            "change_percent": actual_registered.get("change_percent") == rate,
        })
    passed = bool(series_equal and total_equal and all(comparison_checks.values()))
    return {
        "version": "control-a-direct-table-0116",
        "control": "A",
        "status": "validated",
        "method": "independent_csv_recomputation",
        "source": {"path": str(path.relative_to(_project_root())),
                   "sha256": _file_sha256(path)},
        "request": {"origin": origin, "hs6": hs6, "months": list(months)},
        "actual": {"series": actual_series, "total_usd": actual_total},
        "independent": {"series": independent_series, "total_usd": independent_total},
        "checks": {"series_equal": series_equal, "total_equal": total_equal,
                    "comparison_checks": comparison_checks, "passed": passed},
        "scope_limit": "Arithmetic check against the confirmed model-derived request; not an independent intent baseline.",
        "interpretation": ("工作流结果与独立源表复算一致。"
                           if passed
                           else "工作流结果与独立源表复算不一致，不能把本次贸易结果当作通过。"),
    }


def _policy_control_messages(question: str, as_of: str | None = None) -> list[dict[str, str]]:
    """Build the no-evidence baseline prompt; it contains no gold/reference data."""

    return [
        {
            "role": "system",
            "content": (
                "你是一个没有外部检索结果的政策问答基线。回答下面的问题时，"
                "只能使用模型自身已有知识；不要假装看到了政策原文，不要编造引用。"
                "如果无法可靠回答，可以明确说明不确定。仅输出 JSON："
                "{\"answer\":\"...\",\"claims\":[{\"text\":\"...\",\"citations\":[]}] }。"
                "claims中的每一项必须同时包含text和citations；没有主张时使用空数组。"
            ),
        },
        {"role": "user", "content": json.dumps(
            {"question": question, **({"as_of": as_of} if isinstance(as_of, str) else {})},
            ensure_ascii=False)},
    ]


def _evaluate_no_evidence_response(case: SyntheticCase, response: ModelResponse) -> dict[str, Any]:
    """Score the actual B response without replacing it with a forced refusal."""

    text = response.text if isinstance(response.text, str) else str(response.text)
    parsed: Any = None
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        parsed = None
    strict_schema = isinstance(case.policy_reference, Mapping)
    claims: list[Any] = []
    schema_valid = True
    if isinstance(parsed, Mapping):
        candidate = parsed.get("claims")
        if isinstance(candidate, list):
            if strict_schema:
                for item in candidate:
                    if (not isinstance(item, Mapping)
                            or set(item) != {"text", "citations"}
                            or not isinstance(item.get("text"), str)
                            or not isinstance(item.get("citations"), list)
                            or any(not isinstance(ref, str) for ref in item["citations"])):
                        schema_valid = False
                        continue
                    claims.append({"text": item["text"],
                                   "citations": list(item["citations"])})
            else:
                claims = [item for item in candidate if isinstance(item, str)]
                schema_valid = len(claims) == len(candidate)
        answer = parsed.get("answer")
        if isinstance(answer, str):
            claim_text = " ".join(
                item.get("text", "") if isinstance(item, Mapping) else str(item)
                for item in claims
            )
            text_for_search = answer + " " + claim_text
        else:
            claim_text = " ".join(
                item.get("text", "") if isinstance(item, Mapping) else str(item)
                for item in claims
            )
            text_for_search = text + " " + claim_text
    else:
        text_for_search = text
    expected = list(case.control_facts)
    found = [fact for fact in expected if fact and fact in text_for_search]
    # This is an observation about the baseline, not a demand that it pass.
    return {
        "version": "control-b-no-evidence-0116",
        "control": "B",
        "status": "validated",
        "method": "same_question_without_retrieved_evidence",
        "response": {"text": text, "parsed": parsed, "metadata": safe_metadata(response.metadata)},
        "expected_fact_count": len(expected),
        "literal_matches": found,
        "literal_match_fraction": (len(found) / len(expected) if expected else None),
        "fact_recall": None,
        "claim_schema": "policy-claims-v2" if strict_schema else "legacy-string-claims",
        "claim_schema_valid": schema_valid,
        "answer_quality": "unreviewed",
        "semantic_accuracy_measured": False,
        "interpretation": "仅记录字符串出现情况；否定句也可能命中，需逐事实审查后才能判断正确、遗漏或矛盾。",
    }


def _legacy_checklist_review(case: SyntheticCase, stage: str,
                             packet: Mapping[str, Any],
                             submission: Mapping[str, Any],
                             reviewer: str) -> dict[str, Any] | None:
    """Run the established per-fact checklist when a case opts into it.

    The early synthetic smoke cases intentionally use a tiny ``kind``-only
    checklist.  Full prospective cases may provide the existing checklist
    fields (quote, required answer, task, disposition); those are validated by
    the project's original reviewer protocol as an additional, persisted
    audit, rather than silently replaced by the newer terminal guard.
    """

    required = {"id", "quote", "required_answer", "task", "expected_disposition"}
    if not all(isinstance(item, Mapping) and required.issubset(item) for item in case.checklist):
        return None
    artifact = packet.get("preview") if stage == "planning" else packet.get("result")
    if not isinstance(artifact, Mapping):
        return {"status": "not_applicable", "approved": False,
                "reason": "legacy checklist artifact is missing"}
    legacy_packet = {
        "stage": "plan" if stage == "planning" else "answer",
        "case": {"id": case.id, "question": case.question},
        "checklist": [deepcopy(dict(item)) for item in case.checklist],
        "artifact": deepcopy(dict(artifact)),
        "files": deepcopy(packet.get("files", [])),
    }
    legacy_submission = deepcopy(dict(submission))
    legacy_submission["packet_sha256"] = checklist_digest(legacy_packet)
    converted = []
    specs_by_id = {spec["id"]: spec for spec in case.checklist}
    for item in legacy_submission.get("items", []):
        spec = specs_by_id[item["id"]]
        row = deepcopy(dict(item))
        status = row.get("status")
        if stage == "planning":
            if status in {"pass", "supported", "covered"}:
                row["status"] = ("covered" if spec.get("expected_disposition") == "answer"
                                  else "needs_clarification")
            elif status == "fail":
                row["status"] = ("omitted" if spec.get("expected_disposition") == "answer"
                                  else "wrong_scope")
        elif status in {"pass", "supported", "covered"}:
            row["status"] = "supported"
        elif status == "fail":
            row["status"] = "missing"
        converted.append(row)
    legacy_submission["items"] = converted
    try:
        return validate_legacy_checklist_review(legacy_packet, legacy_submission, reviewer)
    except (KeyError, TypeError, ValueError) as exc:
        return {"status": "rejected", "approved": False,
                "reason": f"legacy checklist rejected: {type(exc).__name__}"}


class ProspectiveSyntheticRunner:
    """Run fixed offline cases through the reviewed acceptance protocol."""

    def __init__(self, output: str | Path, *, cases: Iterable[SyntheticCase] | None = None,
                 workflow_factory: Callable[..., Any] = build_product_workflow,
                 model_factory: Callable[..., Any],
                 reviewer: Callable[[Mapping[str, Any]], Mapping[str, Any]] = fixture_review,
                 fact_reviewer: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
                 gap_reviewer: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
                 reviewer_id: str = "offline-fixture-reviewer") -> None:
        self.output = Path(output)
        self.cases = deepcopy(tuple(default_cases() if cases is None else cases))
        if not self.cases or len({case.id for case in self.cases}) != len(self.cases):
            raise AcceptanceGuardError("synthetic case IDs must be unique")
        for case in self.cases:
            if not case.id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in case.id):
                raise AcceptanceGuardError("case ID must be a safe directory name")
        self.workflow_factory = workflow_factory
        self.model_factory = model_factory
        self.reviewer = reviewer
        self.fact_reviewer = fact_reviewer
        if gap_reviewer is not None and not callable(gap_reviewer):
            raise AcceptanceGuardError("gap reviewer must be callable")
        self.gap_reviewer = gap_reviewer
        if not isinstance(reviewer_id, str) or not reviewer_id.strip():
            raise AcceptanceGuardError("explicit reviewer ID is required")
        self.reviewer_id = reviewer_id

    def _snapshot(self) -> dict[str, Any]:
        from . import prospective_acceptance as guard
        from . import unified_research as unified
        root = _project_root()
        paths = [Path(guard.__file__).resolve(), Path(unified.__file__).resolve(),
                 Path(__file__).resolve(),
                 root / "src/tradeintel_ai/structured_workflow.py",
                 root / "src/tradeintel_ai/research_brief.py",
                 root / "src/tradeintel_ai/evidence_v21.py",
                 root / "src/tradeintel_ai/research_brief.py",
                 root / "src/tradeintel_ai/repository.py",
                 root / "src/tradeintel_ai/policy_retrieval.py",
                 root / "src/tradeintel_ai/request_capture.py",
                 root / "src/tradeintel_ai/policy_facts.py",
                 root / REFERENCE_RELATIVE,
                 root / "requirements.txt",
                 root / "data/processed/analysis/policy_case_monthly.csv",
                 root / "data/processed/policy/section301_list1_event.csv",
                 root / "data/processed/analysis/registered_comparison_windows.json",
                 root / "docs/experiments/phase13a-policy-retrieval/corpus.json",
                 root / "docs/experiments/phase13a-policy-retrieval/development_results.json"]
        # The repository exposes a finite set of read-only evidence paths.
        # Include every one in the snapshot instead of relying on whichever
        # subset a particular fixture happened to touch.
        repository_paths = EvidenceRegistryV21().repository.paths
        for name, descriptor in vars(type(repository_paths)).items():
            if isinstance(descriptor, property):
                paths.append(getattr(repository_paths, name))
        # All project Python modules participate in the executable contract;
        # this also covers a helper imported indirectly by the workflow.
        paths.extend(sorted((root / "src/tradeintel_ai").glob("*.py")))
        corpus_path = root / "docs/experiments/phase13a-policy-retrieval/corpus.json"
        if corpus_path.is_file():
            try:
                corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
                for chunk in corpus.get("chunks", []):
                    local_path = chunk.get("local_path") if isinstance(chunk, Mapping) else None
                    if isinstance(local_path, str):
                        paths.append(root / local_path)
            except (OSError, ValueError, TypeError):
                # The explicit corpus JSON remains in the freeze list; a
                # malformed corpus is rejected by the workflow itself.
                pass
        callable_descriptors = {
            "workflow_factory": _callable_descriptor(self.workflow_factory),
            "model_factory": _callable_descriptor(self.model_factory),
            "reviewer": _callable_descriptor(self.reviewer),
            "fact_reviewer": _callable_descriptor(self.fact_reviewer),
            "gap_reviewer": _callable_descriptor(self.gap_reviewer),
        }
        for descriptor in callable_descriptors.values():
            source_path = descriptor.get("source_path")
            if isinstance(source_path, str):
                paths.append(Path(source_path))
        paths = list(dict.fromkeys(path.resolve() for path in paths))
        requirements_path = root / "requirements.txt"
        return freeze_dependencies(
            paths,
            configuration={
                "protocol": "0118-synthetic",
                "case_ids": [case.id for case in self.cases],
                "cases": [asdict(case) for case in self.cases],
                "acceptance_ready": False,
                "dependency_coverage": (
                    "explicit source/data files, runtime identity and injected callable source are frozen; "
                    "transitive packages and OS libraries remain outside the snapshot"
                ),
                "runtime_environment": runtime_environment(
                    requirement_names(requirements_path)
                ),
                "injected_callables": callable_descriptors,
                "reviewer_id": self.reviewer_id,
                "fact_reviewer": getattr(self.fact_reviewer, "__name__", None),
                "gap_reviewer": getattr(self.gap_reviewer, "__name__", None),
                "external_calls": False,
            },
        )

    def _build_workflow(self, planner: LedgerBoundModel, case: SyntheticCase) -> Any:
        """Build the requested workflow without swallowing factory failures."""

        kwargs: dict[str, Any] = {"planner_source_kind": "fixture"}
        if case.allow_host_gap_review:
            kwargs["allow_host_gap_review"] = True
        # Custom offline factories from earlier phases often accept only the
        # original planner_source_kind keyword.  Inspect the signature before
        # adding the new optional gap switch; a TypeError raised *inside* a
        # factory must still propagate as a real failure.
        if "allow_host_gap_review" not in kwargs:
            return self.workflow_factory(planner, **kwargs)
        import inspect
        try:
            signature = inspect.signature(self.workflow_factory)
        except (TypeError, ValueError) as exc:
            raise AcceptanceGuardError("gap-enabled workflow factory signature is unavailable") from exc
        parameters = signature.parameters.values()
        accepts_kwargs = any(parameter.kind == parameter.VAR_KEYWORD
                             for parameter in parameters)
        if not accepts_kwargs and "allow_host_gap_review" not in signature.parameters:
            raise AcceptanceGuardError("workflow factory does not support host gap review")
        return self.workflow_factory(planner, **kwargs)

    def _review(self, ledger: ProspectiveCallLedger, case: SyntheticCase,
                stage: str, packet: Mapping[str, Any]) -> dict[str, Any]:
        submission = self.reviewer(deepcopy(packet))
        if not isinstance(submission, Mapping):
            raise AcceptanceGuardError("reviewer must return an object")
        expected_kind = packet.get("expected_kind", case.expected_kind)
        expected_tasks = packet.get("expected_tasks", list(case.expected_tasks))
        record = validate_structured_review(
            packet,
            submission,
            reviewer=self.reviewer_id,
            expected_kind=expected_kind,
            expected_tasks=expected_tasks,
            stage="plan" if stage == "planning" else "answer",
        )
        legacy = _legacy_checklist_review(
            case, stage, packet, submission, self.reviewer_id
        )
        if legacy is not None:
            record["legacy_checklist_review"] = legacy
            if legacy.get("approved") is not True:
                record["approved"] = False
        saved = ledger.record_review(case.id, stage, submission, packet=packet,
                                     validation=record)
        record = {**record, "saved_artifacts": saved}
        return record

    def _record_fact_review(self, ledger: ProspectiveCallLedger, case: SyntheticCase,
                            packet: Mapping[str, Any]) -> dict[str, Any] | None:
        """Persist a fact review packet; semantic labels remain human-owned."""

        if not case.facts:
            return None
        arm = packet.get("arm")
        packet_name = f"reviews/{case.id}-facts-{arm}-packet.json"
        packet_artifact = ledger.record_artifact(packet_name, packet)
        if self.fact_reviewer is None:
            pending = {
                "version": "fact-review-pending-0118",
                "case_id": case.id,
                "arm": arm,
                "status": "pending_human",
                "packet_sha256": digest(packet),
                "semantic_accuracy_measured": False,
            }
            decision_artifact = ledger.record_artifact(
                f"reviews/{case.id}-facts-{arm}-pending.json", pending
            )
            return {"status": "pending_human", "packet": packet_artifact,
                    "decision": decision_artifact, "semantic_accuracy_measured": False}
        submission = self.fact_reviewer(deepcopy(packet))
        if not isinstance(submission, Mapping):
            raise AcceptanceGuardError("fact reviewer must return an object")
        decision = validate_fact_review(packet, submission, reviewer=self.reviewer_id)
        submission_artifact = ledger.record_artifact(
            f"reviews/{case.id}-facts-{arm}-submission.json", submission
        )
        decision_artifact = ledger.record_artifact(
            f"reviews/{case.id}-facts-{arm}-decision.json", decision
        )
        return {"status": "reviewed", "approved": decision["approved"],
                "packet": packet_artifact, "submission": submission_artifact,
                "decision": decision_artifact,
                "semantic_accuracy_measured": False,
                "review_structure_verified": True}

    @staticmethod
    def _actual_policy_pair_capture(ledger: ProspectiveCallLedger, case_id: str,
                                    pair_packet: Mapping[str, Any]) -> dict[str, Any]:
        """Compare captured provider-neutral payload settings after both calls."""

        captures: dict[str, Any] = {}
        for stage, arm in (("policy_with_evidence", "with_evidence"),
                           ("policy_no_evidence", "without_evidence")):
            row = next((item for item in ledger.state.get("calls", [])
                        if item.get("question_id") == case_id and item.get("stage") == stage), None)
            artifact = row.get("raw_response") if isinstance(row, Mapping) else None
            if not isinstance(artifact, Mapping):
                raise AcceptanceGuardError("policy_pair_actual_payload_missing")
            path = ledger.output / artifact.get("path", "")
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError) as exc:
                raise AcceptanceGuardError("policy_pair_actual_payload_unreadable") from exc
            settings = payload.get("request_config")
            if not isinstance(settings, Mapping):
                raise AcceptanceGuardError("policy_pair_actual_payload_missing_config")
            captures[arm] = {
                "request_config": deepcopy(dict(settings)),
                "messages_sha256": digest(payload.get("messages", [])),
                "tools_sha256": digest(payload.get("tools", [])),
                "request_capture": deepcopy(
                    payload.get("metadata", {}).get("request_capture")
                    if isinstance(payload.get("metadata"), Mapping) else None
                ),
                "response_artifact": deepcopy(dict(artifact)),
            }
        comparable_keys = ("model", "temperature", "max_tokens", "thinking", "stream", "base_url")
        left = captures["with_evidence"]["request_config"]
        right = captures["without_evidence"]["request_config"]
        differences = [key for key in comparable_keys if left.get(key) != right.get(key)]
        if differences:
            raise AcceptanceGuardError("policy_pair_actual_payload_mismatch")
        actual_captures = [captures[arm].get("request_capture") for arm in captures]
        http_capture_available = all(
            isinstance(item, Mapping) and item.get("kind") == "http_payload"
            for item in actual_captures
        )
        verification_differences: list[str] = []
        if http_capture_available:
            for arm in ("with_evidence", "without_evidence"):
                capture = captures[arm]["request_capture"]
                payload = capture.get("payload")
                declared = pair_packet.get(arm, {}).get("configuration", {})
                if not isinstance(payload, Mapping) or not isinstance(declared, Mapping):
                    verification_differences.append(f"{arm}.payload")
                    continue
                for key in ("model", "temperature", "max_tokens", "thinking", "stream"):
                    if payload.get(key) != declared.get(key):
                        verification_differences.append(f"{arm}.{key}")
                if capture.get("timeout_seconds") != declared.get("timeout_seconds"):
                    verification_differences.append(f"{arm}.timeout_seconds")
                serialized = json.dumps(payload.get("messages", []), ensure_ascii=False)
                for label in ("question", "as_of"):
                    value = pair_packet.get(label)
                    if not isinstance(value, str) or value not in serialized:
                        verification_differences.append(f"{arm}.{label}")
        if verification_differences:
            raise AcceptanceGuardError("policy_pair_actual_payload_mismatch")
        return {
            "version": "policy-pair-capture-0118",
            "case_id": case_id,
            "declared_contract_sha256": pair_packet.get("contract", {}).get("configuration_sha256"),
            "captures": captures,
            "comparable_settings_equal": not differences,
            "differences": differences + verification_differences,
            "actual_payloads_verified": http_capture_available,
            "capture_kind": ("http_payload" if http_capture_available
                             else "declared_settings_after_call; not HTTP payload capture"),
            "semantic_accuracy_measured": False,
        }

    @staticmethod
    def _stop(ledger: ProspectiveCallLedger, case_id: str, reason: str) -> None:
        try:
            if ledger.state.get("status") == "running":
                preserve_review_label = (
                    reason == "acceptance_integration_incomplete_0116"
                    and any(row.get("id") == case_id and row.get("status") == "accepted"
                            for row in ledger.state.get("questions", []))
                )
                if not preserve_review_label:
                    ledger.mark_question_status(case_id, "stopped", reason=reason)
                ledger.stop(reason)
        except AcceptanceStopped:
            pass

    def _run_controls(self, ledger: ProspectiveCallLedger, case: SyntheticCase,
                      model: LedgerBoundModel, result: Mapping[str, Any] | None = None,
                      *, pair_packet: Mapping[str, Any] | None = None) -> list[str]:
        """Run actual controls and persist their observed outcome.

        A is a source-table recomputation.  B sends the same policy question
        without retrieved evidence and scores the response that came back;
        it never replaces that response with a prewritten refusal.
        """

        if result is None:
            # Keep the old direct-call seam fail-closed: a control without the
            # executed result has nothing honest to compare.
            raise AcceptanceGuardError("controls_not_implemented_0116")
        control_ids: list[str] = []
        if "trade" in case.expected_tasks:
            control_id = f"control_a:{case.id}"
            payload = _direct_trade_recompute(result)
            payload["question_id"] = case.id
            ledger.record_control(control_id, payload,
                                  artifact_name=f"controls/{case.id}-control-a.json")
            control_ids.append(control_id)
            if payload.get("checks", {}).get("passed") is not True:
                raise AcceptanceGuardError("control_a_failed")
        if "policy" in case.expected_tasks:
            if not case.control_facts:
                raise AcceptanceGuardError("controls_not_implemented_0116")
            if model is None:
                raise AcceptanceGuardError("controls_not_implemented_0116")
            policy_request = result.get("request", {}) if isinstance(result.get("request"), Mapping) else {}
            if isinstance(case.policy_reference, Mapping):
                policy_question = case.policy_reference.get("question")
                policy_as_of = case.policy_reference.get("as_of")
            else:
                policy_question = policy_request.get("policy_question")
                if not isinstance(policy_question, str) or not policy_question.strip():
                    policy_question = case.question
                policy_as_of = policy_request.get("policy_as_of")
            response = model.complete(
                messages=_policy_control_messages(policy_question, policy_as_of), tools=[]
            )
            payload = _evaluate_no_evidence_response(case, response)
            payload["question_id"] = case.id
            if case.facts:
                parsed = payload.get("response", {}).get("parsed", {})
                parsed = parsed if isinstance(parsed, Mapping) else {}
                raw_claims = parsed.get("claims", [])
                if isinstance(case.policy_reference, Mapping):
                    claims = [deepcopy(dict(item)) for item in raw_claims
                              if isinstance(item, Mapping)
                              and set(item) == {"text", "citations"}
                              and isinstance(item.get("text"), str)
                              and isinstance(item.get("citations"), list)]
                else:
                    claims = [{"text": item, "citations": []} for item in raw_claims
                              if isinstance(item, str)]
                packet = _fact_review_packet(
                    case, "without_evidence",
                    answer=parsed.get("answer", payload["response"]["text"])
                    if isinstance(parsed.get("answer", payload["response"]["text"]), str)
                    else payload["response"]["text"],
                    claims=claims,
                    evidence=(reference_evidence(case.policy_reference)
                              if isinstance(case.policy_reference, Mapping) else {}),
                    reference_sha256=(case.policy_reference.get("reference_sha256")
                                      if isinstance(case.policy_reference, Mapping) else None),
                )
                payload["fact_review"] = self._record_fact_review(ledger, case, packet)
            control_id = f"control_b:{case.id}"
            ledger.record_control(control_id, payload,
                                  artifact_name=f"controls/{case.id}-control-b.json")
            control_ids.append(control_id)
            if case.facts and payload["fact_review"].get("status") != "reviewed":
                raise AcceptanceGuardError("baseline_fact_review_pending")
            if pair_packet is not None:
                capture = self._actual_policy_pair_capture(ledger, case.id, pair_packet)
                ledger.record_artifact(
                    f"{case.id}/policy-pair-capture.json", capture
                )
        if not control_ids:
            raise AcceptanceGuardError("controls_not_implemented_0116")
        return control_ids

    def run(self) -> dict[str, Any]:
        for case in self.cases:
            _validate_policy_case_reference(case)
        snapshot = self._snapshot()
        ledger = ProspectiveCallLedger(
            [case.id for case in self.cases], self.output,
            frozen_snapshot=snapshot,
        )
        ledger.record_artifact("frozen-snapshot.json", snapshot)
        active_case = self.cases[0]
        deliveries = []
        try:
            for case in self.cases:
                active_case = case
                case_dir = self.output / case.id
                case_dir.mkdir(parents=False, exist_ok=False)
                independent_baseline = None
                if case.independent_request is not None:
                    independent_baseline = _independent_trade_baseline(case)
                    ledger.record_artifact(
                        f"{case.id}/baseline.json", independent_baseline
                    )
                planner = LedgerBoundModel(
                    _call_factory(self.model_factory, "planning", case), ledger,
                    case.id, "planning", case.reference,
                )
                workflow = self._build_workflow(planner, case)
                preview = workflow.prepare(case.question, audit_output=case_dir / "planning")
                ledger.record_artifact(f"{case.id}/preview.json", preview)
                if preview.get("status") == "needs_gap_review":
                    if self.gap_reviewer is None:
                        self._stop(ledger, case.id, "gap_review_pending")
                        break
                    gap_packet = {
                        "case_id": case.id,
                        "question": case.question,
                        "gap_audit": deepcopy(preview.get("gap_audit")),
                        "preview": deepcopy(preview),
                    }
                    submission = self.gap_reviewer(deepcopy(gap_packet))
                    if not isinstance(submission, Mapping):
                        self._stop(ledger, case.id, "gap_review_rejected")
                        break
                    gap_preview = workflow.approve_gap_review(
                        preview.get("gap_review_token"), submission,
                        reviewer=self.reviewer_id,
                    )
                    if gap_preview.get("status") != "needs_confirmation":
                        self._stop(ledger, case.id, "gap_review_rejected")
                        break
                    preview = gap_preview
                    if isinstance(preview.get("gap_review"), Mapping):
                        ledger.record_artifact(
                            f"{case.id}/gap-review.json", preview["gap_review"]
                        )
                    # Keep both the pre-review plan and the post-review plan:
                    # the latter is the one reviewed and bound to execution.
                    ledger.record_artifact(f"{case.id}/preview-after-gap.json", preview)
                plan_packet = {
                    "preview": preview,
                    "checklist": [deepcopy(item) for item in case.checklist],
                    "expected_kind": case.expected_kind,
                    "expected_tasks": list(case.expected_tasks),
                    "reference": deepcopy(case.reference),
                }
                plan_review = self._review(ledger, case, "planning", plan_packet)
                if not plan_review["approved"]:
                    self._stop(ledger, case.id, "plan_review_rejected")
                    break
                if case.expected_kind != "support":
                    ledger.approve_question(case.id, expected_kind=case.expected_kind,
                                            reason="reviewed_boundary")
                    continue
                if preview.get("status") != "needs_confirmation":
                    self._stop(ledger, case.id, "plan_not_confirmable")
                    break
                policy_model = None
                control_model = None
                pair_packet = None
                if "policy" in preview.get("tasks", []):
                    policy_model = LedgerBoundModel(
                        _call_factory(self.model_factory, "policy_with_evidence", case), ledger,
                        case.id, "policy_with_evidence", case.reference,
                    )
                    if case.run_controls:
                        control_model = LedgerBoundModel(
                            _call_factory(self.model_factory, "policy_no_evidence", case), ledger,
                            case.id, "policy_no_evidence", case.reference,
                        )
                        pair_packet = _policy_pair_packet(
                            case, preview, policy_model.base, control_model.base
                        )
                        ledger.record_artifact(
                            f"{case.id}/policy-pair-contract.json", pair_packet
                        )
                if independent_baseline is not None:
                    request = preview.get("request")
                    proposed = {
                        "trade": request.get("trade") if isinstance(request, Mapping) else None,
                        "comparison": request.get("comparison") if isinstance(request, Mapping) else None,
                    }
                    try:
                        scope_record = compare_trade_scope(
                            independent_baseline["request"], proposed
                        )
                    except AcceptanceGuardError:
                        scope_record = {
                            "scope_equal": False,
                            "differences": ["malformed_proposed_scope"],
                            "reference_sha256": digest(independent_baseline["request"]),
                            "proposed_sha256": digest(proposed),
                            "proposal_repaired": False,
                            "provenance_verified": False,
                        }
                    ledger.record_artifact(
                        f"{case.id}/scope-comparison.json", scope_record
                    )
                    if scope_record.get("scope_equal") is not True:
                        self._stop(ledger, case.id, "trade_scope_mismatch")
                        break
                delivery_dir = case_dir / "delivery"
                result = workflow.confirm(
                    preview["confirmation_token"], delivery_dir,
                    model=policy_model, source_kind="fixture",
                )
                delivery = inspect_delivery(delivery_dir)
                answer_packet = {
                    "preview": preview,
                    "result": result,
                    "delivery": delivery,
                    "checklist": [deepcopy(item) for item in case.checklist],
                    "expected_kind": case.expected_kind,
                    "expected_tasks": list(case.expected_tasks),
                    "reference": deepcopy(case.reference),
                }
                answer_review = self._review(ledger, case, "policy_with_evidence", answer_packet)
                if not answer_review["approved"]:
                    self._stop(ledger, case.id, "answer_review_rejected")
                    break
                main_fact_review = None
                if case.facts and "policy" in preview.get("tasks", []):
                    claims, evidence = _policy_claims_from_result(result)
                    main_fact_packet = _fact_review_packet(
                        case, "with_evidence",
                        answer=(result.get("policy", {}).get("generation", {}).get("raw_text", "")
                                if isinstance(result.get("policy"), Mapping) else ""),
                        claims=claims,
                        evidence={
                            **(reference_evidence(case.policy_reference)
                               if isinstance(case.policy_reference, Mapping) else {}),
                            **evidence,
                        },
                        reference_sha256=(case.policy_reference.get("reference_sha256")
                                          if isinstance(case.policy_reference, Mapping) else None),
                    )
                    main_fact_review = self._record_fact_review(
                        ledger, case, main_fact_packet
                    )
                    ledger.record_artifact(
                        f"{case.id}/fact-review-summary.json", main_fact_review
                    )
                    if main_fact_review.get("status") != "reviewed":
                        self._stop(ledger, case.id, "fact_review_pending")
                        break
                    if main_fact_review.get("approved") is not True:
                        self._stop(ledger, case.id, "main_fact_review_rejected")
                        break
                if inspect_delivery(delivery_dir) != delivery:
                    self._stop(ledger, case.id, "delivery_changed_during_review")
                    break
                deliveries.append((case.id, delivery_dir, delivery))
                delivery_artifact_name = f"{case.id}/delivery-inspection.json"
                ledger.record_artifact(delivery_artifact_name, delivery)
                required_controls: list[str] = []
                if not case.run_controls:
                    # Preserve the visible review result for diagnostics, but
                    # leave it intentionally unbound so finalization cannot
                    # mistake delivery review alone for full acceptance.
                    ledger.mark_question_status(
                        case.id, "accepted", reason="reviewed_delivery_unbound"
                    )
                    raise AcceptanceGuardError("acceptance_integration_incomplete_0116")
                if case.run_controls:
                    required_controls = self._run_controls(
                        ledger, case, control_model, result,
                        pair_packet=pair_packet,
                    )
                ledger.approve_question(
                    case.id,
                    expected_kind=case.expected_kind,
                    answer_stage="policy_with_evidence",
                    delivery_artifact_name=delivery_artifact_name,
                    required_controls=required_controls,
                    reason="reviewed_delivery_and_controls",
                )
            if ledger.state.get("status") == "running":
                for qid, directory, checked in deliveries:
                    if inspect_delivery(directory) != checked:
                        self._stop(ledger, qid, "delivery_changed_after_review")
                        break
            if ledger.state.get("status") == "running":
                required_controls = [key for key, value in ledger.state.get("controls", {}).items()
                                     if isinstance(value, Mapping) and value.get("status") == "validated"]
                try:
                    ledger.finalize_reviewed(required_controls=required_controls)
                except AcceptanceGuardError:
                    # Keep the result explicit if a custom case did not bind
                    # every row.  The error is not silently converted into a
                    # successful acceptance.
                    ledger.stop("acceptance_binding_incomplete")
        except (KeyboardInterrupt, Exception) as exc:
            if ledger.state.get("status") == "running":
                reason = (str(exc)
                          if isinstance(exc, AcceptanceGuardError)
                          and str(exc) in {"controls_not_implemented_0116",
                                           "acceptance_integration_incomplete_0116",
                                           "control_a_failed", "baseline_recompute_failed",
                                           "baseline_fact_review_pending"}
                          else f"runner_failed:{_failure_category(exc)}")
                self._stop(ledger, active_case.id, reason)
        summary = {**ledger.summary(),
                   "acceptance_ready": False,
                   "synthetic_protocol_completed": ledger.state.get("status") == "completed",
                   "semantic_accuracy_measured": False,
                   "controls_are_execution_checks": True}
        ledger.record_artifact("run-summary.json", summary)
        # record_artifact above is intentionally last while the ledger is
        # running or stopped; it remains part of the hash-checked audit.
        return summary


def run_synthetic_batch(output: str | Path, *, model_factory: Callable[..., Any],
                        cases: Iterable[SyntheticCase] | None = None,
                        workflow_factory: Callable[..., Any] = build_product_workflow,
                        reviewer: Callable[[Mapping[str, Any]], Mapping[str, Any]] = fixture_review,
                        fact_reviewer: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
                        gap_reviewer: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
                        reviewer_id: str = "offline-fixture-reviewer") -> dict[str, Any]:
    """Convenience wrapper used by offline tests and development scripts."""

    return ProspectiveSyntheticRunner(
        output,
        cases=cases,
        workflow_factory=workflow_factory,
        model_factory=model_factory,
        reviewer=reviewer,
        fact_reviewer=fact_reviewer,
        gap_reviewer=gap_reviewer,
        reviewer_id=reviewer_id,
    ).run()


__all__ = [
    "LedgerBoundModel",
    "MODEL_STAGES",
    "ProspectiveSyntheticRunner",
    "SyntheticCase",
    "default_cases",
    "fixture_review",
    "run_synthetic_batch",
]
