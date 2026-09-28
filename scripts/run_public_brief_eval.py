"""Run the fixed public-brief questions against one provider configuration.

The default command is an offline preflight.  A real request requires both
``--execute`` and ``--authorize-real-call``.  Every question is sent once, in
the order q1..q4, with no automatic retry.  The script stores the raw answer
locally and only performs structural validation; semantic scoring remains a
separate, blinded review step.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
import signal
import threading
from pathlib import Path
import sys
import time
from urllib.request import HTTPRedirectHandler, build_opener
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.tradeintel_ai.model_adapter import (  # noqa: E402
    ModelAdapterError,
    OpenAICompatibleConfig,
    OpenAICompatibleModel,
    safe_error_details,
)
from src.tradeintel_ai.public_brief_explanation import parse as parse_public  # noqa: E402
from src.tradeintel_ai.public_policy_explanation import parse as parse_policy  # noqa: E402
from src.tradeintel_ai.public_eval_protocols import (  # noqa: E402
    QUESTION_PROTOCOLS, UNIFIED_CANDIDATE_SCHEMA, UNIFIED_EXPERIMENT_ID,
    UNIFIED_FREEZE_SCHEMA, UNIFIED_RUN_SCHEMA, equivalent_messages,
)
from scripts.prepare_public_eval_diagnostic import estimate_input_tokens  # noqa: E402
from src.tradeintel_ai.public_eval_ledger import (  # noqa: E402
    DuplicatePublicRun,
    LedgerStateError,
    append as append_ledger_event,
    canonical_sha,
    claim as claim_ledger,
    file_sha256,
    make_base_key,
    require_previous_review,
)


DEFAULT_MATRIX = ROOT / "evals/public_brief_v1/provider_matrix.json"
DEFAULT_PACKAGE = ROOT / "tmp/public-brief-eval-v2/unified-service-20260923-v2"
SCHEMA = "public-brief-provider-run-v1"
ALLOWED_CHANNELS = {"openai_compatible_api"}
MANUAL_SESSION_CHANNEL = "codex_session"
QUESTION_IDS = ("q1", "q2", "q3", "q4")
MAX_OUTPUT_TOKENS = 2000
MAX_TOTAL_OUTPUT_TOKENS = 8192
MAX_OUTPUT_BYTES = 65536
MAX_BODY_CHARS = 2000
BUDGET_PROTOCOL_V2 = "v2"
BUDGET_PROTOCOL_V3 = "v3"


class ProviderDeadlineExceeded(BaseException):
    """Escape adapter Exception handlers when the whole call exceeds its deadline."""


def _require_deadline_support():
    # This executor is a synchronous CLI. Never silently fall back to a socket
    # timeout on Windows, worker threads, or inside another owner's alarm.
    if (not hasattr(signal, "setitimer") or not hasattr(signal, "ITIMER_REAL")
            or threading.current_thread() is not threading.main_thread()):
        raise ValueError("总时长截止需要POSIX主线程CLI；当前环境不发送请求")
    if any(signal.getitimer(signal.ITIMER_REAL)):
        raise ValueError("已有进程计时器，不能覆盖；当前环境不发送请求")


@contextmanager
def _provider_deadline(seconds):
    _require_deadline_support()
    if type(seconds) not in (float, int) or not 0 < seconds <= 90:
        raise ValueError("请求总时长必须位于0至90秒")
    previous = signal.getsignal(signal.SIGALRM)

    def expired(signum, frame):
        raise ProviderDeadlineExceeded()

    signal.signal(signal.SIGALRM, expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, seconds)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)

FREEZE_SCHEMA = "public-brief-freeze-v1"
FREEZE_EXPERIMENT_ID = "public-brief-v1"
SCORING_FILES = (
    "evals/public_brief_v1/SCORING.zh-CN.md",
    "evals/public_brief_v1/scenarios.json",
)
V3_SCORING_FILES = SCORING_FILES + ("evals/public_brief_v1/SCORING_V3.zh-CN.md",)
RUNTIME_FILES = (
    "scripts/run_public_brief_eval.py",
    "src/tradeintel_ai/public_brief_explanation.py",
    "src/tradeintel_ai/model_adapter.py",
    "src/tradeintel_ai/public_eval_ledger.py",
    "src/tradeintel_ai/public_policy_explanation.py",
    "scripts/score_public_brief_eval.py",
    "scripts/review_public_brief_answer.py",
)
V3_RUNTIME_FILES = RUNTIME_FILES + ("scripts/register_public_historical_prerequisite.py",)
UNIFIED_SCORING_FILES = V3_SCORING_FILES + (
    "evals/public_brief_v1/SCORING_UNIFIED_V2.zh-CN.md",
)
UNIFIED_RUNTIME_FILES = (
    "scripts/prepare_public_service_candidate.py",
    "scripts/prepare_public_eval_diagnostic.py",
    "scripts/run_public_brief_eval.py",
    "scripts/score_public_brief_eval.py",
    "scripts/review_public_brief_answer.py",
    "src/tradeintel_ai/public_eval_protocols.py",
    "src/tradeintel_ai/public_brief_explanation.py",
    "src/tradeintel_ai/public_policy_explanation.py",
    "src/tradeintel_ai/public_eval_ledger.py",
    "src/tradeintel_ai/session_explanation.py",
    "src/tradeintel_ai/web_app.py",
    "src/tradeintel_ai/model_adapter.py",
)


def _sha_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _atomic_write_text(path: Path, value: str) -> None:
    """Write a response artifact without exposing a half-written raw answer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def _atomic_write_json(path: Path, value: object) -> None:
    _atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _public_body_characters(parsed: object) -> int | None:
    """Count only reader-facing explanation fields, not JSON or hidden metadata."""
    if not isinstance(parsed, dict):
        return None
    interpretations = parsed.get("interpretations")
    watchlist = parsed.get("watchlist")
    if not isinstance(interpretations, list) or not isinstance(watchlist, list):
        return None
    # Policy-mode responses add a separate, source-bound explanation section.
    # Keep this optional so historical trade-only v1 answers retain their
    # original budget semantics, while new policy answers cannot hide reader
    # facing text outside the length gate.
    policy_explanations = parsed.get("policy_explanations", [])
    if not isinstance(policy_explanations, list):
        return None
    total = 0
    for item in interpretations:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            return None
        total += len(item["text"])
    for item in watchlist:
        if not isinstance(item, dict) or not isinstance(item.get("rationale"), str):
            return None
        total += len(item["rationale"])
    for item in policy_explanations:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            return None
        total += len(item["text"])
    return total


def _output_budget(raw: str, usage: object, *, max_tokens: int = MAX_OUTPUT_TOKENS,
                   max_bytes: int = MAX_OUTPUT_BYTES, thinking_enabled: bool = False,
                   body_max_tokens: int = MAX_OUTPUT_TOKENS,
                   budget_protocol: str = BUDGET_PROTOCOL_V2,
                   body_max_chars: int = MAX_BODY_CHARS,
                   parsed: object = None) -> dict[str, object]:
    """Report cost and reader length separately.

    v2 retains the historical conservative token estimate.  v3 uses the
    provider's completion usage only for the total-cost gate and counts the
    parsed reader-facing fields in Unicode characters for the product-length
    gate.  Missing usage is unknown, never silently estimated as real usage.
    """
    if budget_protocol not in (BUDGET_PROTOCOL_V2, BUDGET_PROTOCOL_V3):
        raise ValueError("未知的正文预算协议")
    reported = usage.get("completion_tokens") if isinstance(usage, dict) else None
    valid = type(reported) is int and reported >= 0 and (reported > 0 or not raw)
    estimate = estimate_input_tokens([{"content": raw}])
    tokens = reported if valid else (estimate["tokens"] if budget_protocol == BUDGET_PROTOCOL_V2 else None)
    size = len(raw.encode("utf-8"))
    base = {"tokens": tokens,
            "method": ("provider_completion_tokens" if valid else
                        ("fallback_estimate" if budget_protocol == BUDGET_PROTOCOL_V2
                         else "usage_unavailable")),
            "estimate": estimate, "estimated_tokens": estimate["tokens"],
            "utf8_bytes": size,
            "max_tokens": max_tokens, "max_bytes": max_bytes,
            "total_usage_known": valid}
    if budget_protocol == BUDGET_PROTOCOL_V2:
        body_tokens = estimate["tokens"] if thinking_enabled else tokens
        return {**base,
                "budget_protocol": BUDGET_PROTOCOL_V2,
                "body_tokens": body_tokens, "body_max_tokens": body_max_tokens,
                "body_method": "estimate" if thinking_enabled or not valid else "provider_completion_tokens",
                "within_gate": tokens <= max_tokens and body_tokens <= body_max_tokens and size <= max_bytes}
    body_chars = _public_body_characters(parsed)
    cost_gate = valid and reported <= max_tokens
    chars_gate = body_chars is not None and body_chars <= body_max_chars
    bytes_gate = size <= max_bytes
    reason = None
    if not bytes_gate:
        reason = "raw_bytes_exceeded"
    elif not valid:
        reason = "usage_unknown"
    elif not cost_gate:
        reason = "total_output_tokens_exceeded"
    elif not chars_gate:
        reason = "body_characters_exceeded" if body_chars is not None else "body_unavailable"
    return {**base,
            "budget_protocol": BUDGET_PROTOCOL_V3,
            "reported_completion_tokens": reported if valid else None,
            "body_chars": body_chars,
            "body_max_chars": body_max_chars,
            "body_method": "unicode_reader_fields",
            "cost_gate": cost_gate,
            "chars_gate": chars_gate,
            "bytes_gate": bytes_gate,
            "reason": reason,
            "within_gate": cost_gate and chars_gate and bytes_gate}


def _safe_url(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("API 配置缺少 base_url")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment
            or parsed.username or parsed.password):
        raise ValueError("API base_url 必须是无查询参数的 HTTPS URL")
    return value.rstrip("/")


def _validate_provider(provider: dict[str, object]) -> dict[str, object]:
    if not isinstance(provider, dict):
        raise ValueError("provider 配置必须是对象")
    required = {"id", "channel", "model_id"}
    missing = required - set(provider)
    if missing:
        raise ValueError("provider 配置缺少字段：" + ",".join(sorted(missing)))
    channel = provider["channel"]
    if channel not in ALLOWED_CHANNELS | {MANUAL_SESSION_CHANNEL}:
        raise ValueError("未知 provider channel")
    provider_id = provider["id"]
    if not isinstance(provider_id, str) or not provider_id or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in provider_id):
        raise ValueError("provider id 必须是小写安全标识")
    model_id = provider["model_id"]
    if not isinstance(model_id, str) or not model_id.strip():
        raise ValueError("正式执行前必须登记确切 model_id")
    if channel == MANUAL_SESSION_CHANNEL:
        effort = provider.get("reasoning_effort")
        expected_effort = {"gpt-5.6-luna": "max", "gpt-5.6-sol": "high"}
        if model_id.strip() not in expected_effort:
            raise ValueError("Codex 手动会话候选不是本轮已登记的模型")
        if effort != expected_effort[model_id.strip()]:
            raise ValueError("Codex 模型与登记推理档位不匹配")
        if provider.get("status") != "ready_for_manual_session":
            raise ValueError("Codex 会话只能登记为 ready_for_manual_session")
        return {"id": provider_id, "label": provider.get("label"),
                "channel": channel, "model_id": model_id.strip(),
                "base_url": None, "secret_env": None, "request_params": {},
                "provider": None, "reasoning_effort": effort,
                "status": provider["status"]}
    required_api = {"base_url", "secret_env", "request_params"}
    missing_api = required_api - set(provider)
    if missing_api:
        raise ValueError("provider 配置缺少字段：" + ",".join(sorted(missing_api)))
    base_url = _safe_url(provider["base_url"])
    secret_env = provider["secret_env"]
    if not isinstance(secret_env, str) or not secret_env or not secret_env.startswith("TRADEINTEL_"):
        raise ValueError("secret_env 必须是项目专用环境变量名")
    params = provider["request_params"]
    if not isinstance(params, dict) or not {"max_tokens", "thinking"} <= set(params) or set(params) - {"max_tokens", "thinking", "reasoning_effort"}:
        raise ValueError("request_params 必须明确 max_tokens 和 thinking")
    maximum = params["max_tokens"]
    if type(maximum) is not int or not 1 <= maximum <= MAX_TOTAL_OUTPUT_TOKENS:
        raise ValueError("max_tokens 必须位于1至8192")
    thinking = params["thinking"]
    if thinking not in ({"type": "disabled"}, {"type": "enabled"}):
        raise ValueError("必须明确启用或关闭thinking")
    if "reasoning_effort" in params and (provider.get("provider") != "deepseek" or
            thinking != {"type": "enabled"} or params["reasoning_effort"] not in ("low", "high")):
        raise ValueError("只接受DeepSeek enabled配合low/high，不静默改变档位")
    if provider.get("reasoning_effort") != params.get("reasoning_effort"):
        raise ValueError("登记推理档位与实际请求参数不一致")
    return {"id": provider_id, "label": provider.get("label"),
            "channel": provider["channel"], "model_id": model_id.strip(),
            "base_url": base_url, "secret_env": secret_env,
            "request_params": deepcopy(params), "provider": provider.get("provider"),
            "reasoning_effort": provider.get("reasoning_effort"),
            "status": provider.get("status")}


def _bound_hashes(relative_paths: tuple[str, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in relative_paths:
        path = ROOT / relative
        if not path.is_file():
            raise ValueError("冻结所需文件不存在：" + relative)
        result[relative] = _sha_bytes(path)
    return result


def _freeze_provider(provider: dict[str, object]) -> dict[str, object]:
    """Return only non-secret provider identity/configuration fields."""
    return {
        key: deepcopy(provider.get(key))
        for key in ("id", "label", "channel", "provider", "model_id",
                    "base_url", "request_params", "reasoning_effort", "status")
    }


def build_freeze_spec(*, provider: dict[str, object], package_path: Path,
                      matrix_path: Path = DEFAULT_MATRIX,
                      timeout_seconds: float = 90.0,
                      temperature: float = 0.0,
                      body_max_bytes: int = MAX_OUTPUT_BYTES,
                      budget_protocol: str | None = None) -> dict[str, object]:
    """Build an immutable candidate freeze; it is not itself permission to call.

    The current matrix intentionally has no ``ready_for_formal`` provider, so
    this function is useful for review/tests while ``verify_freeze`` remains a
    fail-closed gate for production execution.
    """
    checked = _validate_provider(provider)
    if checked["channel"] != "openai_compatible_api":
        raise ValueError("Codex 手动会话不生成 API 冻结；请从独立新会话按题包作答")
    manifest_path = Path(package_path).resolve() / "MANIFEST.json"
    if not manifest_path.is_file():
        raise ValueError("冻结题包缺少 MANIFEST.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    unified = manifest.get("schema_version") == UNIFIED_CANDIDATE_SCHEMA
    if budget_protocol is None:
        budget_protocol = BUDGET_PROTOCOL_V3 if unified else BUDGET_PROTOCOL_V2
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 90:
        raise ValueError("timeout_seconds 必须位于1至90秒")
    if type(temperature) not in (int, float) or not 0 <= temperature <= 2:
        raise ValueError("temperature 必须位于0至2")
    if type(body_max_bytes) is not int or not 1 <= body_max_bytes <= MAX_OUTPUT_BYTES:
        raise ValueError("body_max_bytes 超出上限")
    if budget_protocol not in (BUDGET_PROTOCOL_V2, BUDGET_PROTOCOL_V3):
        raise ValueError("budget_protocol 只能是v2或v3")
    if unified and budget_protocol != BUDGET_PROTOCOL_V3:
        raise ValueError("统一四题v2只接受包含政策正文的v3预算协议")
    params = checked["request_params"]
    budget = {"body_max_bytes": body_max_bytes}
    if budget_protocol == BUDGET_PROTOCOL_V2:
        budget["body_max_tokens"] = MAX_OUTPUT_TOKENS
    else:
        budget["budget_protocol"] = BUDGET_PROTOCOL_V3
        budget["body_max_chars"] = MAX_BODY_CHARS
    freeze = {
        "schema_version": UNIFIED_FREEZE_SCHEMA if unified else FREEZE_SCHEMA,
        "experiment_id": UNIFIED_EXPERIMENT_ID if unified else FREEZE_EXPERIMENT_ID,
        "status": "candidate_not_formal",
        "provider": _freeze_provider(checked),
        "package": str(Path(package_path).resolve()),
        "package_manifest_sha256": _sha_bytes(manifest_path),
        "provider_matrix_sha256": _sha_bytes(Path(matrix_path)),
        "scoring_sha256": _bound_hashes(UNIFIED_SCORING_FILES if unified else
                                          V3_SCORING_FILES if budget_protocol == BUDGET_PROTOCOL_V3 else SCORING_FILES),
        "runtime_sha256": _bound_hashes(UNIFIED_RUNTIME_FILES if unified else
                                          V3_RUNTIME_FILES if budget_protocol == BUDGET_PROTOCOL_V3 else RUNTIME_FILES),
        "params": {
            "temperature": temperature,
            "thinking": deepcopy(params["thinking"]),
            "max_tokens": params["max_tokens"],
            "reasoning_effort": params.get("reasoning_effort"),
            "timeout_seconds": timeout_seconds,
            **budget,
        },
        "created_at_utc": _utc(),
    }
    if unified:
        freeze.update({
            "candidate_schema": UNIFIED_CANDIDATE_SCHEMA,
            "question_protocols": deepcopy(QUESTION_PROTOCOLS),
            "scoring_version": "public-brief-unified-scoring-v2",
        })
    return freeze


def verify_freeze(*, freeze: dict[str, object], provider: dict[str, object],
                  package_path: Path, matrix_path: Path = DEFAULT_MATRIX,
                  allow_candidate: bool = False) -> str:
    """Verify every binding before constructing a client or reading a key."""
    if not isinstance(freeze, dict):
        raise ValueError("真实评测需要有效的冻结记录")
    unified = freeze.get("schema_version") == UNIFIED_FREEZE_SCHEMA
    expected_schema = UNIFIED_FREEZE_SCHEMA if unified else FREEZE_SCHEMA
    expected_experiment = UNIFIED_EXPERIMENT_ID if unified else FREEZE_EXPERIMENT_ID
    if freeze.get("schema_version") != expected_schema:
        raise ValueError("冻结记录schema不匹配")
    if freeze.get("experiment_id") != expected_experiment:
        raise ValueError("冻结实验身份不匹配")
    if not allow_candidate and freeze.get("status") != "ready_for_formal":
        raise ValueError("冻结记录尚未获得 ready_for_formal 审核，不得调用模型")
    frozen_provider = freeze.get("provider")
    if (not allow_candidate and
            (not isinstance(frozen_provider, dict) or
             frozen_provider.get("status") != "ready_for_formal")):
        raise ValueError("冻结中的 provider 尚未登记为 ready_for_formal")
    checked = _validate_provider(provider)
    if freeze.get("provider") != _freeze_provider(checked):
        raise ValueError("调用方 provider 与冻结配置不一致")
    package = Path(package_path).resolve()
    manifest_path = package / "MANIFEST.json"
    if freeze.get("package") != str(package) or freeze.get("package_manifest_sha256") != _sha_bytes(manifest_path):
        raise ValueError("题包或 MANIFEST 已改变")
    if freeze.get("provider_matrix_sha256") != _sha_bytes(Path(matrix_path)):
        raise ValueError("provider matrix 已改变")
    frozen_params = freeze.get("params")
    if unified and (freeze.get("candidate_schema") != UNIFIED_CANDIDATE_SCHEMA
                    or freeze.get("question_protocols") != QUESTION_PROTOCOLS
                    or freeze.get("scoring_version") != "public-brief-unified-scoring-v2"):
        raise ValueError("统一四题冻结缺少候选、协议或评分版本绑定")
    scoring_files = (UNIFIED_SCORING_FILES if unified else
                     V3_SCORING_FILES if isinstance(frozen_params, dict) and
                     frozen_params.get("budget_protocol") == BUDGET_PROTOCOL_V3 else SCORING_FILES)
    if freeze.get("scoring_sha256") != _bound_hashes(scoring_files):
        raise ValueError("评分文件已改变")
    runtime = freeze.get("runtime_sha256")
    runtime_files = (UNIFIED_RUNTIME_FILES if unified else
                     V3_RUNTIME_FILES if isinstance(frozen_params, dict) and
                     frozen_params.get("budget_protocol") == BUDGET_PROTOCOL_V3 else RUNTIME_FILES)
    if runtime != _bound_hashes(runtime_files):
        raise ValueError("执行器或解析器运行时代码已改变")
    params = freeze.get("params")
    if not isinstance(params, dict):
        raise ValueError("冻结记录缺少 params")
    protocol = params.get("budget_protocol", BUDGET_PROTOCOL_V2)
    if unified and protocol != BUDGET_PROTOCOL_V3:
        raise ValueError("统一四题冻结必须包含政策正文的v3预算")
    if protocol == BUDGET_PROTOCOL_V2:
        expected_keys = {"temperature", "thinking", "max_tokens", "body_max_bytes",
                         "timeout_seconds", "reasoning_effort", "body_max_tokens"}
    elif protocol == BUDGET_PROTOCOL_V3:
        expected_keys = {"temperature", "thinking", "max_tokens", "body_max_bytes",
                         "timeout_seconds", "reasoning_effort", "budget_protocol",
                         "body_max_chars"}
    else:
        raise ValueError("冻结记录的正文预算协议不支持")
    if set(params) != expected_keys:
        raise ValueError("冻结记录字段与正文预算协议不匹配")
    if type(params["temperature"]) not in (int, float) or not 0 <= params["temperature"] <= 2:
        raise ValueError("冻结 temperature 不合法")
    if type(params["max_tokens"]) is not int or not 1 <= params["max_tokens"] <= MAX_TOTAL_OUTPUT_TOKENS:
        raise ValueError("冻结 max_tokens 不合法")
    if type(params["body_max_bytes"]) is not int or not 1 <= params["body_max_bytes"] <= MAX_OUTPUT_BYTES:
        raise ValueError("冻结 body_max_bytes 不合法")
    if type(params["timeout_seconds"]) not in (int, float) or not 0 < params["timeout_seconds"] <= 90:
        raise ValueError("冻结 timeout_seconds 不合法")
    if params["thinking"] != checked["request_params"]["thinking"]:
        raise ValueError("冻结 thinking 参数与 provider 不一致")
    if params["max_tokens"] != checked["request_params"]["max_tokens"] or params["reasoning_effort"] != checked["request_params"].get("reasoning_effort"):
        raise ValueError("冻结预算或推理档位与provider不一致")
    if protocol == BUDGET_PROTOCOL_V2:
        if type(params["body_max_tokens"]) is not int or params["body_max_tokens"] != MAX_OUTPUT_TOKENS:
            raise ValueError("v2正文预算必须为2000估算token")
    elif (type(params["body_max_chars"]) is not int
          or params["body_max_chars"] != MAX_BODY_CHARS):
        raise ValueError("v3正文预算必须为2000个Unicode字符")
    return canonical_sha(freeze)


def _verify_candidate(package: Path) -> dict[str, object]:
    package = package.resolve()
    manifest_path = package / "MANIFEST.json"
    if not manifest_path.is_file():
        raise ValueError("候选题包缺少 MANIFEST.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = manifest.get("schema_version")
    if schema not in {"public-service-candidate-v1", UNIFIED_CANDIDATE_SCHEMA}:
        raise ValueError("候选题包 schema 不匹配")
    unified = schema == UNIFIED_CANDIDATE_SCHEMA
    if manifest.get("status") != "candidate_only_not_frozen":
        raise ValueError("评测器只接受尚未冻结的公共题包")
    if manifest.get("api_calls") != 0:
        raise ValueError("候选题包已经包含 API 调用记录，不能作为干净首轮材料")
    if unified and (manifest.get("experiment_id") != UNIFIED_EXPERIMENT_ID
                    or manifest.get("question_protocols") != QUESTION_PROTOCOLS):
        raise ValueError("统一四题候选包实验身份或协议映射不匹配")
    scenarios = manifest.get("scenarios")
    if not isinstance(scenarios, dict) or tuple(scenarios) != QUESTION_IDS:
        raise ValueError("候选题包必须按 q1、q2、q3、q4 固定")
    files = manifest.get("files_sha256")
    if not isinstance(files, dict):
        raise ValueError("候选题包缺少文件摘要")
    required = {f'{folder}/{qid}/{name}' for qid in QUESTION_IDS
                for folder, name in [('requests', 'messages.json'),
                                     ('host_artifacts', 'response.json'),
                                     ('host_artifacts', 'snapshot.json')]}
    required.update(f'references/{qid}.json' for qid in QUESTION_IDS)
    if unified:
        required.add("host_artifacts/q2/request_context.json")
    if not required <= set(files):
        raise ValueError('候选题包必需文件未全部登记摘要')
    for relative, expected in files.items():
        path = package / relative
        if Path(relative).is_absolute() or '..' in Path(relative).parts or not path.resolve().is_relative_to(package):
            raise ValueError('候选题包路径越界')
        if not path.is_file() or path.is_symlink() or _sha_bytes(path) != expected:
            raise ValueError("候选题包文件摘要不匹配：" + relative)
    unified_snapshots = {}
    for qid in QUESTION_IDS:
        if not (package / "requests" / qid / "messages.json").is_file():
            raise ValueError("缺少送模消息：" + qid)
        if not (package / "host_artifacts" / qid / "response.json").is_file():
            raise ValueError("缺少主机报告：" + qid)
        messages = json.loads((package / 'requests' / qid / 'messages.json').read_text())
        estimate = estimate_input_tokens(messages)
        if estimate != scenarios[qid]['input_estimate'] or estimate['tokens'] > 16000:
            raise ValueError('实际消息预算与登记不符或超限：' + qid)
        if unified:
            expected = QUESTION_PROTOCOLS[qid]
            scenario = scenarios[qid]
            if scenario.get("mode") != expected["mode"] or scenario.get("protocol") != expected["protocol"]:
                raise ValueError("题目模式或解析协议与统一四题映射不一致：" + qid)
            snapshot_path = package / "host_artifacts" / qid / "snapshot.json"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            response_path = package / "host_artifacts" / qid / "response.json"
            response = json.loads(response_path.read_text(encoding="utf-8"))
            if (snapshot.get("mode") != expected["mode"]
                    or snapshot.get("protocol") != expected["protocol"]
                    or snapshot.get("messages") != messages
                    or not isinstance(snapshot.get("question"), str)
                    or scenario.get("question") not in snapshot.get("question", "")
                    or snapshot.get("identity") != {"session_id": scenario.get("session_id"),
                                                       "task_id": scenario.get("task_id")}
                    or snapshot.get("report") != response.get("report")
                    or snapshot.get("report_sha256") != response.get("report_sha256")
                    or snapshot.get("evidence_sha256") != response.get("evidence_sha256")
                    or snapshot.get("policy_context") != response.get("policy_context")):
                raise ValueError("题目快照、政策模式、消息或程序报告绑定不一致：" + qid)
            request_context = None
            context_path = package / "host_artifacts" / qid / "request_context.json"
            if qid == "q2":
                request_context = json.loads(context_path.read_text(encoding="utf-8"))
            elif context_path.exists():
                raise ValueError("只有Q2可以包含上一份程序稿摘要")
            if snapshot.get("request_context") != request_context:
                raise ValueError("追问上下文文件与题目快照不一致：" + qid)
            if expected["mode"] == "policy":
                from src.tradeintel_ai.public_policy_explanation import messages as policy_messages
                rebuilt_messages = policy_messages(
                    snapshot["question"], snapshot["report"],
                    policy_context=snapshot["policy_context"], request_context=request_context)
            else:
                from src.tradeintel_ai.public_brief_explanation import messages as trade_messages
                rebuilt_messages = trade_messages(
                    snapshot["question"], snapshot["report"],
                    policy_context=snapshot.get("policy_context"), request_context=request_context)
            if not equivalent_messages(rebuilt_messages, messages):
                raise ValueError("题目消息不能从冻结快照重建：" + qid)
            if snapshot.get("data_version") != manifest.get("data_version"):
                raise ValueError("四题使用的数据版本与候选包声明不一致：" + qid)
            unified_snapshots[qid] = snapshot
    if unified:
        for qid in QUESTION_IDS:
            if unified_snapshots[qid].get("data_version") != unified_snapshots["q1"].get("data_version"):
                raise ValueError("四题数据版本不一致：" + qid)
        q1_window = (unified_snapshots["q1"].get("request") or {}).get("window")
        q2_window = (unified_snapshots["q2"].get("request") or {}).get("window")
        if q2_window != q1_window:
            raise ValueError("Q2没有继承Q1的固定时间窗口")
    runtime = manifest.get('code_sha256')
    if not isinstance(runtime, dict) or not runtime:
        raise ValueError('缺少运行代码摘要')
    for relative, expected in runtime.items():
        path = ROOT / relative
        if Path(relative).is_absolute() or '..' in Path(relative).parts or not path.resolve().is_relative_to(ROOT):
            raise ValueError('运行代码路径越界')
        if not path.is_file() or _sha_bytes(path) != expected:
            raise ValueError('题包运行代码已变化：' + relative)
    return manifest


class _PublicEvalModel(OpenAICompatibleModel):
    """Add only the parameters explicitly frozen for this public run."""

    def __init__(self, config, *, request_params, opener=None):
        kwargs = {"system_prompt": ""}
        if opener is not None:
            kwargs["opener"] = opener
        super().__init__(config, **kwargs)
        self._request_params = deepcopy(request_params)

    def _payload(self, *, messages, tools):
        payload = super()._payload(messages=messages, tools=tools)
        payload.update(self._request_params)
        return payload


class _NoRedirectHandler(HTTPRedirectHandler):
    """Do not let a provider redirect credentials to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        raise ModelAdapterError("模型端点发生重定向，公共评测拒绝发送凭证")


def _no_redirect_opener():
    return build_opener(_NoRedirectHandler()).open


def preflight(*, matrix_path: Path = DEFAULT_MATRIX,
              package_path: Path = DEFAULT_PACKAGE,
              provider_id: str) -> dict[str, object]:
    matrix = json.loads(Path(matrix_path).read_text(encoding="utf-8"))
    if matrix.get("schema_version") != "public-brief-provider-matrix-v1":
        raise ValueError("provider matrix schema 不匹配")
    manifest = _verify_candidate(package_path)
    candidates = matrix.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("provider matrix 缺少 candidates")
    selected = next((item for item in candidates if item.get("id") == provider_id), None)
    if selected is None:
        raise ValueError("provider matrix 中没有该候选")
    provider = _validate_provider(selected)
    scenarios = manifest["scenarios"]
    result = {
        "schema_version": SCHEMA,
        "status": "preflight_passed",
        "api_calls": 0,
        "execution_channel": provider["channel"],
        "provider": provider,
        "provider_matrix_sha256": _sha_bytes(Path(matrix_path)),
        "package": str(Path(package_path).resolve()),
        "package_manifest_sha256": _sha_bytes(Path(package_path) / "MANIFEST.json"),
        "questions": [{"id": qid, "input_tokens": scenarios[qid]["input_estimate"]["tokens"],
                       "request_sha256": _sha_bytes(Path(package_path) / "requests" / qid / "messages.json")}
                      for qid in QUESTION_IDS],
        "scoring": "structural_only_until_blinded_human_review",
    }
    if provider["channel"] == MANUAL_SESSION_CHANNEL:
        result["scoring"] = "manual_independent_session_required"
    if manifest.get("schema_version") == UNIFIED_CANDIDATE_SCHEMA:
        result.update({"experiment_id": UNIFIED_EXPERIMENT_ID,
                       "candidate_schema": UNIFIED_CANDIDATE_SCHEMA,
                       "question_protocols": deepcopy(QUESTION_PROTOCOLS),
                       "scoring_version": "public-brief-unified-scoring-v2"})
        for item in result["questions"]:
            expected = QUESTION_PROTOCOLS[item["id"]]
            item.update(expected)
    else:
        for item in result["questions"]:
            item.update({"mode": "trade", "protocol": "public-brief-explanation-v1"})
    return result


def _response_parts(response: object) -> tuple[str, dict[str, object]]:
    """Accept a real ModelResponse or a tiny injected tuple in offline tests."""
    if isinstance(response, tuple) and len(response) == 2:
        raw, metadata = response
        if not isinstance(raw, str) or not isinstance(metadata, dict):
            raise ModelAdapterError("注入的模型响应形状不正确")
        return raw, deepcopy(metadata)
    raw = getattr(response, "text", None)
    metadata = getattr(response, "metadata", None)
    if not isinstance(raw, str) or not isinstance(metadata, dict):
        raise ModelAdapterError("模型响应缺少 text/metadata")
    return raw, deepcopy(metadata)


def _parse_candidate_answer(raw: str, *, host_response: dict[str, object],
                            snapshot: dict[str, object], mode: str,
                            protocol: str) -> dict[str, object]:
    """Dispatch only to the parser bound to this question's saved snapshot."""
    if mode == "trade" and protocol == "public-brief-explanation-v1":
        return parse_public(raw, host_response["report"])
    if mode == "policy" and protocol == "public-policy-explanation-prototype-v2":
        return parse_policy(
            raw, snapshot["report"], question=snapshot["question"],
            policy_context=snapshot.get("policy_context") or {},
            request_context=snapshot.get("request_context"),
            enforce_body_budget=False,
        )
    raise ValueError("题目模式与解析协议不受支持")


def _provider_digest(provider: dict[str, object]) -> str:
    return canonical_sha(_freeze_provider(_validate_provider(provider)))


def _run_one_question(*, provider: dict[str, object], package_path: Path,
                      output: Path, question_id: str, matrix_path: Path,
                      provider_call, freeze: dict[str, object], freeze_sha: str,
                      ledger_root: Path, execution_channel: str = "real_api") -> dict[str, object]:
    """Execute one question after all bindings have been verified.

    ``provider_call`` is injected by offline tests and is the model adapter in
    the real path.  It is intentionally invoked only after the ledger claim.
    """
    package = Path(package_path).resolve()
    messages_path = package / "requests" / question_id / "messages.json"
    host_response_path = package / "host_artifacts" / question_id / "response.json"
    snapshot_path = package / "host_artifacts" / question_id / "snapshot.json"
    if not messages_path.is_file() or not host_response_path.is_file() or not snapshot_path.is_file():
        raise ValueError("题包缺少该题的实际消息或主机报告")
    manifest_bytes = (package / "MANIFEST.json").read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest_sha != freeze["package_manifest_sha256"]:
        raise ValueError("发送前MANIFEST发生变化")
    manifest = json.loads(manifest_bytes)
    unified = manifest.get("schema_version") == UNIFIED_CANDIDATE_SCHEMA
    experiment_id = freeze.get("experiment_id", FREEZE_EXPERIMENT_ID)
    candidate_schema = manifest.get("schema_version", "public-service-candidate-v1")
    def read_bound(path):
        content = path.read_bytes()
        actual = hashlib.sha256(content).hexdigest()
        if actual != manifest["files_sha256"].get(str(path.relative_to(package))):
            raise ValueError("发送前材料发生变化：" + path.name)
        return json.loads(content), actual
    messages, actual_messages_sha = read_bound(messages_path)
    host_response, _ = read_bound(host_response_path)
    snapshot, _ = read_bound(snapshot_path)
    expected = QUESTION_PROTOCOLS[question_id] if unified else {
        "mode": "trade", "protocol": "public-brief-explanation-v1"}
    if (snapshot.get("mode", "trade") != expected["mode"]
            or snapshot.get("protocol") != expected["protocol"]
            or snapshot.get("messages") != messages
            or snapshot.get("report") != host_response.get("report")
            or snapshot.get("report_sha256") != host_response.get("report_sha256")
            or snapshot.get("evidence_sha256") != host_response.get("evidence_sha256")):
        raise ValueError("发送前题目模式、消息与已绑定报告不一致")
    mode, protocol = expected["mode"], expected["protocol"]
    # The validated in-memory messages, not a later file read, are sent.
    provider_digest = canonical_sha({"provider_id": provider["id"],
                                     "execution_channel": execution_channel})
    call_count = int(execution_channel == "real_api")
    base_key = make_base_key(manifest_sha, provider_digest, question_id)
    require_previous_review(ledger_root, base_key=base_key)
    if output.exists():
        raise ValueError("输出目录已存在；每次运行必须使用新目录")
    params = deepcopy(freeze["params"])
    _require_deadline_support()
    started = claim_ledger(
        ledger_root,
        base_key=base_key,
        metadata={
            "question_id": question_id,
            "experiment_id": experiment_id,
            "candidate_schema": candidate_schema,
            "mode": mode,
            "protocol": protocol,
            "scoring_version": freeze.get("scoring_version", "public-brief-scoring-v1"),
            "execution_channel": execution_channel,
            "package_manifest_sha256": manifest_sha,
            "provider_digest": provider_digest,
            "provider_id": provider["id"],
            "requested_model": provider["model_id"],
            "request_sha256": actual_messages_sha,
            "freeze_sha256": freeze_sha,
            "config_sha256": canonical_sha({"provider": _freeze_provider(provider), "params": params}),
            "params": params,
            "package_path": str(package),
            "output_dir": str(output.resolve()),
        },
    )
    run_id = started["run_id"]
    output.mkdir(parents=True)
    qdir = output / question_id
    qdir.mkdir()
    started_record = {
        "schema_version": UNIFIED_RUN_SCHEMA if unified else SCHEMA,
        "status": "started",
        "run_id": run_id,
        "question_id": question_id,
        "experiment_id": experiment_id,
        "candidate_schema": candidate_schema,
        "mode": mode,
        "protocol": protocol,
        "scoring_version": freeze.get("scoring_version", "public-brief-scoring-v1"),
        **({"question_protocols": deepcopy(QUESTION_PROTOCOLS)} if unified else {}),
        "execution_channel": execution_channel,
        "provider": {"id": provider["id"], "model_id": provider["model_id"],
                     "base_url": provider["base_url"]},
        "freeze_sha256": freeze_sha,
        "package_manifest_sha256": manifest_sha,
        "package_path": str(package),
        "request_sha256": actual_messages_sha,
        "params": params,
        "api_calls": 0,
        "started_at_utc": _utc(),
    }
    _atomic_write_json(qdir / "run.json", started_record)
    started_monotonic = time.monotonic()
    try:
        with _provider_deadline(params["timeout_seconds"]):
            response = provider_call(messages=messages, tools=[])
            raw, metadata = _response_parts(response)
    except (ProviderDeadlineExceeded, KeyboardInterrupt, Exception) as exc:
        if isinstance(exc, ProviderDeadlineExceeded):
            error_kind = "wall_clock_deadline"
            details = {"message": "本地请求总时长已截止，服务端完成与计费未知"}
        elif isinstance(exc, KeyboardInterrupt):
            error_kind = "operator_interrupted"
            details = {"message": "操作者中断本地请求，服务端完成与计费未知"}
        else:
            error_kind = "transport_error"
            details = safe_error_details(exc)
        result = {**started_record, "status": "unknown_outcome", "api_calls": call_count,
                  "error": "provider outcome unknown", "error_details": details,
                  "error_kind": error_kind,
                  "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
                  "finished_at_utc": _utc()}
        _atomic_write_json(qdir / "run.json", result)
        append_ledger_event(ledger_root, run_id=run_id, event="unknown_outcome",
                            payload={"api_calls": call_count, "error_details": details,
                                     "error_kind": error_kind})
        return result

    elapsed = round(time.monotonic() - started_monotonic, 3)
    usage = metadata.get("usage") if isinstance(metadata.get("usage"), dict) else {}
    finish_reason = metadata.get("finish_reason")
    response_meta = {
        "requested_model": provider["model_id"],
        "returned_model": metadata.get("model"),
        "finish_reason": finish_reason,
        "usage": usage,
        "params": params,
        "elapsed_seconds": elapsed,
    }
    try:
        _atomic_write_text(qdir / "raw-response.txt", raw)
        _atomic_write_json(qdir / "response-metadata.json", response_meta)
    except Exception as exc:
        details = safe_error_details(exc)
        result = {**started_record, "status": "raw_save_failed", "api_calls": call_count,
                  "response_metadata": response_meta, "error_details": details,
                  "finished_at_utc": _utc()}
        _atomic_write_json(qdir / "run.json", result)
        append_ledger_event(ledger_root, run_id=run_id, event="raw_save_failed",
                            payload={"api_calls": call_count, "error_details": details})
        return result

    raw_sha = _sha_text(raw)
    budget_protocol = params.get("budget_protocol", BUDGET_PROTOCOL_V2)

    # v3 checks the safe raw-byte and finish gates before parsing, then counts
    # only the parsed reader-facing fields.  v2 follows its historical order
    # and estimate so old frozen runs remain reproducible.
    if budget_protocol == BUDGET_PROTOCOL_V3:
        if len(raw.encode("utf-8")) > params["body_max_bytes"]:
            budget = _output_budget(raw, usage, max_tokens=params["max_tokens"],
                                    max_bytes=params["body_max_bytes"],
                                    budget_protocol=BUDGET_PROTOCOL_V3,
                                    body_max_chars=params["body_max_chars"])
            common = {**started_record, "api_calls": call_count, "raw_sha256": raw_sha,
                      "response_metadata": response_meta, "output_budget": budget,
                      "finished_at_utc": _utc()}
            result = {**common, "status": "blocked_output_budget"}
            _atomic_write_json(qdir / "validation.json", result)
            _atomic_write_json(qdir / "run.json", result)
            append_ledger_event(ledger_root, run_id=run_id, event="blocked_output_budget",
                                payload={"api_calls": call_count, "raw_sha256": raw_sha,
                                         "usage": usage, "output_budget": budget})
            return result
        if finish_reason != "stop":
            budget = _output_budget(raw, usage, max_tokens=params["max_tokens"],
                                    max_bytes=params["body_max_bytes"],
                                    budget_protocol=BUDGET_PROTOCOL_V3,
                                    body_max_chars=params["body_max_chars"])
            common = {**started_record, "api_calls": call_count, "raw_sha256": raw_sha,
                      "response_metadata": response_meta, "output_budget": budget,
                      "finished_at_utc": _utc()}
            result = {**common, "status": "invalid_response",
                      "error": "非正常 finish_reason，不能计结构成功"}
            _atomic_write_json(qdir / "validation.json", result)
            _atomic_write_json(qdir / "run.json", result)
            append_ledger_event(ledger_root, run_id=run_id, event="invalid_response",
                                payload={"api_calls": call_count, "raw_sha256": raw_sha,
                                         "usage": usage, "finish_reason": finish_reason})
            return result
        try:
            parsed = _parse_candidate_answer(raw, host_response=host_response,
                                             snapshot=snapshot, mode=mode,
                                             protocol=protocol)
            validation = {
                "status": parsed["status"],
                "mode": mode,
                "protocol": protocol,
                "interpretation_count": len(parsed["interpretations"]),
                "watchlist_count": len(parsed["watchlist"]),
            }
            if mode == "policy":
                validation["policy_explanation_count"] = len(parsed["policy_explanations"])
        except Exception as exc:
            budget = _output_budget(raw, usage, max_tokens=params["max_tokens"],
                                    max_bytes=params["body_max_bytes"],
                                    budget_protocol=BUDGET_PROTOCOL_V3,
                                    body_max_chars=params["body_max_chars"])
            common = {**started_record, "api_calls": call_count, "raw_sha256": raw_sha,
                      "response_metadata": response_meta, "output_budget": budget,
                      "finished_at_utc": _utc()}
            details = safe_error_details(exc)
            result = {**common, "status": "invalid_response", "error_details": details}
            _atomic_write_json(qdir / "validation.json", result)
            _atomic_write_json(qdir / "run.json", result)
            append_ledger_event(ledger_root, run_id=run_id, event="invalid_response",
                                payload={"api_calls": call_count, "raw_sha256": raw_sha,
                                         "usage": usage, "error_details": details})
            return result
        budget = _output_budget(raw, usage, max_tokens=params["max_tokens"],
                                max_bytes=params["body_max_bytes"],
                                budget_protocol=BUDGET_PROTOCOL_V3,
                                body_max_chars=params["body_max_chars"], parsed=parsed)
        common = {**started_record, "api_calls": call_count, "raw_sha256": raw_sha,
                  "response_metadata": response_meta, "output_budget": budget,
                  "finished_at_utc": _utc(), "validation": validation}
        # Retain structural evidence even when the independent budget gate fails.
        _atomic_write_json(qdir / "validation.json", parsed)
        if not budget["within_gate"]:
            result = {**common, "status": "blocked_output_budget"}
            _atomic_write_json(qdir / "run.json", result)
            append_ledger_event(ledger_root, run_id=run_id, event="blocked_output_budget",
                                payload={"api_calls": call_count, "raw_sha256": raw_sha,
                                         "usage": usage, "output_budget": budget})
            return result
        _atomic_write_json(qdir / "validation.json", parsed)
        result = {**common, "status": ("awaiting_semantic_review" if parsed["status"] == "manual_review_required"
                                        else "needs_revision"), "validation": validation}
        _atomic_write_json(qdir / "run.json", result)
        append_ledger_event(ledger_root, run_id=result["run_id"], event=result["status"],
                            payload={"api_calls": call_count, "raw_sha256": raw_sha,
                                     "usage": usage, "finish_reason": finish_reason,
                                     "output_budget": budget})
        return result

    budget = _output_budget(raw, usage, max_tokens=params["max_tokens"],
                            max_bytes=params["body_max_bytes"],
                            thinking_enabled=params["thinking"] == {"type": "enabled"},
                            body_max_tokens=params["body_max_tokens"])
    common = {**started_record, "api_calls": call_count, "raw_sha256": raw_sha,
              "response_metadata": response_meta, "output_budget": budget,
              "finished_at_utc": _utc()}
    if not budget["within_gate"]:
        result = {**common, "status": "blocked_output_budget"}
        _atomic_write_json(qdir / "validation.json", result)
        _atomic_write_json(qdir / "run.json", result)
        append_ledger_event(ledger_root, run_id=run_id, event="blocked_output_budget",
                            payload={"api_calls": call_count, "raw_sha256": raw_sha,
                                     "usage": usage, "output_budget": budget})
        return result
    if finish_reason != "stop":
        result = {**common, "status": "invalid_response",
                  "error": "非正常 finish_reason，不能计结构成功"}
        _atomic_write_json(qdir / "validation.json", result)
        _atomic_write_json(qdir / "run.json", result)
        append_ledger_event(ledger_root, run_id=run_id, event="invalid_response",
                            payload={"api_calls": call_count, "raw_sha256": raw_sha,
                                     "usage": usage, "finish_reason": finish_reason})
        return result
    try:
        parsed = _parse_candidate_answer(raw, host_response=host_response,
                                         snapshot=snapshot, mode=mode,
                                         protocol=protocol)
        validation = {
            "status": parsed["status"],
            "mode": mode,
            "protocol": protocol,
            "interpretation_count": len(parsed["interpretations"]),
            "watchlist_count": len(parsed["watchlist"]),
        }
        if mode == "policy":
            validation["policy_explanation_count"] = len(parsed["policy_explanations"])
        _atomic_write_json(qdir / "validation.json", parsed)
    except Exception as exc:
        details = safe_error_details(exc)
        result = {**common, "status": "invalid_response", "error_details": details}
        _atomic_write_json(qdir / "validation.json", result)
        _atomic_write_json(qdir / "run.json", result)
        append_ledger_event(ledger_root, run_id=run_id, event="invalid_response",
                            payload={"api_calls": call_count, "raw_sha256": raw_sha,
                                     "usage": usage, "error_details": details})
        return result
    result = {**common, "status": ("awaiting_semantic_review" if parsed["status"] == "manual_review_required"
                                    else "needs_revision"), "validation": validation}
    _atomic_write_json(qdir / "run.json", result)
    append_ledger_event(ledger_root, run_id=run_id, event=result["status"],
                        payload={"api_calls": call_count, "raw_sha256": raw_sha,
                                 "usage": usage, "finish_reason": finish_reason,
                                 "output_budget": budget})
    return result


def run_injected(*, provider: dict[str, object], package_path: Path, output: Path,
                 question_id: str, provider_call, freeze: dict[str, object],
                 matrix_path: Path = DEFAULT_MATRIX,
                 ledger_root: Path = ROOT) -> dict[str, object]:
    """Run one question with an offline injected provider (never reads a key)."""
    if question_id not in QUESTION_IDS:
        raise ValueError("question_id 只能是 q1..q4")
    plan = preflight(matrix_path=matrix_path, provider_id=provider["id"],
                     package_path=package_path)
    if _validate_provider(provider) != plan["provider"]:
        raise ValueError("调用方provider与矩阵配置不一致")
    freeze_sha = verify_freeze(freeze=freeze, provider=plan["provider"],
                               package_path=package_path, matrix_path=matrix_path,
                               allow_candidate=True)
    return _run_one_question(provider=plan["provider"], package_path=package_path,
                             output=output, question_id=question_id,
                             matrix_path=matrix_path, provider_call=provider_call,
                             freeze=freeze, freeze_sha=freeze_sha,
                             ledger_root=Path(ledger_root), execution_channel="offline_injected")


def run(*, provider: dict[str, object], package_path: Path, output: Path,
        execute: bool, authorize_real_call: bool,
        question_ids: tuple[str, ...] = QUESTION_IDS,
        matrix_path: Path = DEFAULT_MATRIX,
        freeze_path: Path | None = None,
        ledger_root: Path = ROOT) -> dict[str, object]:
    plan = preflight(matrix_path=matrix_path, provider_id=provider["id"],
                     package_path=package_path)
    if _validate_provider(provider) != plan["provider"]:
        raise ValueError("调用方provider与矩阵配置不一致")
    if not execute:
        return plan
    if plan["provider"]["channel"] == MANUAL_SESSION_CHANNEL:
        raise ValueError("Codex 候选需在独立无历史上下文的新会话手动测试；本执行器不会冒充发送API")
    if Path(ledger_root).resolve() != ROOT.resolve():
        raise ValueError("真实API固定使用项目账本，不能换目录绕过去重")
    if not authorize_real_call:
        raise ValueError("真实请求必须同时提供 --execute 和 --authorize-real-call")
    if len(question_ids) != 1 or question_ids[0] not in QUESTION_IDS:
        raise ValueError("真实执行暂未放行：每次只能发送一道 q1..q4，按顺序逐题执行")
    if freeze_path is None or not Path(freeze_path).is_file():
        raise ValueError("真实执行暂未放行：缺少 ready_for_formal 冻结记录")
    freeze = json.loads(Path(freeze_path).read_text(encoding="utf-8"))
    freeze_sha = verify_freeze(freeze=freeze, provider=plan["provider"],
                               package_path=package_path, matrix_path=matrix_path)
    key = os.environ.get(str(plan["provider"]["secret_env"]), "").strip()
    if not key:
        raise ValueError("指定的 API key 环境变量未配置；不会回退读取历史配置")
    params = freeze["params"]
    config = OpenAICompatibleConfig(plan["provider"]["base_url"],
                                    plan["provider"]["model_id"], key,
                                    timeout_seconds=params["timeout_seconds"],
                                    temperature=params["temperature"])
    request_params = {"max_tokens": params["max_tokens"], "thinking": params["thinking"]}
    if params["reasoning_effort"] is not None:
        request_params["reasoning_effort"] = params["reasoning_effort"]
    model = _PublicEvalModel(config, request_params=request_params,
        opener=_no_redirect_opener())
    result = _run_one_question(provider=plan["provider"], package_path=package_path,
                               output=output, question_id=question_ids[0],
                               matrix_path=matrix_path,
                               provider_call=model.complete, freeze=freeze,
                               freeze_sha=freeze_sha, ledger_root=Path(ledger_root))
    return {**plan, "status": result["status"], "api_calls": result.get("api_calls", 0),
            "question_results": [result], "semantic_scoring": "pending_blinded_review"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-id", required=True)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--questions", default=",".join(QUESTION_IDS),
                        help="默认q1,q2,q3,q4；可先传q1,q2做低成本首轮")
    parser.add_argument("--execute", action="store_true", help="实际调用API")
    parser.add_argument("--authorize-real-call", action="store_true",
                        help="明确授权本次真实请求；缺少时只做预检")
    parser.add_argument("--freeze", type=Path,
                        help="ready_for_formal 冻结记录；缺少时真实调用会拒绝")
    parser.add_argument("--ledger-root", type=Path, default=ROOT,
                        help="评测账本根目录（默认项目根目录）")
    args = parser.parse_args()
    try:
        ids = tuple(item.strip() for item in args.questions.split(",") if item.strip())
        plan = preflight(matrix_path=args.matrix, package_path=args.package,
                         provider_id=args.provider_id)
        selected = plan["provider"]
        result = run(provider=selected, package_path=args.package,
                     output=args.output or ROOT / "tmp/public-brief-eval-v1/unused",
                     execute=args.execute, authorize_real_call=args.authorize_real_call,
                     question_ids=ids, matrix_path=args.matrix,
                     freeze_path=args.freeze, ledger_root=args.ledger_root)
    except (ValueError, OSError, json.JSONDecodeError, ModelAdapterError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({k: v for k, v in result.items() if k not in {"provider", "question_results"}},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
