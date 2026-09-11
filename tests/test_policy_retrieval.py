import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from tradeintel_ai.policy_retrieval import PolicyRetriever, build_corpus, draft_answer, scope_refusal
from tradeintel_ai.agent import ModelResponse, ModelToolCall


class PolicyRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = {'coverage': [], 'chunks':[
            {'id':'initial_notice:p1:c0', 'source':'initial_notice', 'published':'2018-06-20',
             'page':1, 'title':'fixture', 'text':'initial china july duties tariff effective consumption additional ad valorem duty percent', 'url':'https://example.invalid/initial.pdf'},
            {'id':'amendment_notice:p2:c0', 'source':'amendment_notice', 'published':'2018-08-16',
             'page':2, 'title':'fixture', 'text':'august china duties tariff effective additional', 'url':'https://example.invalid/amendment.pdf'}]}
        cls.retriever = PolicyRetriever(cls.corpus)

    def test_all_quotes_have_exact_page_offsets(self):
        if not (ROOT/'data/raw/policy/source_manifest.json').exists():
            self.skipTest('Local official PDF corpus has not been downloaded')
        corpus = build_corpus(ROOT)
        pages = {p['id']: p['text'] for p in corpus['pages']}
        self.assertEqual(len(pages), 5)
        for c in corpus['chunks']:
            self.assertEqual(c['text'], pages[c['page_id']][c['start']:c['end']])
            self.assertNotIn('NOPB', c['text'])

    def test_publication_cutoff(self):
        hits = self.retriever.search('第二批关税生效', as_of='2018-07-06')['hits']
        self.assertTrue(hits)
        self.assertTrue(all(h['source'] == 'initial_notice' for h in hits))
        self.assertEqual(self.retriever.search('关税', as_of='2018-06-01')['hits'], [])

    def test_scope_refusals(self):
        for question in ['现在第一批税率多少', '84414000适用吗', '8441.40.00的税率', '2019年豁免', 'latest tariffs']:
            self.assertIsNotNone(scope_refusal(question))
            self.assertEqual(self.retriever.search(question)['hits'], [])

    def test_unrelated_and_invalid_inputs(self):
        self.assertEqual(self.retriever.search('怎样制作草莓蛋糕')['hits'], [])
        for kwargs in [{'top_k':0}, {'top_k':True}, {'method':'dense'}, {'as_of':'not-date'}]:
            with self.assertRaises(ValueError): self.retriever.search('关税', **kwargs)

    def test_no_evidence_never_calls_model(self):
        model = Mock()
        self.assertFalse(draft_answer(model, {'hits':[]})['model_called'])
        model.complete.assert_not_called()

    def test_generated_draft_is_not_semantic_acceptance(self):
        retrieval = self.retriever.search('第一批税率', as_of='2018-07-06')
        model = Mock()
        model.complete.return_value = ModelResponse(text=json.dumps({'claims':[
            {'text':'这是需要核对的主张', 'citations':[retrieval['hits'][0]['id']]}]}))
        output = draft_answer(model, retrieval)
        self.assertEqual(output['status'], 'draft_requires_semantic_review')
        self.assertFalse(output['semantic_verified'])
        self.assertEqual(model.complete.call_count, 1)

    def test_invalid_outputs_not_published(self):
        retrieval = self.retriever.search('第一批税率')
        for payload in ['not json', 'null', '{}', '{"claims":{}}', '{"claims":[{"text":"错误","citations":["invented"]}]}', '{"claims":[{"text":"错误","citations":[]}]}']:
            model = Mock()
            model.complete.return_value = ModelResponse(text=payload)
            self.assertEqual(draft_answer(model,retrieval)['status'], 'rejected_model_output')
        model.complete.return_value = ModelResponse(text='{"claims":[]}', tool_calls=(ModelToolCall('1','x',{}),))
        self.assertEqual(draft_answer(model,retrieval)['status'], 'rejected_model_output')


if __name__ == '__main__': unittest.main()
