import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from src.tradeintel_ai.report_update_impact import assess_report, scan_reports, render_report_impacts
from tests.test_update_brief import snapshot, month


class ReportImpactTests(unittest.TestCase):
    def prepare(self, root, before):
        run=root/'exposure-20260914T120000-abcdef12';run.mkdir()
        (run/'report.zh-CN.md').write_text('saved report')
        (run/'status.json').write_text(json.dumps({'data_version':before['version']}))
        evidence={'data_version':before['version'],'data':{'policy_id':'test',
            'requested_months':['2026-06'],'series':[{'month':'2026-06'}],'coverage_complete':True}}
        (run/'trade-evidence.json').write_text(json.dumps(evidence))
        store=SimpleNamespace(load_snapshot=lambda version:before if version==before['version'] else None)
        return run,store

    def test_fixed_scope_not_invalidated_by_added_month(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);before=snapshot({'2026-06':month()});run,store=self.prepare(root,before)
            after=snapshot({'2026-06':month(),'2026-07':month()})
            self.assertEqual(assess_report(run,store,after)['status'],'unchanged_scope')

    def test_used_revision_and_policy_change_need_review(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);before=snapshot({'2026-06':month()});run,store=self.prepare(root,before)
            for after in [snapshot({'2026-06':month(90,10)}),snapshot({'2026-06':month()},policy='b')]:
                self.assertEqual(assess_report(run,store,after)['status'],'needs_review')
            self.assertEqual((run/'report.zh-CN.md').read_text(),'saved report')

    def test_missing_or_mismatched_version_is_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);before=snapshot({'2026-06':month()});run,store=self.prepare(root,before)
            (run/'status.json').write_text('{}')
            self.assertEqual(assess_report(run,store,before)['status'],'unknown')
            (run/'status.json').write_text(json.dumps({'data_version':before['version']}))
            path=run/'trade-evidence.json';evidence=json.loads(path.read_text());evidence['data_version']='different'
            path.write_text(json.dumps(evidence))
            self.assertEqual(assess_report(run,store,before)['status'],'unknown')

    def test_scan_ignores_symlinks_and_outputs_only_safe_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);before=snapshot({'2026-06':month()});run,store=self.prepare(root,before)
            (root/'exposure-20260914T120001-abcdef13').symlink_to(run,target_is_directory=True)
            items=scan_reports(root,store,before)
            self.assertEqual(len(items),1)
            self.assertNotIn(str(root),render_report_impacts(items))
            self.assertEqual(items[0]['url'],'/api/report/'+run.name)
