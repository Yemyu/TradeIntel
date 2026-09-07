import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import continue_live_evaluation as cont
from src.tradeintel_ai.agent import ModelResponse, ModelToolCall
from src.tradeintel_ai.model_adapter import OpenAICompatibleConfig, ModelAdapterError


class ContinuationTests(unittest.TestCase):
    def parent(self, path):
        plan = cont.live.run_evaluation()
        qs, _ = cont.live.load_question_set(cont.live.DEFAULT_FINAL_QUESTIONS)
        slots = list(cont.schedule(qs, 3, 301))
        rows = []
        for repeat, q, arm in slots[:151]:
            if not rows or (rows[-1]['repeat'], rows[-1]['id']) != (repeat, q['id']):
                rows.append({**q, 'repeat': repeat, 'systems': {}})
            rows[-1]['systems'][arm] = {'status': 'error', 'error': 'preserve me', 'trace': [], 'generation_complete': False}
        parent = {**plan, 'questions': rows, 'request_count': 207, 'seed': 301,
                  'status': 'stopped', 'configuration': {'requested_model': 'fixture', 'temperature': 0.,
                  'timeout_seconds': 60., 'endpoint_sha256': cont.live.hashlib.sha256(b'https://example.test/v1').hexdigest()}}
        path.write_text(json.dumps(parent), encoding='utf-8')
        return parent

    def config(self):
        return OpenAICompatibleConfig('https://example.test/v1', 'fixture', 'fixture-secret')

    def test_preserves_failures_and_finishes_exact_remaining_slots(self):
        def reply(model, *, messages, tools):
            if tools and len(messages) == 1:
                return ModelResponse(tool_calls=(ModelToolCall('p', 'get_policy_event', {}),), metadata={'finish_reason':'tool_calls'})
            return ModelResponse(text='2018年7月6日', metadata={'finish_reason':'stop'})
        with TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            p, out = Path(d)/'old.json', Path(d)/'new.json'
            before = self.parent(p)
            old_bytes = p.read_bytes()
            with patch.object(cont.OpenAICompatibleModel, 'complete', reply):
                result = cont.collect(p, execute=True, config=self.config(), output=out)
            self.assertEqual(result['recorded'], 360)
            self.assertEqual(result['status'], 'collected_not_scored')
            merged, _, all_records = cont.prepare(out)
            self.assertEqual(len(all_records), 360)
            for row in before['questions']:
                for arm, value in row['systems'].items():
                    self.assertEqual(all_records[(row['repeat'],row['id'],arm)], value)
            self.assertEqual(old_bytes, p.read_bytes())
            self.assertFalse(merged['model_adopted'])
            self.assertNotIn('fixture-secret', out.read_text()+out.with_suffix('.jsonl').read_text())

    def test_cooldowns_are_bounded_and_stopped_file_can_resume(self):
        with TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            p, out = Path(d)/'old.json', Path(d)/'new.json'
            self.parent(p)
            with patch.object(cont.OpenAICompatibleModel, 'complete', side_effect=ModelAdapterError('timeout')), patch.object(cont.time, 'sleep') as sleep:
                result = cont.collect(p, execute=True, config=self.config(), output=out, pause=sleep)
            self.assertEqual(result['status'], 'stopped')
            self.assertEqual(result['recorded'], 160)
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(cont.collect(out)['remaining'], 200)

    def test_rejects_nonprefix_and_changed_provider_without_request(self):
        with TemporaryDirectory() as d:
            p = Path(d)/'old.json'
            before = self.parent(p)
            wrong = OpenAICompatibleConfig('https://example.test/v1', 'different')
            with self.assertRaises(ValueError):
                cont.collect(p, execute=True, config=wrong)
            changed = deepcopy(before)
            changed['questions'][0]['systems'].pop(next(iter(changed['questions'][0]['systems'])))
            p.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                cont.prepare(p)

    def test_ctrl_c_retains_report_and_prior_slots(self):
        with TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            p, out = Path(d)/'old.json', Path(d)/'new.json'
            self.parent(p)
            with patch.object(cont.OpenAICompatibleModel, 'complete', side_effect=KeyboardInterrupt):
                result = cont.collect(p, execute=True, config=self.config(), output=out)
            self.assertEqual(result['status'], 'interrupted')
            self.assertEqual(cont.collect(out)['remaining'], 208)
