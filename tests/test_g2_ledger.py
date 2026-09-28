from dataclasses import replace
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch

from scripts.freeze_g2_research import prepare
from tradeintel_ai.g2_ledger import G2Ledger, ExperimentBlocked, FrozenWebModel
from tradeintel_ai.model_adapter import OpenAICompatibleConfig
from tradeintel_ai.research_models import ResearchPlannerModel, JsonResearchModel
from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.web_app import create_server

ROOT=Path(__file__).resolve().parents[1]
CONFIG=OpenAICompatibleConfig('https://fixture.invalid','glm-4.7','fixture-secret',90,0)


class FreeFixture(ResearchPlannerModel):
    max_output_tokens=2000
    calls=0
    def complete(self,**kwargs):
        self.calls+=1
        return ModelResponse(text='模拟回答',metadata={'finish_reason':'stop'})


class JsonFixture(JsonResearchModel):
    max_output_tokens=2000
    calls=0
    def complete(self,**kwargs):
        self.calls+=1
        return ModelResponse(text=json.dumps({'schema_version':'research-brief-v2',
            'findings':[{'observation_id':'observation.amount_leader',
            'explanation':'离线模拟：金额说明统计规模，不是税款。','limitation_ids':['limitation.1']}],
            'followups':[]}),metadata={'finish_reason':'stop'})


class G2LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.inputs=self.root/'inputs'
        prepare(self.inputs)
        self.ledger=G2Ledger(self.inputs,self.root/'ledger')

    def test_durable_once_review_gate_unknown_usage_and_stop(self):
        model=FreeFixture(CONFIG)
        self.ledger.run(0,model)
        other=G2Ledger(self.inputs,self.root/'ledger')
        self.assertIsNone(other.state()['attempts'][0]['usage'])
        for slot in (0,1):
            with self.assertRaises(ExperimentBlocked): other.run(slot,model)
        other.review(0,decision='stop',reason='fixture serious failure',reviewer='fixture')
        with self.assertRaises(ExperimentBlocked): other.run(1,JsonFixture(CONFIG))
        self.assertEqual(model.calls,1)

    def test_failure_retains_slot_and_cannot_be_approved(self):
        class Broken(FreeFixture):
            def complete(self,**kwargs): raise TimeoutError('fixture-secret')
        with self.assertRaises(ExperimentBlocked): self.ledger.run(0,Broken(CONFIG))
        with self.assertRaises(ExperimentBlocked):
            self.ledger.review(0,decision='continue',reason='retry',reviewer='fixture')
        self.assertNotIn('fixture-secret',(self.root/'ledger/state.json').read_text())
        self.assertEqual(self.ledger.state()['attempts'][0]['status'],'failed_or_uncertain')

    def test_settings_tamper_and_reserved_slot_block_before_provider(self):
        model=FreeFixture(replace(CONFIG,timeout_seconds=180))
        with self.assertRaises(ExperimentBlocked): self.ledger.run(0,model)
        self.assertEqual(model.calls,0)
        with self.ledger.locked():
            state=self.ledger.state();state['attempts']=[{'slot':0,'status':'started'}];self.ledger.save(state)
        with self.assertRaises(ExperimentBlocked): self.ledger.run(1,JsonFixture(CONFIG))

    def test_changed_input_blocks(self):
        (self.inputs/'development/B.messages.json').write_text('[]')
        model=FreeFixture(CONFIG)
        with self.assertRaises(ExperimentBlocked): self.ledger.run(0,model)
        self.assertEqual(model.calls,0)

    def test_actual_http_route_uses_frozen_slot_and_blocks_duplicate(self):
        self.ledger.run(0,FreeFixture(CONFIG))
        self.ledger.review(0,decision='continue',reason='synthetic only',reviewer='fixture')
        provider=JsonFixture(CONFIG)
        def factory(config, task): return FrozenWebModel(self.ledger,1,provider)
        server=create_server(root=ROOT,port=0,output_root=self.root/'runs',structured_model_factory=factory)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        task=json.loads((self.inputs/'development/task.json').read_text())
        base=f'http://127.0.0.1:{server.server_port}'
        def post():
            request=Request(base+'/api/research-structured',data=json.dumps(task).encode(),
                            headers={'Content-Type':'application/json','Origin':base})
            return json.load(urlopen(request))
        try:
            with patch('tradeintel_ai.web_app.load_config',return_value=CONFIG):
                result=post()
                self.assertEqual(result['status'],'interpretation_needs_review',result)
                with self.assertRaises(HTTPError) as duplicate:
                    post()
                self.assertEqual(duplicate.exception.code,502)
                alternate=Request(base+'/api/research-v2/preview',data=json.dumps({'question':'anything'}).encode(),
                                  headers={'Content-Type':'application/json','Origin':base})
                with self.assertRaises(HTTPError): urlopen(alternate)
            self.assertEqual(provider.calls,1)
            self.assertEqual(self.ledger.state()['attempts'][1]['timeout_seconds'],90)
        finally:
            server.shutdown();server.server_close();thread.join()
