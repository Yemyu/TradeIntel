from copy import deepcopy
import unittest
from src.tradeintel_ai.evidence_v21 import EvidenceAgentV21, EvidenceRegistryV21, report_v21
from src.tradeintel_ai.agent import ModelResponse, ModelToolCall
from src.tradeintel_ai.report_view import build_view


def answer(calls):
    class Model:
        def complete(self,*,messages,tools):
            if len(messages)==1:
                return ModelResponse(tool_calls=tuple(ModelToolCall(str(i),name,args) for i,(name,args) in enumerate(calls)),
                                     metadata={'finish_reason':'tool_calls'})
            return ModelResponse(text='never publish this draft',metadata={'finish_reason':'stop'})
    return EvidenceAgentV21(Model()).answer('offline fixture')


class ViewTests(unittest.TestCase):
    def test_all_missing_no_false_available_or_zero_amount(self):
        result=answer([('get_trade_series',{'months':['2023-02','2024-09']})])
        original=deepcopy(result)
        view=build_view(result)
        self.assertIn('没有取得任何可用月份金额',view['response'])
        self.assertIn('无可计算观测',view['response'])
        self.assertNotIn('：0 美元',view['response'])
        self.assertNotIn('已返回其余可查月份',view['response'])
        self.assertEqual(result,original)
        self.assertEqual(view['audit_ledger']['facts'],result['facts'])

    def test_mixed_query_lists_only_actual_available_months(self):
        view=build_view(answer([('get_trade_series',{'months':['2014-01','2017-11']})]))
        self.assertIn('本次已返回可查月份：2017-11',view['response'])
        self.assertIn('所列请求月份合计：未知',view['response'])
        self.assertNotIn('never publish',view['response'])

    def test_discrete_months_and_values_stay_bound(self):
        result=answer([('get_trade_series',{'origin':'other_origins','months':['2016-07','2018-04']})])
        view=build_view(result)
        self.assertNotIn('完整窗口',view['response'])
        self.assertNotIn('"start"',view['response'])
        facts=[f for s in view['sections'] for f in s['facts']]
        for f in result['facts']:
            if ' / ' in f['label']:
                self.assertIn(f,facts)
        self.assertFalse(view['scope_verified_against_user_intent'])

    def test_observed_zero_is_still_zero(self):
        result=answer([('get_trade_series',{'months':['2017-02']})])
        tool=result['tool_results'][0]
        tool['data']['series'][0]['value_usd']=0
        tool['data']['total_usd']=tool['data']['observed_total_usd']=0
        report=report_v21(result['tool_results'])
        result.update(facts=report.facts,sources=report.sources)
        view=build_view(result)
        self.assertIn('2017-02 / China 进口额：0 美元',view['response'])
        self.assertNotIn('无可计算观测',view['response'])

    def test_changed_ledger_or_sources_rejected(self):
        result=answer([('get_policy_event',{})])
        for field in ('value','source'):
            bad=deepcopy(result)
            if field=='value':bad['facts'][0]['value']='tampered'
            else:bad['sources'].clear()
            with self.assertRaises(ValueError):build_view(bad)

    def test_host_readiness_condensed_but_user_requested_readiness_kept(self):
        a=build_view(answer([('get_policy_event',{})]))
        self.assertNotIn('v3求解状态码',a['response'])
        self.assertIn('不能报告关税因果效果',a['response'])
        b=build_view(answer([('get_causal_readiness',{})]))
        self.assertIn('v3求解状态码',b['response'])

    def test_truncated_result_not_upgraded_and_no_report_on_error(self):
        result=answer([('get_policy_event',{})])
        result['model_run']['turns'][-1]['finish_reason']='length'
        view=build_view(result)
        self.assertFalse(view['generation_complete'])
        self.assertIn('模型未完整结束',view['response'])
        self.assertEqual(build_view({'status':'error','version':'2.1'})['status'],'unavailable')


if __name__=='__main__':unittest.main()
