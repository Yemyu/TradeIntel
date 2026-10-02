"""Recover a completed saved turn without sending it again; continue remaining cases."""
import argparse
import json
import time
from decimal import Decimal
from pathlib import Path

from scripts.run_glm_flash_retest import (PaidOpener, FlashModel, MODEL, PARAMS,
    BASE_URL, DEFAULT_DATA, CREDENTIALS, load_key)
from scripts.run_glm_remaining import execute_remaining
from scripts.run_us_agent_retest import (AgentCaseExecutor, GateError, write_new,
    verify_snapshot, snapshot_files)
from scripts.us_retest_transport import canonical_hash
from scripts.score_us_agent_retest import check_public_turn, audit_query_actions
from tradeintel_ai.model_adapter import OpenAICompatibleConfig


class CompatiblePaidOpener(PaidOpener):
    @property
    def ledger(self):
        return self

    def __call__(self, request, *, timeout):
        response = super().__call__(request, timeout=timeout)
        # Preserve original receipts; provide the executor contract in sidecars.
        name = f"send-{self.count:03}-counted"
        write_new(self.root / (name + "-received.json"), {"model_response":True})
        write_new(self.root / (name + ".json"), {"id":name,"case_id":self.case_id})
        return response

    def records(self):
        return [json.loads(p.read_text()) for p in sorted(self.root.glob("send-*-counted.json"))]


def recover_first(parent):
    plan=json.loads((parent/"plan.json").read_text())
    turn=json.loads((parent/"turns.json").read_text())[0]
    state=json.loads((parent/"evidence/R01/session-readback.json").read_text())
    current=next(t for t in state["turns"] if t["request_id"]==turn["request_id"])
    if current["status"]!="completed":
        raise GateError("First turn not completed; cannot recover as success")
    files=sorted((parent/"evidence/R01/responses").glob("*-response.json"))
    sends=list((parent/"ledgers").glob("send-[0-9][0-9][0-9].json"))
    settlements=list((parent/"ledgers").glob("send-*-settled.json"))
    if len(files)!=len(sends) or len(sends)!=len(settlements):
        raise GateError("Parent accounting not complete")
    tool_records=[item for p in sorted((parent/"evidence/R01/responses").glob("tool-*.json"))
                  for item in json.loads(p.read_text())["tools"]]
    case=plan["cases"][0]
    audit=check_public_turn(parent/"runtime",current,case,json.loads((parent/"reference.json").read_text()),tool_records)
    if not audit["passed"]:
        raise GateError("Saved first report fails verification")
    return {"case_id":"R01","executed":True,"kind":case["kind"],"responses":len(files),
        "agent_status":"completed","public_audit":audit,"report_checks":audit["checks"],
        "numeric_complete":True,"public_safety":audit["public_safety"],"continuation_ready":True,
        "query_audit":audit_query_actions(case,[json.loads(p.read_text()) for p in files],[{"tools":tool_records}]),
        "request_accounting_complete":True,"accounting_complete":True,"origin":"api",
        "recovered_from_saved_evidence":True,"new_api_requests":0}


def prepare(parent,root):
    old=verify_snapshot(parent/"FROZEN_MANIFEST.json")
    if root.exists(): raise GateError("Recovery package exists")
    result=recover_first(parent)
    root.mkdir(parents=True)
    settlements=[json.loads(p.read_text()) for p in (parent/"ledgers").glob("send-*-settled.json")]
    cost=Decimal("0.0003340")+sum(Decimal(r["estimated_cny"]) for r in settlements)
    info={"parent":str(parent),"parent_requests":len(settlements),"cost_including_probe":str(cost),
          "first_result":result,"remaining_case_ids":[c["id"] for c in json.loads((parent/"plan.json").read_text())["cases"][1:]],
          "budget_cny":"2","retry":False}
    write_new(root/"recovery.json",info)
    paths=[Path(p) for p in old["files"]]+list((parent/"evidence").rglob("*.json"))+list((parent/"ledgers").glob("*.json"))
    paths += [root/"recovery.json",Path(__file__).resolve(),Path(__file__).resolve().parents[1]/"tests/test_glm_flash_recovery.py"]
    snapshot_files(paths,root/"FROZEN_MANIFEST.json",ready_for_permit=True)
    return {"first_status":result["agent_status"],"parent_requests":len(settlements),"cost":str(cost),"new_api_requests":0}


def run(root):
    verify=lambda:verify_snapshot(root/"FROZEN_MANIFEST.json")
    verify()
    write_new(root/"STARTED.json",{"user_authorized":True,"retry":False,"budget_cny":"2"})
    info=json.loads((root/"recovery.json").read_text()); parent=Path(info["parent"])
    ledger=CompatiblePaidOpener(root/"ledgers",verify)
    ledger.cost=Decimal(info["cost_including_probe"])
    ledger.count=info["parent_requests"]
    key=load_key(CREDENTIALS)
    plan=json.loads((parent/"plan.json").read_text()); turns=json.loads((parent/"turns.json").read_text())
    def factory(ident):
        ledger.case_id=ident
        model=FlashModel(OpenAICompatibleConfig(BASE_URL,MODEL,key,90,0),system_prompt="",opener=ledger,request_params=PARAMS)
        model.retest_accounting,model.retest_origin=ledger,"api"
        return model
    executor=AgentCaseExecutor(plan,json.loads((parent/"reference.json").read_text()),DEFAULT_DATA,
                              parent/"runtime",root/"evidence",factory)
    def review(case,result):
        write_new(root/"reviews"/(case["id"]+"-NEEDED.json"),{"result":result,"result_sha256":canonical_hash(result)})
        path=root/"reviews"/(case["id"]+"-DECISION.json")
        while not path.exists():
            if time.monotonic()-ledger.started>7200: raise GateError("Review time exhausted")
            time.sleep(1)
        return json.loads(path.read_text())
    prior={c["id"]:{"case_id":c["id"],"executed":False} for c in plan["cases"]}
    prior["R01"]=info["first_result"]
    execute_remaining(plan,turns,prior,root/"batch",executor,verify=verify,review=review)
    result={"status":"finished","combined_requests":ledger.count,"estimated_cny_including_probe":str(ledger.cost),"billing":"not_verified"}
    write_new(root/"RESULT.json",result)
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("action",choices=("prepare","run"));p.add_argument("--parent",type=Path);p.add_argument("--output",type=Path,required=True);p.add_argument("--execute",action="store_true")
    a=p.parse_args()
    if a.action=="prepare" and not a.parent: p.error("--parent required")
    if a.action=="run" and not a.execute: p.error("--execute required")
    print(json.dumps(prepare(a.parent.absolute(),a.output.absolute()) if a.action=="prepare" else run(a.output.absolute())))
