import io
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from scripts.recover_glm_flash import CompatiblePaidOpener,recover_first
from scripts.run_glm_flash_retest import FlashModel,MODEL,PARAMS,BASE_URL,DEFAULT_DATA
from scripts.run_us_agent_retest import AgentCaseExecutor
from tradeintel_ai.model_adapter import OpenAICompatibleConfig

PARENT=Path(__file__).resolve().parents[1]/"tmp/handoff-runs/model-extension-20261002/flash-high/formal"


class RecoveryTests(unittest.TestCase):
    def test_saved_first_recovers_without_network(self):
        result=recover_first(PARENT)
        self.assertEqual(result["new_api_requests"],0)
        self.assertEqual(result["responses"],3)
        self.assertTrue(result["continuation_ready"])

    def test_actual_executor_accounting_interface_with_saved_http_fixture(self):
        plan=json.loads((PARENT/"plan.json").read_text())
        reference=json.loads((PARENT/"reference.json").read_text())
        receipts=[json.loads(p.read_text()) for p in sorted((PARENT/"ledgers").glob("send-*-received.json"))]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); requests=[]
            def transport(request,timeout):
                receipt=receipts[len(requests)];requests.append(request)
                return io.BytesIO(json.dumps({"model":MODEL,"choices":[{"message":receipt["message"]}],"usage":receipt["usage"]}).encode())
            ledger=CompatiblePaidOpener(root/"ledgers",lambda:None,transport=transport)
            ledger.case_id="R01"
            model=FlashModel(OpenAICompatibleConfig(BASE_URL,MODEL,"fixture-only-key",90,0),system_prompt="",opener=ledger,request_params=PARAMS)
            model.retest_accounting=ledger;model.retest_origin="offline_fixture"
            executor=AgentCaseExecutor(plan,reference,DEFAULT_DATA,root/"runtime",root/"evidence",lambda _:model)
            ident=uuid.uuid4().hex
            # Saved finish IDs must be rebound to the fixture tool's new report ID.
            original=transport
            def rebound(request,timeout):
                body=json.loads(request.data)
                response=json.loads(original(request,timeout).read())
                message=response["choices"][0]["message"]
                if len(requests)==3:
                    feedback=json.loads(next(m["content"] for m in reversed(body["messages"]) if m["role"]=="tool"))
                    calls=message["tool_calls"]
                    args=json.loads(calls[0]["function"]["arguments"])
                    args["report_ids"]=[feedback["report_id"]]
                    calls[0]["function"]["arguments"]=json.dumps(args)
                return io.BytesIO(json.dumps(response).encode())
            ledger.transport=rebound
            result=executor({"case_id":"R01","question":plan["cases"][0]["question"],"request_id":ident,"session_id":ident})
            self.assertEqual(result["responses"],3)
            self.assertTrue(result["request_accounting_complete"])
            self.assertEqual(result["agent_status"],"completed")
