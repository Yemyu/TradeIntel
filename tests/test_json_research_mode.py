import json
import unittest
from src.tradeintel_ai.research_models import ResearchPlannerModel, JsonResearchModel
from src.tradeintel_ai.model_adapter import OpenAICompatibleConfig
from src.tradeintel_ai.policy_conditions import solar_output_schema


class JsonResearchModeTests(unittest.TestCase):
    def test_explicit_json_mode_not_strict_schema_claim(self):
        config = OpenAICompatibleConfig(base_url='https://example.invalid/v1', model='glm-4.7')
        model = JsonResearchModel(config)
        payload = model._payload(messages=[{'role':'user','content':'Return JSON'}],tools=[])
        self.assertEqual(payload['response_format'], {'type':'json_object'})
        self.assertNotIn('json_schema', payload)
        self.assertEqual(model.effective_request_settings()['response_format'], payload['response_format'])
        self.assertNotIn('response_format', ResearchPlannerModel(config)._payload(messages=[],tools=[]))
        with self.assertRaises(ValueError): model._payload(messages=[],tools=[{}])

    def test_schema_locks_codes_status_and_fields_without_answer_values(self):
        schema = solar_output_schema(['85414200','85414300'])
        array = schema['properties']['conditions']
        self.assertEqual(array['minItems'],10)
        self.assertEqual(array['maxItems'],10)
        item = array['items']
        self.assertEqual(item['properties']['status']['enum'],['supported','unknown'])
        self.assertFalse(item['additionalProperties'])
        self.assertNotIn('50%',json.dumps(schema))
        self.assertLess(len(json.dumps(schema)),2000)
        for codes in [[],['85414200','85414200'],['12345678']]:
            with self.assertRaises(ValueError): solar_output_schema(codes)
