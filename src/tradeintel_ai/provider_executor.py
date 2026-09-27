"""Actual provider experiment executor with a persistent event ledger (offline).

This is the REAL-calling executor demanded by the Astra J-acceptance -- the
fake executor cannot serve that role.  It consumes an already-prepared
brief-view package, re-verifies the ACTUAL messages to be sent, re-estimates
the budget (never trusting the manifest numbers), claims a slot in a fresh
append-only event ledger (14 slots; the old G2 ledger stays dead), persists
the ``started`` run manifest BEFORE any call, writes the RAW answer to disk
BEFORE parsing it, records usage verbatim, never auto-retries an unknown
outcome, and supports B and C contracts on the SAME view (only the output
contract differs).

Real provider calls require BOTH an explicit ``--authorize-real-call`` flag
AND a frozen-model marker file (``.local/experiments/frozen-model.json``).
Neither exists in this phase, so the real path refuses by default and every
acceptance runs through an injected stub provider.  Nothing here revives the
old G2 ledger; blocked runs never consume a slot.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
import threading
import fcntl
from contextlib import contextmanager
from functools import wraps
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .brief_business_view import VIEW_SYSTEM_PROMPT_FREE, adapt_answer, view_request
from .brief_fact_catalog import validate_fact_catalog
from .evidence_linked_brief import parse_response, render_pending
from .exposure_version_store import VersionStoreError

RUN_SCHEMA = "provider-run-manifest-v1"
LEDGER_SCHEMA = "provider-ledger-v1"
TOTAL_SLOTS = 14
INPUT_HARD_TOKENS = 16000
OUTPUT_MAX_TOKENS = 2000
OUTPUT_MAX_BYTES = 65536  # Independent parser/text safety bound, not a token estimate.


def output_budget(raw_text, usage):
    """Prefer reported completion tokens; estimates are fallback, not billing."""
    from scripts.prepare_brief_v3_offline import estimate_input_tokens
    estimate = estimate_input_tokens([{"content": raw_text}])
    actual = usage.get('completion_tokens') if isinstance(usage, dict) else None
    valid = type(actual) is int and actual >= 0 and (actual > 0 or not raw_text)
    count = actual if valid else int(estimate['tokens'])
    size = len(raw_text.encode('utf-8'))
    return {'tokens': count, 'method': 'provider_completion_tokens' if valid else 'fallback_estimate',
            'estimate': estimate, 'utf8_bytes': size, 'max_bytes': OUTPUT_MAX_BYTES,
            'within_gate': count <= OUTPUT_MAX_TOKENS and size <= OUTPUT_MAX_BYTES}
DEFAULT_TIMEOUT = 90
CONSUMING_EVENTS = ("started", "completed", "unknown_outcome", "failed_billed",
                    "blocked_output_budget")
_BLOCKING_FOR_DEDUP = ("started", "completed", "unknown_outcome", "resolved_mark_failed",
                       "blocked_output_budget", "invalid_response", "failed_billed")
_LEDGER_LOCK = threading.RLock()
_LOCK_STATE = threading.local()
_DEFAULT_EXPERIMENT_ID = "legacy"
_DEFAULT_PROVIDER_KIND = "shared"


def _safe_key(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 80:
        raise ValueError(f"{label} must be a non-empty key of at most 80 characters")
    if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in value):
        raise ValueError(f"{label} contains unsafe characters")
    return value


def _ledger_context() -> tuple[str, str]:
    return (getattr(_LOCK_STATE, "experiment_id", _DEFAULT_EXPERIMENT_ID),
            getattr(_LOCK_STATE, "provider_kind", _DEFAULT_PROVIDER_KIND))


def _locked(function):
    @wraps(function)
    def wrapped(root, *args, **kwargs):
        # Deliberately serialize experiments, including the bounded provider call.
        # Nested ledger writes reuse the same cross-process lock. Explicit S3
        # runs get a separate ledger for stub and real providers; old callers
        # retain the legacy shared file.
        requested = kwargs.get("experiment_id")
        if requested is None and hasattr(_LOCK_STATE, "experiment_id"):
            experiment_id, provider_kind = _ledger_context()
        elif requested is None:
            experiment_id, provider_kind = _DEFAULT_EXPERIMENT_ID, _DEFAULT_PROVIDER_KIND
        else:
            experiment_id = _safe_key(requested, "experiment_id")
            provider_kind = "stub" if kwargs.get("provider") is not None else "real"
        previous = _ledger_context()
        _LOCK_STATE.experiment_id = experiment_id
        _LOCK_STATE.provider_kind = provider_kind
        try:
            with _ledger_lock(root):
                return function(root, *args, **kwargs)
        finally:
            _LOCK_STATE.experiment_id, _LOCK_STATE.provider_kind = previous
    return wrapped


@contextmanager
def _ledger_lock(root):
    with _LEDGER_LOCK:
        path = ledger_path(root).with_suffix('.lock')
        key = str(path.resolve())
        held = getattr(_LOCK_STATE, 'held', set())
        if key in held:
            yield
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            _LOCK_STATE.held = held | {key}
            try:
                yield
            finally:
                _LOCK_STATE.held = held
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _consumed_slots(ledger):
    # A later resolution cannot undo an earlier reservation/call attempt.
    return len({e['run_id'] for e in ledger.get('events', [])
                if e.get('event') in CONSUMING_EVENTS})


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def experiments_dir(root: Path) -> Path:
    return Path(root) / ".local" / "experiments"


def ledger_path(root: Path) -> Path:
    experiment_id, provider_kind = _ledger_context()
    if experiment_id == _DEFAULT_EXPERIMENT_ID and provider_kind == _DEFAULT_PROVIDER_KIND:
        return experiments_dir(root) / "provider-ledger.json"
    _safe_key(experiment_id, "experiment_id")
    _safe_key(provider_kind, "provider_kind")
    return experiments_dir(root) / f"provider-ledger-{experiment_id}-{provider_kind}.json"


def frozen_marker_path(root: Path, *, experiment_id: str | None = None) -> Path:
    if experiment_id is None or experiment_id == _DEFAULT_EXPERIMENT_ID:
        return experiments_dir(root) / "frozen-model.json"
    return experiments_dir(root) / f"{_safe_key(experiment_id, 'experiment_id')}-frozen-model.json"


def load_ledger(root: Path, *, experiment_id: str | None = None,
                provider_kind: str | None = None) -> dict[str, Any]:
    if experiment_id is not None:
        _LOCK_STATE.experiment_id = _safe_key(experiment_id, "experiment_id")
    if provider_kind is not None:
        _LOCK_STATE.provider_kind = _safe_key(provider_kind, "provider_kind")
    path = ledger_path(root)
    if not path.is_file():
        return {"schema_version": LEDGER_SCHEMA, "total_slots": TOTAL_SLOTS, "events": []}
    ledger = json.loads(path.read_text(encoding="utf-8"))
    if ledger.get("schema_version") != LEDGER_SCHEMA:
        raise ValueError("provider ledger schema mismatch; refusing to touch it")
    return ledger


def _save_ledger(root: Path, ledger: dict[str, Any]) -> None:
    path = ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".provider-ledger.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _latest_event_by_run(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in ledger.get("events", []):
        latest[event["run_id"]] = event
    return latest


@_locked
def ledger_remaining_slots(root: Path, *, experiment_id: str | None = None,
                           provider_kind: str | None = None) -> int:
    ledger = load_ledger(root, experiment_id=experiment_id, provider_kind=provider_kind)
    consumed = _consumed_slots(ledger)
    return int(ledger.get("total_slots", TOTAL_SLOTS)) - consumed


@_locked
def append_ledger_event(root: Path, event: dict[str, Any]) -> None:
    ledger = load_ledger(root)
    event = {**event, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    ledger["events"].append(event)
    _save_ledger(root, ledger)


@_locked
def resolve_unknown_run(root: Path, run_id: str, *, resolution: str,
                        decided_by: str, note: str | None = None,
                        experiment_id: str | None = None,
                        provider_kind: str | None = None) -> dict[str, Any]:
    """Human decision for a run whose provider outcome is unknown.

    ``resolved_retry_authorized`` allows a NEW run with the same request (the
    unknown run stays consuming its slot for audit); ``resolved_mark_failed``
    closes it.  This is the only path out of ``unknown_outcome``.
    """
    if resolution not in ("resolved_retry_authorized", "resolved_mark_failed"):
        raise ValueError("resolution must be resolved_retry_authorized or resolved_mark_failed")
    ledger = load_ledger(root, experiment_id=experiment_id, provider_kind=provider_kind)
    latest = _latest_event_by_run(ledger).get(run_id)
    if not latest or latest.get("event") != "unknown_outcome":
        raise ValueError("run is not in unknown_outcome state")
    append_ledger_event(root, {"run_id": run_id, "event": resolution,
                               "decided_by": decided_by, "note": note,
                               "request_digest": latest.get("request_digest"),
                               "contract": latest.get("contract"),
                               "model": latest.get("model")})
    return {"status": resolution, "run_id": run_id}


def _load_view_package(package: Path, *, contract: str = "C") -> tuple[dict, dict, dict, list[dict[str, str]]]:
    from scripts.run_fake_experiment import _verify_package
    from .brief_business_view import restore, business_payload
    manifest, _required = _verify_package(package)
    is_e = manifest.get('protocol') == 'host-bound-explanation-v1'
    if (contract == 'E') != is_e:
        raise ValueError('package protocol does not match selected contract')
    if is_e:
        required = {'catalog.json', 'business-view.json', 'business-view-sidecar.json',
                    'messages.json', 'program-report-A3.zh-CN.md', 'host-bindings.json'}
        hashes = manifest.get('artifact_files_sha256', {})
        if not required <= set(hashes):
            raise ValueError('incomplete E artifact hashes')
        for name in required:
            if not (package / name).is_file() or _sha_bytes(package / name) != hashes[name]:
                raise ValueError('E artifact missing or changed: ' + name)
    catalog = json.loads((package / "catalog.json").read_text(encoding="utf-8"))
    validate_fact_catalog(catalog)
    view = json.loads((package / "business-view.json").read_text(encoding="utf-8"))
    sidecar = json.loads((package / "business-view-sidecar.json").read_text(encoding="utf-8"))
    binding = (view.get("policy") or {}).get("catalog_sha256")
    if binding != catalog.get("catalog_sha256"):
        raise ValueError("view is not bound to this catalog")
    if manifest.get("binding", {}).get("view_catalog_sha256") != binding:
        raise ValueError("manifest binding does not match the view")
    if restore(view, sidecar) != business_payload(catalog):
        raise ValueError("view does not restore the complete catalog business payload")
    messages = json.loads((package / "messages.json").read_text(encoding="utf-8"))
    if contract == "E":
        from .bounded_explanation import messages as bounded_messages, slots
        if manifest.get('question') != view.get('question'):
            raise ValueError('E question binding mismatch')
        if json.loads((package / 'host-bindings.json').read_text()) != slots(catalog):
            raise ValueError('host bindings differ from catalog')
        from .brief_fact_catalog import render_fact_catalog
        if (package / 'program-report-A3.zh-CN.md').read_text() != render_fact_catalog(catalog):
            raise ValueError('E program report differs from catalog')
        if messages != bounded_messages(manifest.get("question"), catalog):
            raise ValueError("actual request does not match the complete view and E contract")
    elif messages != view_request(view):
        raise ValueError("actual request does not match the complete view and C contract")
    return manifest, view, sidecar, catalog


def _build_real_provider(root, frozen, timeout):
    """Build a bounded provider from reviewed settings; never persist credentials."""
    from .local_provider_config import load_config
    from .model_adapter import OpenAICompatibleConfig, OpenAICompatibleModel, _endpoint
    params = frozen.get('params')
    if not isinstance(params, dict) or set(params) != {'temperature', 'max_tokens', 'thinking'}:
        raise ValueError('frozen params require exactly temperature, max_tokens, thinking')
    temperature = params['temperature']
    maximum = params['max_tokens']
    if type(temperature) not in (int, float) or not 0 <= temperature <= 2:
        raise ValueError('invalid frozen temperature')
    if type(maximum) is not int or not 1 <= maximum <= OUTPUT_MAX_TOKENS:
        raise ValueError('invalid frozen max_tokens')
    if params['thinking'] != {'type': 'disabled'}:
        raise ValueError('this executor requires frozen thinking disabled')
    if type(timeout) not in (int, float) or not 0 < timeout <= DEFAULT_TIMEOUT:
        raise ValueError('timeout must be within the reviewed 90 second ceiling')
    if not isinstance(frozen.get('model'), str) or not frozen['model'].strip():
        raise ValueError('frozen model required')
    if not isinstance(frozen.get('endpoint'), str) or not frozen['endpoint'].strip():
        raise ValueError('frozen endpoint required')
    config = load_config(Path(root) / '.local' / 'glm.json')
    if _endpoint(config.base_url) != _endpoint(frozen['endpoint']):
        raise ValueError('local credential endpoint differs from frozen endpoint')

    class FrozenModel(OpenAICompatibleModel):
        def _payload(self, *, messages, tools):
            payload = super()._payload(messages=messages, tools=tools)
            payload.update(params)
            return payload

    client = FrozenModel(OpenAICompatibleConfig(
        base_url=config.base_url, model=frozen['model'], api_key=config.api_key,
        timeout_seconds=timeout, temperature=temperature), system_prompt='')

    def call(*, messages, timeout):
        response = client.complete(messages=messages, tools=[])
        return response.text, response.metadata.get('usage', {})
    return call


def verify_development_review(root, frozen, ledger, record):
    """Validate a local reviewer decision against this experiment's real runs.

    This validates provenance and explicit scores, not the truth of a human
    judgment. The freeze fixes only the review path; the later review binds
    its freeze hash, so approval never requires mutating a running freeze.
    """
    freeze_sha = _sha256_text(_canonical(frozen))
    if not isinstance(record, dict) or record.get('schema') != 's3-development-gate-v1' \
            or record.get('status') != 'approved' or record.get('freeze_sha256') != freeze_sha \
            or record.get('experiment_id') != frozen.get('experiment_id'):
        raise ValueError('invalid or cross-experiment D1 development gate')
    if not isinstance(record.get('reviewer'), str) or not record['reviewer'].strip():
        raise ValueError('D1 reviewer is required')
    for key in ('hard_checks', 'gain_checks'):
        values = record.get(key)
        if not isinstance(values, list) or len(values) != 3 \
                or any(type(v) is not int or v not in (0, 1) for v in values):
            raise ValueError('invalid D1 review scores')
    if any(record['hard_checks']) or sum(record['gain_checks']) < 2:
        raise ValueError('D1 review did not pass')
    development = [e for e in frozen['allowed_runs'] if e.get('stage') == 'development']
    if len(development) != 2 or {e['contract'] for e in development} != {'B', 'C'} \
            or len({str((Path(root)/e['package']).resolve()) for e in development}) != 1:
        raise ValueError('D1 requires B/C on the same frozen package')
    runs = record.get('d1_runs')
    if not isinstance(runs, list) or len(runs) != 2:
        raise ValueError('D1 requires two reviewed runs')
    seen = set()
    for ref in runs:
        if not isinstance(ref, dict) or ref.get('contract') not in {'B', 'C'} \
                or ref['contract'] in seen:
            raise ValueError('invalid D1 run references')
        seen.add(ref['contract'])
        path = Path(root) / ref.get('run_manifest', '')
        if not path.is_file() or _sha_bytes(path) != ref.get('run_manifest_sha256'):
            raise ValueError('reviewed D1 manifest changed')
        run = json.loads(path.read_text(encoding='utf-8'))
        entry = next(e for e in development if e['contract'] == ref['contract'])
        if run.get('status') != 'completed' or run.get('provider_kind') != 'real' \
                or run.get('experiment_id') != frozen['experiment_id'] \
                or run.get('freeze_sha256') != freeze_sha or run.get('contract') != entry['contract'] \
                or run.get('package') != str((Path(root)/entry['package']).resolve()) \
                or run.get('package_manifest_sha256') != entry['manifest_sha256']:
            raise ValueError('D1 run is not a completed bound real response')
        events = [e for e in ledger.get('events', []) if e.get('run_id') == run.get('run_id')]
        starts = [e for e in events if e.get('event') == 'started']
        if len(starts) != 1 or starts[0].get('freeze_sha256') != freeze_sha \
                or Path(starts[0].get('output_dir', '')).resolve() != path.parent.resolve() \
                or not events or events[-1].get('event') != 'completed':
            raise ValueError('D1 run not confirmed by the real experiment ledger')
        raw = path.parent / 'raw-response.json'
        if not raw.is_file() or _sha_bytes(raw) != run.get('artifact_files_sha256', {}).get('raw-response.json'):
            raise ValueError('reviewed D1 raw answer changed')
    return freeze_sha


def _verify_named_freeze(root, frozen, experiment_id, package, contract, ledger):
    """Fail closed for new real experiments; legacy frozen runs stay untouched.

    Called under the experiment lock, before credentials/client construction
    and before a slot reservation. Hashes bind local reviewed artifacts, not
    an authenticity claim about untrusted input.
    """
    if frozen.get('schema_version') != 'bounded-provider-freeze-v1':
        raise ValueError('named real experiment requires a bounded freeze')
    if frozen.get('experiment_id') != experiment_id:
        raise ValueError('frozen experiment identity mismatch')
    limit = frozen.get('max_calls')
    if type(limit) is not int or not 1 <= limit <= 5:
        raise ValueError('frozen call budget must be between 1 and 5')
    runtime = frozen.get('runtime_sha256')
    required = ('src/tradeintel_ai/provider_executor.py',
                'src/tradeintel_ai/brief_business_view.py',
                'src/tradeintel_ai/evidence_linked_brief.py',
                'src/tradeintel_ai/model_adapter.py',
                'scripts/run_fake_experiment.py',
                'scripts/prepare_brief_v3_offline.py')
    if contract == 'E':
        required += ('src/tradeintel_ai/bounded_explanation.py',
                     'src/tradeintel_ai/response_contract.py',
                     'src/tradeintel_ai/brief_fact_catalog.py',
                     'scripts/prepare_bounded_explanation.py')
        entries = frozen.get('allowed_runs')
        if (limit != 1 or not isinstance(entries, list) or len(entries) != 1
                or entries[0].get('contract') != 'E' or entries[0].get('stage') != 'development'):
            raise ValueError('E currently permits one development call only')
    if not isinstance(runtime, dict) or set(runtime) != set(required):
        raise ValueError('freeze must bind the required runtime files')
    for name in required:
        path = Path(root) / name
        if not path.is_file() or _sha_bytes(path) != runtime[name]:
            raise ValueError('frozen runtime changed: ' + name)
    entries = frozen.get('allowed_runs')
    if not isinstance(entries, list) or not entries or len(entries) > limit:
        raise ValueError('invalid frozen run allowlist')
    seen = set()
    match = None
    for entry in entries:
        if not isinstance(entry, dict) or entry.get('contract') not in ('B', 'C', 'E'):
            raise ValueError('invalid frozen run entry')
        if entry.get('stage', 'formal') not in ('development', 'formal'):
            raise ValueError('invalid frozen run stage')
        candidate = (Path(root) / entry['package']).resolve()
        key = (str(candidate), entry['contract'])
        if key in seen:
            raise ValueError('duplicate frozen run entry')
        seen.add(key)
        for path, digest in ((candidate / 'manifest.json', entry.get('manifest_sha256')),
                             (Path(root) / entry['reference'], entry.get('reference_sha256'))):
            if not path.is_file() or not isinstance(digest, str) or _sha_bytes(path) != digest:
                raise ValueError('frozen package or reference changed')
        if key == (str(Path(package).resolve()), contract):
            match = entry
    if match is None:
        raise ValueError('request is not in the frozen allowlist')
    if match.get('stage', 'formal') == 'formal':
        gate = frozen.get('development_gate')
        if not isinstance(gate, dict) or not isinstance(gate.get('path'), str) or not gate['path']:
            raise ValueError('formal runs require approved D1 development gate')
        gate_path = Path(root) / gate.get('path', '')
        if not gate_path.is_file():
            raise ValueError('D1 development gate is missing')
        verify_development_review(root, frozen, ledger,
                                  json.loads(gate_path.read_text(encoding='utf-8')))
    freeze_sha = _sha256_text(_canonical(frozen))
    starts = [e for e in ledger.get('events', []) if e.get('event') == 'started']
    if any(e.get('freeze_sha256') != freeze_sha for e in starts):
        raise ValueError('freeze changed after an attempt; do not reuse this experiment')
    if _consumed_slots(ledger) >= limit:
        raise ValueError('frozen call budget exhausted')
    if any(e.get('frozen_run_key') == str(Path(package).resolve()) + ':' + contract for e in starts):
        raise ValueError('frozen run already attempted; no automatic or resolved retry')
    return freeze_sha


@_locked
def run_experiment(root: Path, *, package: Path, contract: str, output: Path,
                   provider: Callable[..., tuple[str, dict[str, Any]]] | None = None,
                   authorize_real_call: bool = False,
                   timeout: int = DEFAULT_TIMEOUT,
                   experiment_id: str | None = None) -> dict[str, Any]:
    """Run one B or C experiment against the package with the given provider.

    ``provider(messages, timeout) -> (raw_text, usage)``.  When ``provider``
    is None the real model_adapter path is considered, but it refuses unless
    the frozen-model marker exists AND ``authorize_real_call`` is set.
    """
    if contract not in ("B", "C", "E"):
        raise ValueError("contract must be B, C or E")
    manifest, view, sidecar, catalog = _load_view_package(package, contract=contract)
    if contract in ("C", "E"):
        messages = json.loads((package / "messages.json").read_text(encoding="utf-8"))
    else:
        # Same view, same evidence, only the output contract differs.
        messages = view_request(view, system_prompt=VIEW_SYSTEM_PROMPT_FREE)
    from scripts.prepare_brief_v3_offline import estimate_input_tokens
    input_estimate = estimate_input_tokens(messages)
    input_messages_sha256 = _sha256_text(_canonical(messages))
    view_sha256 = _sha256_text(_canonical(view))
    provider_kind = 'stub' if provider is not None else 'real'
    experiment_key = experiment_id or _DEFAULT_EXPERIMENT_ID
    request_digest = hashlib.sha256(_canonical({
        "experiment_id": experiment_key, "provider_kind": provider_kind,
        "request": manifest.get("question"), "contract": contract,
        "view_sha256": view_sha256}).encode("utf-8")).hexdigest()

    ledger = load_ledger(root)
    for run_id, event in _latest_event_by_run(ledger).items():
        if event.get("request_digest") == request_digest and event.get("contract") == contract \
                and event.get("event") in _BLOCKING_FOR_DEDUP:
            return {"status": "refused_duplicate_run", "run_id": run_id,
                    "reason": "同一请求+合同已有进行中或完成的运行；不能重复调用（先处理unknown_outcome才能重试）。"}
    consumed = _consumed_slots(ledger)
    remaining = int(ledger.get("total_slots", TOTAL_SLOTS)) - consumed
    if int(input_estimate.get("tokens", 0)) > INPUT_HARD_TOKENS:
        append_ledger_event(root, {"run_id": "n/a-blocked", "event": "blocked_budget",
                                   "contract": contract, "request_digest": request_digest,
                                   "input_estimate": input_estimate["tokens"],
                                   "boundary": "超硬门不耗槽；不删除任何法律条件。"})
        return {"status": "blocked_hard_budget", "input_estimate": input_estimate,
                "boundary": "超硬门停止，不删除任何法律条件，返回冻结决定方。"}
    if remaining <= 0:
        return {"status": "refused_no_slots", "remaining_slots": 0,
                "reason": "实验槽位已用尽；需要冻结决定方批准新预算。"}
    frozen = None
    freeze_sha = None
    if provider is None:
        if contract == 'E' and experiment_key == _DEFAULT_EXPERIMENT_ID:
            return {'status': 'real_call_not_authorized', 'reason': 'E requires an isolated named experiment'}
        marker = frozen_marker_path(root, experiment_id=experiment_key)
        if not marker.is_file() or not authorize_real_call:
            return {"status": "real_call_not_authorized",
                    "reason": "模型未冻结或未显式授权；真实调用被拒绝（需要冻结标记+authorize_real_call）。"}
        frozen = json.loads(marker.read_text(encoding="utf-8"))
        if not isinstance(frozen, dict):
            raise ValueError('frozen configuration must be an object')
        if experiment_key != _DEFAULT_EXPERIMENT_ID:
            freeze_sha = _verify_named_freeze(root, frozen, experiment_key,
                                             package, contract, ledger)
        provider = _build_real_provider(root, frozen, timeout)
        model, endpoint = frozen["model"], frozen["endpoint"]
    else:
        model, endpoint = getattr(provider, "model_name", "stub"), "injected-stub"

    run_id = "prov-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    if output.exists():
        raise ValueError(f"refusing to overwrite existing run directory: {output}")
    output.mkdir(parents=True)
    # The started manifest is persisted BEFORE any provider call.
    run_manifest: dict[str, Any] = {
        "schema_version": RUN_SCHEMA, "run_id": run_id, "status": "started",
        "contract": contract, "model": model, "endpoint": endpoint,
        "provider_kind": provider_kind,
        "experiment_id": experiment_key,
        "frozen_params": frozen.get('params') if frozen else None,
        "freeze_sha256": freeze_sha,
        "package": str(package.resolve()),
        "package_manifest_sha256": _sha256_text((package / "manifest.json").read_text(encoding="utf-8")),
        "catalog_sha256": catalog["catalog_sha256"], "view_sha256": view_sha256,
        "request_digest": request_digest,
        "input_messages_sha256": input_messages_sha256,
        "input_estimate": input_estimate, "api_calls": 0, "usage": None,
        "budgets": {"input_hard_tokens": INPUT_HARD_TOKENS,
                    "output_max_tokens": OUTPUT_MAX_TOKENS, "timeout_seconds": timeout},
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "boundary": "原答先落盘再解析；unknown结果不自动重试；usage原样记录。",
    }
    _write_manifest(output, run_manifest)
    append_ledger_event(root, {"run_id": run_id, "event": "started", "contract": contract,
                               "freeze_sha256": freeze_sha,
                               "frozen_run_key": str(Path(package).resolve()) + ':' + contract,
                               "model": model, "endpoint": endpoint,
                               "request_digest": request_digest,
                               "input_messages_sha256": input_messages_sha256,
                               "input_estimate": input_estimate["tokens"],
                               "output_dir": str(output)})

    try:
        raw_text, usage = provider(messages=messages, timeout=timeout)
    except Exception as exc:  # timeout / network / provider error: outcome unknown
        from .model_adapter import safe_error_details
        run_manifest["status"] = "unknown_outcome"
        run_manifest["api_calls"] = 1
        run_manifest["error"] = f"{type(exc).__name__}: provider outcome unknown"
        run_manifest["error_details"] = safe_error_details(exc)
        run_manifest["completed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _write_manifest(output, run_manifest)
        append_ledger_event(root, {"run_id": run_id, "event": "unknown_outcome",
                                   "contract": contract, "model": model,
                                   "request_digest": request_digest,
                                   "error": run_manifest["error"],
                                   "error_details": run_manifest["error_details"],
                                   "api_calls": 1,
                                   "boundary": "未知结果不自动重试；需人工决定（resolved_*）。"})
        return {"status": "unknown_outcome", "run_id": run_id, "error": run_manifest["error"],
                "error_details": run_manifest["error_details"]}

    run_manifest["api_calls"] = 1
    run_manifest["usage"] = deepcopy_usage(usage)
    # RAW answer hits the disk BEFORE any parsing.
    raw_path = output / "raw-response.json"
    raw_path.write_text(raw_text if isinstance(raw_text, str) else json.dumps(raw_text, ensure_ascii=False),
                        encoding="utf-8")
    budget = output_budget(raw_text, usage)
    output_estimate = budget['estimate']
    run_manifest["output_estimate"] = output_estimate
    run_manifest['output_budget'] = budget
    run_manifest["output_within_gate"] = budget['within_gate']
    artifacts = {"raw-response.json": _sha_bytes(raw_path)}
    run_manifest['status'] = 'response_saved'
    run_manifest['artifact_files_sha256'] = artifacts
    _write_manifest(output, run_manifest)
    parse_failed = False
    if not run_manifest['output_within_gate']:
        run_manifest['validation_status'] = 'not_parsed_over_budget'
    elif contract == "C":
        try:
            from .response_contract import parse_json_response
            answer_view = parse_json_response(raw_text)
            converted = adapt_answer(answer_view, view, sidecar, catalog)
            parsed = parse_response(json.dumps(converted, ensure_ascii=False) + "\n", catalog)
            converted_path = output / "answer.converted.json"
            converted_path.write_text(json.dumps(converted, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
            report_path = output / "pending-report.zh-CN.md"
            report_path.write_text(render_pending(converted, catalog, parsed["validation"]),
                                   encoding="utf-8")
            run_manifest["validation_status"] = parsed["validation"]["status"]
            run_manifest["coverage"] = parsed["validation"]["task_coverage"]
            artifacts["answer.converted.json"] = _sha_bytes(converted_path)
            artifacts["pending-report.zh-CN.md"] = _sha_bytes(report_path)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            parse_failed = True
            run_manifest['validation_status'] = 'invalid_response'
            run_manifest['error'] = f'{type(exc).__name__}: response contract rejected'
    elif contract == "E":
        try:
            from .bounded_explanation import parse as parse_bounded
            parsed = parse_bounded(raw_text, catalog)
            converted_path = output / "bounded-answer.json"
            converted_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
            report_path = output / "pending-explanation.zh-CN.md"
            report_path.write_text(
                "# AI解释附件（待人工审阅）\n\n" + parsed["boundary"] + "\n\n" +
                json.dumps(parsed["answer"], ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            run_manifest["validation_status"] = parsed["status"]
            run_manifest["coverage"] = parsed["validation"]["task_coverage"]
            run_manifest["semantic_flags"] = parsed["flags"]
            run_manifest['approved'] = False
            artifacts["bounded-answer.json"] = _sha_bytes(converted_path)
            artifacts["pending-explanation.zh-CN.md"] = _sha_bytes(report_path)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            parse_failed = True
            run_manifest['validation_status'] = 'invalid_response'
            run_manifest['error'] = f'{type(exc).__name__}: bounded explanation rejected'
    else:
        run_manifest["validation_status"] = "free_form_manual_review_required"
        note_path = output / "manual-review-note.md"
        note_path.write_text(
            "# B合同回答（自由格式，未做程序校验）\n\n原答已原样保存于 raw-response.json；"
            "B回答不经过结构校验，人工审阅判断是否越界或引用缺失。\n", encoding="utf-8")
        artifacts["manual-review-note.md"] = _sha_bytes(note_path)

    if not run_manifest["output_within_gate"]:
        run_manifest["status"] = "blocked_output_budget"
    elif parse_failed:
        run_manifest['status'] = 'invalid_response'
    else:
        run_manifest["status"] = "completed"
    run_manifest["completed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run_manifest["artifact_files_sha256"] = artifacts
    _write_manifest(output, run_manifest)
    append_ledger_event(root, {"run_id": run_id, "event": run_manifest["status"],
                               "contract": contract, "model": model,
                               "request_digest": request_digest,
                               "usage": deepcopy_usage(usage),
                               "output_estimate": output_estimate.get("tokens"),
                               "output_budget": budget,
                               "api_calls": 1})
    return {"status": run_manifest["status"], "run_id": run_id,
            "manifest": run_manifest}


def deepcopy_usage(usage: Any) -> Any:
    return json.loads(_canonical(usage)) if usage is not None else None


def _sha_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(output: Path, manifest: dict[str, Any]) -> None:
    path = output / "run-manifest.json"
    handle, temporary = tempfile.mkstemp(dir=str(output), prefix=".run-manifest.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
