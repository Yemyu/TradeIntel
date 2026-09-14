import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from scripts.build_trade_panel import download_archive, month_source
from scripts.inventory_census_import import InventoryError, resolve_member


def zip_bytes(names):
    stream = io.BytesIO()
    with ZipFile(stream, 'w') as archive:
        for name in names:
            archive.writestr(name, 'fixture')
    return stream.getvalue()


class CensusMembersTests(unittest.TestCase):
    def test_case_only_variants(self):
        for name in ('IMP_DETL.TXT', 'IMP_DETL.txt'):
            with ZipFile(io.BytesIO(zip_bytes([name]))) as archive:
                self.assertEqual(resolve_member(archive, 'IMP_DETL.TXT'), name)

    def test_ambiguous_or_nested_members_rejected(self):
        for names in (['IMP_DETL.TXT', 'IMP_DETL.txt'], ['REF/IMP_DETL.txt'], []):
            with ZipFile(io.BytesIO(zip_bytes(names))) as archive:
                with self.assertRaises(InventoryError):
                    resolve_member(archive, 'IMP_DETL.TXT')

    def test_unexpected_valid_archive_is_preserved_without_retry(self):
        payload = zip_bytes(['unexpected.txt'])
        with tempfile.TemporaryDirectory() as tmp:
            with patch('scripts.build_trade_panel.urlopen', return_value=io.BytesIO(payload)) as fetch:
                with self.assertRaisesRegex(InventoryError, 'Archive retained'):
                    download_archive(month_source(2025, 1), Path(tmp))
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual((Path(tmp) / 'IMDB2501.ZIP').read_bytes(), payload)

    def test_lowercase_download_accepted(self):
        payload = zip_bytes(['IMP_DETL.txt'])
        with tempfile.TemporaryDirectory() as tmp:
            with patch('scripts.build_trade_panel.urlopen', return_value=io.BytesIO(payload)):
                result, status, _ = download_archive(month_source(2025, 1), Path(tmp))
            self.assertEqual(status, 'downloaded')
            self.assertEqual(result.read_bytes(), payload)
