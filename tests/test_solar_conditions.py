import copy
import unittest
from src.tradeintel_ai.policy_conditions import validate_conditions, SOLAR_FIELDS, contract_for_policy

POLICY = 'us_301_solar2024'


class SolarConditionsTests(unittest.TestCase):
    def setUp(self):
        self.hits = [
            {'id':'scope','text':'8541.43.00..... Cells. Products of China.'},
            {'id':'fr202421217:general_conditions','text':'General duties and exceptions apply.'}]
        self.answer = {'conditions':[
            {'hts8':'85414300','field':field,'status':'supported','text':'待人工核查的说明',
             'citation':self.hits[1 if field == 'general_conditions' else 0]['id'],
             'quote':self.hits[1 if field == 'general_conditions' else 0]['text']}
            for field in SOLAR_FIELDS]}

    def validate(self, answer):
        return validate_conditions(answer, ['85414300'], self.hits, policy_id=POLICY)

    def test_requires_five_fields_without_auto_approval(self):
        _, coverage = self.validate(self.answer)
        self.assertEqual(coverage['expected_conditions'], 5)
        self.assertEqual(coverage['contract_version'], 'solar-five-fields-v1')
        self.assertFalse(coverage['semantic_approval'])
        old = copy.deepcopy(self.answer); old['conditions'] = old['conditions'][:3]
        with self.assertRaises(ValueError): self.validate(old)
        self.assertIn('分别返回五项', contract_for_policy(POLICY))

    def test_wrong_origin_quote_or_general_source_rejected(self):
        answer = copy.deepcopy(self.answer)
        answer['conditions'][3]['quote'] = 'Cells.'
        with self.assertRaises(ValueError): self.validate(answer)
        answer = copy.deepcopy(self.answer)
        answer['conditions'][4].update(citation='scope', quote=self.hits[0]['text'])
        with self.assertRaises(ValueError): self.validate(answer)

    def test_unknown_is_explicit_and_not_success(self):
        answer = copy.deepcopy(self.answer)
        for row in answer['conditions'][3:]:
            row.update(status='unknown', text='适用范围仍需补核', citation='', quote='')
        claims, coverage = self.validate(answer)
        self.assertEqual(len(claims), 3)
        self.assertEqual(coverage['status'], 'needs_evidence')
        self.assertEqual(len(coverage['unknown']), 2)

    def test_grouped_five_fields_preserve_contract(self):
        grouped = {'hts8':'85414300'}
        for row in self.answer['conditions']:
            grouped[row['field']] = {k:v for k,v in row.items() if k != 'hts8'}
        _, coverage = self.validate({'conditions':[grouped]})
        self.assertEqual(coverage['expected_conditions'], 5)
