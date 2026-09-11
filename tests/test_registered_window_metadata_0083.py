import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.repository import DataPaths, EvidenceRepository, RepositoryError
from tradeintel_ai.research_comparison import registered_comparison_metadata, registered_windows
from tradeintel_ai.unified_research import UnifiedResearchWorkflow
from tests.test_unified_research import QUESTION, plan


class RegisteredWindowMetadataTests(unittest.TestCase):
    def test_registered_windows_use_amount_free_metadata_not_summary_loader(self):
        repository = EvidenceRepository()
        with patch.object(repository, 'statistical_baseline', side_effect=AssertionError('不要读取旧摘要接口')):
            windows = registered_windows(repository)
        window = windows['immediate_post_same_months']
        self.assertEqual(window['months_per_window'], 5)
        self.assertEqual(window['source']['path'],
                         'data/processed/analysis/registered_comparison_windows.json')
        self.assertEqual(window['source']['summary_path'],
                         'data/processed/analysis/statistical_baseline_summary.json')

    def test_source_summary_hash_mismatch_is_rejected(self):
        source_root = ROOT / 'data/processed/analysis'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'data/processed/analysis'
            target.mkdir(parents=True)
            shutil.copyfile(source_root / 'registered_comparison_windows.json',
                            target / 'registered_comparison_windows.json')
            summary = source_root / 'statistical_baseline_summary.json'
            (target / summary.name).write_bytes(summary.read_bytes() + b'\nchanged')
            repository = EvidenceRepository(DataPaths(root))
            with self.assertRaisesRegex(RepositoryError, '版本不一致'):
                registered_comparison_metadata(repository)

    def test_v3_registered_window_derives_months_and_records_provenance(self):
        payload = plan()
        payload['comparison'] = {'kind': 'registered',
                                 'comparison_id': 'immediate_post_same_months'}
        payload['policy_search_query'] = (
            'initial Section 301 List 1 effective date additional duty rate')
        payload['trade']['months'] = None
        selected = '明确选择 immediate_post_same_months 登记窗口'
        payload['evidence']['trade.months'] = selected
        payload['evidence']['trade.comparison'] = selected
        question = QUESTION.replace('2018-09和2018-10', '') + selected + '。'
        model = Mock()
        model.complete.return_value = ModelResponse(
            text=json.dumps(payload, ensure_ascii=False),
            metadata={'finish_reason': 'stop'})

        preview = UnifiedResearchWorkflow(model).prepare(question)
        self.assertEqual(preview['status'], 'needs_confirmation')
        expected = ['2017-08', '2017-09', '2017-10', '2017-11', '2017-12',
                    '2018-08', '2018-09', '2018-10', '2018-11', '2018-12']
        self.assertEqual(preview['plan']['trade']['months'], expected)
        self.assertEqual(preview['derived_parameters']['trade.months']['value'], expected)
        self.assertEqual(preview['derived_parameters']['trade.months']['input_id'],
                         'immediate_post_same_months')
        self.assertEqual(preview['plan']['comparison_contract']['window_source']['path'],
                         'data/processed/analysis/registered_comparison_windows.json')
        self.assertEqual(preview['provenance']['case_settings']['status'], 'confirmed')
        self.assertEqual(preview['provenance']['trade.months']['kind'], 'derived')
        self.assertFalse(preview['trade_assessment']['amounts_read'])

        # The model must not hide explicit user months by returning null.
        for expression in ('2018-09和2018-10', '2018年9月和10月', '去年8月'):
            rejected = UnifiedResearchWorkflow(model).prepare(question + expression)
            self.assertEqual(rejected['status'], 'needs_clarification')
            self.assertNotIn('confirmation_token', rejected)
            self.assertEqual(rejected['planner_audit']['status'], 'clarification')

    def test_explicit_cutoff_reuse_is_visible_and_conflicts_stop(self):
        phrase = '沿用已确认的政策资料截止日'
        question = '第一批何时生效？' + phrase
        payload = {'status': 'plan', 'policy_question': '第一批何时生效？',
                   'policy_as_of': None, 'trade': None, 'comparison': None,
                   'policy_search_query': 'initial Section 301 effective date',
                   'tasks': ['policy'], 'missing': [],
                   'evidence': {'policy_question_quote': '第一批何时生效？',
                                'policy_as_of_quote': phrase}}
        model = Mock()
        model.complete.return_value = ModelResponse(text=json.dumps(payload),
                                                    metadata={'finish_reason': 'stop'})
        workflow = UnifiedResearchWorkflow(model)
        preview = workflow.prepare(question)
        self.assertEqual(preview['status'], 'needs_confirmation')
        self.assertEqual(preview['plan']['policy_as_of'], '2018-07-06')
        self.assertEqual(preview['provenance']['policy_as_of']['kind'], 'confirmed_setting')
        with tempfile.TemporaryDirectory() as tmp:
            result = workflow.confirm(preview['confirmation_token'], Path(tmp) / 'delivery')
            self.assertEqual(result['plan']['policy_as_of'], '2018-07-06')
        rejected = workflow.prepare(question + '改为2019-01-01')
        self.assertEqual(rejected['status'], 'needs_clarification')
        self.assertNotIn('confirmation_token', rejected)
        rejected = workflow.prepare('第一批何时生效？')
        self.assertEqual(rejected['status'], 'needs_review')


if __name__ == '__main__':
    unittest.main()
