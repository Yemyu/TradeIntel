"""First trade-agent development question. Default: offline preflight only.

The live path is deliberately single-use. It must not be used until the
operator has checked same-day provider pricing and approved one paid attempt.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tradeintel_ai.local_provider_config import (
    PRODUCT_CONFIG_PATH, load_product_config, product_config_identity,
    product_request_params, product_status,
)
from tradeintel_ai.model_adapter import OpenAICompatibleModel
from tradeintel_ai.trade_agent import TOOL_SCHEMAS, TradeResearchAgent, initial_messages
from tradeintel_ai.trade_agent_deepseek import DeepSeekThinkingToolModel
from tradeintel_ai.trade_agent_tools import TradeAgentTools, _months


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "tmp/handoff-runs/trade-demo-data-20260925"
LEDGER_DIR = ROOT / ".local/trade-agent-live-pilot/20260929-v1"
QUESTION = "最近美国大豆进口有什么变化？"
AS_OF = date(2026, 9, 29)
MAX_ROUNDS = 4
MAX_TOOLS = 8
MAX_TOKENS = 4096
# Keep a separate release switch even after the offline contract tests pass.
# Only this product-specific adapter may pass the pilot's thinking-mode gate.
THINKING_TOOL_REPLAY_VERIFIED = True
EXPECTED_VERSIONS = {
    "import": "dd9801492e80268e51480b08c2edcbf495aba3ce01b7ee64739566f67a151ef8",
    "export": "4308e4a820cd86bb6a19e223b4ae887fe0a030eef4a8af0c1ce96cb8c30a4b9f",
    "classification": "a758a0236d12bea52cae670b99b05997a1b1c14d8442bcda7ea05bb3b436a632",
}
SOURCE_FILES = (
    "src/tradeintel_ai/agent.py",
    "src/tradeintel_ai/trade_agent.py",
    "src/tradeintel_ai/trade_agent_deepseek.py",
    "src/tradeintel_ai/trade_agent_tools.py",
    "src/tradeintel_ai/trade_agent_store.py",
    "src/tradeintel_ai/trade_classification_catalog.py",
    "src/tradeintel_ai/trade_data_repository.py",
    "src/tradeintel_ai/trade_export_repository.py",
    "src/tradeintel_ai/trade_query_flow.py",
    "src/tradeintel_ai/trade_report_store.py",
    "src/tradeintel_ai/trade_explanation_v4.py",
    "src/tradeintel_ai/model_adapter.py",
    "src/tradeintel_ai/local_provider_config.py",
    "scripts/run_trade_agent_pilot.py",
)


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()


def _ledger_folder() -> Path:
    for path in (ROOT / ".local", LEDGER_DIR.parent, LEDGER_DIR):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError("试跑账本目录不安全")
        path.mkdir(mode=0o700, exist_ok=True)
    return LEDGER_DIR


def _ledger_path() -> Path:
    return _ledger_folder() / "first-question.json"


def _write_existing(path: Path, value: dict) -> None:
    encoded = _json_bytes(value)
    if len(encoded) > 1_000_000:
        raise ValueError("试跑记录超过上限")
    fd, temporary = tempfile.mkstemp(prefix=".trade-agent-pilot-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _append_event(event: dict) -> None:
    path = _ledger_path()
    if path.is_symlink() or not path.is_file():
        raise ValueError("试跑账本缺失或不安全")
    lock = path.with_suffix(".lock")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if path.stat().st_size > 1_000_000:
            raise ValueError("试跑账本超过上限")
        value = json.loads(path.read_text(encoding="utf-8"))
        value["events"].append(event)
        if event.get("type") == "agent_finished":
            value["status"] = event["status"]
        _write_existing(path, value)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _safe_metadata(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    result = {}
    for key in ("response_id", "model", "requested_model", "finish_reason"):
        item = value.get(key)
        if isinstance(item, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", item):
            result[key] = item
    usage = value.get("usage")
    if isinstance(usage, dict):
        result["usage"] = {key: item for key in
                           ("prompt_tokens", "completion_tokens", "total_tokens")
                           if type(item := usage.get(key)) is int and 0 <= item <= 1_000_000}
    return result


class RecordingModel:
    """Keep private original tool decisions and usage after every model round."""

    def __init__(self, inner: OpenAICompatibleModel, *, append_event=None):
        self.inner = inner
        self.append_event = append_event or _append_event

    def complete(self, *, messages, tools):
        payload = self.inner._payload(messages=messages, tools=tools)
        self.append_event({"at": _now(), "type": "request_started",
                       "payload_sha256": _sha(_json_bytes(payload)),
                       "payload_bytes": len(_json_bytes(payload))})
        response = self.inner.complete(messages=messages, tools=tools)
        calls = [{"call_id": item.call_id, "name": item.name,
                  "arguments": item.arguments} for item in response.tool_calls]
        self.append_event({"at": _now(), "type": "response_saved", "text": response.text,
                       "tool_calls": calls, "metadata": _safe_metadata(dict(response.metadata))})
        return response


def preflight() -> tuple[dict, OpenAICompatibleModel]:
    if not DATA_ROOT.is_dir() or not PRODUCT_CONFIG_PATH.is_file() or PRODUCT_CONFIG_PATH.is_symlink():
        raise ValueError("数据包或本机产品模型配置不存在")
    status = product_status()
    config = load_product_config()
    configured_params = product_request_params()
    if (status["provider"] != "deepseek" or status["model"] != "deepseek-flash" or
            status["reasoning"] != "high" or not config.api_key or
            config.temperature != 0 or config.base_url.rstrip("/") != "https://api.deepseek.com" or
            configured_params.get("thinking") != {"type": "enabled"} or
            configured_params.get("reasoning_effort") != "high"):
        raise ValueError("当前产品配置不是预定的 DeepSeek Flash/high，不能沿用本试跑方案")
    if not THINKING_TOOL_REPLAY_VERIFIED:
        raise ValueError("DeepSeek 高推理工具回合缺少 reasoning_content 回传；暂停真实调用")
    config = replace(config, timeout_seconds=min(config.timeout_seconds, 90))
    params = {**configured_params, "max_tokens": MAX_TOKENS}
    model = DeepSeekThinkingToolModel(config, system_prompt="", request_params=params)
    coverage = {flow: _months(DATA_ROOT, flow)[1][flow] for flow in ("import", "export")}
    tools = TradeAgentTools(DATA_ROOT, ROOT, today=AS_OF, question=QUESTION)
    versions = {**coverage, "classification": tools.catalog.version}
    if versions != EXPECTED_VERSIONS:
        raise ValueError("数据或分类目录版本已变化，必须先重新锁定参考")
    soy = tools.search_products("大豆", "import")["candidates"]
    corn = tools.search_products("玉米", "import")["candidates"]
    if (not soy or (soy[0]["id"], soy[0]["match_type"]) != ("import:1201", "exact_product") or
            not corn or (corn[0]["id"], corn[0]["match_type"]) != ("import:1005", "exact_product") or
            any(item["id"] == "import:1904" and item["match_type"] != "related_candidate"
                for item in corn)):
        raise ValueError("商品候选安全门未通过")
    dummy_state = {"scope": None, "turns": [{"question": QUESTION, "status": "in_progress"}]}
    payload = model._payload(messages=initial_messages(QUESTION, dummy_state, AS_OF), tools=TOOL_SCHEMAS)
    if (len(payload.get("tools", [])) != 6 or "tool_choice" in payload or
            payload.get("max_tokens") != MAX_TOKENS or len(_json_bytes(payload)) > 16_000):
        raise ValueError("首轮实际模型请求没有通过工具或输入预算门")
    source_hashes = {name: _sha((ROOT / name).read_bytes()) for name in SOURCE_FILES}
    snapshot = {"schema": "trade-agent-pilot-preflight-v1", "question": QUESTION,
                "today": AS_OF.isoformat(), "model": config.model, "reasoning": "high",
                "params": params, "max_rounds": MAX_ROUNDS, "max_tools": MAX_TOOLS,
                "request_payload_sha256": _sha(_json_bytes(payload)),
                "request_payload_bytes": len(_json_bytes(payload)),
                "data_versions": versions, "source_sha256": source_hashes,
                "product_config_identity": product_config_identity()}
    snapshot["snapshot_sha256"] = _sha(_json_bytes(snapshot))
    return snapshot, model


def run_live(snapshot: dict, model: OpenAICompatibleModel) -> dict:
    path = _ledger_path()
    if path.is_symlink() or path.exists():
        raise ValueError("首题已有账本，不允许自动重试；先只读诊断")
    request_id = uuid.uuid4().hex
    ledger = {"schema": "trade-agent-pilot-once-v1", "status": "reserved",
              "request_id": request_id, "reserved_at": _now(), "snapshot": snapshot,
              "events": []}
    encoded = _json_bytes(ledger)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    recorder = RecordingModel(model)
    agent = TradeResearchAgent(DATA_ROOT, ROOT, recorder, today=AS_OF,
                               max_rounds=MAX_ROUNDS, max_tools=MAX_TOOLS)
    try:
        result = agent.turn(QUESTION, request_id)
        last = result["turns"][-1]
        _append_event({"at": _now(), "type": "agent_finished", "status": last["status"],
                       "session_id": result["session_id"], "report_ids": last.get("report_ids", []),
                       "tool_trace": last.get("tool_calls", [])})
        return {"status": last["status"], "session_id": result["session_id"],
                "report_ids": last.get("report_ids", []), "ledger": str(path)}
    except BaseException:
        # The reserved ledger intentionally remains. A timeout, interruption
        # or uncertain provider response must never initiate a second request.
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="send the one paid development question")
    parser.add_argument("--authorize-one-attempt", action="store_true")
    parser.add_argument("--price-checked-date", help="Asia/Shanghai date YYYY-MM-DD")
    parser.add_argument("--account-checked-date", help="Asia/Shanghai date YYYY-MM-DD")
    parser.add_argument("--expected-snapshot-sha256", help="value printed by offline preflight")
    args = parser.parse_args()
    try:
        snapshot, model = preflight()
    except ValueError as exc:
        parser.error(str(exc))
    if not args.live:
        if (args.authorize_one_attempt or args.price_checked_date or args.account_checked_date or
                args.expected_snapshot_sha256):
            parser.error("预检模式不接受真实调用许可参数")
        print(json.dumps({"status": "offline_ready", "snapshot": snapshot,
                          "ledger_exists": (LEDGER_DIR / "first-question.json").exists()},
                         ensure_ascii=False, indent=2))
        return
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    if (not args.authorize_one_attempt or args.price_checked_date != today or
            args.account_checked_date != today or
            args.expected_snapshot_sha256 != snapshot["snapshot_sha256"]):
        parser.error("真实调用需单次许可、当日价格与账户核对，以及完全一致的预检摘要")
    print(json.dumps(run_live(snapshot, model), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
