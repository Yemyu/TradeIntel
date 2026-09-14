import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from pathlib import Path
from tradeintel_ai.interpretation_review_store import FILES, packet, submit, reviewed_draft
from tradeintel_ai.host_review import _publish

SOURCE=Path(__file__).resolve().parents[1]/'tmp/trade-aware-interpretation-v1-first/run'


class ReviewRevisionTests(unittest.TestCase):
    def prepare(self, root):
        for name in FILES:
            (root/name).write_bytes((SOURCE/name).read_bytes())
        return {'fingerprint':packet(root)['fingerprint'],'reviewer':'fixture','facts_checked':True,
                'decisions':[{'index':0,'verdict':'reject','reason':'unsupported'},
                             {'index':1,'verdict':'needs_revision','reason':'check source'}]}

    def revision(self, root, payload):
        return {**payload,'base_review_digest':packet(root)['review_digest'],
                'change_reason':'核对原文后重新判断'}

    def test_latest_decision_controls_export_and_history_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);payload=self.prepare(root);submit(root,payload)
            original=(root/'human-interpretation-review.json').read_bytes()
            revised=self.revision(root,payload)
            revised['decisions'][1]={'index':1,'verdict':'accept','reason':'source checked'}
            result=submit(root,revised)
            self.assertEqual(result['revision'],2)
            self.assertEqual(result['history'][0]['decisions'][1]['verdict'],'needs_revision')
            self.assertIn('审阅版本：2',reviewed_draft(root))
            second=(root/'human-interpretation-review.000002.json').read_bytes()
            revoked=self.revision(root,payload)
            revoked['decisions'][1]={'index':1,'verdict':'reject','reason':'withdraw acceptance'}
            submit(root,revoked)
            with self.assertRaises(ValueError):reviewed_draft(root)
            self.assertEqual(original,(root/'human-interpretation-review.json').read_bytes())
            self.assertEqual(second,(root/'human-interpretation-review.000002.json').read_bytes())
            self.assertEqual(packet(root)['revision'],3)

    def test_stale_edit_and_changed_evidence_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);payload=self.prepare(root);submit(root,payload)
            revised=self.revision(root,payload)
            with self.assertRaises(ValueError):submit(root,{**revised,'change_reason':' '})
            submit(root,revised)
            with self.assertRaises(ValueError):submit(root,revised)
            newest=self.revision(root,payload)
            (root/'source-packet.zh-CN.md').write_text('changed')
            with self.assertRaises(ValueError):submit(root,newest)
            self.assertFalse((root/'human-interpretation-review.000003.json').exists())

    def test_corrupted_history_cannot_silently_select_latest(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);payload=self.prepare(root);submit(root,payload)
            submit(root,self.revision(root,payload))
            original=root/'human-interpretation-review.json'
            record=json.loads(original.read_text());record['reviewer']='changed'
            original.write_text(json.dumps(record))
            with self.assertRaises(ValueError):packet(root)

    def test_simultaneous_revisions_cannot_overwrite_each_other(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);payload=self.prepare(root);submit(root,payload)
            revised=self.revision(root,payload)
            barrier=Barrier(2)
            def publish(path,record):
                barrier.wait(timeout=5)
                return _publish(path,record)
            def save(label):
                try:
                    submit(root,{**revised,'reviewer':label})
                    return True
                except Exception:
                    return False
            with patch('tradeintel_ai.interpretation_review_store._publish',publish):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    outcomes=list(pool.map(save,['one','two']))
            self.assertEqual(sorted(outcomes),[False,True])
            self.assertEqual(packet(root)['revision'],2)
