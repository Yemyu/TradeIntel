"""Third trade-agent development question; offline preflight unless explicitly released.

This question starts a new session. A reserved ledger is never reused or removed,
even when the provider outcome is unknown.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts import run_trade_agent_pilot as first
from tradeintel_ai.trade_agent import TOOL_SCHEMAS, TradeResearchAgent, initial_messages
from tradeintel_ai.trade_agent_tools import TradeAgentTools
from tradeintel_ai.trade_data_repository import TradeDataRepository, TradeQuery
from tradeintel_ai.trade_export_repository import ExportDataRepository, ExportTradeQuery


ROOT = first.ROOT
DATA_ROOT = first.DATA_ROOT
LEDGER_DIR = first.LEDGER_DIR
QUESTION = "最近美国大豆的进口和出口分别怎么样？能说明政策奏效吗？"
EXPECTED_IMPORT = {"2026-06": 32_877_827, "2026-07": 46_041_287}
EXPECTED_EXPORT = {"2026-06": 892_879_462, "2026-07": 889_379_312}


def _ledger_path() -> Path:
    for folder in (ROOT / ".local", LEDGER_DIR.parent, LEDGER_DIR):
        if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
            raise ValueError("试跑账本目录不安全")
        folder.mkdir(mode=0o700, exist_ok=True)
    return LEDGER_DIR / "third-question.json"


def _policy_hashes() -> dict[str, str]:
    """Lock the exact local policy files the bounded search can examine."""
    directory = ROOT / ".local" / "announcement-docs"
    if not directory.exists():
        return {}
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("政策目录不安全")
    result = {}
    for path in sorted(directory.glob("*.json"))[:40]:
        if path.is_symlink() or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", path.stem):
            continue
        if not path.is_file() or path.stat().st_size > 20_000_000:
            raise ValueError("政策文件无效或超过上限")
        result[path.name] = first._sha(path.read_bytes())
    return result


def preflight() -> tuple[dict, object]:
    base, model = first.preflight()
    tools = TradeAgentTools(DATA_ROOT, ROOT, today=first.AS_OF, question=QUESTION)
    matches = tools.search_products("大豆", "both")["candidates"]
    if not matches or (matches[0]["id"], matches[0]["match_type"]) != ("both:1201", "exact_product"):
        raise ValueError("进出口商品候选不准确")
    imported = TradeDataRepository(DATA_ROOT).query(TradeQuery(
        "US", "import", "1201", "2026-06", "2026-07", "ALL_ORIGINS",
        first.EXPECTED_VERSIONS["import"]))
    exported = ExportDataRepository(DATA_ROOT).query(ExportTradeQuery(
        "US", "export", "1201", "2026-06", "2026-07", "ALL_DESTINATIONS",
        first.EXPECTED_VERSIONS["export"]))
    if ({row["month"]: row["value_usd"] for row in imported["months"]} != EXPECTED_IMPORT or
            {row["month"]: row["value_usd"] for row in exported["months"]} != EXPECTED_EXPORT):
        raise ValueError("第三题答前参考与已发布数据不符")
    pending = {"scope": None, "turns": [{"question": QUESTION, "status": "in_progress"}]}
    payload = model._payload(messages=initial_messages(QUESTION, pending, first.AS_OF),
                             tools=TOOL_SCHEMAS)
    encoded = first._json_bytes(payload)
    if (len(payload.get("tools", [])) != 6 or "tool_choice" in payload or
            payload.get("max_tokens") != first.MAX_TOKENS or len(encoded) > 16_000):
        raise ValueError("第三题请求超过已锁预算或协议不符")
    source_hashes = dict(base["source_sha256"])
    source_hashes["scripts/run_trade_agent_third_pilot.py"] = first._sha(Path(__file__).read_bytes())
    for name in ("src/tradeintel_ai/announcement_store.py",
                 "src/tradeintel_ai/policy_search.py"):
        source_hashes[name] = first._sha((first.ROOT / name).read_bytes())
    snapshot = {"schema": "trade-agent-third-preflight-v1", "question": QUESTION,
                "today": first.AS_OF.isoformat(), "model": base["model"],
                "reasoning": base["reasoning"], "params": base["params"],
                "max_rounds": first.MAX_ROUNDS, "max_tools": first.MAX_TOOLS,
                "request_payload_sha256": first._sha(encoded),
                "request_payload_bytes": len(encoded),
                "data_versions": base["data_versions"], "source_sha256": source_hashes,
                "policy_store_sha256": _policy_hashes(),
                "product_config_identity": base["product_config_identity"]}
    snapshot["snapshot_sha256"] = first._sha(first._json_bytes(snapshot))
    return snapshot, model


def _append_event(event: dict) -> None:
    path = _ledger_path()
    if path.is_symlink() or not path.is_file():
        raise ValueError("第三题账本缺失或不安全")
    lock = path.with_suffix(".lock")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if path.stat().st_size > 1_000_000:
            raise ValueError("第三题账本超过上限")
        ledger = json.loads(path.read_text(encoding="utf-8"))
        ledger["events"].append(event)
        if event.get("type") == "agent_finished":
            ledger["status"] = event["status"]
        first._write_existing(path, ledger)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def run_live(snapshot: dict, model: object) -> dict:
    current, _ = preflight()
    if snapshot != current:
        raise ValueError("第三题预检快照已变化，不得发送请求")
    path = _ledger_path()
    if path.is_symlink() or path.exists():
        raise ValueError("第三题已有账本，不允许自动重试")
    request_id = uuid.uuid4().hex
    ledger = {"schema": "trade-agent-third-once-v1", "status": "reserved",
              "request_id": request_id, "reserved_at": first._now(),
              "snapshot": snapshot, "events": []}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(first._json_bytes(ledger))
        stream.flush()
        os.fsync(stream.fileno())
    recorder = first.RecordingModel(model, append_event=_append_event)
    agent = TradeResearchAgent(DATA_ROOT, ROOT, recorder, today=first.AS_OF,
                               max_rounds=first.MAX_ROUNDS, max_tools=first.MAX_TOOLS)
    result = agent.turn(QUESTION, request_id)
    last = result["turns"][-1]
    _append_event({"at": first._now(), "type": "agent_finished", "status": last["status"],
                   "session_id": result["session_id"], "report_ids": last.get("report_ids", []),
                   "tool_trace": last.get("tool_calls", [])})
    return {"status": last["status"], "session_id": result["session_id"],
            "report_ids": last.get("report_ids", []), "ledger": str(path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--authorize-one-attempt", action="store_true")
    parser.add_argument("--price-checked-date", help="Asia/Shanghai date YYYY-MM-DD")
    parser.add_argument("--account-checked-date", help="Asia/Shanghai date YYYY-MM-DD")
    parser.add_argument("--expected-snapshot-sha256")
    args = parser.parse_args()
    try:
        snapshot, model = preflight()
    except ValueError as exc:
        parser.error(str(exc))
    if not args.live:
        if (args.authorize_one_attempt or args.price_checked_date or args.account_checked_date or
                args.expected_snapshot_sha256):
            parser.error("离线预检不接受真实调用许可参数")
        print(json.dumps({"status": "offline_ready", "snapshot": snapshot,
                          "ledger_exists": (LEDGER_DIR / "third-question.json").exists()},
                         ensure_ascii=False, indent=2))
        return
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    if (not args.authorize_one_attempt or args.price_checked_date != today or
            args.account_checked_date != today or
            args.expected_snapshot_sha256 != snapshot["snapshot_sha256"]):
        parser.error("真实调用需本题单次许可、当日价格和账户核对、完全一致的预检摘要")
    print(json.dumps(run_live(snapshot, model), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
