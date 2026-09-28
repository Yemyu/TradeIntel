from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.freeze_g2_research import prepare, TASKS, estimate_tokens
from tradeintel_ai.business_evidence_view import build_view, restore
from tradeintel_ai.evidence_transport import unpack


class BusinessEvidenceViewTests(unittest.TestCase):
    def test_distinct_values_and_uncatalogued_urls_not_hidden(self):
        info = {'policy_id':'case','data_version':'v', 'request':{'month':'2026-06'},
                'sources':[{'id':'trade:abc','url':'https://example.test/a','sha256':'hash'}],
                'metrics':[{'id':'long-metric','value':0,'period':'2026-05','status':'unknown'}],
                'policy_facts':{'origin':'China','product_rates':[{'details':{'origin':'different',
                    'field_refs':{'origin':{'url':'https://example.test/unique','policy_id':'other'}}}}]}}
        before = deepcopy(info)
        packet,audit = build_view(info)
        model = unpack(packet)
        self.assertEqual(restore(packet,audit), before)
        self.assertEqual(info,before)
        detail=model['policy_facts']['product_rates'][0]['details']
        self.assertEqual(detail['origin'],'different')
        self.assertEqual(detail['field_refs']['origin']['url'],'https://example.test/unique')
        self.assertEqual(model['metrics'][0]['period'],'2026-05')
        self.assertNotIn('sha256',model['sources'][0])

    def test_all_frozen_candidates_same_information_and_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'preparation'
            result=prepare(root)
            self.assertEqual(result['status'],'inputs_prepared_runner_not_ready')
            self.assertFalse(result['live_execution_allowed'])
            manifest=json.loads((root/'manifest.json').read_text())
            self.assertEqual(len(manifest['schedule']),12)
            self.assertTrue(all(s['estimated_input_tokens']<=8000 for s in manifest['schedule']))
            for name,*_ in TASKS:
                folder=root/name
                read=lambda filename: json.loads((folder/filename).read_text())
                b,c=read('B.messages.json'),read('C.messages.json')
                self.assertEqual(b[1],c[1])
                restored=restore(json.loads(c[1]['content']),read('business-view-audit.json'))
                self.assertEqual(restored,read('unpacked-information.json'))
                self.assertNotIn('rubric',restored)
                self.assertNotIn('reference',restored)
                self.assertLessEqual(estimate_tokens(c),8000)
