import copy
import json
import unittest

from tradeintel_ai.bounded_explanation import slots, messages, parse
from tradeintel_ai.brief_business_view import restore, build_view, business_payload
from tests.test_evidence_linked_brief import catalog


class BoundedExplanationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = catalog()
        self.answer = {'interpretations': {k: '金额与来源份额反映不同侧面，不能仅凭排名推断替代能力。'
                                           for k in slots(self.catalog)},
                       'missing_evidence': '供应商产能与产品规格可比性尚需核实。',
                       'question': '哪些产品存在可行的替代供应？'}

    def parse(self, value):
        return parse(json.dumps(value, ensure_ascii=False), self.catalog)

    def test_host_bindings_and_no_approval(self):
        result = self.parse(self.answer)
        self.assertFalse(result['approved'])
        self.assertEqual(len(result['answer']['findings']), len(slots(self.catalog)))
        for row in result['answer']['findings']:
            self.assertTrue(row['policy_refs'])
        self.assertTrue(result['validation']['task_coverage']['structural_coverage_complete'])

    def test_model_cannot_override_bindings(self):
        for key in ('fact_ids', 'policy_refs', 'catalog_sha256'):
            bad = copy.deepcopy(self.answer); bad[key] = []
            with self.assertRaises(ValueError): self.parse(bad)

    def test_wrong_total_is_rejected_not_repaired(self):
        for text in ('两个合计占96.5025%。', '合计百分之九十六。'):
            bad = copy.deepcopy(self.answer); bad['interpretations']['slot1'] = text
            with self.assertRaises(ValueError): self.parse(bad)

    def test_policy_missing_claim_requires_revision(self):
        self.answer['missing_evidence'] = '缺少其余商品的政策原文。'
        self.assertEqual(self.parse(self.answer)['status'], 'needs_revision')

    def test_semantic_error_without_digits_is_not_claimed_detected(self):
        self.answer['interpretations']['slot1'] = '两项合计等于单项份额。'
        self.assertFalse(self.parse(self.answer)['approved'])

    def test_malformed_duplicate_keys_and_slots(self):
        for raw in ('{"interpretations":', '{"x":1,"x":2}'):
            with self.assertRaises(ValueError): parse(raw, self.catalog)
        for change in ('missing', 'extra', 'empty'):
            bad = copy.deepcopy(self.answer)
            if change == 'missing': bad['interpretations'].pop('slot1')
            elif change == 'extra': bad['interpretations']['invented'] = '解释'
            else: bad['interpretations']['slot1'] = ''
            with self.assertRaises(ValueError): self.parse(bad)

    def test_all_evidence_preserved_and_aliases_known(self):
        request = messages('解释差异', self.catalog)
        body = json.loads(request[1]['content'])
        view, sidecar = build_view('解释差异', self.catalog, deduplicate=True)
        self.assertEqual(body['evidence'], view)
        self.assertEqual(restore(view, sidecar), business_payload(self.catalog))
        known = set(sidecar['id_map'].values())
        for slot in body['slots'].values():
            self.assertTrue(set(slot['fact_ids']) <= known)
