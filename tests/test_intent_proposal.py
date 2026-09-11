import json
import unittest
from unittest.mock import Mock, patch

from src.tradeintel_ai.intent_proposal import propose_intent, validate_candidate


def candidate():
    return {'status': 'proposal', 'request': {'task': 'counts'},
            'evidence': {'task': '解释三个商品计数'}, 'missing': []}


def model(value=None, **changes):
    response = {'text': json.dumps(value or candidate(), ensure_ascii=False),
                'metadata': {'finish_reason': 'stop'}}
    response.update(changes)
    return Mock(complete=Mock(return_value=response))


class IntentTests(unittest.TestCase):
    def test_proposal_never_executes_and_receives_no_tools(self):
        m = model()
        with patch('src.tradeintel_ai.structured_workflow.execute_request', side_effect=AssertionError('no execution')):
            r = propose_intent('请解释三个商品计数', m)
        self.assertEqual(r['status'], 'needs_confirmation')
        self.assertFalse(r['intent_verified'])
        self.assertFalse(r['executed'])
        self.assertEqual(m.complete.call_args.kwargs['tools'], [])
        self.assertEqual(m.complete.call_count, 1)

    def test_fabricated_quote_rejected(self):
        self.assertEqual(propose_intent('查GDP', model())['status'], 'needs_clarification')

    def test_quote_presence_is_not_semantic_verification(self):
        r = propose_intent('不要解释三个商品计数，只查GDP', model())
        self.assertEqual(r['status'], 'needs_confirmation')
        self.assertFalse(r['intent_verified'])
        self.assertFalse(r['executed'])

    def test_unknown_fields_rejected(self):
        for key in ('sql', 'approved', 'intent_verified'):
            c = candidate(); c['request'][key] = True
            self.assertEqual(propose_intent('解释三个商品计数', model(c))['status'], 'needs_clarification')

    def test_invalid_json_duplicate_keys_and_constants(self):
        for text in ('not json', '{"status":"proposal","status":"clarify"}', '{"status":NaN}', '```json\n{}\n```'):
            self.assertEqual(propose_intent('问题', model(text=text))['status'], 'needs_clarification')

    def test_no_tool_calls_or_truncated_responses(self):
        for changes in ({'metadata': {'finish_reason': 'length'}}, {'metadata': {}},
                        {'tool_calls': [{'name': 'delete', 'arguments': {}}]}):
            self.assertEqual(propose_intent('解释三个商品计数', model(**changes))['status'], 'needs_clarification')

    def test_provider_error_does_not_leak_secret_or_retry(self):
        m = Mock(); m.complete.side_effect = RuntimeError('api_key=secret-test')
        r = propose_intent('问题', m)
        self.assertNotIn('secret-test', str(r))
        self.assertEqual(m.complete.call_count, 1)

    def test_empty_input_uses_no_model(self):
        m = model()
        for question in ('', None, 'x' * 12001):
            self.assertEqual(propose_intent(question, m)['model_calls'], 0)
        m.complete.assert_not_called()

    def test_explicit_clarification(self):
        c = {'status': 'clarify', 'request': None, 'evidence': {}, 'missing': ['months']}
        self.assertEqual(propose_intent('查一下', model(c))['status'], 'needs_clarification')

    def test_trade_preserves_unsupported_scope(self):
        question = '查德国企业2018年4月进口额'
        fields = dict(policy_id='us_301_list1_2018', operation='read', metric='import_value_consumption_usd',
                      origin='Germany', granularity='company', months=['2018-04'], hs6=None, causal_effect=False)
        c = {'status': 'proposal', 'request': {'task': 'trade', 'request': fields},
             'evidence': {'task': question, **{'request.' + k: question for k in fields}}, 'missing': []}
        # Deliberately weak quotes demonstrate why confirmation remains mandatory.
        r = propose_intent(question, model(c))
        self.assertEqual(r['request']['request']['origin'], 'Germany')
        self.assertEqual(r['status'], 'needs_confirmation')
        self.assertFalse(r['intent_verified'])
        for change in ({'months': ['2018-13']}, {'causal_effect': 1}, {'months': ['2018-04'] * 2}):
            c['request']['request'] = {**fields, **change}
            self.assertEqual(propose_intent(question, model(c))['status'], 'needs_clarification')


if __name__ == '__main__':
    unittest.main()
