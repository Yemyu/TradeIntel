import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.tradeintel_ai.business_series import summarize_series, render_series
from src.tradeintel_ai.business_workflow import validate_plan, run_business_question
from tests.test_business_workflow import response
from tests.test_policy_exposure_tools import make_fixture
from tests.test_policy_exposure_workflow import Model
from tests.test_policy_conditions import conditions_fixture


class BusinessSeriesTests(unittest.TestCase):
    def test_sequence_complete_workflow(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); repo = make_fixture(root)
            plan = {'kind':'series_brief', 'start':'2025-01', 'end':'2025-02',
                    'hts8':'12345678', 'comparison':{'kind':'sequence'}}
            model = Model([response(plan), response(conditions_fixture(quote='1234.56.78 subject to conditions'))])
            with patch('src.tradeintel_ai.business_workflow.retrieve_exposure_policy', return_value={'hits':[
                {'id':'fixture:p1','text':'1234.56.78 subject to conditions','citation_url':'https://example.test'}]}):
                result = run_business_question(model, '列出2025-01至2025-02的12345678逐月金额并解释政策', root/'run', repository=repo)
            self.assertEqual(result['status'], 'draft_needs_review')
            self.assertEqual(result['comparison_status'], 'sequence_only')
            report = (root/'run/report.zh-CN.md').read_text()
            self.assertIn('| 2025-01 | 12345678 | 20 | 25 | 80.00% |', report)
            self.assertIn('| 2025-02 | 12345678 | 10 | 10 | 100.00% |', report)
            self.assertNotIn('变化率：', report)
            self.assertIn('登记商品中文描述（程序读取，仍需与原文核对）：测试商品', report)
            self.assertIn('所问编码 12345678 的原文所在行', report)
            supplied = json.loads(model.requests[1]['messages'][1]['content'])
            self.assertEqual(supplied['requested_scope']['hts8'], '12345678')
            self.assertEqual((result['model_calls'], result['tool_calls']), (2,2))

    def test_direction_and_requested_comparison_cannot_be_dropped(self):
        plan = {'kind':'series_brief','start':'2026-06','end':'2026-07','hts8':'38180000',
                'comparison':{'kind':'endpoint','reference_month':'2026-06','current_month':'2026-07',
                              'quote':'以2026-06为基准，比较2026-07'}}
        q = '38180000：以2026-06为基准，比较2026-07，解释政策'
        validate_plan(plan, q)
        for question in ['38180000以2026-07为基准，比较2026-06', '不要'+q]:
            with self.assertRaises(ValueError): validate_plan(plan, question)
        plan['comparison'] = {'kind':'sequence'}
        with self.assertRaises(ValueError): validate_plan(plan, q)

    def fixture(self):
        series = [{'month':m, 'all_origins_value_usd':w, 'china_value_usd':c,
                   'product_breakdown':[{'hts8':'38180000','all_origins_value_usd':w,'china_value_usd':c}]}
                  for m,w,c in [('2026-06',100,0),('2026-07',80,20)]]
        sources = [{'path':f'data/processed/policy_exposure/monthly/p_{m}.csv','sha256':m} for m in ['2026_06','2026_07']]
        evidence = {'data':{'coverage_complete':True,'policy_id':'p','hts8':'38180000',
                           'series':series,'start':'2026-06','end':'2026-07'}, 'evidence':{'sources':sources}}
        review = {'status':'reviewed_specific_transition','reference_month':'2026-06','current_month':'2026-07',
                  'sources':sources, 'comparison':{'reference_value_usd':100,'current_value_usd':80},
                  'scope_limit':'仅专项窗口','source_url':'https://example.test'}
        comparison = {'kind':'endpoint','reference_month':'2026-06','current_month':'2026-07'}
        return evidence, review, comparison

    def test_reviewed_amounts_zero_baseline_and_percentage_points(self):
        evidence, review, comparison = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'review.json'; path.write_text(json.dumps(review))
            summary = summarize_series(evidence, comparison, review_path=path)
            self.assertEqual(summary['metrics']['all_origins_value_usd']['change_percent'], '-20.00')
            self.assertIsNone(summary['metrics']['china_value_usd']['change_percent'])
            self.assertEqual(summary['china_share_change_percentage_points'], 25)
            self.assertIn('25.00 个百分点', '\n'.join(render_series(evidence, summary)))

    def test_bad_hash_amounts_or_scope_fail_closed(self):
        evidence, review, comparison = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'review.json'
            self.assertEqual(summarize_series(evidence, comparison, review_path=path)['status'], 'comparability_unreviewed')
            for mutate in [lambda r:r['sources'][0].update(sha256='bad'),
                           lambda r:r['comparison'].update(reference_value_usd=999),
                           lambda r:r.update(reference_month='2025-06')]:
                bad = copy.deepcopy(review); mutate(bad); path.write_text(json.dumps(bad))
                with self.assertRaises(ValueError): summarize_series(evidence, comparison, review_path=path)
            path.write_text(json.dumps(review))
            evidence['data']['hts8'] = None
            self.assertEqual(summarize_series(evidence, comparison, review_path=path)['status'], 'comparability_unreviewed')

    def test_missing_month_not_zero_filled(self):
        evidence, review, comparison = self.fixture()
        evidence['data']['coverage_complete'] = False
        with self.assertRaises(ValueError): summarize_series(evidence, comparison, review_path=Path('unused'))
