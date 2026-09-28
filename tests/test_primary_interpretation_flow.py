"""Real published data and HTTP workflow, deterministic model response only."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request,urlopen
from src.tradeintel_ai.web_app import create_server
from src.tradeintel_ai.agent import ModelResponse
from src.tradeintel_ai.model_adapter import OpenAICompatibleConfig

ROOT=Path(__file__).resolve().parents[1]


class PrimaryFlowTests(unittest.TestCase):
    def test_unsupported_investigation_flags(self):
        from src.tradeintel_ai.primary_fact_sheet import build_primary_fact_sheet
        from src.tradeintel_ai.exposure_policy import retrieve_exposure_policy
        from src.tradeintel_ai.fact_interpretation import review
        sheet=build_primary_fact_sheet(retrieve_exposure_policy(ROOT,'全部登记商品',as_of='2026-09-15'),'fixture')
        answer={'notes':[{'kind':'investigation','fact_ids':['policy.entry_events'],
                          'text':'核查生效前入库是否豁免。'},
                         {'kind':'investigation','fact_ids':['policy.origin'],
                          'text':'需调查第三国转运。'}]}
        result=review(answer,sheet)
        self.assertFalse(result['approved'])
        self.assertEqual({f['reason'] for f in result['flags']},
                         {'exemption_inference_requires_explicit_clause','origin_anomaly_requires_transaction_evidence'})

    def test_changed_clause_cannot_reuse_mapping(self):
        from src.tradeintel_ai.primary_fact_sheet import build_primary_fact_sheet
        from src.tradeintel_ai.exposure_policy import retrieve_exposure_policy
        evidence=retrieve_exposure_policy(ROOT,'五个登记商品',as_of='2026-09-15')
        sheet=build_primary_fact_sheet(evidence,'fixture-version')
        self.assertEqual(len(sheet['product_rates']),5)
        evidence['hits'][0]['text']+=' Additional conflicting condition.'
        with self.assertRaises(ValueError):build_primary_fact_sheet(evidence,'fixture-version')

    def test_primary_question_data_review_export(self):
        seen=[]
        def model_response(self,**kwargs):
            seen.append(kwargs)
            return ModelResponse(text=json.dumps({'notes':[{'kind':'limitation','fact_ids':['trade.measure'],
                'text':'若要判断企业实际承担的税款，需要逐笔税单；当前消费进口金额只能说明统计规模。'}]},ensure_ascii=False))
        with tempfile.TemporaryDirectory() as folder:
            server=create_server(root=ROOT,port=0,output_root=Path(folder)/'runs')
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            def post(route,value):
                return json.load(urlopen(Request(base+route,data=json.dumps(value).encode(),
                    headers={'Content-Type':'application/json','Origin':base})))
            try:
                with (patch('src.tradeintel_ai.web_app.load_config',return_value=OpenAICompatibleConfig('https://example.invalid','fixture','fixture')),
                      patch('src.tradeintel_ai.research_models.JsonResearchModel.complete',model_response)):
                    result=post('/api/research-structured',{'policy_id':'us_301_review2025_tungsten_solar',
                        'month':'2026-07','product':'all','task':'source_and_investigation'})
                self.assertEqual(result['status'],'interpretation_needs_review')
                self.assertEqual(len(seen),1)
                facts={f['id']:f['value'] for f in json.loads(seen[0]['messages'][1]['content'])['facts']}
                self.assertEqual(facts['policy.additional_duty.38180000'],50)
                self.assertEqual(facts['policy.additional_duty.81019910'],25)
                html=urlopen(base+result['data_report']['url']).read().decode()
                self.assertIn('193,774,871',html)
                suffix='?run_id='+result['run_id']
                review=json.load(urlopen(base+'/api/saved-interpretation-review'+suffix))
                post('/api/saved-interpretation-review'+suffix,{'fingerprint':review['fingerprint'],
                    'reviewer':'automated-fixture-only','facts_checked':True,
                    'decisions':[{'index':0,'verdict':'accept','reason':'test fixture only'}]})
                draft=urlopen(base+'/api/saved-interpretation-draft'+suffix).read().decode()
                self.assertIn('38180000：额外加征50%',draft)
                self.assertIn('81019910：额外加征25%',draft)
                self.assertIn('| 2026-07 |',draft)
                self.assertIn(result['data_report']['url'],draft)
            finally:
                server.shutdown();server.server_close();thread.join(timeout=2)
