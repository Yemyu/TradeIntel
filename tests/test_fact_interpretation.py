import json
import tempfile
import unittest
from pathlib import Path
from copy import deepcopy
from tradeintel_ai.fact_interpretation import review, messages, trade_context
from tradeintel_ai.solar_fact_sheet import build_fact_sheet
from tradeintel_ai.solar_policy import build_corpus
from tradeintel_ai.agent import ModelResponse
from scripts.run_solar_brief_pilot import run, ROOT

class InterpretationTests(unittest.TestCase):
    def sheet(self):
        corpus=build_corpus(ROOT)
        return build_fact_sheet({'policy_id':corpus['policy_id'],'hits':corpus['chunks']},'v')
    def answer(self,text='需进一步核查企业实际入境事件是否符合公告范围。'):
        return {'notes':[{'kind':'investigation','fact_ids':['policy.entry_events'],'text':text}]}
    def trade(self):
        return {'status':'ok','data_version':'v','data':{'policy_id':'us_301_solar2024',
            'coverage_complete':True,'measure':'import_value_consumption_usd','origin':'China',
            'requested_months':['2026-07'],'series':[{'month':'2026-07','product_breakdown':[
                {'hts8':'85414200','all_origins_value_usd':100,'china_value_usd':5,'china_share_percent':5.0}]}]}}
    def test_trade_context_binding_and_message(self):
        trade=self.trade(); original=deepcopy(trade)
        content=json.loads(messages('问题',self.sheet(),trade)[1]['content'])
        ids={f['id'] for f in content['facts']}
        self.assertIn('trade.2026-07.85414200',ids)
        self.assertEqual(content['trade_context']['source_artifact'],'trade-evidence.json')
        self.assertEqual(trade,original)
        for change in ('version','case','coverage','month'):
            bad=deepcopy(trade)
            if change=='version': bad['data_version']='another'
            elif change=='case': bad['data']['policy_id']='another'
            elif change=='coverage': bad['data']['coverage_complete']=False
            else: bad['data']['requested_months']=['2026-06']
            with self.assertRaises(ValueError): trade_context(bad,self.sheet())
    def test_false_missing_data_flag_and_valid_reference(self):
        answer=self.answer('缺乏贸易流量，需重新计算金额。')
        answer['notes'][0]['fact_ids']=['trade.available']
        result=review(answer,self.sheet(),self.trade())
        self.assertIn('possible_missing_data_claim_or_duplicate_completed_query',[f['reason'] for f in result['flags']])
        answer['notes'][0]['text']='统计金额不能说明企业实际承担税款，需要税单与合同核查。'
        result=review(answer,self.sheet(),self.trade())
        self.assertEqual(result['status'],'manual_review_required')
        self.assertFalse(result['approved'])
    def test_checks_never_approve(self):
        result=review(self.answer(),self.sheet())
        self.assertFalse(result['approved'])
        flagged=review(self.answer('上午12:01生效，将会导致损失。'),self.sheet())
        self.assertEqual(flagged['status'],'needs_revision')
        bad=self.answer(); bad['notes'][0]['fact_ids']=['invented']
        with self.assertRaises(ValueError): review(bad,self.sheet())
        with self.assertRaises(ValueError): review({'notes':[]},self.sheet())
        self.assertIn('policy.entry_events',messages('问题',self.sheet())[1]['content'])
    def test_live_path_fixture_quarantines_all_prose(self):
        text='上午12:01生效，将会导致损失。'
        answer=self.answer(text)
        saved=deepcopy(answer)
        replies=iter([{'kind':'brief','month':'2026-05','hts8':'85414300'},answer])
        class Fixture:
            def complete(self,**kwargs): return ModelResponse(text=json.dumps(next(replies),ensure_ascii=False))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'pilot'
            result=run(root,Fixture(),interpretation_mode=True)
            self.assertEqual(result['status'],'interpretation_needs_review')
            self.assertEqual(result['model_calls'],2)
            self.assertEqual(result['interpretation_status'],'needs_revision')
            self.assertNotIn(text,(root/'run/source-packet.zh-CN.md').read_text())
            self.assertIn(text,(root/'run/interpretation-pending.zh-CN.md').read_text())
            self.assertFalse((root/'run/report.zh-CN.md').exists())
            self.assertFalse(result['delivery']['approved'])
        self.assertEqual(answer,saved)
