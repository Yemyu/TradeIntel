import json
from pathlib import Path
import tempfile
import unittest

from scripts.freeze_g2_research import prepare
from scripts.prepare_g2_revision import prepare as revise, LIMIT
from tradeintel_ai.g2_ledger import G2Ledger, ExperimentBlocked
from tradeintel_ai.business_evidence_view import restore
from tests.test_g2_ledger import FreeFixture, CONFIG


class RevisionTests(unittest.TestCase):
    def test_revision_keeps_failed_call_budget_and_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);parent=root/'parent';child=root/'child'
            prepare(parent);old=G2Ledger(parent,parent/'execution-ledger')
            old.run(0,FreeFixture(CONFIG))
            old.review(0,decision='stop',reason='fixture semantic error',reviewer='fixture')
            before=(parent/'execution-ledger/state.json').read_bytes()
            manifest=revise(parent,child)
            self.assertFalse(manifest['over_budget'])
            self.assertEqual(len(manifest['schedule']),11)
            ledger=G2Ledger(child,child/'execution-ledger');ledger.verify()
            self.assertEqual(before,(parent/'execution-ledger/state.json').read_bytes())
            for name in ('development','primary_all','primary_single','solar_all','solar_single'):
                b=json.loads((child/name/'B.messages.json').read_text())
                c=json.loads((child/name/'C.messages.json').read_text())
                self.assertEqual(b[1],c[1])
                packet=json.loads(c[1]['content']);self.assertEqual(packet['metric_limits'],LIMIT)
                audit=json.loads((child/name/'business-view-audit.json').read_text())
                self.assertEqual(restore(packet,audit),json.loads((parent/name/'unpacked-information.json').read_text()))
                self.assertEqual((child/name/'reference.private.json').read_bytes(),(parent/name/'reference.private.json').read_bytes())
            second=root/'second';revise(parent,second)
            with self.assertRaises(ExperimentBlocked):G2Ledger(second,second/'execution-ledger')
            with self.assertRaises(ExperimentBlocked):ledger.run(11,FreeFixture(CONFIG))
            self.assertEqual(ledger.state()['attempts'],[])

    def test_share_does_not_identify_total_concentration(self):
        concentrated=[5,95]; dispersed=[5,19,19,19,19,19]
        self.assertEqual(concentrated[0]/sum(concentrated),dispersed[0]/sum(dispersed))
        self.assertNotEqual(sum(x*x for x in concentrated),sum(x*x for x in dispersed))
