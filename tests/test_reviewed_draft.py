import tempfile
import unittest
import json
from unittest.mock import patch
from pathlib import Path
from tradeintel_ai.interpretation_review_store import FILES, packet, submit, reviewed_draft

SOURCE=Path(__file__).resolve().parents[1]/'tmp/trade-aware-interpretation-v1-first/run'

class ReviewedDraftTests(unittest.TestCase):
    def copy(self,root):
        for name in FILES:(root/name).write_bytes((SOURCE/name).read_bytes())
    def payload(self,root,first='reject',second='accept',facts=True):
        return {'fingerprint':packet(root)['fingerprint'],'reviewer':'local-review','facts_checked':facts,
                'decisions':[{'index':0,'verdict':first,'reason':'本次资料不足以支持该方向'},
                             {'index':1,'verdict':second,'reason':'明确区分统计金额和企业税负'}]}
    def test_export_only_accepts_and_preserves_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.copy(root);submit(root,self.payload(root))
            before={name:(root/name).read_bytes() for name in FILES}
            draft=reviewed_draft(root)
            self.assertIn('AI建议（仅纳入人工采纳项）',draft)
            self.assertIn('现有数据为海关统计金额',draft)
            self.assertIn('/api/version-report?version=',draft)
            self.assertNotIn('第三国转运或轻微加工',draft)
            self.assertIn('360,659,187',draft)
            self.assertIn('fr202421217:scope_and_effective',draft)
            self.assertEqual(before,{name:(root/name).read_bytes() for name in FILES})
    def test_export_rejects_pending_revision_or_unchecked(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.copy(root)
            with self.assertRaises(ValueError):reviewed_draft(root)
            submit(root,self.payload(root,facts=False))
            with self.assertRaises(ValueError):reviewed_draft(root)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.copy(root);submit(root,self.payload(root,first='needs_revision'))
            with self.assertRaises(ValueError):reviewed_draft(root)
    def test_export_keeps_month_and_single_product_without_breakdown(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.copy(root)
            path=root/'trade-evidence.json';trade=json.loads(path.read_text())
            trade['data'].update(hts8='85414200',series=[
                {'month':'2026-06','all_origins_value_usd':100,'china_value_usd':20},
                {'month':'2026-07','all_origins_value_usd':200,'china_value_usd':30}])
            path.write_text(json.dumps(trade));submit(root,self.payload(root))
            draft=reviewed_draft(root)
            self.assertIn('| 2026-06 | 85414200 | 100 | 20 | 20.00% |',draft)
            self.assertIn('| 2026-07 | 85414200 | 200 | 30 | 15.00% |',draft)
    def test_export_rejects_stale_packet(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.copy(root);submit(root,self.payload(root));(root/'policy-facts.json').write_text('changed')
            with self.assertRaises(ValueError):reviewed_draft(root)

    def test_export_uses_the_same_bytes_as_the_approved_fingerprint(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.copy(root);submit(root,self.payload(root))
            original_read=Path.read_bytes
            changed=False
            def replace_after_read(path):
                nonlocal changed
                content=original_read(path)
                if path==root/'trade-evidence.json' and not changed:
                    changed=True
                    new=json.loads(content)
                    new['data']['series'][0]['product_breakdown'][0]['all_origins_value_usd']=999999999
                    path.write_text(json.dumps(new),encoding='utf-8')
                return content
            with patch.object(Path,'read_bytes',replace_after_read):
                draft=reviewed_draft(root)
            self.assertIn('360,659,187',draft)
            self.assertNotIn('999,999,999',draft)
            self.assertEqual(packet(root)['status'],'stale')
