import json
import tempfile
import unittest
from pathlib import Path
from scripts.run_solar_brief_pilot import run, ROOT
from tradeintel_ai.agent import ModelResponse


class SolarBriefPilotTests(unittest.TestCase):
    def test_sealed_brief_with_exact_source_conditions(self):
        corpus = json.loads((ROOT/'data/candidates/solar2024/policy_corpus.json').read_text())
        chunks = {c['title']: c for c in corpus['chunks']}
        fields = {'product_scope': ('products', '已组装成组件或面板的光伏电池。'),
                  'additional_duty': ('rate', '中国原产适用税率之外额外50%，不是现行综合税率。'),
                  'effective_conditions': ('scope_and_effective', '2024-09-27美国东部夏令时间00:01起，消费入境或从仓库提取消费的中国原产商品。'),
                  'origin_scope': ('scope_and_effective', '适用于中国原产商品。'),
                  'general_conditions': ('general_conditions', '一般税率、其他税费及例外仍需按原文逐项核查，不是综合税率。')}
        answer = {'conditions': [{'hts8':'85414300','field':field,'status':'supported',
                   'text':text,'citation':chunks[label]['id']}
                   for field,(label,text) in fields.items()]}
        responses = iter([{'kind':'brief','month':'2026-05','hts8':'85414300'}, answer])
        class FixtureModel:
            def complete(self, **kwargs):
                return ModelResponse(text=json.dumps(next(responses), ensure_ascii=False))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'pilot'
            result = run(output, FixtureModel())
            self.assertEqual(result['status'], 'draft_needs_review')
            self.assertEqual(result['model_calls'], 2)
            self.assertIsNotNone(result['data_version'])
            trade = json.loads((output/'run/trade-evidence.json').read_text())
            self.assertEqual(trade['data_version'], result['data_version'])
            self.assertEqual(trade['data']['policy_id'], 'us_301_solar2024')
            links = json.loads((output/'run/scope-links.json').read_text())
            self.assertEqual(links['data_version'], result['data_version'])
            coverage = json.loads((output/'run/condition-coverage.json').read_text())
            self.assertFalse(coverage['semantic_approval'])
            self.assertEqual(coverage['expected_conditions'], 5)
            self.assertTrue((output/'run/report.zh-CN.md').is_file())
