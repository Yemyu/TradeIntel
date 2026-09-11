"""Offline characterization, not semantic accuracy or a new acceptance gate."""
import unittest

from tradeintel_ai.request_coverage import materialize_units, validate_units, validate_mapping, request_results
from tradeintel_ai.unified_research import UnifiedResearchWorkflow


def units(parts):
    question = ''.join(p[0] for p in parts)
    wire = [dict(quote=q, kind=k, target=t) for q, k, t in parts]
    return question, validate_units(materialize_units(wire, question), question)


class GranularityAuditTests(unittest.TestCase):
    def test_split_policy_requests_still_share_one_execution_task(self):
        question, rows = units([('措施何时实施？', 'request', 'policy'),
                                ('适用对象是什么？', 'request', 'policy')])
        plan = {'status': 'plan', 'tasks': ['policy'], 'policy_question': question}
        validate_mapping(rows, plan)
        self.assertEqual(len({r['id'] for r in rows}), 2)
        self.assertEqual({r['task_id'] for r in rows}, {'policy_question'})
        self.assertEqual(len(UnifiedResearchWorkflow._obligations(plan)), 1)

    def test_partial_and_full_claims_have_identical_pending_semantic_states(self):
        question, rows = units([('措施何时实施？', 'request', 'policy'),
                                ('适用对象是什么？', 'request', 'policy')])
        obligations = UnifiedResearchWorkflow._obligations({'tasks': ['policy'], 'policy_question': question})
        results = []
        for claims in ([{'text': '仅回答实施时间'}],
                       [{'text': '回答实施时间'}, {'text': '回答适用对象'}]):
            result = {'policy': {'generation': {'status': 'draft_requires_semantic_review', 'claims': claims}}}
            final = UnifiedResearchWorkflow._finalize_obligations(obligations, result)
            results.append(request_results(rows, final))
        self.assertEqual(results[0], results[1])
        self.assertEqual([r['execution_status'] for r in results[0]], ['needs_review', 'needs_review'])
        self.assertTrue(all(r['semantic_coverage_verified'] is False for r in results[0]))

    def test_merged_and_split_preserve_same_policy_question_and_obligation(self):
        split = [('措施何时实施，', 'request', 'policy'), ('适用对象是什么？', 'request', 'policy')]
        question, separate = units(split)
        _, merged = units([(question, 'request', 'policy')])
        plan = {'status': 'plan', 'tasks': ['policy'], 'policy_question': question}
        for rows in (separate, merged):
            validate_mapping(rows, plan)
            self.assertEqual(''.join(r['quote'] for r in rows), question)
        self.assertEqual(len(separate), 2)
        self.assertEqual(len(merged), 1)
        self.assertEqual(UnifiedResearchWorkflow._obligations(plan)[0]['request'], question)

    def test_punctuation_count_is_not_a_question_count(self):
        examples = [
            [('请解释这项措施，尤其是它的适用对象。', 'request', 'policy')],
            [('措施何时实施及适用对象是什么', 'request', 'policy')],
            [('请说明适用范围。', 'request', 'policy'), ('不要推断经济效果，不要预测未来。', 'constraint', 'none')],
            [('资料写着“什么时候实施，适用谁？”；', 'context', 'none'), ('请解释该文件的来源。', 'request', 'policy')],
        ]
        for parts in examples:
            with self.subTest(parts=parts):
                question, rows = units(parts)
                self.assertEqual(''.join(r['quote'] for r in rows), question)
                self.assertEqual(len([r for r in rows if r['id']]), 1)
        # These are supplied classifications, not evidence of model understanding.

    def test_literal_coverage_cannot_validate_an_incorrect_background_label(self):
        question, rows = units([('措施何时实施？', 'request', 'policy'),
                                ('另外请列出进口份额。', 'context', 'none')])
        validate_mapping(rows, {'status': 'plan', 'tasks': ['policy'], 'policy_question': '措施何时实施？'})
        self.assertEqual(''.join(r['quote'] for r in rows), question)
        self.assertEqual(rows[1]['id'], None)
        # Deliberately wrong semantic label passes literal validation: review must
        # start from the original question, not just the model-created request IDs.


if __name__ == '__main__':
    unittest.main()
