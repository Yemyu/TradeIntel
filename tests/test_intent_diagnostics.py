import unittest
from src.tradeintel_ai.intent_diagnostics import diagnose_response
from src.tradeintel_ai.intent_diagnostics import DiagnosticModel
from unittest.mock import Mock


class DiagnosticTests(unittest.TestCase):
    def test_failures_have_distinct_stages(self):
        for text, stage in (('', 'empty_text'), ('```json\n{}\n```', 'json_decode'),
                            ('{}', 'candidate_validation')):
            r = diagnose_response('问题', {'text': text, 'metadata': {'finish_reason': 'stop'}})
            self.assertEqual(r['stage'], stage)
            self.assertFalse(r['executed'])

    def test_valid_clarification_is_not_failure(self):
        r = diagnose_response('问题', {'text': '{"status":"clarify","request":null,"evidence":{},"missing":["scope"]}',
                                     'metadata': {'finish_reason': 'stop'}})
        self.assertEqual(r['stage'], 'valid_clarification')
        self.assertIsNone(r['semantic_correctness'])

    def test_no_exception_content_exposed(self):
        r = diagnose_response('问题', {'text': 'secret-test'})
        self.assertNotIn('secret-test', str(r))

    def test_raw_response_is_saved_redacted_before_parsing(self):
        events = []
        m = DiagnosticModel(Mock(complete=Mock(return_value={'text':'bad JSON secret-test'})), events.append, api_key='secret-test')
        m.complete(messages=[], tools=[])
        self.assertEqual(events[-1]['response']['text'], 'bad JSON [REDACTED]')
        with self.assertRaises(ValueError): m.complete(messages=[], tools=[])

    def test_failed_attempt_count_and_no_secret_exception(self):
        events = []
        m = DiagnosticModel(Mock(complete=Mock(side_effect=RuntimeError('secret-test'))), events.append, api_key='secret-test')
        with self.assertRaises(RuntimeError): m.complete(messages=[], tools=[])
        self.assertEqual(m.attempts, 1)
        self.assertEqual(events[-1]['event'], 'request_failed')
        self.assertNotIn('secret-test', str(events))
