"""Execute the single real strict-tool capability probe.

The probe is deliberately separate from the old policy-extraction ledgers. It
uses the frozen structured profile, saves a start record before the request and
the raw provider bytes before parsing, and never retries or enables a policy
candidate. A successful response is still only a transport result; semantic
quality is not scored on the development notice.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import urllib.error
import urllib.request
from typing import Any

from scripts.prepare_policy_extraction_schema_request import verify_profile
from scripts.prepare_policy_extraction_schema_v2_request import verify_profile as verify_profile_v2
from tradeintel_ai.announcement_extraction_pilot import adapt_suggestion
from tradeintel_ai.announcement_extraction_schema import (
    parse_tool_response,
    normalise_transport_answer,
)
from tradeintel_ai.announcement_extraction_transport_v2 import (
    CONTRACT_VERSION as TRANSPORT_V2_VERSION,
    complete_hts_code_evidence_v2,
    normalise_transport_answer_v2,
)
from tradeintel_ai.local_provider_config import load_product_config, product_status


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "tmp/policy-extraction-schema-20260927/r2-strict-tool-v3"
LEDGER_ROOT = ROOT / ".local/experiments/policy-extraction-schema-probe-v1"
FREEZE_MARKER = LEDGER_ROOT / "frozen-model.json"
MAX_RESPONSE_BYTES = 1_000_000
TIMEOUT_SECONDS = 90
LOCAL_BUDGET_USD = 0.05
INPUT_PRICE_PER_MILLION = 0.30
OUTPUT_PRICE_PER_MILLION = 1.20


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read(path: Path) -> dict[str, Any] | None:
    if path.is_symlink() or not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > 2_000_000:
        raise ValueError("invalid probe record")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("probe record must be an object")
    return value


def _atomic(path: Path, value: dict[str, Any]) -> None:
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=".schema-probe-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _save_raw(path: Path, data: bytes) -> str:
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("provider response exceeds safe storage limit")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(data).hexdigest()


def _usage_cost(usage: dict[str, Any]) -> float | None:
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if type(prompt) is not int or type(completion) is not int or prompt < 0 or completion < 0:
        return None
    return round((prompt * INPUT_PRICE_PER_MILLION +
                  completion * OUTPUT_PRICE_PER_MILLION) / 1_000_000, 8)


def _provider_metadata(raw: bytes) -> dict[str, Any]:
    """Read safe envelope metadata before validating tool arguments.

    A malformed tool-arguments string must not erase provider usage from the
    experiment ledger.  Duplicate keys in the outer response are rejected;
    this helper deliberately does not inspect or repair tool arguments.
    """
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate provider response key")
            result[key] = value
        return result

    try:
        provider = json.loads(raw, object_pairs_hook=no_duplicates,
                              parse_constant=lambda token: (_ for _ in ()).throw(
                                  ValueError(f"invalid JSON constant: {token}")))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("provider response metadata is not valid JSON") from exc
    if not isinstance(provider, dict):
        raise ValueError("provider response metadata must be an object")
    metadata: dict[str, Any] = {}
    if isinstance(provider.get("model"), str):
        metadata["response_model"] = provider["model"]
    choices = provider.get("choices")
    if isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], dict) \
            and isinstance(choices[0].get("finish_reason"), str):
        metadata["finish_reason"] = choices[0]["finish_reason"]
    usage = provider.get("usage")
    if isinstance(usage, dict):
        prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
        if type(prompt) is int and type(completion) is int and prompt >= 0 and completion >= 0:
            metadata["usage"] = {"prompt_tokens": prompt, "completion_tokens": completion}
            total = usage.get("total_tokens")
            if type(total) is int and total >= 0:
                metadata["usage"]["total_tokens"] = total
            metadata["peak_cost_estimate_usd"] = _usage_cost(metadata["usage"])
        else:
            metadata["usage_status"] = "malformed_in_provider_response"
    return metadata


def _private_root() -> Path:
    if LEDGER_ROOT.exists() and LEDGER_ROOT.is_symlink():
        raise ValueError("unsafe probe ledger path")
    LEDGER_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    if LEDGER_ROOT.stat().st_mode & 0o077:
        os.chmod(LEDGER_ROOT, 0o700)
    return LEDGER_ROOT


def configure(*, profile: Path | None = None, experiment_dir: Path | None = None,
              freeze_marker: Path | None = None) -> None:
    """Select a new independently versioned probe without changing old ledgers."""
    global PROFILE, LEDGER_ROOT, FREEZE_MARKER
    if profile is not None:
        PROFILE = profile.resolve()
    if experiment_dir is not None:
        LEDGER_ROOT = experiment_dir.resolve()
    FREEZE_MARKER = (freeze_marker.resolve() if freeze_marker is not None
                     else LEDGER_ROOT / "frozen-model.json")


def _load_profile() -> tuple[dict[str, Any], dict[str, Any], bytes, Path]:
    profile_record = json.loads((PROFILE / "profile.json").read_text(encoding="utf-8"))
    verifier = (verify_profile_v2
                if profile_record.get("schema_version") == TRANSPORT_V2_VERSION
                else verify_profile)
    profile = verifier(PROFILE)
    body = json.loads((PROFILE / "provider-body.json").read_text(encoding="utf-8"))
    encoded = json.dumps(body, ensure_ascii=False, allow_nan=False,
                         separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(encoded).hexdigest() != profile_record["body_sha256"] \
            or len(encoded) != profile_record["body_bytes"]:
        raise ValueError("frozen provider body changed")
    if profile_record.get("endpoint") != "https://api.deepseek.com/beta/chat/completions":
        raise ValueError("probe is not bound to the DeepSeek beta endpoint")
    return profile, profile_record, encoded, Path(profile_record["base_package"])


def _verify_freeze(profile_record: dict[str, Any]) -> dict[str, Any]:
    freeze = _read(FREEZE_MARKER)
    if freeze is None:
        raise ValueError("capability probe freeze marker is missing")
    expected = {
        "profile": str(PROFILE.relative_to(ROOT)),
        "endpoint": profile_record["endpoint"],
        "model": profile_record["model"],
        "thinking": "disabled",
        "max_tokens": 8192,
        "tool_choice": "submit_policy_fields",
        "parallel_tool_calls": False,
        "one_call_only": True,
        "local_budget_usd": LOCAL_BUDGET_USD,
        "on_failure": "stop_without_retry",
    }
    if any(freeze.get(key) != value for key, value in expected.items()):
        raise ValueError("capability probe freeze marker differs from the profile")
    return freeze


def _config() -> Any:
    config = load_product_config()
    status = product_status()
    if not config.api_key or status.get("provider") != "deepseek" \
            or config.model != "deepseek-flash":
        raise ValueError("local DeepSeek Flash credentials/model are not available")
    return config


def _post(endpoint: str, body: bytes, api_key: str) -> bytes:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            raise ValueError("provider redirect refused")

    request = urllib.request.Request(
        endpoint, data=body,
        headers={"Authorization": "Bearer " + api_key,
                 "Content-Type": "application/json"}, method="POST")
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise ValueError("provider did not return HTTP 200")
        data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("provider response exceeds safe storage limit")
    return data


def check() -> dict[str, Any]:
    profile, profile_record, body, _ = _load_profile()
    freeze = _verify_freeze(profile_record)
    _config()
    root = _private_root()
    existing = _read(root / "ledger.json")
    return {"status": "preflight_passed", "profile": str(PROFILE),
            "body_bytes": len(body), "body_sha256": profile_record["body_sha256"],
            "endpoint": profile_record["endpoint"], "model": profile_record["model"],
            "ledger_status": existing.get("status") if existing else "not_started",
            "api_calls": 0, "local_budget_usd": LOCAL_BUDGET_USD,
            "input_token_estimate": profile_record["input_token_estimate"],
            "freeze_schema_version": freeze.get("schema_version")}


def run_once() -> dict[str, Any]:
    profile, profile_record, body, base_package = _load_profile()
    _verify_freeze(profile_record)
    config = _config()
    root = _private_root()
    ledger = root / "ledger.json"
    raw_path = root / "response.json"
    draft_path = root / "draft.json"
    if _read(ledger) is not None or raw_path.exists() or draft_path.exists():
        raise ValueError("capability probe already has an attempt; never retry or overwrite")
    record: dict[str, Any] = {
        "schema_version": "policy-extraction-schema-probe-v1",
        "status": "provider_call_started",
        "started_at_utc": _now(),
        "profile": str(PROFILE),
        "profile_sha256": hashlib.sha256((PROFILE / "manifest.json").read_bytes()).hexdigest(),
        "endpoint": profile_record["endpoint"],
        "model": profile_record["model"],
        "thinking": "disabled",
        "tool_choice": "submit_policy_fields",
        "body_bytes": len(body),
        "body_sha256": profile_record["body_sha256"],
        "local_budget_usd": LOCAL_BUDGET_USD,
        "api_calls": 1,
        "attempts": 1,
    }
    _atomic(ledger, record)
    try:
        raw = _post(profile_record["endpoint"], body, config.api_key)
    except urllib.error.HTTPError as exc:
        record.update(status="provider_http_error", http_status=exc.code, finished_at_utc=_now())
        _atomic(ledger, record)
        return {"status": record["status"], "http_status": exc.code, "api_calls": 1}
    except Exception as exc:
        record.update(status="unknown_outcome", error_type=type(exc).__name__, finished_at_utc=_now())
        _atomic(ledger, record)
        return {"status": record["status"], "error_type": type(exc).__name__, "api_calls": 1}
    try:
        raw_hash = _save_raw(raw_path, raw)
    except Exception as exc:
        record.update(status="blocked_output_budget", error_type=type(exc).__name__,
                      response_bytes=len(raw), finished_at_utc=_now())
        _atomic(ledger, record)
        return {"status": record["status"], "error_type": type(exc).__name__,
                "response_bytes": len(raw), "api_calls": 1}
    record.update(status="raw_saved", response_sha256=raw_hash, response_bytes=len(raw),
                  finished_at_utc=_now())
    _atomic(ledger, record)
    try:
        record.update(_provider_metadata(raw))
        _atomic(ledger, record)
        parsed = parse_tool_response(raw)
        usage = record.get("usage")
        cost = record.get("peak_cost_estimate_usd")
        if cost is None:
            raise ValueError("provider usage absent or malformed")
        if cost > LOCAL_BUDGET_USD:
            raise ValueError("recorded usage exceeds local budget")
        if profile_record.get("schema_version") == TRANSPORT_V2_VERSION:
            answer = normalise_transport_answer_v2(parsed["arguments"])
        else:
            answer = normalise_transport_answer(parsed["arguments"])
        store = json.loads((base_package / "document-store.json").read_text(encoding="utf-8"))
        if profile_record.get("schema_version") == TRANSPORT_V2_VERSION:
            answer = complete_hts_code_evidence_v2(answer, store)
        draft = adapt_suggestion(answer, store, profile_record["doc_version"])
        _atomic(draft_path, draft)
        record.update(status="needs_review", usage=usage, peak_cost_estimate_usd=cost,
                      finish_reason=parsed.get("finish_reason"), response_model=parsed.get("model"))
    except (ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError) as exc:
        record.update(status="invalid_answer", validation_error_type=type(exc).__name__,
                      validation_error=str(exc)[:200])
    _atomic(ledger, record)
    return {"status": record["status"], "api_calls": 1,
            "response_sha256": record.get("response_sha256"),
            "usage": record.get("usage"),
            "peak_cost_estimate_usd": record.get("peak_cost_estimate_usd"),
            "validation_error_type": record.get("validation_error_type")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--authorize-one-call", action="store_true")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--experiment-dir", type=Path)
    parser.add_argument("--freeze-marker", type=Path)
    args = parser.parse_args()
    if args.live != args.authorize_one_call:
        parser.error("live mode requires both --live and --authorize-one-call")
    configure(profile=args.profile, experiment_dir=args.experiment_dir,
              freeze_marker=args.freeze_marker)
    result = run_once() if args.live else check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
