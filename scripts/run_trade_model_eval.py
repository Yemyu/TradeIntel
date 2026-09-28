"""Run one frozen v3 evaluation question at a time with a durable call record.

Preflight is the default. A live attempt needs both --live and
--authorize-one-call. A returned answer is screened for severe factual errors
before the next question is allowed; final comparative scoring is separate.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time
from typing import Any

from tradeintel_ai.local_provider_config import (
    CONFIG_PATH, PRODUCT_CONFIG_PATH, PRODUCT_PROVIDERS, load_config,
    load_product_config, product_config_identity, product_request_params, product_status,
)
from tradeintel_ai.model_adapter import ModelAdapterError, OpenAICompatibleModel
from tradeintel_ai.trade_explanation import MAX_INPUT_BYTES, MAX_RAW_BYTES, parse, report_sha256

from scripts.freeze_trade_model_eval import verify_frozen
from scripts.run_trade_v3_canary import (
    DeadlineExceeded, _atomic, _bytes, _deadline, _locked, _now,
    _safe_metadata, _save_raw, _SAFE_ERROR_KEYS,
)


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "tmp/trade-model-eval-v3/candidate-20260924-b"
FROZEN = ROOT / "evals/trade_model_v3/frozen/20260924-v2"
CASE_IDS = ("t1", "t2", "t3", "t4")
SCHEMA = "trade-v3-formal-case-v1"
DEADLINE_SECONDS = 90
MAX_TOKENS = 2048
MODELS = {
    "deepseek-flash-high": ("deepseek", "deepseek-flash"),
    "glm-4.6v-default": ("glm", "glm-4.6v"),
    "deepseek-v4-pro-high": ("deepseek", "deepseek-v4-pro"),
}


def _ledger_root(root: Path, model_id: str) -> Path:
    if model_id not in MODELS:
        raise ValueError("未登记的 API 模型候选")
    base = root / ".local"
    parent = base / "trade-model-eval-v3"
    folder = parent / model_id
    for path in (base, parent, folder):
        if path.is_symlink():
            raise ValueError("正式评测账本路径不安全")
        path.mkdir(mode=0o700, exist_ok=True)
        if not path.is_dir():
            raise ValueError("正式评测账本目录无效")
    return folder


def _read(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 100_000:
        raise ValueError("正式评测账本文件无效")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA:
        raise ValueError("正式评测账本结构无效")
    return value


def _verified(root: Path, candidate: Path, frozen: Path, model_id: str) -> dict[str, Any]:
    verify_frozen(root, candidate, frozen)
    matrix = json.loads((frozen / "MODEL_MATRIX.json").read_text(encoding="utf-8"))
    if not any(item.get("id") == model_id and item.get("planned_formal_questions") == 4
               and item.get("completed_formal_answers") == 0
               for item in matrix.get("candidates", [])):
        raise ValueError("模型未列入本版正式题包")
    return json.loads((frozen / "MANIFEST.json").read_text(encoding="utf-8"))


def _config(model_id: str) -> tuple[Any, dict[str, object], str, str]:
    provider, model = MODELS[model_id]
    if provider == "deepseek":
        if not PRODUCT_CONFIG_PATH.is_file() or PRODUCT_CONFIG_PATH.is_symlink():
            raise ValueError("本机没有安全保存的 DeepSeek 产品配置")
        base = load_product_config()
        status = product_status()
        params = {**product_request_params(), "max_tokens": MAX_TOKENS}
        if (status["provider"] != provider or status["model"] != "deepseek-flash" or
                status["reasoning"] not in {"default", "high"} or
                base.base_url.rstrip("/") != PRODUCT_PROVIDERS[provider] or
                params != {"thinking": {"type": "enabled"},
                           "reasoning_effort": "high", "max_tokens": MAX_TOKENS}):
            raise ValueError("DeepSeek 配置与冻结的 high 推理参数不一致")
        identity = product_config_identity()
    else:
        if not CONFIG_PATH.is_file() or CONFIG_PATH.is_symlink():
            raise ValueError("本机没有安全保存的 GLM 配置")
        base = load_config(CONFIG_PATH)
        if base.base_url.rstrip("/") != PRODUCT_PROVIDERS[provider]:
            raise ValueError("GLM 配置接口地址与候选不一致")
        params = {"max_tokens": MAX_TOKENS}
        identity = hashlib.sha256(_bytes({"base_url": base.base_url, "model": model,
                                          "api_key": base.api_key})).hexdigest()
    if not base.api_key or base.temperature != 0:
        raise ValueError("模型密钥或温度与冻结评测参数不一致")
    return replace(base, model=model, timeout_seconds=min(base.timeout_seconds, DEADLINE_SECONDS)), params, identity, provider


def _case_inputs(frozen: Path, manifest: dict[str, Any], case_id: str) -> tuple[list, dict, str]:
    if case_id not in CASE_IDS:
        raise ValueError("题目编号无效")
    messages = json.loads((frozen / f"requests/{case_id}/messages.json").read_text(encoding="utf-8"))
    report = json.loads((frozen / f"host_artifacts/{case_id}/report.json").read_text(encoding="utf-8"))
    digest = manifest["source_report_sha256_by_scenario"][case_id]
    if report_sha256(report) != digest or not isinstance(messages, list):
        raise ValueError("正式题目报告或消息不一致")
    if len(_bytes(messages)) > MAX_INPUT_BYTES:
        raise ValueError("正式题目输入超过产品预算")
    return messages, report, digest


def _paths(folder: Path, case_id: str) -> tuple[Path, Path, Path]:
    return folder / f"{case_id}.json", folder / f"{case_id}.raw.txt", folder / "model.lock"


def _gate(folder: Path, case_id: str) -> None:
    current, raw, _ = _paths(folder, case_id)
    if current.exists() or raw.exists():
        raise ValueError("这道正式题已有调用记录，不能再次调用")
    for prior in CASE_IDS[:CASE_IDS.index(case_id)]:
        record = _read(folder / f"{prior}.json")
        if (not record or record.get("status") != "needs_review" or
                record.get("safety_screen", {}).get("outcome") != "clear"):
            raise ValueError("前一题尚未完成严重事实错误筛查，不能继续")


def check(root: Path, candidate: Path, frozen: Path, model_id: str, case_id: str) -> dict[str, Any]:
    root, candidate, frozen = map(lambda path: Path(path).resolve(), (root, candidate, frozen))
    manifest = _verified(root, candidate, frozen, model_id)
    _case_inputs(frozen, manifest, case_id)
    config, params, _, provider = _config(model_id)
    folder = _ledger_root(root, model_id)
    _, _, lock = _paths(folder, case_id)
    with _locked(lock):
        _gate(folder, case_id)
    return {"status": "ready", "model_id": model_id, "requested_model": config.model,
            "provider": provider, "case_id": case_id, "max_tokens": params["max_tokens"],
            "deadline_seconds": DEADLINE_SECONDS, "api_calls_this_check": 0}


def _update(path: Path, lock: Path, changes: dict[str, Any]) -> dict[str, Any]:
    with _locked(lock):
        record = _read(path)
        if record is None or record.get("status") != "provider_call_started":
            raise ValueError("正式题状态已变化；不得覆盖")
        record.update(changes)
        _atomic(path, record)
        return record


def run_one(root: Path, candidate: Path, frozen: Path, model_id: str, case_id: str) -> dict[str, Any]:
    root, candidate, frozen = map(lambda path: Path(path).resolve(), (root, candidate, frozen))
    manifest = _verified(root, candidate, frozen, model_id)
    messages, report, digest = _case_inputs(frozen, manifest, case_id)
    config, params, identity, provider = _config(model_id)
    folder = _ledger_root(root, model_id)
    ledger, raw_path, lock = _paths(folder, case_id)
    started = {"schema_version": SCHEMA, "status": "provider_call_started",
               "case_id": case_id, "model_id": model_id, "provider": provider,
               "requested_model": config.model, "config_sha256": identity,
               "frozen_manifest_sha256": hashlib.sha256((frozen / "MANIFEST.json").read_bytes()).hexdigest(),
               "request_sha256": hashlib.sha256(_bytes(messages)).hexdigest(),
               "report_sha256": digest, "request_params": params,
               "deadline_seconds": DEADLINE_SECONDS, "api_calls_reserved": 1,
               "started_at": _now()}
    with _locked(lock):
        _gate(folder, case_id)
        _atomic(ledger, started)
    began = time.monotonic()
    try:
        with _deadline(DEADLINE_SECONDS):
            answer = OpenAICompatibleModel(config, system_prompt="",
                                           request_params=params).complete(messages=messages, tools=[])
            raw = getattr(answer, "text", None)
            if not isinstance(raw, str) or not raw.strip():
                return _update(ledger, lock, {"status": "failed", "ended_at": _now(),
                                              "elapsed_seconds": round(time.monotonic() - began, 3),
                                              "error_category": "empty_response"})
            raw_digest = _save_raw(raw_path, raw)
            metadata = _safe_metadata(getattr(answer, "metadata", None))
            usage = metadata.get("usage") or {}
            completion = usage.get("completion_tokens") if isinstance(usage, dict) else None
            if getattr(answer, "tool_calls", ()):
                error = "unexpected_tool_call"
            elif metadata["finish_reason"] != "stop":
                error = "finish_reason_not_stop"
            elif len(raw.encode("utf-8")) > MAX_RAW_BYTES or (type(completion) is int and completion > MAX_TOKENS):
                error = "output_over_budget"
            else:
                try:
                    parsed = parse(raw, report, digest)
                except ValueError:
                    error = "contract_rejected"
                else:
                    error = None
            return _update(ledger, lock, {"status": "needs_review" if error is None else "invalid_answer",
                                          "ended_at": _now(),
                                          "elapsed_seconds": round(time.monotonic() - began, 3),
                                          "raw_sha256": raw_digest, "raw_file": raw_path.name,
                                          "contract_pass": error is None,
                                          "interpretation_count": len(parsed["interpretations"]) if error is None else None,
                                          "error_category": error, **metadata})
    except ModelAdapterError as exc:
        code = exc.details.get("http_status")
        rejected = type(code) is int and 400 <= code < 500
        return _update(ledger, lock, {"status": "failed" if rejected else "unknown_outcome",
                                      "ended_at": _now(),
                                      "elapsed_seconds": round(time.monotonic() - began, 3),
                                      "error_category": "provider_rejected" if rejected else "provider_outcome_unknown",
                                      "error_details": {key: value for key, value in exc.details.items()
                                                        if key in _SAFE_ERROR_KEYS}})
    except Exception as exc:
        return _update(ledger, lock, {"status": "unknown_outcome", "ended_at": _now(),
                                      "elapsed_seconds": round(time.monotonic() - began, 3),
                                      "error_category": "total_deadline" if isinstance(exc, DeadlineExceeded)
                                      else "local_outcome_unknown"})


def screen(root: Path, model_id: str, case_id: str, *, outcome: str,
           reviewer: str, note: str) -> dict[str, Any]:
    if outcome not in {"clear", "severe"} or not reviewer.strip() or not note.strip():
        raise ValueError("筛查结果、审阅者及说明必须完整")
    folder = _ledger_root(Path(root).resolve(), model_id)
    ledger, raw, lock = _paths(folder, case_id)
    with _locked(lock):
        record = _read(ledger)
        if (not record or record.get("status") != "needs_review" or
                "safety_screen" in record or not raw.is_file() or raw.is_symlink() or
                hashlib.sha256(raw.read_bytes()).hexdigest() != record.get("raw_sha256")):
            raise ValueError("原答尚未完成或已筛查，不能记录筛查结论")
        record["safety_screen"] = {"outcome": outcome, "reviewer": reviewer,
                                   "note": note, "screened_at": _now(),
                                   "final_blind_scoring_complete": False}
        _atomic(ledger, record)
        return {"model_id": model_id, "case_id": case_id, "outcome": outcome,
                "next_case_allowed": outcome == "clear"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--frozen", type=Path, default=FROZEN)
    parser.add_argument("--model-id", choices=tuple(MODELS), required=True)
    parser.add_argument("--case", choices=CASE_IDS, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--authorize-one-call", action="store_true")
    parser.add_argument("--screen", choices=("clear", "severe"))
    parser.add_argument("--reviewer")
    parser.add_argument("--note")
    args = parser.parse_args()
    if args.screen:
        if args.live or args.authorize_one_call:
            parser.error("筛查与真实调用不能同时执行")
        result = screen(args.root, args.model_id, args.case, outcome=args.screen,
                        reviewer=args.reviewer or "", note=args.note or "")
    elif args.live and args.authorize_one_call:
        result = run_one(args.root, args.candidate, args.frozen, args.model_id, args.case)
    elif args.live or args.authorize_one_call:
        parser.error("真实调用需同时提供 --live 与 --authorize-one-call")
    else:
        result = check(args.root, args.candidate, args.frozen, args.model_id, args.case)
    visible = {key: value for key, value in result.items()
               if key not in {"config_sha256", "request_params"}}
    print(json.dumps(visible, ensure_ascii=False))


if __name__ == "__main__":
    main()
