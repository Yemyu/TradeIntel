import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from scripts.run_unified_research import ProductPolicyModel, main
from tradeintel_ai.model_adapter import OpenAICompatibleConfig
from tradeintel_ai.prospective_runner import paired_policy_messages


class ProductPolicyEntryTests(unittest.TestCase):
    def test_actual_policy_boundary_uses_reviewed_message_builder(self):
        model = ProductPolicyModel(OpenAICompatibleConfig('https://offline.invalid', 'test', api_key='test'))
        evidence = [{'id': 's', 'text': 'at 12:01 a.m.'}]
        with patch('tradeintel_ai.research_models.ResearchPolicyModel.complete') as complete:
            model.complete(messages=[{'role': 'user', 'content': json.dumps(
                {'question': '何时？', 'as_of': '2018-07-06', 'evidence': evidence})}], tools=[])
        self.assertEqual(complete.call_args.kwargs['messages'],
                         paired_policy_messages('何时？', '2018-07-06', evidence))

    def test_noninteractive_confirm_stops_before_loading_key(self):
        with patch('scripts.run_unified_research.sys.stdin.isatty', return_value=False), \
             patch('scripts.run_unified_research.load_config') as load, \
             redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                main(['--question', 'test', '--confirm'])
        load.assert_not_called()
