import copy
import json
from pathlib import Path
import unittest
from src.tradeintel_ai.policy_conditions import validate_solar_choices, normalize_solar_choices


class SolarSourceChoiceTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.hits = json.loads((root/'data/candidates/solar2024/policy_corpus.json').read_text())['chunks']
        sources = {'product_scope':'products', 'additional_duty':'rate',
                   'effective_conditions':'scope_and_effective', 'origin_scope':'scope_and_effective',
                   'general_conditions':'general_conditions'}
        self.answer = {'conditions':[{'hts8':'85414200','field':field,'status':'supported',
            'text':'测试说明，不代表语义正确','citation':'fr202421217:'+source}
            for field,source in sources.items()]}

    def validate(self, answer):
        return validate_solar_choices(answer, ['85414200'], self.hits)

    def test_binds_unmodified_full_source_without_claiming_quote_accuracy(self):
        before = copy.deepcopy(self.answer)
        _, coverage = self.validate(self.answer)
        self.assertEqual(coverage['contract_version'], 'solar-source-choice-v1.1')
        self.assertFalse(coverage['semantic_approval'])
        self.assertFalse(coverage['model_quote_verified'])
        refs = {h['id']:h['text'] for h in self.hits}
        for binding in coverage['source_bindings']:
            self.assertEqual(binding['source_text'], refs[binding['citation']])
        self.assertEqual(before, self.answer)

    def test_wrong_source_unknown_id_extra_quote_and_missing_fields_rejected(self):
        for mutate in [lambda a:a['conditions'][1].update(citation='fr202421217:products'),
                       lambda a:a['conditions'][1].update(citation='invented'),
                       lambda a:a['conditions'][1].update(quote='fabricated'),
                       lambda a:a['conditions'].pop()]:
            answer = copy.deepcopy(self.answer); mutate(answer)
            with self.assertRaises(ValueError): self.validate(answer)

    def test_unknown_keeps_missing_evidence_visible(self):
        self.answer['conditions'][-1].update(status='unknown', citation='', text='仍需核查一般限定')
        _, coverage = self.validate(self.answer)
        self.assertEqual(coverage['status'], 'needs_evidence')
        self.assertEqual(len(coverage['source_bindings']),4)

    def test_valid_source_does_not_approve_false_chinese_claim(self):
        self.answer['conditions'][1]['text'] = '这是最终综合税率。'
        _, coverage = self.validate(self.answer)
        self.assertFalse(coverage['semantic_approval'])

    def test_grouped_multiple_products_are_lossless(self):
        group = {row['field']:copy.deepcopy(row) for row in self.answer['conditions']}
        second = copy.deepcopy(group)
        for row in second.values(): row['hts8'] = '85414300'
        second['general_conditions'].update(status='unknown', citation='', text='待核查')
        before = copy.deepcopy([group, second])
        rows, records = normalize_solar_choices([group, second])
        self.assertEqual(rows, list(group.values()) + list(second.values()))
        self.assertEqual(before, [group, second])
        self.assertEqual(len(records),2)
        _, coverage = validate_solar_choices({'conditions':[group,second]}, ['85414200','85414300'], self.hits)
        self.assertEqual(coverage['status'],'needs_evidence')

    def test_group_conflicts_and_mixed_shapes_are_rejected(self):
        original = {r['field']:copy.deepcopy(r) for r in self.answer['conditions']}
        for mutate in [lambda g:g['origin_scope'].update(field='product_scope'),
                       lambda g:g['origin_scope'].update(hts8='85414300'),
                       lambda g:g.pop('origin_scope'),
                       lambda g:g['origin_scope'].update(quote='fake'),
                       lambda g:g['origin_scope'].update(text=None)]:
            group = copy.deepcopy(original); mutate(group)
            with self.assertRaises(ValueError): normalize_solar_choices([group])
        with self.assertRaises(ValueError):
            normalize_solar_choices([original, self.answer['conditions'][0]])
        with self.assertRaises(ValueError):
            validate_solar_choices({'conditions':[original, original]}, ['85414200'], self.hits)
