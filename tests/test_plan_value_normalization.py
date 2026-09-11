import json
import unittest

from src.tradeintel_ai.plan_value_normalization import literal_months, normalize_plan_values


class NormalizationTests(unittest.TestCase):
    def convert(self, fields, evidence, question):
        obj = {'steps': [{'request': {'task': 'trade', 'request': fields}, 'evidence': evidence}]}
        raw = {'text': json.dumps(obj), 'metadata': {'finish_reason': 'stop'}}
        response, _ = normalize_plan_values(raw, question)
        result = json.loads(response.text)['steps'][0]
        self.assertEqual(result['evidence'], evidence)
        return result['request']['request']

    def test_shared_year(self):
        self.assertEqual(literal_months('2018年9月与10月')['2018年10月'], '2018-10')

    def test_ambiguous_invalid_and_ranges_unchanged(self):
        for quote in ['去年9月', '2018年9月至10月', '2018年12月与1月',
                      '2018年13月', '0000年1月', '不是2018年9月', '2018年9月，次年10月']:
            self.assertEqual(literal_months(quote), {}, quote)

    def test_explicit_cross_year(self):
        self.assertEqual(literal_months('2018年12月与2019年1月')['2019年1月'], '2019-01')

    def test_order_duplicates_and_unmentioned_values_preserved(self):
        result = self.convert({'months': ['2018年10月', '2018年9月', '2018年9月', '2019年1月']},
                              {'request.months': '2018年9月与10月'}, '查询2018年9月与10月')
        self.assertEqual(result['months'], ['2018-10', '2018-09', '2018-09', '2019年1月'])

    def test_forged_quote_not_converted(self):
        fields = {'months': ['2018年10月'], 'operation': '只读查'}
        self.assertEqual(self.convert(fields, {'request.months': '2018年9月与10月',
                                              'request.operation': '只读查'}, '无这些原文'), fields)

    def test_country_not_broadened(self):
        for value, expected in [('日本', 'Japan'), ('德国', 'Germany'), ('法国', '法国'),
                                ('除中国外其他原产地合计', 'other_origins')]:
            self.assertEqual(self.convert({'origin': value}, {'request.origin': value}, value)['origin'], expected)

    def test_operation_and_scope_guards(self):
        for value in ['删除', '写入']:
            self.assertEqual(self.convert({'operation': value}, {'request.operation': value}, value)['operation'], value)
        fields = {'granularity': '整体范围', 'policy_id': 'us_301_list1_2018', 'hs6': '123456'}
        self.assertEqual(self.convert(fields, {'request.granularity': '整体范围'}, '整体范围'), fields)

    def test_read_alias(self):
        self.assertEqual(self.convert({'operation': '只读查'}, {'request.operation': '只读查'}, '只读查')['operation'], 'read')
