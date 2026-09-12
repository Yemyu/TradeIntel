"""Verify transmitted instructions and unchanged strict parsing, offline."""
from copy import deepcopy
import json
import unittest
from unittest.mock import Mock

from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.policy_focus import FocusedPolicyModel, FOCUS_RULES
from tradeintel_ai.policy_retrieval import draft_answer
from tradeintel_ai.policy_response_format import normalize_policy_response


class OutputContractTests(unittest.TestCase):
    def test_actual_generation_message_keeps_evidence_and_one_call(self):
        evidence = {'hits': [{'id': 'fixture-source', 'title': 'Fixture',
                             'published': '2000-01-01', 'page': 1, 'text': 'Fixture evidence'}],
                    'question': '请回答资料中的问题', 'as_of': '2000-01-02'}
        original = deepcopy(evidence)
        model = Mock()
        model.complete.return_value = ModelResponse(text='{"claims":[]}')
        draft_answer(FocusedPolicyModel(model), evidence)
        self.assertEqual(model.complete.call_count, 1)
        messages = model.complete.call_args.kwargs['messages']
        system = messages[0]['content']
        self.assertIn('整个消息只能是一个JSON对象', system)
        self.assertIn('不是在JSON前另写一段答案', system)
        self.assertIn('不得推断现行适用性', system)
        self.assertNotIn('先直接回答用户的问题，再补充', system)
        self.assertEqual(json.loads(messages[1]['content'])['evidence'][0]['text'], 'Fixture evidence')
        self.assertEqual(evidence, original)

    def test_prefix_suffix_and_multiple_objects_remain_rejected(self):
        body = '{"claims":[{"text":"fixture","citations":["source"]}]}'
        for text in ('答案\n```json\n'+body+'\n```',
                     '```json\n'+body+'\n```\n补充结论', body+'\n补充结论', body+body):
            with self.subTest(text=text):
                raw = ModelResponse(text=text, metadata={'finish_reason': 'stop'})
                self.assertEqual(normalize_policy_response(raw).text, '')
                self.assertEqual(raw.text, text)

    def test_plain_and_whole_fence_keep_claims_unchanged(self):
        body = '{"claims":[{"text":"fixture","citations":["source"]}]}'
        for text in (body, '```json\n'+body+'\n```'):
            self.assertEqual(normalize_policy_response(ModelResponse(text=text)).text, body)

    def test_no_development_answers_in_instruction(self):
        for value in ('2018', '25%', 'D89', '36587820118', '7月6日'):
            self.assertNotIn(value, FOCUS_RULES)


if __name__ == '__main__': unittest.main()
