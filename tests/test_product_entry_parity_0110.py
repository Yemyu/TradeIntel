"""The user-facing and reviewed development paths share one strict workflow."""
import json
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.development_smoke import workflow as smoke_workflow
from tradeintel_ai.unified_research import (PRODUCT_WORKFLOW_OPTIONS,
                                            _render_trade_only,
                                            build_product_workflow)


class ProductEntryParityTests(unittest.TestCase):
    def test_shared_builder_uses_all_locked_options(self):
        model = Mock()
        built = build_product_workflow(model, planner_source_kind='fixture',
                                        allow_host_gap_review=True)
        for name, value in PRODUCT_WORKFLOW_OPTIONS.items():
            self.assertEqual(getattr(built, name), value)
        self.assertTrue(built.allow_host_gap_review)
        self.assertEqual(built.planner_source_kind, 'fixture')

    def test_reviewed_smoke_path_uses_same_builder_when_neutral_mode_enabled(self):
        model = Mock()
        smoke = smoke_workflow(model, 'fixture', True, True, True)
        daily = build_product_workflow(Mock(), planner_source_kind='fixture',
                                       allow_host_gap_review=True)
        for name in PRODUCT_WORKFLOW_OPTIONS:
            self.assertEqual(getattr(smoke, name), getattr(daily, name))
        self.assertEqual(smoke.allow_host_gap_review, daily.allow_host_gap_review)

    def test_outer_cli_forwards_gap_review_to_natural_entry(self):
        from scripts.run_research_brief import main
        with patch('scripts.run_unified_research.main', return_value=0) as delegate:
            self.assertEqual(main(['--natural-language', '--question', 'fixture',
                                   '--allow-host-gap-review']), 0)
        forwarded = delegate.call_args.args[0]
        self.assertIn('--allow-host-gap-review', forwarded)

    def test_natural_cli_uses_strict_prompt_without_network(self):
        from scripts.run_unified_research import main
        from tests.test_trade_mapping_proposal_0105 import QUESTION, candidate

        planner = Mock()
        planner.complete.return_value = ModelResponse(
            text=json.dumps(candidate(), ensure_ascii=False),
            metadata={'finish_reason': 'stop'},
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {'TRADEINTEL_MODEL_NAME': 'glm-4.7'}, clear=False), \
                 patch('scripts.run_unified_research.getpass.getpass', return_value='test-key'), \
                 patch('scripts.run_unified_research.ResearchPlannerModel', return_value=planner):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(main(['--question', QUESTION, '--output-root', tmp]), 0)
        prompt = planner.complete.call_args.kwargs['messages'][0]['content']
        self.assertIn('target只能是policy/trade/unsupported/none', prompt)
        self.assertNotIn('target只能是policy/trade_series/trade_comparison', prompt)

    def test_trade_only_report_shows_official_archive_url(self):
        result = {
            'status': 'trade_draft',
            'request': {'trade': {'origin': 'other_origins', 'hs6': None}},
            'trade': {'sources': {
                'month': {'path': 'IMDB1809.ZIP', 'file_name': 'IMDB1809.ZIP',
                          'sha256': 'abc',
                          'url': 'https://www.census.gov/trade/IMDB1809.ZIP'},
            }},
            'summary': {'series': [{'month': '2018-09', 'value_usd': 10}],
                        'total_usd': 10, 'comparison': None},
        }
        rendered = _render_trade_only(result)
        self.assertIn('IMDB1809.ZIP', rendered)
        self.assertIn('来源网址：https://www.census.gov/trade/IMDB1809.ZIP', rendered)


if __name__ == '__main__':
    unittest.main()
