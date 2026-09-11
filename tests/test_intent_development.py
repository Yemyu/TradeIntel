import unittest
from scripts.check_intent_development import evaluate, load_cases, canonical


class IntentDevelopmentTests(unittest.TestCase):
    def test_missing_runs_stay_in_denominator(self):
        result = evaluate([])
        self.assertEqual(result['planned'], 12)
        self.assertEqual(result['correct'], 0)
        self.assertEqual(result['parse_or_missing_failures'], 12)
        self.assertFalse(result['model_adopted'])

    def test_parse_failure_is_not_correct_clarification(self):
        rows = [{'id': c['id'], 'response': {'text': 'bad json', 'metadata': {'finish_reason': 'stop'}}}
                for c in load_cases()]
        result = evaluate(rows)
        self.assertEqual(result['correct'], 0)
        self.assertEqual(result['parse_or_missing_failures'], 12)

    def test_abstain_on_everything_does_not_pass(self):
        text = '{"status":"clarify","request":null,"evidence":{},"missing":["scope"]}'
        result = evaluate([{'id':c['id'], 'response':{'text':text,'metadata':{'finish_reason':'stop'}}} for c in load_cases()])
        self.assertEqual(result['correct'], 3)
        self.assertEqual(result['parse_or_missing_failures'], 0)
        self.assertFalse(result['semantic_review_complete'])

    def test_duplicate_unknown_records_rejected(self):
        for rows in ([{'id':'unknown','response':{}}], [{'id':'D01','response':{}}]*2):
            with self.assertRaises(ValueError):
                evaluate(rows)

    def test_month_order_only_is_normalized(self):
        req = load_cases()[10]['expected']
        other = {'task': 'trade', 'request': {**req['request'], 'months': list(reversed(req['request']['months']))}}
        self.assertEqual(canonical(req), canonical(other))
        other['request']['origin'] = 'all_origins'
        self.assertNotEqual(canonical(req), canonical(other))


if __name__ == '__main__': unittest.main()
