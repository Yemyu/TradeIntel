import unittest
from unittest.mock import patch
from src.tradeintel_ai.version_report import render_version_report, version_report
from src.tradeintel_ai.exposure_version_store import VersionStoreError
from tests.test_update_brief import snapshot, month


class VersionReportTests(unittest.TestCase):
    def test_version_and_denominator(self):
        s=snapshot({'2026-06':month(),'2026-07':month(200,30)})
        html=render_version_report(s)
        self.assertIn('15.00%',html)
        self.assertIn('?version='+s['version'],html)
        self.assertIn('2026-07',html)
        self.assertIn('width:100.000%',html)

    def test_zero_missing_and_invalid(self):
        for values in [(0,0),(None,None)]:
            self.assertIn('未知',render_version_report(snapshot({'2026-06':month(*values)})))
        with self.assertRaises(VersionStoreError):
            render_version_report(snapshot({'2026-06':month(1,2)}))

    def test_explicit_version_not_replaced_with_active(self):
        old=snapshot({'2026-06':month()})
        with patch('src.tradeintel_ai.version_report.ExposureVersionStore') as cls:
            store=cls.return_value
            store.load_snapshot.return_value=old
            html=version_report('/unused',old['version'])
            store.active_version.assert_not_called()
            store.release_root.assert_called_once_with(old['version'])
            self.assertNotIn('2026-07',html)

    def test_source_html_escaped(self):
        m=month();m['source_url']='https://example.org/" onclick="bad'
        html=render_version_report(snapshot({'2026-06':m}))
        self.assertNotIn('href="https://example.org/" onclick=',html)
