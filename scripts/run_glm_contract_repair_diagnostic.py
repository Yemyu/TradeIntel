"""Run one isolated GLM format-repair diagnostic.

This is deliberately separate from the frozen unified evaluator.  It copies
the saved Q1 materials, adds one prompt-only intervention, and can make at
most one provider request.  It never reads or writes the formal provider
ledger and never modifies the source package.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import time
from urllib.request import HTTPRedirectHandler, build_opener

from src.tradeintel_ai.model_adapter import (
    ModelAdapterError,
    OpenAICompatibleConfig,
    OpenAICompatibleModel,
    safe_error_details,
)
from src.tradeintel_ai.public_brief_explanation import parse
from scripts.prepare_public_eval_diagnostic import estimate_input_tokens
from scripts.run_public_brief_eval import _output_budget


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PACKAGE = ROOT / "tmp/public-brief-eval-v2/unified-service-20260923-v2"
DEFAULT_OUTPUT = ROOT / "tmp/public-brief-eval-v2/glm-contract-repair-20260923-r1"
MODEL_ID = "glm-4.6v"
BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
TIMEOUT_SECONDS = 90.0
MAX_TOKENS = 8192
BODY_MAX_BYTES = 65536
BODY_MAX_CHARS = 2000

INTERVENTION = (
    "FORMAT: text/rationale 禁止数字、日期、税号、金额；先自检。"
)


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        raise ModelAdapterError("模型端点发生重定向，诊断拒绝发送凭证")


class _DeadlineExceeded(BaseException):
    pass


@contextmanager
def _deadline(seconds: float):
    if not hasattr(signal, "setitimer") or signal.getitimer(signal.ITIMER_REAL)[0]:
        raise RuntimeError("当前环境不支持安全的单次总时长截止")
    old = signal.getsignal(signal.SIGALRM)

    def alarm(signum, frame):
        raise _DeadlineExceeded()

    signal.signal(signal.SIGALRM, alarm)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def _sha_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _write_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    path.write_text(raw, encoding="utf-8")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def prepare(source: Path, output: Path) -> dict[str, object]:
    source = source.resolve()
    output = output.resolve()
    if output.exists():
        raise ValueError("诊断输出目录已存在，不覆盖历史材料")
    if not (source / "MANIFEST.json").is_file():
        raise ValueError("源题包缺少 MANIFEST.json")
    source_manifest = json.loads((source / "MANIFEST.json").read_text(encoding="utf-8"))
    if source_manifest.get("schema_version") != "public-service-candidate-v2":
        raise ValueError("源题包不是统一 v2 候选包")
    files = source_manifest.get("files_sha256")
    if not isinstance(files, dict):
        raise ValueError("源题包缺少文件摘要")
    for relative, expected in files.items():
        path = source / relative
        if not path.is_file() or _sha_bytes(path) != expected:
            raise ValueError("源题包摘要不一致：" + relative)
    qdir = source / "requests" / "q1"
    hdir = source / "host_artifacts" / "q1"
    messages = json.loads((qdir / "messages.json").read_text(encoding="utf-8"))
    if not isinstance(messages, list) or not messages or messages[0].get("role") != "system":
        raise ValueError("Q1 消息结构不正确")
    repaired = [dict(item) for item in messages]
    repaired[0]["content"] = str(repaired[0].get("content", "")) + INTERVENTION
    output.mkdir(parents=True)
    (output / "q1").mkdir()
    artifacts = {
        output / "q1" / "messages.json": repaired,
        output / "q1" / "host_response.json": json.loads((hdir / "response.json").read_text(encoding="utf-8")),
        output / "q1" / "snapshot.json": json.loads((hdir / "snapshot.json").read_text(encoding="utf-8")),
        output / "q1" / "reference.json": json.loads((source / "references" / "q1.json").read_text(encoding="utf-8")),
    }
    artifact_hashes = {str(path.relative_to(output)): _write_json(path, value)
                       for path, value in artifacts.items()}
    input_estimate = estimate_input_tokens(repaired)
    if input_estimate["tokens"] > input_estimate["hard"]:
        raise ValueError("修复提示加入后超过输入硬门")
    manifest = {
        "schema_version": "glm-contract-repair-diagnostic-v1",
        "experiment_id": "public-brief-glm-contract-repair-20260923-r1",
        "status": "ready_for_one_q1",
        "provider": {"model_id": MODEL_ID, "base_url": BASE_URL,
                     "thinking": {"type": "enabled"}, "reasoning_effort": None},
        "source_package": str(source),
        "source_manifest_sha256": _sha_bytes(source / "MANIFEST.json"),
        "source_q1_messages_sha256": _sha_bytes(qdir / "messages.json"),
        "intervention_sha256": hashlib.sha256(INTERVENTION.encode("utf-8")).hexdigest(),
        "question_id": "q1",
        "parameters": {"temperature": 0.0, "max_tokens": MAX_TOKENS,
                        "thinking": {"type": "enabled"},
                        "timeout_seconds": TIMEOUT_SECONDS,
                        "body_max_bytes": BODY_MAX_BYTES,
                        "body_max_chars": BODY_MAX_CHARS,
                        "budget_protocol": "v3"},
        "input_estimate": input_estimate,
        "artifact_sha256": artifact_hashes,
        "api_calls": 0,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    manifest_sha = _write_json(output / "MANIFEST.json", manifest)
    return {"status": "prepared", "output": str(output),
            "manifest_sha256": manifest_sha, "api_calls": 0,
            "input_estimate": input_estimate}


def execute(output: Path, key_env: str) -> dict[str, object]:
    output = output.resolve()
    manifest_path = output / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "ready_for_one_q1":
        raise ValueError("诊断包不是待执行状态")
    key = os.environ.get(key_env, "").strip()
    if not key:
        raise ValueError("指定的临时 API key 环境变量为空")
    messages = json.loads((output / "q1" / "messages.json").read_text(encoding="utf-8"))
    host = json.loads((output / "q1" / "host_response.json").read_text(encoding="utf-8"))
    config = OpenAICompatibleConfig(BASE_URL, MODEL_ID, key,
                                    timeout_seconds=TIMEOUT_SECONDS, temperature=0.0)
    model = OpenAICompatibleModel(config, system_prompt="",
                                  opener=build_opener(_NoRedirectHandler()).open)
    started = time.monotonic()
    result: dict[str, object] = {"schema_version": "glm-contract-repair-run-v1",
                                 "experiment_id": manifest["experiment_id"],
                                 "question_id": "q1", "api_calls": 1,
                                 "manifest_sha256": _sha_bytes(manifest_path),
                                 "started_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        with _deadline(TIMEOUT_SECONDS):
            response = model.complete(messages=messages, tools=[])
    except _DeadlineExceeded:
        result.update(status="unknown_outcome", error_kind="wall_clock_deadline",
                      error="本地请求截止，服务端完成和计费未知")
        _write_json(output / "result.json", result)
        return result
    except BaseException as exc:
        result.update(status="unknown_outcome", error_kind=type(exc).__name__,
                      error_details=safe_error_details(exc),
                      error="模型请求未得到可确认结果")
        _write_json(output / "result.json", result)
        return result
    raw = response.text
    metadata = dict(response.metadata)
    _write_json(output / "response-metadata.json", metadata)
    (output / "raw-response.txt").write_text(raw, encoding="utf-8")
    finish_reason = metadata.get("finish_reason")
    result.update(returned_model=metadata.get("model"), finish_reason=finish_reason,
                  usage=metadata.get("usage", {}),
                  elapsed_seconds=round(time.monotonic() - started, 3),
                  raw_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest())
    if finish_reason != "stop":
        result.update(status="invalid_response", error="非 stop finish_reason")
        _write_json(output / "result.json", result)
        return result
    try:
        parsed = parse(raw, host["report"])
        budget = _output_budget(raw, metadata.get("usage", {}),
                                max_tokens=MAX_TOKENS, max_bytes=BODY_MAX_BYTES,
                                budget_protocol="v3", body_max_chars=BODY_MAX_CHARS,
                                parsed=parsed)
        _write_json(output / "validation.json", parsed)
        result.update(status="parsed", validation=parsed, output_budget=budget)
        if not budget.get("within_gate"):
            result["status"] = "blocked_output_budget"
    except BaseException as exc:
        result.update(status="invalid_response", error_kind=type(exc).__name__,
                      error_details=safe_error_details(exc))
    _write_json(output / "result.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_PACKAGE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--key-env", default="TRADEINTEL_GLM_API_KEY_REPAIR")
    args = parser.parse_args()
    try:
        prepared = prepare(args.source, args.output)
        result = execute(args.output, args.key_env) if args.execute else prepared
    except (ValueError, OSError, json.JSONDecodeError, ModelAdapterError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
