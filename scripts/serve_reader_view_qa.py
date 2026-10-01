"""Offline reader QA: real trade data, explicitly synthetic policy evidence."""
from pathlib import Path
import tempfile
import sys
import uuid

from tradeintel_ai.trade_agent_tools import TradeAgentTools
from tradeintel_ai.trade_agent_store import begin_turn, finish_turn
from tradeintel_ai.web_app import create_server

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tmp/handoff-runs/trade-demo-data-20260925"


def guard(event, args):
    if event == "socket.connect" and (not isinstance(args[1], tuple) or args[1][0] not in {"127.0.0.1", "::1"}):
        raise RuntimeError("offline QA forbids external connections")


def main():
    sys.addaudithook(guard)
    with tempfile.TemporaryDirectory(prefix="trade-reader-qa-") as folder:
        root = Path(folder)
        server = create_server(root=root, trade_data_root=DATA, host="127.0.0.1", port=0)
        server.RequestHandlerClass.static_root = ROOT / "web"
        port = server.server_address[1]
        for policy in (False, True):
            question = "最近美国大豆进口有什么变化？" + ("政策是否奏效？（离线页面测试）" if policy else "")
            request = uuid.uuid4().hex
            session, _ = begin_turn(root, None, request, question)
            tools = TradeAgentTools(DATA, root, question=question)
            tools.search_products("大豆", "import")
            rid = tools.query_trade("import:1201", "import", "all", {"type": "latest_contiguous", "count": 6})["report_id"]
            evidence = {"schema": "trade-policy-evidence-v1", "status": "partial", "searches": [],
                        "evidence_bundles": [{"hit": {"citation_id": "fixture:v1:hit",
                            "text": "OFFLINE FIXTURE — 仅供排版测试，不是官方政策材料。"},
                            "required_context": [{"dependency": "exceptions", "status": "known",
                                "citation_id": "fixture:v1:exception", "text": "OFFLINE FIXTURE — 仅限指定用途，其他情形不得据此判断适用。"}]}]} if policy else {
                                "schema": "trade-policy-evidence-v1", "status": "not_searched", "searches": [], "evidence_bundles": []}
            finish_turn(root, session["session_id"], request, {"status": "completed", "message": "",
                "message_kind": "program_summary_v1", "report_ids": [rid], "primary_report_id": rid,
                "policy_evidence": evidence}, tools.reports[rid]["scope"])
            print(("POLICY_FIXTURE" if policy else "DATA") + f" http://127.0.0.1:{port}/preview/?agent_session_id={session['session_id']}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
