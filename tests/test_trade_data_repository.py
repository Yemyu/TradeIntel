import csv
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.tradeintel_ai.trade_data_repository import (
    TradeDataError, TradeDataRepository, TradeQuery,
)


FIELDS = [
    'year', 'month', 'hts10', 'hts8',
    'china_import_value_consumption_usd',
    'all_origin_import_value_consumption_usd',
    'china_observed', 'all_origin_observed',
    'source_sha256',
]
SOURCE_HASH = 'a' * 64


def fixture(root):
    raw = root / 'data/raw/trade-detail'
    raw.mkdir(parents=True)
    (raw / 'IMDB2606.ZIP').write_bytes(b'raw-only fixture')
    processed = root / 'data/processed/trade_hts10/monthly'
    processed.mkdir(parents=True)
    with (processed / 'trade_hts10_2026_07.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerow(dict(year=2026, month=7, hts10='1201900005', hts8='12019000',
                             china_import_value_consumption_usd=0,
                             all_origin_import_value_consumption_usd=12,
                             china_observed=0, all_origin_observed=1,
                             source_sha256=SOURCE_HASH))
        writer.writerow(dict(year=2026, month=7, hts10='1201900010', hts8='12019000',
                             china_import_value_consumption_usd=0,
                             all_origin_import_value_consumption_usd=0,
                             china_observed=1, all_origin_observed=1,
                             source_sha256=SOURCE_HASH))
    (processed.parent / 'manifest.json').write_text(json.dumps({'months': [{
        'year': 2026, 'month': 7, 'status': 'processed',
        'monthly_output': 'data/processed/trade_hts10/monthly/trade_hts10_2026_07.csv',
        'source_sha256': SOURCE_HASH,
        'source_url': 'https://www.census.gov/fixture',
    }]}))


class TradeDataRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        fixture(self.root)
        self.repo = TradeDataRepository(self.root)

    def query(self, code='12019000', partner='ALL_ORIGINS', start='2026-06', end='2026-07'):
        return self.repo.query(TradeQuery('US', 'import', code, start, end,
                                          partner, self.repo.catalog()['dataset_version']))

    def test_raw_archive_is_discoverable_but_not_queryable(self):
        months = {m['month']: m for m in self.repo.catalog()['months']}
        self.assertEqual(months['2026-06']['status'], 'raw_only')
        self.assertIsNone(months['2026-06']['processed_file'])
        result = self.query()['months']
        self.assertEqual(result[0]['status'], 'not_processed')
        self.assertTrue(result[0]['raw_available'])
        self.assertIsNone(result[0]['value_usd'])
        self.assertEqual(result[1]['value_usd'], 12)

    def test_zero_not_observed_and_missing_code_are_distinct(self):
        self.assertEqual(self.query('1201900010', start='2026-07')["months"][0]['value_usd'], 0)
        self.assertEqual(self.query('1201900005', 'CHINA', '2026-07')["months"][0]['status'],
                         'not_observed')
        self.assertIsNone(self.query('1201900005', 'CHINA', '2026-07')["months"][0]['value_usd'])
        self.assertEqual(self.query('1201900090', start='2026-07')["months"][0]['status'],
                         'no_record')

    def test_export_and_unavailable_partner_never_fall_back_to_import(self):
        version = self.repo.catalog()['dataset_version']
        for flow, partner in [('export', 'ALL_ORIGINS'), ('import', 'BRAZIL')]:
            with self.subTest(flow=flow, partner=partner), self.assertRaises(TradeDataError):
                self.repo.query(TradeQuery('US', flow, '12019000', '2026-07',
                                           '2026-07', partner, version))

    def test_stale_version_or_modified_file_is_refused(self):
        query = TradeQuery('US', 'import', '12019000', '2026-07', '2026-07',
                           'ALL_ORIGINS', self.repo.catalog()['dataset_version'])
        file = self.root / 'data/processed/trade_hts10/monthly/trade_hts10_2026_07.csv'
        file.write_text(file.read_text() + '\n')
        with self.assertRaisesRegex(TradeDataError, '数据版本已变化'):
            self.repo.query(query)

    def test_real_july_soybean_snapshot_and_honest_june_status(self):
        real_root = Path(__file__).resolve().parents[1]
        if not (real_root / 'data/processed/trade_hts10/monthly/trade_hts10_2026_07.csv').is_file():
            self.skipTest('本地加工文件未随仓库分发')
        repo = TradeDataRepository(real_root)
        catalog = repo.catalog()
        months = {m['month']: m for m in catalog['months']}
        self.assertEqual(months['2026-07']['status'], 'queryable_aggregate')
        self.assertIn(months['2026-06']['status'], {'raw_only', 'queryable_aggregate'})
        result = repo.query(TradeQuery('US', 'import', '12019000', '2026-06',
                                       '2026-07', 'ALL_ORIGINS', catalog['dataset_version']))
        expected_june = ('observed' if months['2026-06']['status'] == 'queryable_aggregate'
                         else 'not_processed')
        self.assertEqual(result['months'][0]['status'], expected_june)
        self.assertEqual(result['months'][1]['status'], 'observed')
        self.assertGreater(result['months'][1]['value_usd'], 0)

    def test_local_http_query_is_bounded_and_returns_catalog_version(self):
        from src.tradeintel_ai.web_app import create_server
        server = create_server(root=self.root, host='127.0.0.1', port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            with urlopen(base + '/api/trade/catalog') as response:
                catalog = json.load(response)
            payload = dict(reporter='US', flow='import', product_code='12019000',
                           start_month='2026-07', end_month='2026-07',
                           partner='ALL_ORIGINS', dataset_version=catalog['dataset_version'])
            def post(data):
                return urlopen(Request(base + '/api/trade/query',
                                       data=json.dumps(data).encode(),
                                       headers={'Content-Type': 'application/json'}))
            with post(payload) as response:
                self.assertEqual(json.load(response)['months'][0]['value_usd'], 12)
            with self.assertRaises(HTTPError) as rejected:
                post({**payload, 'flow': 'export'})
            self.assertEqual(rejected.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
