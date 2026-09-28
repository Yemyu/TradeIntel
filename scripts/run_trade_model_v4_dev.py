"""One frozen v4 development question at a time; offline check is the default.

This is not the v3 formal runner and does not publish model text to the product.
A paid request needs --live, --authorize-one-call and a same-day price check.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any

from tradeintel_ai.local_provider_config import (
    PRODUCT_CONFIG_PATH, load_product_config, product_config_identity,
    product_request_params, product_status,
)
from tradeintel_ai.model_adapter import ModelAdapterError, OpenAICompatibleModel
from tradeintel_ai.trade_explanation_v4 import MAX_INPUT_BYTES, MAX_RAW_BYTES, parse

from scripts.freeze_trade_model_v4 import IDS, ROOT, _json_bytes, verify_frozen
from scripts.run_trade_v3_canary import (
    DeadlineExceeded, _atomic, _deadline, _locked, _now,
)


FROZEN = ROOT / "evals/trade_model_v4/frozen/20260928-v1"
LOCAL = ROOT / ".local/trade-model-eval-v4/deepseek-flash-high"
SCHEMA = "trade-model-v4-development-call-v1"
MODEL = "deepseek-flash"
ACCEPTED_RESPONSE_MODELS = frozenset({"deepseek-flash", "deepseek-v4.1-flash"})
PARAMS = {"thinking": {"type": "enabled"}, "reasoning_effort": "high",
          "max_tokens": 8192}
DEADLINE_SECONDS = 90
MAX_ALL_MESSAGE_BYTES = 24_000
RESERVED_INPUT_TOKENS = 40_000
PEAK_INPUT_USD_PER_M = Decimal("0.30")
PEAK_OUTPUT_USD_PER_M = Decimal("1.20")
PLANNED_USD_LIMIT = Decimal("0.06")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _today() -> str:
    return datetime.now().astimezone().date().isoformat()


def _budget() -> dict[str, object]:
    estimate = ((Decimal(RESERVED_INPUT_TOKENS) * PEAK_INPUT_USD_PER_M +
                 Decimal(len(IDS) * PARAMS["max_tokens"]) * PEAK_OUTPUT_USD_PER_M) /
                Decimal(1_000_000))
    if estimate > PLANNED_USD_LIMIT:
        raise ValueError("峰时预算估算超过事前上限")
    return {"price_basis": "DeepSeek peak, cache miss, checked again before live call",
            "reserved_input_tokens": RESERVED_INPUT_TOKENS,
            "reserved_output_tokens": len(IDS) * PARAMS["max_tokens"],
            "estimated_usd": str(estimate), "planned_usd_limit": str(PLANNED_USD_LIMIT),
            "account_hard_cap": False}


def _folder(*, create: bool) -> Path:
    paths = (LOCAL.parent.parent, LOCAL.parent, LOCAL)
    for path in paths:
        if path.is_symlink():
            raise ValueError("评测账本路径是符号链接")
        if path.exists() and not path.is_dir():
            raise ValueError("评测账本路径不是目录")
    if create:
        LOCAL.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(LOCAL, 0o700)
    return LOCAL


def _paths(case_id: str, *, create: bool) -> tuple[Path, Path, Path]:
    if case_id not in IDS:
        raise ValueError("未登记的 v4 题号")
    folder = _folder(create=create)
    return (folder / f"{case_id}.json", folder / f"{case_id}.raw.txt",
            folder / "model.lock")


def _read(path: Path) -> dict[str, Any] | None:
    if path.is_symlink():
        raise ValueError("v4 调用账本不能是符号链接")
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > 100_000:
        raise ValueError("v4 调用账本文件无效")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA:
        raise ValueError("v4 调用账本版本无效")
    return value


def _verified(root: Path, frozen: Path) -> dict[str, Any]:
    if frozen.is_symlink():
        raise ValueError("冻结包目录不能是符号链接")
    verify_frozen(root, frozen)
    manifest = json.loads((frozen / "MANIFEST.json").read_text(encoding="utf-8"))
    if sum(case["input_bytes"] for case in manifest["scenarios"].values()) > MAX_ALL_MESSAGE_BYTES:
        raise ValueError("四题消息超出事前输入预算")
    _budget()
    return manifest


def _case(frozen: Path, case_id: str) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any]]:
    if case_id not in IDS:
        raise ValueError("未登记的 v4 题号")
    folder = frozen / "cases" / case_id
    messages = json.loads((folder / "messages.json").read_text(encoding="utf-8"))
    record = json.loads((folder / "record.json").read_text(encoding="utf-8"))
    if not isinstance(messages, list) or len(_json_bytes(messages)) > MAX_INPUT_BYTES:
        raise ValueError("v4 模型消息格式或字节预算无效")
    return messages, record["report"], record


def _config() -> tuple[Any, str]:
    if not PRODUCT_CONFIG_PATH.is_file() or PRODUCT_CONFIG_PATH.is_symlink():
        raise ValueError("本机没有安全保存的产品模型配置")
    config = load_product_config()
    status = product_status()
    params = product_request_params()
    if (not config.api_key or status["provider"] != "deepseek" or
            status["model"] != MODEL or status["reasoning"] != "high" or
            config.model != MODEL or config.base_url.rstrip("/") != "https://api.deepseek.com" or
            config.temperature != 0 or params != PARAMS):
        raise ValueError("产品配置不符合唯一开发候选 DeepSeek Flash/high")
    return replace(config, timeout_seconds=min(config.timeout_seconds, DEADLINE_SECONDS)), product_config_identity()


def _gate(case_id: str, *, current_request_bytes: int, manifest_sha256: str) -> None:
    index = IDS.index(case_id)
    ledger, raw, _ = _paths(case_id, create=False)
    if ledger.is_symlink() or raw.is_symlink() or ledger.exists() or raw.exists():
        raise ValueError("本题已有调用记录或原答，不允许重试")
    gains = 0
    used_input = used_output = 0
    for prior in IDS[:index]:
        previous, _, _ = _paths(prior, create=False)
        record = _read(previous)
        if not record or record.get("status") != "reviewed_clear":
            raise ValueError("前题尚未通过人工审阅，不能继续")
        if (record.get("case_id") != prior or record.get("manifest_sha256") != manifest_sha256 or
                record.get("requested_model") != MODEL or record.get("request_params") != PARAMS):
            raise ValueError("前题账本与本次冻结材料或模型配置不一致")
        gains += int(record.get("review", {}).get("reading_gain") is True)
        usage = record.get("usage") or {}
        prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
        if type(prompt) is not int or type(completion) is not int:
            raise ValueError("前题缺少可核验的服务商用量，停止后续调用")
        used_input += prompt
        used_output += completion
    peak_used = ((Decimal(used_input) * PEAK_INPUT_USD_PER_M +
                  Decimal(used_output) * PEAK_OUTPUT_USD_PER_M) / Decimal(1_000_000))
    # This is a conservative local preflight, not a provider-side account cap.
    # Message bytes plus protocol overhead are reserved before the one call.
    next_input_reserve = current_request_bytes + 1024
    next_output_reserve = PARAMS["max_tokens"]
    projected_peak = ((Decimal(used_input + next_input_reserve) * PEAK_INPUT_USD_PER_M +
                       Decimal(used_output + next_output_reserve) * PEAK_OUTPUT_USD_PER_M) /
                      Decimal(1_000_000))
    if (used_input + next_input_reserve > RESERVED_INPUT_TOKENS or
            used_output + next_output_reserve > len(IDS) * PARAMS["max_tokens"] or
            peak_used > PLANNED_USD_LIMIT or projected_peak > PLANNED_USD_LIMIT):
        raise ValueError("前题用量超过事前预算，停止后续调用")
    if gains + len(IDS[index:]) < 2:
        raise ValueError("剩余题数已不可能达到阅读增益门，停止调用")


def _safe_metadata(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    result: dict[str, Any] = {}
    for source, target in (("response_id", "response_id"), ("model", "response_model"),
                           ("finish_reason", "finish_reason")):
        item = value.get(source)
        result[target] = (item if isinstance(item, str) and
                          re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", item) else None)
    usage = value.get("usage")
    safe_usage = {}
    if isinstance(usage, dict):
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            item = usage.get(field)
            if type(item) is int and 0 <= item <= 1_000_000:
                safe_usage[field] = item
        details = usage.get("completion_tokens_details")
        if isinstance(details, dict):
            reasoning = details.get("reasoning_tokens")
            if type(reasoning) is int and 0 <= reasoning <= 1_000_000:
                safe_usage["reasoning_tokens"] = reasoning
    result["usage"] = safe_usage or None
    return result


def _save_raw(path: Path, raw: str) -> str:
    body = raw.encode("utf-8")
    if len(body) > 1_000_000:
        raise ValueError("模型原答超过安全留档上限")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    return _sha(body)


def _update(case_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    ledger, _, lock = _paths(case_id, create=True)
    with _locked(lock):
        record = _read(ledger)
        if not record or record.get("status") != "provider_call_started":
            raise ValueError("v4 调用状态已变化，不能覆盖")
        record.update(changes)
        _atomic(ledger, record)
        return record


def check(root: Path = ROOT, frozen: Path = FROZEN, case_id: str = IDS[0]) -> dict[str, Any]:
    if Path(frozen).is_symlink():
        raise ValueError("冻结包目录不能是符号链接")
    root, frozen = Path(root).resolve(), Path(frozen).resolve()
    manifest = _verified(root, frozen)
    manifest_sha256 = _sha((frozen / "MANIFEST.json").read_bytes())
    messages, _report, _record = _case(frozen, case_id)
    config, _identity = _config()
    ledger, raw, _ = _paths(case_id, create=False)
    if ledger.is_symlink() or raw.is_symlink() or ledger.exists() or raw.exists():
        current = _read(ledger)
        state = current["status"] if current else "orphan_raw"
    else:
        _gate(case_id, current_request_bytes=len(_json_bytes(messages)),
              manifest_sha256=manifest_sha256)
        state = "ready"
    return {"status": state, "case_id": case_id, "provider": "deepseek",
            "requested_model": config.model, "reasoning_effort": "high",
            "max_tokens": PARAMS["max_tokens"], "deadline_seconds": DEADLINE_SECONDS,
            "request_bytes": len(_json_bytes(messages)),
            "manifest_sha256": manifest_sha256,
            "frozen_status": manifest["status"], "budget": _budget(),
            "api_calls_this_check": 0}


def run_one(root: Path = ROOT, frozen: Path = FROZEN, case_id: str = IDS[0], *,
            authorized: bool = False, price_confirmed_date: str | None = None) -> dict[str, Any]:
    if not authorized or price_confirmed_date != _today():
        raise ValueError("真实调用需明确授权并核对当天官方价格")
    if Path(frozen).is_symlink():
        raise ValueError("冻结包目录不能是符号链接")
    root, frozen = Path(root).resolve(), Path(frozen).resolve()
    manifest = _verified(root, frozen)
    manifest_sha256 = _sha((frozen / "MANIFEST.json").read_bytes())
    prompt, report, record = _case(frozen, case_id)
    config, config_identity = _config()
    ledger, raw_path, lock = _paths(case_id, create=True)
    started = {"schema_version": SCHEMA, "status": "provider_call_started",
               "case_id": case_id, "started_at": _now(), "api_calls_reserved": 1,
               "provider": "deepseek", "requested_model": MODEL,
               "config_sha256": config_identity,
               "manifest_sha256": manifest_sha256,
               "request_sha256": _sha(_json_bytes(prompt)),
               "report_sha256": record["report_sha256"],
               "relation_snapshot_sha256": record["relation_snapshot_sha256"],
               "runner_sha256": _sha(Path(__file__).read_bytes()),
               "adapter_sha256": _sha((root / "src/tradeintel_ai/model_adapter.py").read_bytes()),
               "request_params": PARAMS, "temperature_sent": config.temperature,
               "deadline_seconds": DEADLINE_SECONDS, "price_confirmed_date": price_confirmed_date,
               "budget": _budget(), "frozen_status": manifest["status"]}
    with _locked(lock):
        _gate(case_id, current_request_bytes=len(_json_bytes(prompt)),
              manifest_sha256=manifest_sha256)
        _atomic(ledger, started)
    began = time.monotonic()
    try:
        with _deadline(DEADLINE_SECONDS):
            response = OpenAICompatibleModel(config, system_prompt="",
                                             request_params=PARAMS).complete(messages=prompt, tools=[])
        metadata = _safe_metadata(getattr(response, "metadata", None))
        text = getattr(response, "text", None)
        tool_calls = getattr(response, "tool_calls", ())
        common = {"ended_at": _now(), "elapsed_seconds": round(time.monotonic() - began, 3),
                  "tool_calls_count": len(tool_calls), **metadata}
        if not isinstance(text, str) or not text.strip():
            category = ("unexpected_tool_call" if tool_calls else
                        "finish_reason_length_empty_content" if metadata["finish_reason"] == "length"
                        else "empty_response")
            return _update(case_id, {**common, "status": "failed", "error_category": category,
                                     "raw_utf8_bytes": 0})
        raw_hash = _save_raw(raw_path, text)
        usage = metadata["usage"] or {}
        prompt_tokens, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
        if tool_calls:
            error = "unexpected_tool_call"
        elif metadata["finish_reason"] != "stop":
            error = "finish_reason_not_stop"
        elif not isinstance(metadata["response_model"], str) or (
                metadata["response_model"].casefold() not in ACCEPTED_RESPONSE_MODELS):
            error = "response_model_mismatch"
        elif type(prompt_tokens) is not int or type(completion) is not int:
            error = "usage_missing"
        elif len(text.encode("utf-8")) > MAX_RAW_BYTES or (
                completion > PARAMS["max_tokens"]):
            error = "output_over_budget"
        else:
            try:
                parsed = parse(text, report, record["relation_snapshot"],
                               record["relation_snapshot_sha256"])
            except ValueError:
                error = "contract_rejected"
            else:
                error = None
        return _update(case_id, {**common,
                                 "status": "needs_review" if error is None else "invalid_answer",
                                 "raw_sha256": raw_hash, "raw_file": raw_path.name,
                                 "raw_utf8_bytes": len(text.encode("utf-8")),
                                 "contract_pass": error is None,
                                 "interpretation_count": len(parsed["interpretations"]) if error is None else None,
                                 "error_category": error})
    except ModelAdapterError as exc:
        code = exc.details.get("http_status")
        rejected = type(code) is int and 400 <= code < 500
        safe = {key: value for key, value in exc.details.items()
                if key in {"http_status", "code", "param", "category"} and
                (type(value) is int or isinstance(value, str) and len(value) <= 120)}
        return _update(case_id, {"status": "failed" if rejected else "unknown_outcome",
                                 "ended_at": _now(),
                                 "elapsed_seconds": round(time.monotonic() - began, 3),
                                 "error_category": "provider_rejected" if rejected else "provider_outcome_unknown",
                                 "error_details": safe})
    except Exception as exc:
        return _update(case_id, {"status": "unknown_outcome", "ended_at": _now(),
                                 "elapsed_seconds": round(time.monotonic() - began, 3),
                                 "error_category": "total_deadline" if isinstance(exc, DeadlineExceeded)
                                 else "local_outcome_unknown"})


def review(case_id: str, *, reviewer: str, note: str, severe_error: bool,
           factual_fidelity: bool, answers_question: bool, reading_gain: bool,
           baseline_quote: str = "", model_quote: str = "") -> dict[str, Any]:
    if (case_id not in IDS or not reviewer.strip() or not note.strip() or
            type(severe_error) is not bool or type(factual_fidelity) is not bool or
            type(answers_question) is not bool or type(reading_gain) is not bool):
        raise ValueError("人工审阅字段不完整")
    if reading_gain and (severe_error or not factual_fidelity or not answers_question or
                         not baseline_quote.strip() or not model_quote.strip()):
        raise ValueError("阅读增益须给出页面与原答的具体对照")
    ledger, raw_path, lock = _paths(case_id, create=False)
    with _locked(lock):
        state = _read(ledger)
        if (not state or state.get("status") != "needs_review" or
                raw_path.is_symlink() or not raw_path.is_file() or
                _sha(raw_path.read_bytes()) != state.get("raw_sha256")):
            raise ValueError("原答未就绪、已审阅或摘要不符")
        if reading_gain:
            _verified(ROOT, FROZEN)
            baseline = (FROZEN / "cases" / case_id / "baseline.zh-CN.txt").read_text(encoding="utf-8")
            raw_text = raw_path.read_text(encoding="utf-8")
            if baseline_quote.strip() not in baseline or model_quote.strip() not in raw_text:
                raise ValueError("阅读增益引文未出现在冻结页面基线或模型原答中")
        if state.get("manifest_sha256") != _sha((FROZEN / "MANIFEST.json").read_bytes()):
            raise ValueError("审阅账本与当前冻结材料不一致")
        outcome = ("reviewed_severe" if severe_error or not factual_fidelity else
                   "reviewed_inadequate" if not answers_question else "reviewed_clear")
        state["status"] = outcome
        state["review"] = {"reviewer": reviewer.strip(), "note": note.strip(),
                           "reviewed_at": _now(), "severe_error": severe_error,
                           "factual_fidelity": factual_fidelity,
                           "answers_question": answers_question,
                           "reading_gain": reading_gain,
                           "baseline_quote": baseline_quote.strip(),
                           "model_quote": model_quote.strip()}
        _atomic(ledger, state)
        next_case_allowed = False
        next_case_block_reason = None
        next_index = IDS.index(case_id) + 1
        if outcome == "reviewed_clear" and next_index < len(IDS):
            next_case = IDS[next_index]
            next_messages, _, _ = _case(FROZEN, next_case)
            try:
                _gate(next_case, current_request_bytes=len(_json_bytes(next_messages)),
                      manifest_sha256=state["manifest_sha256"])
            except ValueError as exc:
                next_case_block_reason = str(exc)
            else:
                next_case_allowed = True
        return {"case_id": case_id, "status": outcome, "reading_gain": reading_gain,
                "next_case_allowed": next_case_allowed,
                "next_case_block_reason": next_case_block_reason}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=IDS, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--authorize-one-call", action="store_true")
    parser.add_argument("--price-confirmed-date", default=None)
    parser.add_argument("--review", choices=("clear", "severe"))
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--note", default="")
    parser.add_argument("--factual-fidelity", choices=("yes", "no"))
    parser.add_argument("--answers-question", choices=("yes", "no"))
    parser.add_argument("--reading-gain", choices=("yes", "no"))
    parser.add_argument("--baseline-quote", default="")
    parser.add_argument("--model-quote", default="")
    args = parser.parse_args()
    if args.review:
        if args.live or args.authorize_one_call or args.price_confirmed_date:
            parser.error("人工审阅与真实调用不能同时执行")
        if None in (args.factual_fidelity, args.answers_question, args.reading_gain):
            parser.error("人工审阅须填写事实、回答和阅读增益")
        result = review(args.case, reviewer=args.reviewer, note=args.note,
                        severe_error=args.review == "severe",
                        factual_fidelity=args.factual_fidelity == "yes",
                        answers_question=args.answers_question == "yes",
                        reading_gain=args.reading_gain == "yes",
                        baseline_quote=args.baseline_quote, model_quote=args.model_quote)
    elif args.live and args.authorize_one_call:
        result = run_one(case_id=args.case, authorized=True,
                         price_confirmed_date=args.price_confirmed_date)
    elif args.live or args.authorize_one_call or args.price_confirmed_date:
        parser.error("真实调用须同时使用 --live、--authorize-one-call 和当天价格确认日期")
    else:
        result = check(case_id=args.case)
    visible = {key: value for key, value in result.items()
               if key not in {"config_sha256", "request_params", "review"}}
    print(json.dumps(visible, ensure_ascii=False))


if __name__ == "__main__":
    main()
