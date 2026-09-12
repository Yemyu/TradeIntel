"""New guidance is derived from current keys; no network or auto-correction."""
import json
import unittest
from unittest.mock import Mock

from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.unified_research import (UnifiedResearchWorkflow, evidence_key_instructions,
                                           _EVIDENCE_KEYS, _DEFAULT_EVIDENCE, validate_plan)
from tradeintel_ai.request_coverage import materialize_units
from tests.test_unified_research_v2 import trade_plan


class WireGuidanceTests(unittest.TestCase):
    def test_guidance_keys_come_from_validator(self):
        text = evidence_key_instructions()
        required = sorted(_EVIDENCE_KEYS - _DEFAULT_EVIDENCE - {'policy_question_quote', 'policy_as_of_quote'})
        self.assertIn(json.dumps(required, ensure_ascii=False), text)
        self.assertIn('不要给贸易键添加_quote后缀', text)
        for answer in ('2018', '25%', 'D89', '36587820118', 'other_origins'):
            self.assertNotIn(answer, text)

    def test_new_mode_sends_guidance_without_changing_user_text(self):
        for enabled in (False, True):
            model = Mock()
            model.complete.return_value = ModelResponse(text='{}', metadata={'finish_reason': 'stop'})
            question = '请查询；不要估计因果。'
            work = UnifiedResearchWorkflow(model, require_request_units=True, derive_request_offsets=True,
                                           allow_grouped_policy_requests=enabled)
            work.prepare(question)
            messages = model.complete.call_args.kwargs['messages']
            self.assertEqual(messages[1]['content'], question)
            self.assertEqual('提交前字段核对' in messages[0]['content'], enabled)
            self.assertEqual('分号、逗号、句号及引号' in messages[0]['content'], enabled)

    def test_punctuation_can_be_preserved_but_never_dropped(self):
        q = '金额是多少；不做因果分析。'
        parts = [dict(quote='金额是多少', kind='request', target='trade_series'),
                 dict(quote='；', kind='context', target='none'),
                 dict(quote='不做因果分析。', kind='constraint', target='none')]
        self.assertEqual(''.join(r['quote'] for r in materialize_units(parts, q)), q)
        with self.assertRaises(ValueError): materialize_units([parts[0], parts[2]], q)
        with self.assertRaises(ValueError): materialize_units(parts[:2], q)

    def test_wrong_evidence_suffix_still_rejected_not_repaired(self):
        p = trade_plan()
        q = '查询其他原产地整体2018-09和2018-10的美元消费进口额，只做描述性比较，不做因果分析；第一批关税，政策整体范围。'
        self.assertTrue(validate_plan(p, q))
        p['evidence']['trade.metric_quote'] = p['evidence'].pop('trade.metric')
        before = json.dumps(p, sort_keys=True)
        with self.assertRaisesRegex(ValueError, 'research evidence keys'): validate_plan(p, q)
        self.assertEqual(json.dumps(p, sort_keys=True), before)


if __name__ == '__main__': unittest.main()
