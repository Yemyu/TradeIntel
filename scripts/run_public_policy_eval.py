"""Run the isolated policy Q3 contract against one provider configuration.

The default command only performs an offline preflight.  A provider request
requires both ``--execute`` and ``--authorize-real-call`` plus a formal
freeze.  The injected path is used by offline tests and records zero API
calls in an independent policy ledger.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_public_brief_eval import (  # noqa: E402
    DEFAULT_MATRIX, MAX_OUTPUT_BYTES, MAX_OUTPUT_TOKENS, MAX_TOTAL_OUTPUT_TOKENS,
    BUDGET_PROTOCOL_V3, ProviderDeadlineExceeded, _NoRedirectHandler,
    _PublicEvalModel, _atomic_write_text, _output_budget, _provider_deadline, _require_deadline_support,
    _response_parts, _safe_url, _sha_bytes, _sha_text, _utc, _validate_provider,
    safe_error_details, OpenAICompatibleConfig,
)
from scripts.prepare_public_eval_diagnostic import estimate_input_tokens  # noqa: E402
from src.tradeintel_ai.public_policy_explanation import PROTOCOL, parse as parse_policy  # noqa: E402
from src.tradeintel_ai.public_policy_eval_ledger import (  # noqa: E402
    DuplicatePolicyRun, append as append_ledger, claim as claim_ledger,
)
from src.tradeintel_ai.public_eval_ledger import canonical_sha  # noqa: E402

PACKAGE_SCHEMA = "public-policy-service-candidate-v1"
FREEZE_SCHEMA = "public-policy-freeze-v1"
FREEZE_EXPERIMENT_ID = "public-policy-q3-v1"
SCORING_FILES = ("evals/public_brief_v1/SCORING_POLICY_Q3.zh-CN.md",)
QUESTION_ID = "q3"
MAX_POLICY_BODY_CHARS = 2000
RUNTIME_FILES = (
    "scripts/prepare_public_policy_candidate.py",
    "scripts/run_public_policy_eval.py",
    "src/tradeintel_ai/public_policy_explanation.py",
    "src/tradeintel_ai/public_policy_eval_ledger.py",
    "src/tradeintel_ai/session_explanation.py",
    "src/tradeintel_ai/public_report.py",
    "src/tradeintel_ai/interpretation_review_store.py",
    "src/tradeintel_ai/model_adapter.py",
    "src/tradeintel_ai/public_eval_ledger.py",
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def _bound_hashes(relative_paths: tuple[str, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in relative_paths:
        path = ROOT / relative
        if not path.is_file():
            raise ValueError("冻结所需文件不存在：" + relative)
        result[relative] = _sha_bytes(path)
    return result


def _validate_matrix_path(path: Path) -> dict[str, object]:
    matrix = json.loads(Path(path).read_text(encoding="utf-8"))
    if (not isinstance(matrix, dict)
            or matrix.get("schema_version") != "public-brief-provider-matrix-v1"
            or not isinstance(matrix.get("candidates"), list)
            or not all(isinstance(item, dict) for item in matrix["candidates"])):
        raise ValueError("provider matrix格式不合法")
    ids = [item.get("id") for item in matrix["candidates"]]
    if not all(isinstance(item, str) and item for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("provider matrix候选ID无效或重复")
    return matrix


def _verify_host_binding(snapshot: dict, response: dict) -> None:
    for field in ("report", "report_sha256", "evidence_sha256"):
        if field not in snapshot or field not in response or snapshot[field] != response[field]:
            raise ValueError("政策Q3快照与程序报告绑定不一致：" + field)


def _freeze_provider(provider: dict[str, object]) -> dict[str, object]:
    return {key: deepcopy(provider.get(key)) for key in (
        "id", "label", "channel", "provider", "model_id", "base_url",
        "request_params", "reasoning_effort", "status")}


def _verify_candidate(package: Path) -> dict[str, object]:
    package = Path(package).resolve()
    manifest_path = package / "MANIFEST.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("政策候选题包缺少MANIFEST")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("schema_version") != PACKAGE_SCHEMA
            or manifest.get("protocol") != PROTOCOL
            or manifest.get("status") != "candidate_only_not_frozen"
            or manifest.get("api_calls") != 0
            or manifest.get("question_ids") != [QUESTION_ID]):
        raise ValueError("政策候选题包状态、协议或题号不匹配")
    files = manifest.get("files_sha256")
    required = {
        "requests/q3/messages.json", "host_artifacts/q3/response.json",
        "host_artifacts/q3/snapshot.json", "host_artifacts/q3/reference.json",
    }
    if not isinstance(files, dict) or not required <= set(files):
        raise ValueError("政策候选题包缺少必需材料摘要")
    for relative, expected in files.items():
        path = package / relative
        if (Path(relative).is_absolute() or ".." in Path(relative).parts
                or not path.resolve().is_relative_to(package)
                or path.is_symlink() or not path.is_file()
                or _sha_bytes(path) != expected):
            raise ValueError("政策候选材料摘要不匹配：" + relative)
    messages = json.loads((package / "requests/q3/messages.json").read_text(encoding="utf-8"))
    estimate = estimate_input_tokens(messages)
    if (estimate != manifest.get("input_estimate")
            or estimate["tokens"] > estimate["hard"]):
        raise ValueError("政策Q3输入预算与登记不符或超过硬门")
    snapshot = json.loads((package / "host_artifacts/q3/snapshot.json").read_text(encoding="utf-8"))
    response = json.loads((package / "host_artifacts/q3/response.json").read_text(encoding="utf-8"))
    _verify_host_binding(snapshot, response)
    if (snapshot.get("protocol") != PROTOCOL or snapshot.get("mode") != "policy"
            or snapshot.get("messages") != messages):
        raise ValueError("政策候选快照与消息协议不一致")
    runtime = manifest.get("code_sha256")
    if not isinstance(runtime, dict) or set(runtime) != set(
            ["scripts/prepare_public_policy_candidate.py", "scripts/run_public_policy_eval.py",
             "src/tradeintel_ai/public_policy_explanation.py", "src/tradeintel_ai/session_explanation.py",
             "src/tradeintel_ai/public_report.py", "src/tradeintel_ai/interpretation_review_store.py",
             "src/tradeintel_ai/model_adapter.py", "src/tradeintel_ai/public_eval_ledger.py",
             "src/tradeintel_ai/public_policy_eval_ledger.py",
             "evals/public_brief_v1/scenarios.json"]):
        raise ValueError("政策候选包运行时代码清单不完整")
    for relative, expected in runtime.items():
        path = ROOT / relative
        if (Path(relative).is_absolute() or ".." in Path(relative).parts
                or not path.is_file() or _sha_bytes(path) != expected):
            raise ValueError("政策候选包运行代码已变化：" + relative)
    return manifest


def build_freeze_spec(*, provider: dict[str, object], package_path: Path,
                      matrix_path: Path = DEFAULT_MATRIX,
                      timeout_seconds: float = 90.0,
                      temperature: float = 0.0) -> dict[str, object]:
    _validate_matrix_path(matrix_path)
    checked = _validate_provider(provider)
    manifest = _verify_candidate(package_path)
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 90:
        raise ValueError("timeout_seconds必须位于0至90秒")
    if type(temperature) not in (int, float) or not 0 <= temperature <= 2:
        raise ValueError("temperature必须位于0至2")
    return {
        "schema_version": FREEZE_SCHEMA,
        "experiment_id": FREEZE_EXPERIMENT_ID,
        "status": "candidate_not_formal",
        "protocol": PROTOCOL,
        "provider": _freeze_provider(checked),
        "package": str(Path(package_path).resolve()),
        "package_manifest_sha256": _sha_bytes(Path(package_path) / "MANIFEST.json"),
        "provider_matrix_sha256": _sha_bytes(Path(matrix_path)),
        "scoring_sha256": _bound_hashes(SCORING_FILES),
        "runtime_sha256": _bound_hashes(RUNTIME_FILES),
        "params": {
            "temperature": temperature,
            "thinking": deepcopy(checked["request_params"]["thinking"]),
            "max_tokens": checked["request_params"]["max_tokens"],
            "reasoning_effort": checked["request_params"].get("reasoning_effort"),
            "timeout_seconds": timeout_seconds,
            "budget_protocol": BUDGET_PROTOCOL_V3,
            "body_max_bytes": MAX_OUTPUT_BYTES,
            "body_max_chars": MAX_POLICY_BODY_CHARS,
        },
        "created_at_utc": _utc(),
    }


def verify_freeze(*, freeze: dict[str, object], provider: dict[str, object],
                  package_path: Path, matrix_path: Path = DEFAULT_MATRIX,
                  allow_candidate: bool = False) -> str:
    _validate_matrix_path(matrix_path)
    if not isinstance(freeze, dict) or freeze.get("schema_version") != FREEZE_SCHEMA:
        raise ValueError("政策Q3需要public-policy-freeze-v1")
    if freeze.get("experiment_id") != FREEZE_EXPERIMENT_ID or freeze.get("protocol") != PROTOCOL:
        raise ValueError("政策Q3冻结身份或协议不匹配")
    if not allow_candidate and freeze.get("status") != "ready_for_formal":
        raise ValueError("政策Q3冻结尚未获得ready_for_formal审核")
    checked = _validate_provider(provider)
    if freeze.get("provider") != _freeze_provider(checked):
        raise ValueError("冻结provider与调用方不一致")
    package = Path(package_path).resolve()
    manifest_path = package / "MANIFEST.json"
    if (freeze.get("package") != str(package)
            or freeze.get("package_manifest_sha256") != _sha_bytes(manifest_path)):
        raise ValueError("政策候选题包已变化")
    if freeze.get("provider_matrix_sha256") != _sha_bytes(Path(matrix_path)):
        raise ValueError("provider matrix已变化")
    if freeze.get("scoring_sha256") != _bound_hashes(SCORING_FILES):
        raise ValueError("政策评分文件已变化")
    if freeze.get("runtime_sha256") != _bound_hashes(RUNTIME_FILES):
        raise ValueError("政策Q3运行代码已变化")
    params = freeze.get("params")
    expected = {"temperature", "thinking", "max_tokens", "reasoning_effort",
                "timeout_seconds", "budget_protocol", "body_max_bytes", "body_max_chars"}
    if not isinstance(params, dict) or set(params) != expected:
        raise ValueError("政策Q3冻结预算字段不完整")
    if params["budget_protocol"] != BUDGET_PROTOCOL_V3:
        raise ValueError("政策Q3只接受v3预算")
    if params["thinking"] != checked["request_params"]["thinking"]:
        raise ValueError("冻结thinking与provider不一致")
    if params["max_tokens"] != checked["request_params"]["max_tokens"]:
        raise ValueError("冻结max_tokens与provider不一致")
    if params["reasoning_effort"] != checked["request_params"].get("reasoning_effort"):
        raise ValueError("冻结推理档位与provider不一致")
    if type(params["body_max_bytes"]) is not int or params["body_max_bytes"] != MAX_OUTPUT_BYTES:
        raise ValueError("政策Q3原始字节门不合法")
    if type(params["body_max_chars"]) is not int or params["body_max_chars"] != MAX_POLICY_BODY_CHARS:
        raise ValueError("政策Q3正文字符门不合法")
    return canonical_sha(freeze)


def preflight(*, provider_id: str, package_path: Path,
              matrix_path: Path = DEFAULT_MATRIX) -> dict[str, object]:
    matrix = _validate_matrix_path(matrix_path)
    candidates = matrix.get("candidates") if isinstance(matrix, dict) else None
    selected = next((item for item in candidates or [] if item.get("id") == provider_id), None)
    if selected is None:
        raise ValueError("provider matrix中没有该候选")
    provider = _validate_provider(selected)
    manifest = _verify_candidate(package_path)
    return {"schema_version": "public-policy-provider-run-v1", "status": "preflight_passed",
            "api_calls": 0, "protocol": PROTOCOL, "provider": provider,
            "package": str(Path(package_path).resolve()),
            "package_manifest_sha256": _sha_bytes(Path(package_path) / "MANIFEST.json"),
            "question": QUESTION_ID, "input_tokens": manifest["input_estimate"]["tokens"]}


def _read_bound(package: Path, manifest: dict[str, object], relative: str) -> object:
    path = package / relative
    if (not path.is_file() or path.is_symlink()
            or _sha_bytes(path) != manifest["files_sha256"].get(relative)):
        raise ValueError("政策Q3材料发送前发生变化：" + relative)
    return json.loads(path.read_text(encoding="utf-8"))


def _run_one(*, provider: dict[str, object], package_path: Path, output: Path,
             provider_call, freeze: dict[str, object], freeze_sha: str,
             ledger_root: Path, execution_channel: str) -> dict[str, object]:
    package = Path(package_path).resolve()
    manifest = _verify_candidate(package)
    messages = _read_bound(package, manifest, "requests/q3/messages.json")
    host_response = _read_bound(package, manifest, "host_artifacts/q3/response.json")
    snapshot = _read_bound(package, manifest, "host_artifacts/q3/snapshot.json")
    if not isinstance(snapshot, dict) or not isinstance(host_response, dict):
        raise ValueError("政策Q3主机材料不是对象")
    _verify_host_binding(snapshot, host_response)
    provider_digest = canonical_sha({"provider": _freeze_provider(provider),
                                    "execution_channel": execution_channel})
    base_key = canonical_sha({"package_manifest": _sha_bytes(package / "MANIFEST.json"),
                              "provider": provider_digest, "question": QUESTION_ID,
                              "protocol": PROTOCOL})
    if output.exists():
        raise ValueError("输出目录已存在；每次政策Q3运行使用新目录")
    params = deepcopy(freeze["params"])
    _require_deadline_support()
    started = claim_ledger(ledger_root, base_key=base_key, metadata={
        "question_id": QUESTION_ID, "execution_channel": execution_channel,
        "package_manifest_sha256": _sha_bytes(package / "MANIFEST.json"),
        "provider_id": provider["id"], "provider_digest": provider_digest,
        "freeze_sha256": freeze_sha, "params": params,
        "output_dir": str(Path(output).resolve()),
    })
    run_id = started["run_id"]
    qdir = Path(output) / QUESTION_ID
    qdir.mkdir(parents=True)
    started_record = {"schema_version": "public-policy-provider-run-v1", "status": "started",
                      "run_id": run_id, "question_id": QUESTION_ID,
                      "execution_channel": execution_channel,
                      "provider": {"id": provider["id"], "model_id": provider["model_id"]},
                      "freeze_sha256": freeze_sha, "params": params, "api_calls": 0,
                      "started_at_utc": _utc()}
    _write_json(qdir / "run.json", started_record)
    started_monotonic = time.monotonic()
    call_count = int(execution_channel == "real_api")
    try:
        with _provider_deadline(params["timeout_seconds"]):
            response = provider_call(messages=messages, tools=[])
            raw, metadata = _response_parts(response)
    except (ProviderDeadlineExceeded, KeyboardInterrupt, Exception) as exc:
        kind = ("wall_clock_deadline" if isinstance(exc, ProviderDeadlineExceeded)
                else "operator_interrupted" if isinstance(exc, KeyboardInterrupt)
                else "transport_error")
        result = {**started_record, "status": "unknown_outcome", "api_calls": call_count,
                  "error_kind": kind, "error_details": ({"message": "请求总时长截止，服务端结果未知"}
                                                           if kind == "wall_clock_deadline"
                                                           else safe_error_details(exc)),
                  "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
                  "finished_at_utc": _utc()}
        _write_json(qdir / "run.json", result)
        append_ledger(ledger_root, run_id=run_id, event="unknown_outcome",
                      payload={"api_calls": call_count, "error_kind": kind})
        return result
    usage = metadata.get("usage") if isinstance(metadata.get("usage"), dict) else {}
    finish_reason = metadata.get("finish_reason")
    response_meta = {"requested_model": provider["model_id"],
                     "returned_model": metadata.get("model"), "finish_reason": finish_reason,
                     "usage": usage, "params": params,
                     "elapsed_seconds": round(time.monotonic() - started_monotonic, 3)}
    _write_json(qdir / "response-metadata.json", response_meta)
    raw_path = qdir / "raw-response.txt"
    _atomic_write_text(raw_path, raw)
    raw_sha = _sha_text(raw)
    if finish_reason != "stop":
        result = {**started_record, "status": "invalid_response", "api_calls": call_count,
                  "raw_sha256": raw_sha, "response_metadata": response_meta,
                  "error": "非正常finish_reason，不能计结构成功", "finished_at_utc": _utc()}
        _write_json(qdir / "run.json", result)
        append_ledger(ledger_root, run_id=run_id, event="invalid_response",
                      payload={"api_calls": call_count, "raw_sha256": raw_sha})
        return result
    try:
        parsed = parse_policy(raw, host_response["report"], question=snapshot["question"],
                              policy_context=snapshot.get("policy_context") or {},
                              request_context=snapshot.get("request_context"))
    except Exception as exc:
        details = safe_error_details(exc)
        result = {**started_record, "status": "invalid_response", "api_calls": call_count,
                  "raw_sha256": raw_sha, "response_metadata": response_meta,
                  "error_details": details, "finished_at_utc": _utc()}
        _write_json(qdir / "validation.json", {"status": "invalid_response", "error_details": details,
                                                "raw_sha256": raw_sha})
        _write_json(qdir / "run.json", result)
        append_ledger(ledger_root, run_id=run_id, event="invalid_response",
                      payload={"api_calls": call_count, "raw_sha256": raw_sha,
                               "error_details": details})
        return result
    budget = _output_budget(raw, usage, max_tokens=params["max_tokens"],
                            max_bytes=params["body_max_bytes"], budget_protocol=BUDGET_PROTOCOL_V3,
                            body_max_chars=params["body_max_chars"], parsed=parsed)
    validation = {"protocol": PROTOCOL, "status": parsed["status"],
                  "raw_sha256": raw_sha, "policy_explanation_count": len(parsed["policy_explanations"]),
                  "interpretation_count": len(parsed["interpretations"]),
                  "watchlist_count": len(parsed["watchlist"])}
    _write_json(qdir / "validation.json", {**parsed, **validation})
    common = {**started_record, "api_calls": call_count, "raw_sha256": raw_sha,
              "response_metadata": response_meta, "output_budget": budget,
              "validation": validation, "finished_at_utc": _utc()}
    if not budget["within_gate"]:
        result = {**common, "status": "blocked_output_budget"}
        _write_json(qdir / "run.json", result)
        append_ledger(ledger_root, run_id=run_id, event="blocked_output_budget",
                      payload={"api_calls": call_count, "raw_sha256": raw_sha,
                               "output_budget": budget})
        return result
    result = {**common, "status": "awaiting_semantic_review"}
    _write_json(qdir / "run.json", result)
    append_ledger(ledger_root, run_id=run_id, event="awaiting_semantic_review",
                  payload={"api_calls": call_count, "raw_sha256": raw_sha,
                           "output_budget": budget})
    return result


def run_injected(*, provider: dict[str, object], package_path: Path, output: Path,
                 provider_call, freeze: dict[str, object],
                 matrix_path: Path = DEFAULT_MATRIX, ledger_root: Path = ROOT) -> dict[str, object]:
    plan = preflight(provider_id=provider["id"], package_path=package_path, matrix_path=matrix_path)
    freeze_sha = verify_freeze(freeze=freeze, provider=plan["provider"], package_path=package_path,
                               matrix_path=matrix_path, allow_candidate=True)
    result = _run_one(provider=plan["provider"], package_path=package_path, output=output,
                      provider_call=provider_call, freeze=freeze, freeze_sha=freeze_sha,
                      ledger_root=Path(ledger_root), execution_channel="offline_injected")
    return {**plan, "status": result["status"], "api_calls": result["api_calls"],
            "run": result, "semantic_scoring": "pending_blinded_review"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-id", required=True)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--candidate-freeze-output", type=Path,
                        help="离线写入candidate冻结；不会获得真实调用许可")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--authorize-real-call", action="store_true")
    parser.add_argument("--ledger-root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        plan = preflight(provider_id=args.provider_id, package_path=args.package, matrix_path=args.matrix)
        if not args.execute:
            if args.candidate_freeze_output is not None:
                freeze = build_freeze_spec(provider=plan["provider"], package_path=args.package,
                                           matrix_path=args.matrix)
                _write_json(args.candidate_freeze_output, freeze)
                plan = {**plan, "candidate_freeze": str(args.candidate_freeze_output.resolve()),
                        "freeze_status": freeze["status"]}
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0
        if not args.authorize_real_call:
            raise ValueError("真实请求必须同时提供--execute和--authorize-real-call")
        if args.freeze is None or not args.freeze.is_file():
            raise ValueError("真实请求需要ready_for_formal政策冻结")
        if args.output is None:
            raise ValueError("真实请求需要新的输出目录")
        if args.ledger_root.resolve() != ROOT.resolve():
            raise ValueError("真实请求必须使用项目固定账本，不能更换账本目录")
        freeze = json.loads(args.freeze.read_text(encoding="utf-8"))
        freeze_sha = verify_freeze(freeze=freeze, provider=plan["provider"], package_path=args.package,
                                   matrix_path=args.matrix)
        key = str(plan["provider"]["secret_env"])
        import os
        secret = os.environ.get(key, "").strip()
        if not secret:
            raise ValueError("API key环境变量未配置；不会读取历史配置")
        params = freeze["params"]
        config = OpenAICompatibleConfig(plan["provider"]["base_url"], plan["provider"]["model_id"], secret,
                                        timeout_seconds=params["timeout_seconds"], temperature=params["temperature"])
        request_params = {"max_tokens": params["max_tokens"], "thinking": params["thinking"]}
        if params["reasoning_effort"] is not None:
            request_params["reasoning_effort"] = params["reasoning_effort"]
        model = _PublicEvalModel(config, request_params=request_params,
                                 opener=__import__("urllib.request", fromlist=["build_opener"])
                                 .build_opener(_NoRedirectHandler()).open)
        result = _run_one(provider=plan["provider"], package_path=args.package, output=args.output,
                          provider_call=model.complete, freeze=freeze, freeze_sha=freeze_sha,
                          ledger_root=args.ledger_root, execution_channel="real_api")
        print(json.dumps({**plan, "status": result["status"], "api_calls": result["api_calls"],
                          "run": result}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "preflight_failed", "error": safe_error_details(exc)},
                         ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
