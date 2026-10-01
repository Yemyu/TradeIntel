"""Independent supplementary boundary checks; default is offline preflight."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts import run_trade_agent_pilot as first
from scripts import run_trade_agent_third_pilot as third
from tradeintel_ai.trade_agent import TOOL_PROTOCOL, TOOL_SCHEMAS, TradeResearchAgent, initial_messages
from tradeintel_ai.trade_agent_tools import TradeAgentTools
from tradeintel_ai.trade_data_repository import TradeDataRepository, TradeQuery

ROOT = first.ROOT
DATA_ROOT = first.DATA_ROOT
LEDGER_DIR = ROOT / ".local/trade-agent-live-pilot/supplemental-boundaries-20260930-v1"
QUESTIONS = {"soybean-oil": "美国豆油进口最近怎样？",
             "missing-last-month": "上个月美国大豆进口额是多少？"}


def _path(case_id: str, *, create=False) -> Path:
    if case_id not in QUESTIONS:
        raise ValueError("未知补充题")
    for folder in (ROOT / ".local", LEDGER_DIR.parent, LEDGER_DIR):
        if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
            raise ValueError("试跑账本目录不安全")
        if create:
            folder.mkdir(mode=0o700, exist_ok=True)
    return LEDGER_DIR / f"{case_id}.json"


def preflight(case_id: str) -> tuple[dict, object]:
    _path(case_id)
    base, model = first.preflight()
    question = QUESTIONS[case_id]
    tools = TradeAgentTools(DATA_ROOT, ROOT, today=first.AS_OF, question=question)
    finish = next(item for item in TOOL_SCHEMAS if item["name"] == "finish")
    if (TOOL_PROTOCOL != "trade-agent-tools-v2" or
            set(finish["parameters"]["properties"]) != {"report_ids", "source_ids"} or
            set(finish["parameters"]["required"]) != {"report_ids", "source_ids"}):
        raise ValueError("完成工具合同不是已定版本")
    if case_id == "soybean-oil":
        candidates = tools.search_products("豆油", "import")["candidates"]
        if not candidates or (candidates[0]["id"], candidates[0]["match_type"]) != ("import:1507", "exact_product"):
            raise ValueError("豆油候选不准确")
        facts = TradeDataRepository(DATA_ROOT).query(TradeQuery(
            "US", "import", "1507", "2026-06", "2026-07", "ALL_ORIGINS",
            first.EXPECTED_VERSIONS["import"]))
        if {row["month"]: row["value_usd"] for row in facts["months"]} != {
                "2026-06": 30_844_293, "2026-07": 27_503_913}:
            raise ValueError("豆油答前参考变化")
    else:
        coverage = tools.coverage()["coverage"]["import"]
        anchor = tools.calendar_month_anchor
        if not anchor or anchor.month != "2026-08" or coverage["latest"] != "2026-07":
            raise ValueError("日历或发布覆盖与缺月参考不符")
    payload = model._payload(messages=initial_messages(question,
        {"scope": None, "turns": [{"question": question, "status": "in_progress"}]}, first.AS_OF),
        tools=TOOL_SCHEMAS)
    encoded = first._json_bytes(payload)
    if len(payload.get("tools", [])) != 6 or payload.get("max_tokens") != 4096 or len(encoded) > 16_000:
        raise ValueError("请求超过已锁预算")
    hashes = dict(base["source_sha256"])
    for name in ("scripts/run_trade_agent_supplemental_pilot.py",
                 "scripts/run_trade_agent_third_pilot.py",
                 "src/tradeintel_ai/policy_search.py", "src/tradeintel_ai/announcement_store.py"):
        hashes[name] = first._sha((first.ROOT / name).read_bytes())
    snapshot = {"schema": "trade-agent-supplemental-preflight-v1", "case_id": case_id,
                "question": question, "tool_protocol": TOOL_PROTOCOL, "today": first.AS_OF.isoformat(),
                "model": base["model"], "reasoning": base["reasoning"], "params": base["params"],
                "max_rounds": first.MAX_ROUNDS, "max_tools": first.MAX_TOOLS,
                "request_payload_sha256": first._sha(encoded), "request_payload_bytes": len(encoded),
                "data_versions": base["data_versions"], "source_sha256": hashes,
                "policy_store_sha256": third._policy_hashes(),
                "product_config_identity": base["product_config_identity"]}
    snapshot["snapshot_sha256"] = first._sha(first._json_bytes(snapshot))
    return snapshot, model


def _append(case_id: str, event: dict) -> None:
    path = _path(case_id)
    if path.is_symlink() or not path.is_file():
        raise ValueError("补充题账本缺失或不安全")
    fd = os.open(path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if path.stat().st_size > 1_000_000:
            raise ValueError("补充题账本超过上限")
        ledger = json.loads(path.read_text())
        ledger["events"].append(event)
        if event.get("type") == "agent_finished":
            ledger["status"] = event["status"]
        first._write_existing(path, ledger)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def run_live(case_id: str, snapshot: dict, model: object) -> dict:
    current, _ = preflight(case_id)
    if current != snapshot:
        raise ValueError("补充题预检快照已变化，不得发送请求")
    path = _path(case_id, create=True)
    if path.is_symlink() or path.exists():
        raise ValueError("补充题已有账本，不允许自动重试")
    request_id = uuid.uuid4().hex
    ledger = {"schema": "trade-agent-supplemental-once-v1", "status": "reserved",
              "case_id": case_id, "request_id": request_id, "reserved_at": first._now(),
              "snapshot": snapshot, "events": []}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(first._json_bytes(ledger)); stream.flush(); os.fsync(stream.fileno())
    recorder = first.RecordingModel(model, append_event=lambda event: _append(case_id, event))
    result = TradeResearchAgent(DATA_ROOT, ROOT, recorder, today=first.AS_OF,
        max_rounds=first.MAX_ROUNDS, max_tools=first.MAX_TOOLS).turn(QUESTIONS[case_id], request_id)
    turn = result["turns"][-1]
    _append(case_id, {"at": first._now(), "type": "agent_finished", "status": turn["status"],
                     "session_id": result["session_id"], "report_ids": turn.get("report_ids", []),
                     "tool_trace": turn.get("tool_calls", [])})
    return {"status": turn["status"], "session_id": result["session_id"],
            "report_ids": turn.get("report_ids", []), "ledger": str(path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=QUESTIONS, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--authorize-one-attempt", action="store_true")
    parser.add_argument("--price-checked-date")
    parser.add_argument("--account-checked-date")
    parser.add_argument("--expected-snapshot-sha256")
    args = parser.parse_args()
    try:
        snapshot, model = preflight(args.case)
    except ValueError as exc:
        parser.error(str(exc))
    if not args.live:
        if args.authorize_one_attempt or args.price_checked_date or args.account_checked_date or args.expected_snapshot_sha256:
            parser.error("离线预检不接受真实调用许可参数")
        print(json.dumps({"status": "offline_ready", "snapshot": snapshot,
                          "ledger_exists": _path(args.case).exists()}, ensure_ascii=False, indent=2))
        return
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    if (not args.authorize_one_attempt or args.price_checked_date != today or
            args.account_checked_date != today or args.expected_snapshot_sha256 != snapshot["snapshot_sha256"]):
        parser.error("真实调用需本题单次许可、当日价格和账户核对、完全一致的预检摘要")
    print(json.dumps(run_live(args.case, snapshot, model), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
