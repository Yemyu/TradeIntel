import copy
import unittest
from scripts.replay_exposure_update import compare, digest


class UpdateTests(unittest.TestCase):
    def state(self):
        value = {'policy_id': 'registered', 'start': '2025-01',
                 'policy_files': {'policy': 'hash'},
                 'months': {'2026-06': {'archive_sha256': 'first', 'amount': 20}}}
        return self.seal(value)

    def seal(self, value):
        value['version'] = digest({k: v for k, v in value.items() if k != 'version'})
        return value

    def test_same_version_is_unchanged(self):
        value = self.state()
        self.assertEqual(compare(value, value)['status'], 'unchanged')

    def test_equal_amount_source_revision_requires_review(self):
        old = self.state()
        new = copy.deepcopy(old)
        new['months']['2026-06']['archive_sha256'] = 'revised'
        result = compare(old, self.seal(new))
        self.assertEqual(result['revised_months'], ['2026-06'])
        self.assertTrue(result['requires_review'])

    def test_new_month_and_policy_change_are_distinct(self):
        old = self.state()
        new = copy.deepcopy(old)
        new['months']['2026-07'] = {'amount': 30}
        result = compare(old, self.seal(new))
        self.assertEqual(result['added_months'], ['2026-07'])
        self.assertFalse(result['requires_review'])
        new['policy_files']['policy'] = 'changed'
        self.assertTrue(compare(old, self.seal(new))['policy_changed'])

    def test_modified_snapshot_is_rejected(self):
        old = self.state()
        new = copy.deepcopy(old)
        new['months'].clear()
        with self.assertRaises(ValueError):
            compare(old, new)
