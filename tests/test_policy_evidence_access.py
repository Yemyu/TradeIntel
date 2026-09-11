import hashlib
import unittest
from copy import deepcopy
from pathlib import Path

from tradeintel_ai.policy_evidence_access import PolicyRetriever, expand_context
from tradeintel_ai.policy_workflow import load_frozen_corpus


class EvidenceAccessTests(unittest.TestCase):
    def test_historical_prefix_preserves_question_and_current_refusal(self):
        corpus = load_frozen_corpus(Path(__file__).resolve().parents[1])
        retriever = PolicyRetriever(corpus)
        q = '目前请分析2018年第一批关税何时生效？'
        result = retriever.search(q, as_of='2018-07-06')
        self.assertTrue(result['hits'])
        self.assertEqual(result['question'], q)
        for q in ('2018年关税目前还有效吗？', '目前请分析2018年关税的最新税率',
                  '目前请分析2018年至2019年的修订'):
            self.assertFalse(retriever.search(q, as_of='2018-07-06')['hits'])

    def test_merge_keeps_text_coverage_parents_and_hash(self):
        text = ''.join(str(i % 10) for i in range(2200))
        chunks = [{'id': name, 'page_id': 'p', 'start': start, 'end': end,
                   'text': text[start:end]} for name, start, end in
                  [('a', 0, 1200), ('b', 1000, 2200)]]
        corpus = {'pages': [{'id': 'p', 'text': text}], 'chunks': chunks}
        retrieval = {'hits': deepcopy(chunks), 'status': 'candidate_evidence'}
        result = expand_context(retrieval, corpus)
        self.assertEqual(len(result['hits']), 1)
        hit = result['hits'][0]
        self.assertEqual(hit['text'], text)
        self.assertEqual([p['chunk_id'] for p in hit['parents']], ['a', 'b'])
        self.assertEqual(hit['text_sha256'], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(result['context_expansion']['duplicated_chars'], 0)
        self.assertEqual(retrieval['hits'], chunks)

    def test_oversized_union_is_not_merged(self):
        text = 'x' * 3200
        chunks = [{'id': name, 'page_id': 'p', 'start': start, 'end': end,
                   'text': text[start:end]} for name, start, end in
                  [('a', 0, 1200), ('b', 2000, 3200)]]
        result = expand_context({'hits': chunks},
                                {'pages': [{'id': 'p', 'text': text}], 'chunks': chunks})
        self.assertEqual(len(result['hits']), 2)
        self.assertTrue(all(len(h['text']) <= 2400 for h in result['hits']))
