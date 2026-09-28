import csv
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_public_brief_candidate import _independent_reference, POLICY
from tradeintel_ai.policy_cases import CASES


class ReferenceRecomputeTests(unittest.TestCase):
    def test_aggregates_detail_rows_and_uses_product_denominator(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / CASES[POLICY].monthly / f"{POLICY}_2026_07.csv"
            path.parent.mkdir(parents=True)
            fields = ['policy_id', 'year', 'month', 'canonical_hts8',
                      'origin_code', 'import_value_consumption_usd']
            with path.open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for origin, amount in [('5700', 20), ('5700', 10), ('5880', 70)]:
                    writer.writerow(dict(zip(fields, [POLICY, 2026, 7, '38180000', origin, amount])))
            request = {'policy_id': POLICY, 'data_version': 'a' * 64,
                       'products': ['38180000'], 'window': {'anchor_month': '2026-07'},
                       'comparisons': ['mom']}
            reference = _independent_reference(root, request, scenario='q1')
            row = reference['latest_rows']['38180000']
            self.assertEqual(row['all_origins_value_usd'], 100)
            self.assertEqual(row['china_value_usd'], 30)
            self.assertEqual(row['china_share_percent'], '30')
            self.assertEqual(len(reference['source_files_sha256']), 1)
            request['products'] = ['99999999']
            with self.assertRaisesRegex(ValueError, '缺少'):
                _independent_reference(root, request, scenario='q1')


if __name__ == '__main__':
    unittest.main()
