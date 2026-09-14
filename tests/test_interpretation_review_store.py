from pathlib import Path
import tempfile
import unittest
from tradeintel_ai.interpretation_review_store import packet, submit, FILES

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'tmp/trade-aware-interpretation-v1-first/run'

class ReviewStoreTests(unittest.TestCase):
    def copy(self,root):
        for name in FILES: (root/name).write_bytes((SOURCE/name).read_bytes())
    def payload(self,root):
        return {'fingerprint':packet(root)['fingerprint'],'reviewer':'test-reviewer','facts_checked':True,
                'decisions':[{'index':0,'verdict':'reject','reason':'No evidence for priority'},
                             {'index':1,'verdict':'accept','reason':'Separates actual tax from trade totals'}]}
    def test_bound_decisions_and_no_publication(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.copy(root)
            before={name:(root/name).read_bytes() for name in FILES}
            result=submit(root,self.payload(root))
            self.assertEqual(result['status'],'recorded')
            self.assertTrue(result['decision']['eligible_for_reviewed_draft'])
            self.assertFalse(result['decision']['case_publication_allowed'])
            self.assertEqual(before,{name:(root/name).read_bytes() for name in FILES})
            (root/'source-packet.zh-CN.md').write_text('changed')
            self.assertEqual(packet(root)['status'],'stale')
    def test_reject_stale_incomplete_and_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.copy(root)
            payload=self.payload(root)
            for altered in [{**payload,'fingerprint':'wrong'}, {**payload,'decisions':[]}, {**payload,'facts_checked':'yes'}]:
                with self.assertRaises(ValueError):submit(root,altered)
            self.assertFalse((root/'human-interpretation-review.json').exists())
            submit(root,payload)
            with self.assertRaises(Exception):submit(root,{**payload,'reviewer':'another'})
    def test_unfinished_or_all_rejected_not_draft_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.copy(root)
            payload=self.payload(root);payload['facts_checked']=False
            result=submit(root,payload)
            self.assertFalse(result['decision']['eligible_for_reviewed_draft'])
