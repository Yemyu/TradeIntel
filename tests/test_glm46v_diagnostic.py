import io
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from scripts.run_glm46v_diagnostic import run


class GlmDiagnosticTests(unittest.TestCase):
    def perform(self, opener):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'run.json'
            result = run(execute=True, api_key='test-key-secret', output=output, opener=opener)
            report = json.loads(output.read_text())
            journal = [json.loads(line) for line in output.with_suffix('.jsonl').read_text().splitlines()]
            with self.assertRaises(ValueError):
                run(execute=True, api_key='test-key-secret', output=output, opener=opener)
            return result, report, journal

    def test_http_to_parser_retains_json_failure_and_responses(self):
        payloads = []
        def opener(request, **kwargs):
            payload = json.loads(request.data)
            payloads.append(payload)
            self.assertEqual(payload['model'], 'glm-4.6v')
            self.assertNotIn('tools', payload)
            self.assertEqual(len(payload['messages']), 2)
            return io.BytesIO(json.dumps({'choices':[{'finish_reason':'stop', 'message':
                {'role':'assistant','content':'```json\n{}\n``` test-key-secret', 'reasoning_content':'audit-only'}}]}).encode())
        result, report, events = self.perform(opener)
        self.assertEqual(len(payloads), 3)
        self.assertEqual(result['api_requests'], 3)
        self.assertEqual(result['status'], 'collected_not_scored')
        self.assertTrue(all(q['diagnostic']['stage']=='json_decode' for q in report['questions']))
        self.assertEqual([e['item'] for e in events if e['event']=='answer_recorded'], report['questions'])
        self.assertEqual(events[-1]['event'], 'run_finished')
        self.assertNotIn('test-key-secret', json.dumps(events))
        self.assertEqual(len([e for e in events if e['event']=='http_response']), 3)
        self.assertIn('reasoning_content', json.dumps(events))

    def test_http_error_counted_and_stops_once(self):
        def opener(request, **kwargs):
            raise HTTPError(request.full_url, 401, 'test-key-secret', {}, None)
        result, report, events = self.perform(opener)
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(result['api_requests'], 1)
        self.assertNotIn('test-key-secret', json.dumps(events))

    def test_interrupt_preserves_attempt_and_finished_marker(self):
        def opener(*args, **kwargs): raise KeyboardInterrupt
        result, report, events = self.perform(opener)
        self.assertEqual(result['status'], 'interrupted')
        self.assertEqual(result['api_requests'], 1)
        self.assertEqual(events[-1]['status'], 'interrupted')

    def test_valid_response_is_replayable(self):
        from src.tradeintel_ai.intent_proposal import propose_intent
        from scripts.check_intent_development import RecordedModel
        def opener(*args, **kwargs):
            return io.BytesIO(json.dumps({'choices':[{'finish_reason':'stop', 'message':{'role':'assistant',
              'content':json.dumps({'status':'clarify','request':None,'evidence':{},'missing':['scope']})}}]}).encode())
        result, report, events = self.perform(opener)
        for q in report['questions']:
            self.assertEqual(propose_intent(q['question'], RecordedModel(q['response'])), q['result'])
            self.assertEqual(q['diagnostic']['stage'], 'valid_clarification')

    def test_extra_tool_request_stops_without_execution(self):
        def opener(*args, **kwargs):
            return io.BytesIO(json.dumps({'choices':[{'finish_reason':'tool_calls','message':{'content':'',
                'tool_calls':[{'id':'x','type':'function','function':{'name':'delete','arguments':'{}'}}]}}]}).encode())
        result, report, events = self.perform(opener)
        self.assertEqual(result['api_requests'], 1)
        self.assertEqual(result['status'], 'stopped')
        self.assertFalse(report['questions'][0]['result']['executed'])


if __name__ == '__main__': unittest.main()
