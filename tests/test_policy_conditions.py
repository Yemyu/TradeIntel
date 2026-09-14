import copy
import unittest
from src.tradeintel_ai.policy_conditions import validate_conditions, FIELDS


def conditions_fixture(code='12345678', source='fixture:p1', quote='China goods 1234.56.78, subject to conditions.'):
    return {'conditions':[{'hts8':code,'field':field,'status':'supported','text':'测试条件',
                           'citation':source,'quote':quote} for field in FIELDS]}


class PolicyConditionsTests(unittest.TestCase):
    def test_whitespace_alignment_requires_unique_unchanged_text(self):
        source = 'China goods 1234.56.78, subject to conditions.\nEffective  on January 1.'
        answer = conditions_fixture()
        answer['conditions'][1]['quote'] = 'Effective on January 1.'
        hits = [{'id':'fixture:p1','text':source}]
        _, coverage = validate_conditions(answer, ['12345678'], hits)
        record = coverage['normalizations'][0]
        self.assertEqual(record['source_quote'], 'Effective  on January 1.')
        self.assertEqual(source[record['source_start']:record['source_end']], record['source_quote'])
        for altered in ['Effective on January 2.', 'Effective on January 1!']:
            answer['conditions'][1]['quote'] = altered
            with self.assertRaises(ValueError): validate_conditions(answer, ['12345678'], hits)
        answer['conditions'][1]['quote'] = 'Effective on January 1.'
        hits[0]['text'] = source + '\nEffective  on January 1.'
        with self.assertRaises(ValueError): validate_conditions(answer, ['12345678'], hits)

    def test_table_dot_leaders_are_not_ten_digit_codes(self):
        for text, accepted in [('8541.43.00.....  Photovoltaic cells', True),
                               ('8541.43.00.10  Extended code', False),
                               ('8541430010 Extended code', False)]:
            answer = conditions_fixture('85414300', quote=text)
            hits = [{'id':'fixture:p1','text':text}]
            if accepted:
                validate_conditions(answer, ['85414300'], hits)
            else:
                with self.assertRaises(ValueError):
                    validate_conditions(answer, ['85414300'], hits)

    def setUp(self):
        self.hits=[{'id':'fixture:p1','text':'China goods 1234.56.78, subject to conditions.'}]
        self.answer=conditions_fixture()

    def test_complete_is_not_semantic_approval(self):
        claims, coverage=validate_conditions(self.answer,['12345678'],self.hits)
        self.assertEqual(len(claims),3)
        self.assertFalse(coverage['semantic_approval'])

    def test_missing_duplicate_or_other_product_rejected(self):
        for mutate in [lambda a:a['conditions'].pop(),
                       lambda a:a['conditions'].append(a['conditions'][0]),
                       lambda a:a['conditions'][0].update(hts8='87654321')]:
            answer=copy.deepcopy(self.answer);mutate(answer)
            with self.assertRaises(ValueError):validate_conditions(answer,['12345678'],self.hits)

    def test_invented_or_abbreviated_quote_rejected(self):
        for quote in ['invented','1234.56.78']:
            answer=copy.deepcopy(self.answer);answer['conditions'][0]['quote']=quote
            with self.assertRaises(ValueError):validate_conditions(answer,['12345678'],self.hits)

    def test_unknown_explicit_not_false_success(self):
        self.answer['conditions'][0].update(status='unknown',citation='',quote='',text='缺商品描述证据')
        claims, coverage=validate_conditions(self.answer,['12345678'],self.hits)
        self.assertEqual(len(claims),2)
        self.assertEqual(coverage['status'],'needs_evidence')
        self.assertEqual(coverage['unknown'][0]['field'],'product_scope')

    def test_exact_grouped_representation_and_recorded_conversion(self):
        grouped={'hts8':'12345678'}
        for row in self.answer['conditions']:
            grouped[row['field']]={k:v for k,v in row.items() if k!='hts8'}
        answer={'conditions':[grouped]}; before=copy.deepcopy(answer)
        claims, coverage=validate_conditions(answer,['12345678'],self.hits)
        self.assertEqual(len(claims),3)
        self.assertEqual(coverage['normalizations'][0]['kind'],'grouped_conditions_to_rows')
        self.assertEqual(answer,before)
        grouped['product_scope']['field']='additional_duty'
        with self.assertRaises(ValueError):validate_conditions(answer,['12345678'],self.hits)

    def test_literal_newline_only_when_exact_source_match(self):
        self.hits[0]['text'] += '\nSecond line'
        self.answer['conditions'][1]['quote']=self.hits[0]['text'].replace('\n','\\n')
        _, coverage=validate_conditions(self.answer,['12345678'],self.hits)
        self.assertEqual(coverage['normalizations'][0]['kind'],'escaped_newline_to_source_newline')
        self.answer['conditions'][1]['quote']+=' invented'
        with self.assertRaises(ValueError):validate_conditions(self.answer,['12345678'],self.hits)
