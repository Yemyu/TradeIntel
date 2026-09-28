import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tests.test_policy_exposure_tools import make_fixture
from tests.test_policy_exposure_workflow import Model
from src.tradeintel_ai.agent import ModelResponse
from src.tradeintel_ai.business_workflow import run_business_question, validate_plan
from tests.test_policy_conditions import conditions_fixture


def response(value):
    return ModelResponse(text=json.dumps(value, ensure_ascii=False))


class BusinessWorkflowTests(unittest.TestCase):
    def test_brief_combines_real_fixture_query_and_policy_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); repo = make_fixture(root)
            model = Model([response({'kind': 'brief', 'month': '2025-01', 'hts8': '12345678'}),
                           response(conditions_fixture())])
            hits = [{'id': 'fixture:p1', 'text': 'China goods 1234.56.78, subject to conditions.',
                     'citation_url': 'https://example.test/policy'}]
            with patch('src.tradeintel_ai.business_workflow.retrieve_exposure_policy', return_value={'hits': hits}):
                result = run_business_question(model, '请结合登记政策解释及2025-01的12345678贸易金额写简报', root/'run', repository=repo)
            self.assertEqual(result['status'], 'draft_needs_review')
            self.assertEqual((result['model_calls'], result['tool_calls']), (2, 2))
            report = (root/'run/report.zh-CN.md').read_text()
            self.assertIn('| 12345678 | 20 | 25 | 80.00% |', report)
            self.assertIn('政策与统计连接', report)
            self.assertIn('> China goods 1234.56.78', report)
            self.assertIn('不是逐笔实际征税基数', report)
            for name in ['trade-evidence.json', 'policy-evidence.json', 'scope-links.json']:
                self.assertTrue((root/'run'/name).is_file())

    def test_brief_unmatched_policy_keeps_records_without_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); repo = make_fixture(root)
            for index, text in enumerate(['Other 8765.43.21', 'Only 1234.56.78.90']):
                model = Model([response({'kind':'brief','month':'2025-01','hts8':'12345678'})])
                with patch('src.tradeintel_ai.business_workflow.retrieve_exposure_policy', return_value={'hits':[
                    {'id':'fixture:p1','text':text,'citation_url':'https://example.test/policy'}]}):
                    result = run_business_question(model, '2025-01的12345678政策及金额简报', root/f'run{index}', repository=repo)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['model_calls'], 1)
                self.assertTrue((root/f'run{index}/scope-links.json').exists())
                self.assertFalse((root/f'run{index}/report.zh-CN.md').exists())

    def test_brief_does_not_invent_scope(self):
        plan = {'kind':'brief','month':'2025-01','hts8':'12345678'}
        for question in ['登记政策简报', '2025-01的87654321政策简报']:
            with self.assertRaises(ValueError):
                validate_plan(plan, question)

    def test_schema_instructions_cannot_be_delivered_as_answers(self):
        for kind, text in [('clarify','中文补问缺少的月份、商品或排序条件'),
                           ('unsupported','说明未覆盖及所需政策原文、国家商品和统计期')]:
            with self.assertRaises(ValueError): validate_plan({'kind':kind,'message':text}, '测试')

    def test_negative_current_rate_clause_keeps_historical_scope(self):
        from src.tradeintel_ai.exposure_policy import scope_check
        self.assertIsNone(scope_check('解释存档通知，不必确认现行全部税率。'))
        self.assertIsNotNone(scope_check('不要推断今天的综合税率，但是请查最新税率。'))
        self.assertIsNotNone(scope_check('不要忽略今天的税率'))
    def test_arbitrary_question_ranking_uses_fixture_amounts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = make_fixture(root)
            plan = dict(kind='trade', month='2025-01', hts8=None, sort='china_usd', limit=1)
            result = run_business_question(Model([response(plan)]),
                '2025年1月全部商品按中国金额从大到小列前1项', root/'run', repository=repo)
            self.assertEqual(result['status'], 'draft_needs_review')
            self.assertEqual(result['model_calls'], 1)
            self.assertEqual(result['tool_calls'], 1)
            report = (root/'run/report.zh-CN.md').read_text()
            self.assertIn('12345678', report)
            self.assertNotIn('23456789 |', report)

    def test_missing_or_invented_scope_never_queries(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); repo=make_fixture(root)
            for i, plan in enumerate([
                {'kind':'clarify','message':'请明确月份与商品范围'},
                {'kind':'unsupported','message':'尚无该政策数据，请提供原文及统计期'},
                {'kind':'trade','month':'2025-01','hts8':None,'sort':'none','limit':5},
            ]):
                with patch('src.tradeintel_ai.business_workflow.get_policy_exposure_series') as query:
                    result=run_business_question(Model([response(plan)]), '我还没选月份',root/f'run{i}',repository=repo)
                query.assert_not_called()
                self.assertEqual(result['tool_calls'],0)
                self.assertFalse((root/f'run{i}/report.zh-CN.md').exists())

    def test_policy_citations_and_failure_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); repo=make_fixture(root)
            hit={'id':'synthetic:p1','text':'fixture effective at 12:03 a.m.','citation_url':'https://example.test/source'}
            for i, citation in enumerate(['synthetic:p1','invented:p9','synthetic:p1']):
                claim_text = '测试主张' if i != 2 else '上午12:03生效'
                model=Model([response({'kind':'policy'}),response({'claims':[{'text':claim_text,'citations':[citation]}]})])
                with patch('src.tradeintel_ai.business_workflow.retrieve_exposure_policy',return_value={'hits':[hit]}):
                    result=run_business_question(model,'解释已登记通知',root/f'run{i}',repository=repo)
                self.assertEqual(result['model_calls'],2)
                supplied = json.loads(model.requests[1]['messages'][1]['content'])
                self.assertEqual(supplied['evidence'][0]['derived_clock_hints'][0]['clock_24h'],'00:03')
                self.assertEqual(result['status'],'draft_needs_review' if i==0 else 'failed')
                self.assertEqual((root/f'run{i}/report.zh-CN.md').exists(),i==0)
                if i == 0:
                    report = (root/f'run{i}/report.zh-CN.md').read_text()
                    self.assertIn('> fixture effective at 12:03 a.m.', report)
                    self.assertIn('`00:03`', report)
                    self.assertIn('人工核查清单', report)

    def test_sort_and_limit_must_be_explicit(self):
        plan=dict(kind='trade',month='2025-01',hts8=None,sort='china_usd',limit=3)
        for question in ['2025-01全部商品中国金额从大到小列前1项','2025-01全部商品列前3项']:
            with self.assertRaises(ValueError): validate_plan(plan,question)

    def test_negative_causal_boundary_is_not_treated_as_causal_request(self):
        plan={'kind':'brief','month':'2025-01','hts8':None}
        validate_plan(plan, '2025-01全部登记商品的研究简报，不做因果分析或预测。')
        with self.assertRaises(ValueError):
            validate_plan(plan, '2025-01全部登记商品的研究简报，预测政策会造成什么结果。')
