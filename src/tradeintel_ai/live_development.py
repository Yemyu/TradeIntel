"""Bounded provider entry with frozen preflight and persisted host review.

Deterministic matching is not semantic review. Compatibility review entry
points fail closed; the runner reads explicit host submissions instead.
"""

from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

from .model_adapter import OpenAICompatibleConfig
from .prospective_acceptance import AcceptanceGuardError
from .prospective_acceptance import digest, verify_dependencies
from .host_review import HostReviewStore, _publish
from .prospective_runner import (
    LIVE_STAGE_BUDGETS,
    LIVE_TOKEN_BUDGET,
    ModelInput,
    ProspectiveSyntheticRunner,
    development_cases,
)
from .research_models import ResearchPlannerModel, ResearchPolicyModel


LIVE_REVIEWER_ID = "tradeintel-host-ai-assisted-reviewer-0128"


def _profile(profile):
    if profile == 'four-scenes':
        return development_cases(), deepcopy(LIVE_STAGE_BUDGETS)
    if profile == 'policy-followup':
        cases = tuple(case for case in development_cases()
                      if case.id in {'SYN-POLICY-01', 'SYN-COMBINED-01'})
        return cases, {'planning': 2, 'policy_with_evidence': 2, 'policy_no_evidence': 2}
    raise AcceptanceGuardError('unknown live development profile')


def _safe_base_url(value: str) -> str:
    """Keep endpoint identity while dropping credentials/query strings."""

    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return "[REDACTED_ENDPOINT]"
    if parsed.username is not None or parsed.password is not None:
        return "[REDACTED_ENDPOINT]"
    if not parsed.scheme or not parsed.netloc:
        return parsed.path.rstrip("/") or "[REDACTED_ENDPOINT]"
    try:
        host = parsed.hostname or ""
        if parsed.port:
            host = f"{host}:{parsed.port}"
    except ValueError:
        host = parsed.netloc.rsplit("@", 1)[-1].split(":", 1)[0]
    return urlunsplit((parsed.scheme, host, parsed.path.rstrip("/"), "", ""))


def runtime_configuration(config: OpenAICompatibleConfig, profile='four-scenes') -> dict[str, Any]:
    """Return the provider settings frozen before a live batch.

    The API key is represented only by a boolean.  Generation limits are
    explicit because the policy pair must use the same model settings.
    """

    _, budgets = _profile(profile)
    return {
        'profile': profile,
        "provider": {
            "base_url": _safe_base_url(config.base_url),
            "model": config.model,
            "temperature": config.temperature,
            "timeout_seconds": config.timeout_seconds,
            "api_key_present": bool(config.api_key),
        },
        "generation": {
            "planning": {"max_tokens": 1536, "thinking": {"type": "disabled"}, "stream": False},
            "policy": {"max_tokens": 768, "thinking": {"type": "disabled"}, "stream": False},
        },
        "budgets": {
            "stage_calls": budgets,
            "reported_token_stop": LIVE_TOKEN_BUDGET,
        },
        "automatic_retry": False,
    }


def model_factory(config: OpenAICompatibleConfig):
    """Build one model per ledger stage without exposing a reference answer."""

    def factory(stage: str, case: ModelInput):
        if not isinstance(case, ModelInput):
            raise AcceptanceGuardError("live model factory received an invalid public case")
        if stage == "planning":
            return ResearchPlannerModel(config)
        if stage in {"policy_with_evidence", "policy_no_evidence"}:
            return ResearchPolicyModel(config)
        raise AcceptanceGuardError("unknown live model stage")

    return factory


LIVE_BLOCKERS = ("persisted_preflight_required",)


def _validate_config(config):
    parsed = urlsplit(config.base_url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not config.model.strip() or not config.api_key
            or not math.isfinite(config.temperature) or not math.isfinite(config.timeout_seconds)
            or config.timeout_seconds <= 0):
        raise AcceptanceGuardError('complete HTTPS provider configuration required')


def _prepared_runner(output, config, profile='four-scenes'):
    runner = _build_unstarted_runner(output, config, profile)
    runner._checkpoint_reviews = True
    runner._persisted_host_reviews = True
    runner.required_reviews = {case.id: {
        'facts': case.expected_kind == 'support' and 'policy' in case.expected_tasks,
        'baseline': case.expected_kind == 'support' and 'trade' in case.expected_tasks,
        'gap': case.allow_host_gap_review,
    } for case in runner.cases}
    return runner


def _preflight_path(output):
    path = Path(output)
    return path.parent / (path.name + '.preflight.json')


def ai_assisted_review(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Compatibility entry: never impersonate a host semantic judgement."""
    raise AcceptanceGuardError("actual host review required; automatic approval disabled")


def ai_assisted_fact_review(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Both arms require actual semantic review; lexical matches are insufficient."""
    raise AcceptanceGuardError("actual host fact review required; automatic approval disabled")


def _build_unstarted_runner(output: str | Path, config: OpenAICompatibleConfig, profile='four-scenes') -> ProspectiveSyntheticRunner:
    """Construct metadata for inspection only; review callbacks fail closed."""

    cases, budgets = _profile(profile)
    return ProspectiveSyntheticRunner(
        output,
        cases=cases,
        model_factory=model_factory(config),
        reviewer=ai_assisted_review,
        fact_reviewer=ai_assisted_fact_review,
        strict_protocol=True,
        reviewer_id=LIVE_REVIEWER_ID,
        run_mode="live_development",
        external_calls=True,
        reviewer_type="ai_assisted",
        stage_budgets=budgets,
        token_budget=LIVE_TOKEN_BUDGET,
        runtime_configuration=runtime_configuration(config, profile),
    )


def live_preflight(output: str | Path, config: OpenAICompatibleConfig, *, persist=False, profile='four-scenes') -> dict[str, Any]:
    """Return a no-network preflight report for the exact live configuration."""

    path = Path(output)
    if path.exists() or path.is_symlink():
        raise AcceptanceGuardError("live preflight output must be a new path")
    runner = _prepared_runner(path, config, profile)
    snapshot = runner._snapshot()
    if persist:
        _validate_config(config)
        _preflight_path(path).parent.mkdir(parents=True, exist_ok=True)
        _publish(_preflight_path(path), {'output': str(path.resolve()), 'snapshot': snapshot,
                                        'snapshot_sha256': digest(snapshot)})
    return {
        "version": "live-development-preflight-0128",
        "ready_for_bounded_run": bool(persist),
        "blocking_reasons": [] if persist else list(LIVE_BLOCKERS),
        "resume_supported": bool(persist),
        "credentials_verified": False,
        "snapshot_persisted": bool(persist),
        "preflight_path": str(_preflight_path(path)) if persist else None,
        "network_calls": 0,
        "run_mode": "live_development",
        "external_calls": True,
        "reviewer_type": "ai_assisted",
        "reviewer_id": LIVE_REVIEWER_ID,
        "cases": [{"id": case.id, "question": case.question,
                    "expected_kind": case.expected_kind,
                    "expected_tasks": list(case.expected_tasks)}
                   for case in runner.cases],
        "configuration": runtime_configuration(config, profile),
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "stage_budgets": deepcopy(runner.stage_budgets),
        "reported_token_stop": LIVE_TOKEN_BUDGET,
        "automatic_retry": False,
        "semantic_accuracy_measured": False,
        "human_review_pending": True,
    }


def build_live_runner(output: str | Path, config: OpenAICompatibleConfig) -> ProspectiveSyntheticRunner:
    """Require the exact persisted preflight before constructing a live runner."""
    path = _preflight_path(output)
    if not path.is_file() or path.is_symlink():
        raise AcceptanceGuardError('live development blocked: persisted_preflight_required')
    _validate_config(config)
    saved = json.loads(path.read_text())
    profile = saved['snapshot']['configuration']['runtime_configuration']['profile']
    runner = _prepared_runner(output, config, profile)
    snapshot = runner._snapshot()
    if (saved.get('output') != str(Path(output).resolve())
            or saved.get('snapshot_sha256') != digest(saved.get('snapshot'))
            or digest(saved.get('snapshot')) != digest(snapshot)):
        raise AcceptanceGuardError('persisted preflight differs from current configuration or dependencies')
    verify_dependencies(snapshot)
    return runner


def run_live_development(output: str | Path, config: OpenAICompatibleConfig, *, resume=False) -> dict[str, Any]:
    """Start or resume only an explicitly waiting, frozen review batch."""

    runner = build_live_runner(output, config)
    return runner.run(checkpoint_reviews=True, persisted_host_reviews=True, resume=resume)


def review_store(output):
    """Open the existing review store without credentials or provider access."""
    path = Path(output)
    snapshot = json.loads((path / 'frozen-snapshot.json').read_text())
    verify_dependencies(snapshot)
    if not (path / 'host-reviews' / 'manifest.json').is_file():
        raise AcceptanceGuardError('host review store has not been created')
    return HostReviewStore(path / 'host-reviews', snapshot=snapshot, reviewer=LIVE_REVIEWER_ID)


def pending_reviews(output):
    store = review_store(output)
    rows = []
    from .host_review import HostReviewPending
    for path in sorted(store.directory.glob('*.packet.json')):
        envelope = json.loads(path.read_text())
        try:
            store.receive(envelope['slot'])
        except HostReviewPending:
            rows.append({'slot': envelope['slot'], 'kind': envelope['kind'],
                         'path': str(path), 'packet': envelope['packet']})
    return {'status': 'review_materials', 'pending': rows, 'network_calls': 0}


__all__ = [
    "LIVE_REVIEWER_ID",
    "ai_assisted_fact_review",
    "ai_assisted_review",
    "build_live_runner",
    "live_preflight",
    "model_factory",
    "run_live_development",
    "runtime_configuration",
]
