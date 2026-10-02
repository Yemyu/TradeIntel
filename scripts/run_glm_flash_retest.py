"""Finite paid GLM-5.3-Flash High evaluation on the unchanged twelve cases."""
import argparse
import io
import json
import threading
import time
import uuid
from decimal import Decimal
from pathlib import Path

from scripts.run_glm_agent_retest import DEFAULT_TEMPLATE, DEFAULT_DATA, CREDENTIALS, POLICY_FILE
from scripts.glm_retest_transport import ENDPOINT, BASE_URL, load_key
from scripts.run_glm_remaining import execute_remaining
from scripts.run_us_agent_retest import (AgentCaseExecutor, GateError, copy_new_bytes,
    snapshot_files, verify_snapshot, write_new)
from scripts.us_retest_transport import official_transport, canonical_hash
from tradeintel_ai.model_adapter import OpenAICompatibleConfig, OpenAICompatibleModel
from tradeintel_ai.trade_agent_deepseek import ThinkingToolResponse

MODEL = "glm-5.3-flash"
PARAMS = {"thinking": {"type": "enabled"}, "reasoning_effort": "high", "max_tokens": 8192}
PROBE_COST = Decimal("0.0003340")
# Conservative full capacity fallback, including thinking, not byte/token guesses.
RESERVATION = Decimal(1048576) * Decimal("0.8") / 1000000 + Decimal(131072) * Decimal("2.8") / 1000000


class FlashModel(OpenAICompatibleModel):
    def _payload(self, *, messages, tools):
        body = super()._payload(messages=messages, tools=tools)
        body["stream"] = False
        for source, target in zip(messages, body["messages"]):
            if "reasoning_content" in source:
                target["reasoning_content"] = source["reasoning_content"]
        return body

    def complete(self, *, messages, tools):
        result = super().complete(messages=messages, tools=tools)
        message = self.retest_accounting.message
        return ThinkingToolResponse(text=result.text, tool_calls=result.tool_calls, metadata=result.metadata,
            reasoning_content=message.get("reasoning_content"), reasoning_present="reasoning_content" in message,
            wire_content=message.get("content"), wire_content_present="content" in message)


class PaidOpener:
    def __init__(self, root, verify, *, transport=official_transport):
        self.root, self.verify, self.transport = root, verify, transport
        self.cost, self.count, self.pending = PROBE_COST, 0, False
        self.message = None
        self.started = time.monotonic()
        self.per_case = {}
        self.case_id = None

    def __call__(self, request, *, timeout):
        self.verify()
        body = json.loads(request.data)
        expected = {"model": MODEL, "temperature": 0, "stream": False, **PARAMS}
        if (request.full_url != ENDPOINT or request.get_method() != "POST" or len(request.data) > 65536
                or any(body.get(k) != v for k,v in expected.items())
                or set(body) - {*expected, "messages", "tools", "tool_choice"}):
            raise GateError("Flash wire profile changed")
        if (self.pending or self.count >= 48 or self.per_case.get(self.case_id, 0) >= 6
                or self.cost + RESERVATION > Decimal("2") or not 0 < timeout <= 90
                or time.monotonic() - self.started > 7200):
            raise GateError("Flash paid budget/time/request limit")
        self.count += 1
        self.per_case[self.case_id] = self.per_case.get(self.case_id, 0) + 1
        self.pending = True
        write_new(self.root / f"send-{self.count:03}.json", {"case_id": self.case_id,
            "body_sha256": canonical_hash(body), "reserved_cny": str(RESERVATION)})
        try:
            with self.transport(request, timeout=timeout) as response:
                if getattr(response, "status", 200) != 200 or (hasattr(response, "geturl") and response.geturl() != ENDPOINT):
                    raise GateError("Flash HTTP status/redirect")
                raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise GateError("Flash response size")
            result = json.loads(raw)
            if result.get("model") != MODEL:
                raise GateError("Flash response model mismatch")
            self.message = result["choices"][0]["message"]
            self.usage = result.get("usage")
            write_new(self.root / f"send-{self.count:03}-received.json", {
                "model": result["model"], "message": {k:self.message[k] for k in ("role","content","tool_calls") if k in self.message},
                "usage": {k:self.usage[k] for k in ("prompt_tokens","completion_tokens","total_tokens") if isinstance(self.usage,dict) and k in self.usage}})
            return io.BytesIO(raw)
        except Exception:
            self.fail("http_or_protocol_unknown")
            raise

    def settle(self):
        vals = [self.usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")] if isinstance(self.usage,dict) else []
        if (len(vals) != 3 or any(type(v) is not int or v < 0 for v in vals)
                or vals[0] > 1048576 or vals[1] > 131072 or vals[2] != vals[0] + vals[1]):
            self.fail("unaccounted_usage")
            raise GateError("Flash usage unknown")
        cost = (Decimal(vals[0])*Decimal("0.8") + Decimal(vals[1])*Decimal("2.8"))/1000000
        self.cost += cost
        write_new(self.root / f"send-{self.count:03}-settled.json", {
            "prompt_tokens":vals[0],"completion_tokens":vals[1],"total_tokens":vals[2],
            "estimated_cny":str(cost),"cumulative_including_probe_cny":str(self.cost),"billing":"not_verified"})
        self.pending = False

    def fail(self, reason):
        if not (self.root / "STOP.json").exists():
            write_new(self.root / "STOP.json", {"reason":reason,"retry":False})

    def accounting_complete(self):
        return not self.pending and not (self.root / "STOP.json").exists()


def prepare(root):
    old = verify_snapshot(DEFAULT_TEMPLATE / "FROZEN_MANIFEST.json")
    if root.exists():
        raise GateError("Flash package exists")
    root.mkdir(parents=True)
    copy_new_bytes(DEFAULT_TEMPLATE / "inputs/plan.json",root / "plan.json")
    copy_new_bytes(DEFAULT_TEMPLATE / "reference/trade.json",root / "reference.json")
    copy_new_bytes(DEFAULT_TEMPLATE / "runtime/.local/announcement-docs" / POLICY_FILE,
                   root / "runtime/.local/announcement-docs" / POLICY_FILE)
    plan = json.loads((root / "plan.json").read_text())
    sessions, turns = {}, []
    for c in plan["cases"]:
        ident = uuid.uuid4().hex
        sessions.setdefault(c["session"],ident)
        turns.append({"case_id":c["id"],"question":c["question"],"requires":c.get("requires"),
                      "request_id":ident,"session_id":sessions[c["session"]]})
    write_new(root / "turns.json",turns)
    write_new(root / "config.json", {"model":MODEL,"params":PARAMS,"budget_cny":"2",
        "probe_cost_cny":str(PROBE_COST),"reservation_cny":str(RESERVATION),
        "input_per_million":"0.8","output_per_million":"2.8", "max_requests":48,
        "price_source":"https://docs.bigmodel.cn/cn/guide/start/pricing",
        "hypothesis":"Newer GLM can complete unchanged agent tasks", "retry":False,
        "control":"same twelve questions, data, agent, tools and scoring; no gold in model inputs"})
    paths = [Path(p) for p in old["files"]] + list(root.glob("*.json"))
    paths += [root / "runtime/.local/announcement-docs" / POLICY_FILE, Path(__file__).resolve(),
              Path(__file__).with_name("run_glm_remaining.py")]
    snapshot_files(paths,root / "FROZEN_MANIFEST.json",ready_for_permit=True)
    return {"status":"prepared","api_calls":0}


def run(root):
    verify = lambda: verify_snapshot(root / "FROZEN_MANIFEST.json")
    verify()
    write_new(root / "STARTED.json",{"user_authorized":True,"budget_cny":"2","retry":False})
    key = load_key(CREDENTIALS)
    ledger = PaidOpener(root / "ledgers",verify)
    plan = json.loads((root / "plan.json").read_text())
    turns = json.loads((root / "turns.json").read_text())
    def factory(case):
        ledger.case_id = case
        model = FlashModel(OpenAICompatibleConfig(BASE_URL,MODEL,key,90,0),system_prompt="",opener=ledger,request_params=PARAMS)
        model.retest_accounting,model.retest_origin = ledger,"api"
        return model
    executor = AgentCaseExecutor(plan,json.loads((root / "reference.json").read_text()),DEFAULT_DATA,
                                root / "runtime",root / "evidence",factory)
    def review(case,result):
        write_new(root / "reviews" / (case["id"]+"-NEEDED.json"),{"result":result,"result_sha256":canonical_hash(result)})
        path = root / "reviews" / (case["id"]+"-DECISION.json")
        while not path.exists():
            if time.monotonic()-ledger.started > 7200:
                raise GateError("Review time limit")
            time.sleep(1)
        return json.loads(path.read_text())
    prior = {c["id"]:{"case_id":c["id"],"executed":False} for c in plan["cases"]}
    execute_remaining(plan,turns,prior,root / "batch",executor,verify=verify,review=review)
    receipt = {"status":"finished","requests":ledger.count,"estimated_cny_including_probe":str(ledger.cost),"billing":"not_verified"}
    write_new(root / "RESULT.json",receipt)
    return receipt


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("prepare","run"))
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--execute",action="store_true")
    args=parser.parse_args()
    if args.action=="run" and not args.execute:
        parser.error("--execute required")
    print(json.dumps(prepare(args.output.absolute()) if args.action=="prepare" else run(args.output.absolute())))
