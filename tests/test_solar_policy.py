import json
from pathlib import Path
import tempfile
import unittest
import shutil
from src.tradeintel_ai.solar_policy import build_corpus, retrieve_solar_policy, BASE

ROOT = Path(__file__).resolve().parents[1]

class SolarPolicyTests(unittest.TestCase):
    def test_all_sections_and_exact_product_scope(self):
        corpus=build_corpus(ROOT)
        self.assertEqual(len(corpus['chunks']),4)
        by_id={c['id'].split(':')[1]:c['text'] for c in corpus['chunks']}
        self.assertIn('8541.42.00',by_id['products'])
        self.assertIn('8541.43.00',by_id['products'])
        self.assertIn('+ 50%',by_id['rate'])
        self.assertIn('chapter 98',by_id['general_conditions'])
        self.assertIn('eastern daylight time',by_id['scope_and_effective'])
        result=retrieve_solar_policy(ROOT,'解释85414200存档条款',as_of='2025-01-01')
        self.assertEqual(len(result['hits']),4)

    def test_cross_case_current_and_cutoff_rejected(self):
        for question,day in [('解释38180000','2025-01-01'),('最新85414300税率','2026-01-01'),('解释85414200','2024-09-17')]:
            result=retrieve_solar_policy(ROOT,question,as_of=day)
            self.assertEqual(result['hits'],[])

    def test_index_or_original_changes_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            shutil.copytree(ROOT/BASE,root/BASE,ignore=shutil.ignore_patterns('monthly','manifest.json','window_validation*'))
            path=root/BASE/'policy_corpus.json'
            corpus=json.loads(path.read_text());corpus['chunks'].pop()
            path.write_text(json.dumps(corpus))
            with self.assertRaises(ValueError):retrieve_solar_policy(root,'85414200',as_of='2025-01-01')
            source=root/BASE/'2024-21217.html'
            source.write_bytes(source.read_bytes()+b'changed')
            with self.assertRaises(ValueError):build_corpus(root)
