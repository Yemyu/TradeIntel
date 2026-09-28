"""Independently check one extracted import month against its retained ZIP."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from scripts.validate_hts10_extraction import check_rows, digest


def verify(root: Path, month: str) -> dict[str, object]:
    year, month_number = (int(value) for value in month.split('-'))
    manifest = json.loads((root / 'data/processed/trade_hts10/manifest.json').read_text())
    records = [item for item in manifest['months']
               if (item['year'], item['month']) == (year, month_number)]
    if len(records) != 1:
        raise ValueError(f'Expected exactly one registered month: {month}')
    record = records[0]
    if record.get('status') != 'processed' or record.get('raw_archive_retained_after_processing') is not True:
        raise ValueError('Month is not processed with retained source')
    archive = root / 'data/raw/trade-detail' / record['source_file_name']
    output = root / record['monthly_output']
    if not archive.is_file() or not output.is_file():
        raise ValueError('Missing retained archive or processed file')
    if digest(archive) != record['source_sha256']:
        raise ValueError('Retained source hash mismatch')
    with output.open(newline='', encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    check_rows(rows, (year, month_number), record)
    if len(rows) != record['output_rows'] or len(rows) != record['unique_hts10_count']:
        raise ValueError('Processed row count mismatch')
    if sum(int(row['all_origin_detail_row_count']) for row in rows) != record['raw_detail_rows']:
        raise ValueError('Raw detail row count mismatch')
    for field, expected in (
        ('all_origin_import_value_consumption_usd', 'raw_all_origin_value_usd'),
        ('china_import_value_consumption_usd', 'raw_china_value_usd'),
    ):
        if sum(int(row[field]) for row in rows) != record[expected]:
            raise ValueError(f'Monthly total mismatch: {field}')
    return {'month': month, 'status': 'verified', 'hts10_rows': len(rows),
            'raw_detail_rows': record['raw_detail_rows'],
            'source_sha256': record['source_sha256'],
            'processed_sha256': digest(output)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('month', help='YYYY-MM')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(verify(args.root, args.month), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
