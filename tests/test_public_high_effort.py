import copy
import json
import unittest

from scripts import run_public_brief_eval as runner


class HighEffortTests(unittest.TestCase):
    def provider(self):
        matrix = json.loads(runner.DEFAULT_MATRIX.read_text())
        p = copy.deepcopy(next(x for x in matrix['candidates'] if x['id'] == 'deepseek-flash'))
        p['reasoning_effort'] = 'high'
        p['request_params']['reasoning_effort'] = 'high'
        return p

    def test_high_survives_payload(self):
        p = runner._validate_provider(self.provider())
        client = runner._PublicEvalModel(runner.OpenAICompatibleConfig(p['base_url'], p['model_id'], 'fixture'), request_params=p['request_params'])
        self.assertEqual(client._payload(messages=[{'role':'user','content':'test'}], tools=[])['reasoning_effort'], 'high')

    def test_mislabel_rejected(self):
        p = self.provider()
        p['request_params']['reasoning_effort'] = 'low'
        with self.assertRaisesRegex(ValueError, '不一致'):
            runner._validate_provider(p)

    def test_glm_and_disabled_and_unapproved_effort_rejected(self):
        for field,value in [('provider','zhipu'),('thinking',{'type':'disabled'}),('reasoning_effort','max')]:
            p = self.provider()
            if field == 'provider': p[field] = value
            else: p['request_params'][field] = value
            with self.assertRaises(ValueError): runner._validate_provider(p)
