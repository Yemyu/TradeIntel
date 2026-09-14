import copy
import unittest
from src.tradeintel_ai.update_brief import render_update_brief
from src.tradeintel_ai.exposure_version_store import content_digest, VersionStoreError


def snapshot(months, policy='a'):
    body={'policy_id':'test','start':'2026-06','end':max(months),'months':months,
          'policy_files':{'policy.csv':policy},'mode':'current_vintage_window_replay'}
    return {**body,'version':content_digest(body)}


def month(world=100,china=20):
    return {'output_sha256':'a'*64,'source_url':'https://example.org/source.zip',
            'metrics':{'all_origins_value_usd':world,'china_value_usd':china}}


class UpdateBriefTests(unittest.TestCase):
    def test_added_month_and_correct_denominator(self):
        before=snapshot({'2026-06':month()})
        after=snapshot({'2026-06':month(),'2026-07':month(200,30)})
        report=render_update_brief(before,after)
        self.assertIn('新增月份：2026-07',report)
        self.assertIn('15.00%',report)
        self.assertIn('当前数据版本的窗口回放',report)
        self.assertNotIn('版本修订差额',report)

    def test_revision_and_policy_file_change_are_not_growth(self):
        before=snapshot({'2026-06':month(100,20),'2026-07':month()})
        after=snapshot({'2026-06':month(90,10)},policy='b')
        report=render_update_brief(before,after)
        self.assertIn('版本修订差额：-10',report)
        self.assertIn('移除月份：2026-07',report)
        self.assertIn('文件变化本身不能证明政策已经调整',report)

    def test_unchanged_does_not_generate_new_findings(self):
        same=snapshot({'2026-06':month()})
        self.assertIn('本次没有新增研究结论',render_update_brief(same,same))

    def test_missing_or_zero_is_not_imputed(self):
        before=snapshot({'2026-06':month()})
        for world,china in [(None,None),(0,0)]:
            after=snapshot({'2026-06':month(),'2026-07':month(world,china)})
            self.assertIn('未知（缺数据或分母为零）',render_update_brief(before,after))

    def test_corruption_and_impossible_share_rejected(self):
        before=snapshot({'2026-06':month()})
        bad=copy.deepcopy(before);bad['months']['2026-06']=month(9,1)
        with self.assertRaises(VersionStoreError):render_update_brief(before,bad)
        bad=snapshot({'2026-06':month(),'2026-07':month(10,11)})
        with self.assertRaises(VersionStoreError):render_update_brief(before,bad)
