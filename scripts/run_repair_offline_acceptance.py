"""Freeze independent CSV references, then run four offline scripted-agent cases.

This checks wiring and guards, not model accuracy or unseen-model performance.
The only policy notice in this suite is explicitly synthetic.
"""
from pathlib import Path
from datetime import date
import argparse
import csv
import hashlib
import json
import tempfile
import uuid

from tradeintel_ai.agent import ModelResponse, ModelToolCall
from tradeintel_ai.trade_agent import TradeResearchAgent, read_public_session
from tradeintel_ai.trade_report_store import get_state
from tradeintel_ai.policy_documents import build_document, build_document_store
from tradeintel_ai.policy_search import set_required_dependencies
from tradeintel_ai.announcement_store import save_announcement_store

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tmp/handoff-runs/trade-demo-data-20260925"
CASES = [
    {"id": "coffee", "question": "最近美国咖啡进口金额怎么样？", "code": "0901", "flow": "import", "partner": "all", "month": "2026-07"},
    {"id": "beans-export", "question": "美国向中国出口干豆的金额是多少？", "code": "0713", "flow": "export", "partner": "china", "month": "2026-07"},
    {"id": "sugar-date", "question": "2026年6月美国糖的进口额是多少？", "code": "1701", "flow": "import", "partner": "all", "month": "2026-06", "wrong_month_first": True},
    {"id": "aluminium-policy", "question": "美国未锻轧铝进口怎么样？本地有没有相关政策资料？", "code": "7601", "flow": "import", "partner": "all", "month": "2026-07", "policy_fixture": True},
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def policy_fixture():
    doc = build_document({"policy_id": "repair-fixture", "sources": [
        {"id": "repair:p1", "url": "https://example.test/offline-fixture", "text": "OFFLINE SYNTHETIC FIXTURE. Aluminium 7601 candidate scope only. Applies on July 1, 2026 to designated goods of designated origin."},
        {"id": "repair:p2", "url": "https://example.test/offline-fixture", "text": "OFFLINE SYNTHETIC EXCEPTION. Only specified end uses qualify; no general exemption is established."}]}, doc_id="repair-notice", status="enabled")
    set_required_dependencies(doc, {name: {"status": "known", "section_ids": ["repair:p1:para1"]}
        for name in ("effective_date", "origin", "conditions")})
    doc["required_dependencies"]["exceptions"] = {"status": "known", "section_ids": ["repair:p2:para1"]}
    return build_document_store([doc], policy_id="repair-fixture", data_version="fixture-only")


def references():
    refs = []
    for case in CASES:
        export = case["flow"] == "export"
        manifest_path = DATA / "data/processed" / ("trade_scheduleb10" if export else "trade_hts10") / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        entry = next(e for e in manifest["months"] if f"{e['year']:04d}-{e['month']:02d}" == case["month"])
        path = DATA / entry["processed_file" if export else "monthly_output"]
        if export: assert sha(path) == entry["processed_sha256"]
        values = []
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                if not row["scheduleb10" if export else "hts10"].startswith(case["code"]): continue
                if export:
                    if case["partner"] == "china" and row["partner_code"] != "5700": continue
                    values.append(int(row["total_export_fas_usd"]))
                else:
                    prefix = "china" if case["partner"] == "china" else "all_origin"
                    if row[prefix + "_observed"] == "1":
                        values.append(int(row[prefix + "_import_value_consumption_usd"]))
        refs.append({**case, "expected_value_usd": sum(values) if values else None,
                     "reference_file": str(path.relative_to(DATA)), "reference_sha256": sha(path),
                     "manifest_sha256": sha(manifest_path), "source_sha256": entry["source_sha256"]})
    return refs


class ScriptedModel:
    def __init__(self, case): self.case = case; self.calls = 0; self.wrong_sent = False
    def complete(self, *, messages, tools):
        self.calls += 1; case = self.case; last = messages[-1]
        results = [json.loads(m["content"]) for m in messages if m.get("name") == "query_trade"]
        reports = [r["report_id"] for r in results if "report_id" in r]
        if last["role"] == "user":
            name, args = "search_products", {"term": case["code"], "flow": case["flow"]}
        elif not reports:
            wrong = case.get("wrong_month_first") and not self.wrong_sent
            self.wrong_sent = True
            month = "2026-07" if wrong else case["month"]
            name, args = "query_trade", {"candidate_id": f"{case['flow']}:{case['code']}", "flow": case["flow"],
                "partner": case["partner"], "period": {"type": "absolute", "start": month, "end": month}}
        elif case.get("policy_fixture") and last.get("name") != "search_policy":
            name, args = "search_policy", {"query": "Aluminium 7601", "candidate_id": f"{case['flow']}:{case['code']}"}
        else:
            sources = [h["citation_id"] for h in json.loads(last["content"]).get("hits", [])] if case.get("policy_fixture") else []
            name, args = "finish", {"report_ids": reports, "source_ids": sources}
        return ModelResponse(tool_calls=(ModelToolCall(uuid.uuid4().hex, name, args),))


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("mode", choices=["freeze", "run"])
    parser.add_argument("--output", type=Path, required=True); args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_file = args.output / "frozen.json"
    if args.mode == "freeze":
        if manifest_file.exists(): raise ValueError("Frozen suite already exists; never overwrite it")
        files = sorted((ROOT / "src/tradeintel_ai").glob("trade_agent*.py")) + [Path(__file__).resolve(), ROOT / "web/design-preview/live.js"]
        frozen = {"schema": "repair-offline-acceptance-v1", "date": "2026-10-01", "today": "2026-10-01",
            "scope": "scripted engineering acceptance, not model quality; v2 is harness-correction regression after v1 range/absolute error", "cases": references(),
            "code_sha256": {str(p.relative_to(ROOT)): sha(p) for p in files}, "policy_fixture": policy_fixture()}
        manifest_file.write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Frozen four cases; 0 API calls"); return
    frozen = json.loads(manifest_file.read_text())
    for name, digest in frozen["code_sha256"].items():
        if sha(ROOT / name) != digest: raise ValueError("Frozen source changed: " + name)
    if references() != frozen["cases"]: raise ValueError("Frozen reference data changed")
    target = args.output / "results.json"
    if target.exists(): raise ValueError("Results exist; preserve original outcome")
    outcomes = []
    for case in frozen["cases"]:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            if case.get("policy_fixture"): save_announcement_store(root, "repair-fixture", frozen["policy_fixture"])
            model = ScriptedModel(case); request = uuid.uuid4().hex
            agent = TradeResearchAgent(DATA, root, model, today=date.fromisoformat(frozen["today"]))
            state = agent.turn(case["question"], request); turn = state["turns"][-1]
            result = {"id": case["id"], "completed": turn["status"] == "completed", "scope_correct": False,
                      "facts_correct": False, "scripted_calls": model.calls, "reader_projection": bool(turn.get("reader_view")),
                      "model_quality": "not_measured", "human_readability": "not_independently_scored"}
            if turn["report_ids"]:
                report = get_state(root, turn["report_ids"][0]); scope = report["scope"]
                partner = "CHINA" if case["partner"] == "china" else "ALL_ORIGINS"
                result["scope_correct"] = (scope["flow"], scope["product_code"], scope["partner"], scope["start_month"], scope["end_month"]) == (case["flow"], case["code"], partner, case["month"], case["month"])
                result["facts_correct"] = report["summary"]["latest_value_usd"] == case["expected_value_usd"]
            result["guard_intercepted_wrong_month"] = any(e["tool"] == "query_trade" and e["status"] == "error" for e in turn["tool_calls"]) if case.get("wrong_month_first") else None
            if case.get("policy_fixture"):
                bundles = turn["policy_evidence"]["evidence_bundles"]
                result["fixture_exception_preserved"] = bool(bundles) and any("specified end uses" in (c.get("text") or "") for b in bundles for c in b["required_context"])
            result["saved_read_equal"] = state == read_public_session(root, state["session_id"])
            replay = agent.turn(case["question"], request)
            result["replay_without_call"] = replay == state and model.calls == result["scripted_calls"]
            outcomes.append(result)
    target.write_text(json.dumps({"frozen_sha256": sha(manifest_file), "real_api_calls": 0, "results": outcomes}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(outcomes, ensure_ascii=False, indent=2))
    if not all(r["completed"] and r["scope_correct"] and r["facts_correct"] and r["saved_read_equal"] and r["replay_without_call"] and r.get("fixture_exception_preserved", True) and r.get("guard_intercepted_wrong_month") is not False for r in outcomes):
        raise SystemExit("Acceptance did not pass; original results retained")


if __name__ == "__main__": main()
