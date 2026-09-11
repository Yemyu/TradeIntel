import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.policy_response_format import normalize_policy_response


class PolicyFormatTests(unittest.TestCase):
    def test_whole_fence_only(self):
        text='{"claims":[{"text":"原主张","citations":["exact-id"]}]}'
        result=normalize_policy_response(ModelResponse(text='```json\n'+text+'\n```'))
        self.assertEqual(result.text,text)

    def test_surrounding_prose_not_extracted(self):
        result=normalize_policy_response(ModelResponse(text='说明\n```json\n{"claims":[]}\n```'))
        self.assertEqual(result.text,'')

    def test_duplicate_keys_and_nonstandard_values_rejected(self):
        for text in ['{"claims":[],"claims":[]}','{"claims":NaN}','{"claims":[{"text":"x","text":"y"}]}']:
            self.assertEqual(normalize_policy_response(ModelResponse(text=text)).text,'')

    def test_truncation_not_repaired(self):
        raw=ModelResponse(text='```json\n{"claims":[]}\n```',metadata={'finish_reason':'length'})
        self.assertEqual(normalize_policy_response(raw).text,'')

    def test_plain_json_unchanged(self):
        self.assertEqual(normalize_policy_response(ModelResponse(text='{"claims":[]}')).text,'{"claims":[]}')
