"""Verify the two frozen Phase12j China absences against retained ZIP bytes.

No imputation, post-policy reads, matching, or causal estimates.
"""
import csv
import json
from pathlib import Path
from zipfile import ZipFile
from inventory_census_import import parse_detail_line, sha256_file

ROOT = Path(__file__).resolve().parents[1]
CASES = [(2017, 1, '84414000'), (2018, 1, '84209190')]


def audit():
    panel_path = ROOT/'data/processed/trade_hts8/monthly/hts8_candidates_prepolicy_v2.csv'
    with panel_path.open() as handle:
        panel = {(int(r['year']), int(r['month']), r['hts8']): r for r in csv.DictReader(handle)}
    rows = []
    for year, month, hts8 in CASES:
        expected = panel[year, month, hts8]
        path = ROOT/'data/raw/trade-detail'/expected['source_file_name']
        digest = sha256_file(path)
        if digest != expected['source_sha256']:
            raise ValueError('Source archive fingerprint mismatch')
        matches = []
        scanned = 0
        with ZipFile(path) as archive, archive.open('IMP_DETL.TXT') as handle:
            for number, raw in enumerate(handle, 1):
                scanned += 1
                if raw[:8] != hts8.encode('ascii'):
                    continue
                record = parse_detail_line(raw, line_number=number)
                if (record.year, record.month) != (year, month):
                    raise ValueError('Unexpected record month')
                matches.append({'line':number, 'hts10':record.hts10,
                    'country':record.country_code, 'consumption_value_usd':record.consumption_value_usd})
        china = [r for r in matches if r['country'] == '5700']
        total = sum(r['consumption_value_usd'] for r in matches)
        if china or expected['china_observed'] != '0' or expected['china_import_value_consumption_usd'] != '':
            raise ValueError('Frozen missing-China case no longer matches source')
        if total != int(expected['all_origin_import_value_consumption_usd']):
            raise ValueError('All-origin aggregate mismatch')
        rows.append({'year':year, 'month':month, 'hts8':hts8, 'source_sha256':digest,
            'source_file':path.name, 'source_url':expected['source_url'],
            'scanned_detail_rows':scanned, 'china_rows':len(china),
            'all_origin_value_usd':total, 'matching_source_rows':matches,
            'conclusion':'absence_confirmed_in_raw_source_not_extractor_loss',
            'imputed':False})
    return {'cases':rows, 'panel_sha256':sha256_file(panel_path),
            'interpretation':'Raw absence verified; missingness mechanism not established. No zero imputation or causal estimation.'}


if __name__ == '__main__':
    result = audit()
    output = ROOT/'docs/experiments/phase12k-source-absence.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    for r in result['cases']:
        print(r['hts8'], r['year'], 'china_rows=',r['china_rows'], 'all_origin_usd=',r['all_origin_value_usd'])
    print(output)
