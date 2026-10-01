"""Second trade-agent development question. Offline by default; live is one-use.

This follows the completed first-question session. It does not authorize a
provider request: the operator must separately approve this paid attempt.
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts import run_trade_agent_pilot as first
from tradeintel_ai.trade_agent import TOOL_SCHEMAS, TradeResearchAgent, initial_messages
from tradeintel_ai.trade_agent_store import read_session
from tradeintel_ai.trade_agent_tools import TradeAgentTools
from tradeintel_ai.trade_export_repository import ExportDataRepository, ExportTradeQuery
from tradeintel_ai.trade_report_store import get_state


ROOT = first.ROOT
DATA_ROOT = first.DATA_ROOT
LEDGER_DIR = first.LEDGER_DIR
QUESTION = "出口呢？"
FIRST_QUESTION = first.QUESTION
EXPECTED_EXPORT = {"2026-06": 892_879_462, "2026-07": 889_379_312}


def _ledger_path() -> Path:
    for folder in (ROOT / ".local", LEDGER_DIR.parent, LEDGER_DIR):
        if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
            raise ValueError("试跑账本目录不安全")
        folder.mkdir(mode=0o700, exist_ok=True)
    return LEDGER_DIR / "second-question.json"


def _read_first() -> tuple[dict, bytes, dict, dict]:
    path = LEDGER_DIR / "first-question.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
        raise ValueError("首题正式账本缺失或不安全")
    raw = path.read_bytes()
    try:
        ledger = json.loads(raw)
        finished = [item for item in ledger["events"] if item.get("type") == "agent_finished"]
        if ledger["status"] != "completed" or len(finished) != 1 or finished[0]["status"] != "completed":
            raise ValueError("首题尚未正式完成")
        session_id = finished[0]["session_id"]
        state = read_session(ROOT, session_id)
        if (len(state["turns"]) != 1 or state["turns"][0]["question"] != FIRST_QUESTION or
                state["turns"][0]["status"] != "completed" or
                state["turns"][0]["report_ids"] != finished[0]["report_ids"] or
                len(finished[0]["report_ids"]) != 1):
            raise ValueError("首题会话与正式账本不一致")
        scope = state["scope"]
        if (scope["selected_product_id"] != "import:1201" or scope["flow"] != "import" or
                scope["partner"] != "ALL_ORIGINS" or scope["end_month"] != "2026-07" or
                scope["dataset_version"] != first.EXPECTED_VERSIONS["import"]):
            raise ValueError("首题范围变化，不能沿用追问")
        report = get_state(ROOT, finished[0]["report_ids"][0])
        if (report["scope"] != scope or report["summary"]["latest_value_usd"] != 46_041_287):
            raise ValueError("首题报告与已确认范围不一致")
        return ledger, raw, state, report
    except (KeyError, TypeError, IndexError, json.JSONDecodeError) as exc:
        raise ValueError("首题账本或会话无效") from exc


def preflight() -> tuple[dict, object]:
    base, model = first.preflight()
    _, first_bytes, state, report = _read_first()
    candidate = TradeAgentTools(DATA_ROOT, ROOT, today=first.AS_OF, question=QUESTION)
    matches = candidate.search_products(state["scope"]["product_label"], "export")["candidates"]
    if not matches or (matches[0]["id"], matches[0]["match_type"]) != ("export:1201", "exact_product"):
        raise ValueError("追问的出口商品候选不准确")
    result = ExportDataRepository(DATA_ROOT).query(ExportTradeQuery(
        "US", "export", "1201", "2026-06", "2026-07", "ALL_DESTINATIONS",
        first.EXPECTED_VERSIONS["export"]))
    if {item["month"]: item["value_usd"] for item in result["months"]} != EXPECTED_EXPORT:
        raise ValueError("出口答前参考与已发布数据不符")
    # begin_turn appends this entry before the real first model request.
    pending = copy.deepcopy(state)
    pending["turns"].append({"question": QUESTION, "status": "in_progress"})
    payload = model._payload(messages=initial_messages(QUESTION, pending, first.AS_OF),
                             tools=TOOL_SCHEMAS)
    encoded = first._json_bytes(payload)
    if (len(payload.get("tools", [])) != 6 or "tool_choice" in payload or
            payload.get("max_tokens") != first.MAX_TOKENS or len(encoded) > 16_000):
        raise ValueError("第二题请求超过已锁预算或协议不符")
    source_hashes = dict(base["source_sha256"])
    source_hashes["scripts/run_trade_agent_followup_pilot.py"] = first._sha(Path(__file__).read_bytes())
    snapshot = {"schema": "trade-agent-followup-preflight-v1", "question": QUESTION,
                "today": first.AS_OF.isoformat(), "model": base["model"],
                "reasoning": base["reasoning"], "params": base["params"],
                "max_rounds": first.MAX_ROUNDS, "max_tools": first.MAX_TOOLS,
                "first_session_id": state["session_id"],
                "first_ledger_sha256": first._sha(first_bytes),
                "first_state_sha256": first._sha(first._json_bytes(state)),
                "first_report_sha256": report["report_sha256"],
                "request_payload_sha256": first._sha(encoded), "request_payload_bytes": len(encoded),
                "data_versions": base["data_versions"], "source_sha256": source_hashes,
                "product_config_identity": base["product_config_identity"]}
    snapshot["snapshot_sha256"] = first._sha(first._json_bytes(snapshot))
    return snapshot, model


def _append_event(event: dict) -> None:
    path = _ledger_path()
    if path.is_symlink() or not path.is_file():
        raise ValueError("第二题账本缺失或不安全")
    lock = path.with_suffix(".lock")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if path.stat().st_size > 1_000_000:
            raise ValueError("第二题账本超过上限")
        value = json.loads(path.read_text(encoding="utf-8"))
        value["events"].append(event)
        if event.get("type") == "agent_finished":
            value["status"] = event["status"]
        first._write_existing(path, value)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def run_live(snapshot: dict, model: object) -> dict:
    current, _ = preflight()
    if snapshot != current:
        raise ValueError("第二题预检快照已变化，不得发送请求")
    path = _ledger_path()
    if path.is_symlink() or path.exists():
        raise ValueError("第二题已有账本，不允许自动重试")
    request_id = uuid.uuid4().hex
    ledger = {"schema": "trade-agent-followup-once-v1", "status": "reserved",
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
    # A reserved ledger is never removed, even when the provider outcome is unknown.
    result = agent.turn(QUESTION, request_id, session_id=snapshot["first_session_id"])
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
                          "ledger_exists": (LEDGER_DIR / "second-question.json").exists()},
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
