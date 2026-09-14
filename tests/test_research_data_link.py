import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tests.test_update_brief import snapshot, month
from src.tradeintel_ai.research_data_link import research_data_link
from src.tradeintel_ai.exposure_version_store import VersionStoreError


class ResearchDataLinkTests(unittest.TestCase):
    def test_missing_release_degrades_without_crashing(self):
        with tempfile.TemporaryDirectory() as folder, patch('src.tradeintel_ai.research_data_link.ExposureVersionStore') as cls:
            run=Path(folder);(run/'status.json').write_text(json.dumps({'data_version':'a'*64}))
            cls.return_value.load_snapshot.side_effect=VersionStoreError('missing snapshot')
            self.assertEqual(research_data_link(run,run)['status'],'unavailable')

    def test_pinned_amounts_scope_and_mismatch(self):
        s=snapshot({'2026-06':month()})
        with tempfile.TemporaryDirectory() as folder, patch('src.tradeintel_ai.research_data_link.ExposureVersionStore') as cls:
            run=Path(folder)
            cls.return_value.load_snapshot.return_value=s
            (run/'status.json').write_text(json.dumps({'data_version':s['version']}))
            evidence={'data_version':s['version'],'data':{'policy_id':s['policy_id'],
                'coverage_complete':True,'requested_months':['2026-06'],
                'series':[{'month':'2026-06','all_origins_value_usd':100,'china_value_usd':20}]}}
            (run/'trade-evidence.json').write_text(json.dumps(evidence))
            bound=research_data_link(run,run)
            self.assertEqual(bound['status'],'bound')
            self.assertEqual(bound['url'],'/api/version-report?version='+s['version'])
            self.assertEqual(bound['months'],['2026-06'])
            cls.return_value.active_version.assert_not_called()
            evidence['data']['series'][0]['china_value_usd']=21
            (run/'trade-evidence.json').write_text(json.dumps(evidence))
            self.assertIsNone(research_data_link(run,run)['url'])
            evidence['data']['hts8']='12345678'
            (run/'trade-evidence.json').write_text(json.dumps(evidence))
            self.assertIsNone(research_data_link(run,run)['url'])

    def test_old_missing_version_is_not_guessed(self):
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder);(run/'status.json').write_text('{}')
            self.assertEqual(research_data_link(run,run)['status'],'unavailable')
