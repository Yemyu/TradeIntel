import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.tradeintel_ai.agent import ModelResponse, ModelToolCall
from src.tradeintel_ai.policy_exposure_workflow import EXPECTED, run_exposure_demo, normalise_hts_argument
from src.tradeintel_ai.policy_exposure_tools import get_policy_exposure_series
from src.tradeintel_ai.repository import RepositoryError
from tests.test_policy_exposure_tools import make_fixture
from src.tradeintel_ai.exposure_report import FACTS, render_exposure_report, parse_actions, answer_contract

DRAFT = json.dumps({'next_steps': ['product_breakdown', 'supply_conditions']})


class Model:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def complete(self, **kwargs):
        self.requests.append(kwargs)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class ExposureWorkflowTests(unittest.TestCase):
    def test_actions_only_and_complete_fence(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = make_fixture(Path(directory))
            evidence = get_policy_exposure_series(start='2025-01', end='2025-01', repository=repo)
            text = '{"next_steps": ["origin_breakdown"]}'
            for value in [text, '```json\n' + text + '\n```', '```\n' + text + '\n```']:
                self.assertIn('55 美元', render_exposure_report(value, [evidence], report_date='2026-09-14'))
            self.assertEqual(parse_actions('```json\n' + text + '\n```', [evidence])['normalization'], 'json_fence_removed')
            for value in ['说明\n' + text, text + '\n没有短缺', '```json\n' + text,
                          '{"next_steps": ["origin_breakdown"], "conclusion": "产能充足"}',
                          '{"next_steps": ["origin_breakdown"], "next_steps": ["supply_conditions"]}']:
                with self.assertRaises(ValueError):
                    parse_actions(value, [evidence])

    def test_single_product_actions_exclude_redundant_scope_breakdown(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = make_fixture(Path(directory))
            evidence = get_policy_exposure_series(start='2025-01', end='2025-01', hts8='12345678', repository=repo)
            self.assertNotIn('product_breakdown', answer_contract([evidence])['allowed_next_steps'])
            with self.assertRaises(ValueError):
                parse_actions('{"next_steps": ["product_breakdown"]}', [evidence])
            self.assertIn('25 美元', render_exposure_report('{"next_steps": ["origin_breakdown"]}', [evidence], report_date='2026-09-14'))

    def test_observed_value_decorated_fact_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = make_fixture(Path(directory))
            evidence = get_policy_exposure_series(start='2025-01', end='2025-01', repository=repo)
            decorated = json.dumps({'facts': ['all_origins_usd: 55', 'china_usd: 20', 'china_share_percent: 36.3636'],
                                    'next_steps': ['origin_breakdown']})
            for text in [decorated, '```json\n' + decorated + '\n```']:
                with self.assertRaises(ValueError):
                    render_exposure_report(text, [evidence], report_date='2026-09-14')

    def test_hts_normalization_does_not_guess_missing_digits(self):
        self.assertEqual(normalise_hts_argument({'hts8': 81019910}), {'hts8': '81019910'})
        for value in [True, 1234567, 81019910.0, '08101991', None]:
            result = normalise_hts_argument({'hts8': value})['hts8']
            self.assertEqual(result, value)
            self.assertEqual(type(result), type(value))

    def test_two_queries_and_saved_selection_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = make_fixture(root)
            evidence = get_policy_exposure_series(start='2025-01', end='2025-01', repository=repo)
            selection = ModelResponse(tool_calls=(
                ModelToolCall('a', 'get_policy_exposure_series', {**EXPECTED, 'origin': 'all_origins'}),
                ModelToolCall('b', 'get_policy_exposure_series', EXPECTED)))
            with patch('src.tradeintel_ai.policy_exposure_workflow.PolicyExposureRegistry.call', return_value=evidence):
                run_exposure_demo(Model([selection, ModelResponse(text=DRAFT), ModelResponse(text='baseline')]),
                                  root / 'prior', repository=repo)
                model = Model([ModelResponse(text=DRAFT), ModelResponse(text='baseline')])
                state = run_exposure_demo(model, root / 'resumed', repository=repo, resume_selection=root / 'prior')
            self.assertEqual(state['model_calls'], 3)
            self.assertEqual(len(model.requests), 2)
            self.assertEqual(len([m for m in model.requests[0]['messages'] if m['role'] == 'tool']), 2)
            self.assertEqual(state['status'], 'draft_needs_review')

    def test_two_stage_route_and_separate_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = make_fixture(root)
            evidence = get_policy_exposure_series(start='2025-01', end='2025-01', repository=repo)
            model = Model([ModelResponse(tool_calls=(ModelToolCall('a', 'get_policy_exposure_series', EXPECTED),)),
                           ModelResponse(text=DRAFT), ModelResponse(text='没有数据 SECRET')])
            with patch('src.tradeintel_ai.policy_exposure_workflow.PolicyExposureRegistry.call', return_value=evidence) as call:
                state = run_exposure_demo(model, root / 'run', repository=repo, secret='SECRET')
            call.assert_called_once_with('get_policy_exposure_series', EXPECTED)
            self.assertEqual(state['model_calls'], 3)
            self.assertEqual(state['status'], 'draft_needs_review')
            self.assertEqual(len(model.requests[0]['tools']), 1)
            self.assertNotIn('tool', [m['role'] for m in model.requests[0]['messages']])
            self.assertEqual(model.requests[2]['tools'], [])
            self.assertEqual(model.requests[2]['messages'], model.requests[0]['messages'])
            self.assertNotIn('SECRET', (root / 'run/report.zh-CN.md').read_text())
            self.assertNotIn('SECRET', (root / 'run/baseline-response.json').read_text())
            # Fixture has no old List 1 / causal files, yet the route completes.
            self.assertFalse(repo.paths.causal_design.exists())
            with self.assertRaises(FileExistsError):
                run_exposure_demo(model, root / 'run', repository=repo)

    def test_wrong_scope_or_transport_stops_without_retry(self):
        for response in [ModelResponse(tool_calls=(ModelToolCall('a', 'get_policy_exposure_series', {**EXPECTED, 'start': '2018-01'}),)),
                         RuntimeError('secret transport detail')]:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                model = Model([response])
                with patch('src.tradeintel_ai.policy_exposure_workflow.PolicyExposureRegistry.call') as call:
                    state = run_exposure_demo(model, root / 'run', repository=make_fixture(root))
                call.assert_not_called()
                self.assertEqual(state['model_calls'], 1)
                self.assertEqual(state['status'], 'failed')
                self.assertNotIn('secret transport detail', (root / 'run/main-error.json').read_text())

    def test_equal_total_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = make_fixture(Path(directory))
            monthly = next((Path(directory) / 'data/processed/policy_exposure/monthly').glob('*_01.csv'))
            text = monthly.read_text().replace(',20,1,', ',21,1,').replace(',5,1,', ',4,1,')
            monthly.write_text(text)
            with self.assertRaises(RepositoryError):
                get_policy_exposure_series(start='2025-01', end='2025-01', repository=repo)

    def test_report_contract_blocks_economic_overreach_and_forged_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = make_fixture(Path(directory))
            evidence = get_policy_exposure_series(start='2025-01', end='2025-01', repository=repo)
            for claim in ['政策未导致严重供应短缺', '本土产能已填补需求缺口', '第三国转运已经出现', '进口已去风险化']:
                for text in [claim, json.dumps({'facts': FACTS, 'next_steps': ['product_breakdown'], 'conclusion': claim}),
                             json.dumps({'facts': FACTS, 'next_steps': [claim]})]:
                    with self.assertRaises(ValueError):
                        render_exposure_report(text, [evidence], report_date='2026-09-14')
            for text in ['{"facts": [], "facts": [], "next_steps": []}',
                         json.dumps({'facts': FACTS, 'next_steps': ['product_breakdown'], 'source': 'https://invented'})]:
                with self.assertRaises(ValueError):
                    render_exposure_report(text, [evidence], report_date='2026-09-14')
            report = render_exposure_report(DRAFT, [evidence], report_date='2026-09-14')
            self.assertIn('55 美元', report)
            self.assertIn('36.36%', report)
            self.assertIn('| 12345678 | 25 | 20 | 80.00% | 45.45% |', report)
            self.assertEqual(sum(p['china_value_usd'] for p in evidence['data']['series'][0]['product_breakdown']), 20)
            with self.assertRaises(ValueError):
                render_exposure_report(DRAFT, [evidence], report_date='2024-12-31')

    def test_bad_answer_retained_but_not_delivered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = make_fixture(root)
            evidence = get_policy_exposure_series(start='2025-01', end='2025-01', repository=repo)
            model = Model([ModelResponse(tool_calls=(ModelToolCall('a', 'get_policy_exposure_series', EXPECTED),)),
                           ModelResponse(text='没有供应短缺')])
            with patch('src.tradeintel_ai.policy_exposure_workflow.PolicyExposureRegistry.call', return_value=evidence):
                state = run_exposure_demo(model, root / 'run', repository=repo)
            self.assertEqual(state['status'], 'failed')
            self.assertEqual(state['model_calls'], 2)
            self.assertTrue((root / 'run/answer-response.json').exists())
            self.assertFalse((root / 'run/report.zh-CN.md').exists())
