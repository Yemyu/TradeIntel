import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from src.tradeintel_ai.exposure_policy import retrieve_exposure_policy
from src.tradeintel_ai.policy_retrieval import PolicyRetriever


class ExposurePolicyTests(unittest.TestCase):
    def test_registered_corpus_preserves_rate_code_groups(self):
        root = Path(__file__).resolve().parents[1]
        result = retrieve_exposure_policy(root, '登记政策税率和生效时间', as_of='2026-09-14')
        self.assertEqual(len(result['hits']), 3)
        texts = [h['text'] for h in result['hits']]
        self.assertTrue(any('50 percent' in t and '2804.61.00' in t and '3818.00.00' in t for t in texts))
        self.assertTrue(any('25 percent' in t and '8101.99.10' in t and 'sintering' in t for t in texts))
        self.assertFalse(any('100 percent' in t for t in texts))

    def test_retrieval_scope_dates_and_source_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / 'notice.html'
            text = 'Tungsten 8101.99.10 additional duty effective January 1 2025.'
            raw.write_text('<p>' + text + '</p>')
            chunk = {'id': 'cbp:p0', 'text': text, 'paragraph_index': 0,
                     'published': '2024-12-31', 'page': 1, 'url': 'https://example.test/notice',
                     'citation_url': 'https://example.test/notice', 'local_path': 'notice.html',
                     'sha256': hashlib.sha256(raw.read_bytes()).hexdigest()}
            corpus = {'chunks': [chunk], 'coverage': [], 'limitations': ['new-case limit']}
            path = root / 'data/processed/policy_exposure/policy_corpus.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(corpus))
            self.assertEqual(retrieve_exposure_policy(root, '81019910 生效', as_of='2026-09-14')['status'], 'candidate_evidence')
            self.assertEqual(retrieve_exposure_policy(root, '81019910 生效', as_of='2024-12-30')['hits'], [])
            self.assertEqual(retrieve_exposure_policy(root, '99999999 税率', as_of='2026-09-14')['hits'], [])
            self.assertEqual(retrieve_exposure_policy(root, '今天税率', as_of='2026-09-14')['hits'], [])
            self.assertEqual(PolicyRetriever(corpus).search('2025 税率')['hits'], [])
            chunk['text'] = 'invented policy'
            path.write_text(json.dumps(corpus))
            with self.assertRaises(ValueError):
                retrieve_exposure_policy(root, '税率', as_of='2026-09-14')
