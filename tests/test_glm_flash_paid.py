import io
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from urllib.request import Request
from scripts.run_glm_flash_retest import PaidOpener, ENDPOINT, MODEL, PARAMS, PROBE_COST, RESERVATION
from scripts.run_us_agent_retest import GateError


class PaidTests(unittest.TestCase):
    def test_settlement_and_before_send_money_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[]
            def transport(req,timeout):
                calls.append(req)
                return io.BytesIO(json.dumps({"model":MODEL,"choices":[{"message":{"role":"assistant","content":"OK"}}],
                    "usage":{"prompt_tokens":100,"completion_tokens":20,"total_tokens":120}}).encode())
            ledger=PaidOpener(Path(tmp)/"ledger",lambda:None,transport=transport)
            ledger.case_id="R01"
            request=Request(ENDPOINT,data=json.dumps({"model":MODEL,"temperature":0,"stream":False,**PARAMS,"messages":[]}).encode(),method="POST")
            ledger(request,timeout=90)
            ledger.settle()
            self.assertEqual(ledger.cost,PROBE_COST+Decimal("0.000136"))
            self.assertTrue(ledger.accounting_complete())
            ledger.cost=Decimal("2")-RESERVATION+Decimal("0.000001")
            with self.assertRaises(GateError): ledger(request,timeout=90)
            self.assertEqual(len(calls),1)

    def test_unknown_usage_keeps_reservation_and_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=PaidOpener(Path(tmp),lambda:None)
            ledger.pending=True;ledger.usage={}
            with self.assertRaises(GateError): ledger.settle()
            self.assertFalse(ledger.accounting_complete())
            self.assertTrue(ledger.pending)
