"""Compare official HTS revisions around the registered July 2026 transition."""
import hashlib
import json
import csv
import sys
from collections import defaultdict
from pathlib import Path
from urllib.request import Request, urlopen
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
CODES = {'28046100', '38180000', '81019400', '81019910', '81019980'}


def fetch(revision):
    folder = ROOT / 'data/raw/policy/review2025'
    folder.mkdir(parents=True, exist_ok=True)
    url = f'https://www.usitc.gov/sites/default/files/tata/hts/hts_2026_revision_{revision}_json.json'
    path = folder / f'hts_2026_revision_{revision}.json'
    meta = path.with_suffix('.source.json')
    if not path.exists():
        with urlopen(Request(url, headers={'User-Agent': 'TradeIntel research'}), timeout=45) as response:
            content = response.read(30_000_001)
        if len(content) > 30_000_000:
            raise ValueError('unexpected archive size')
        json.loads(content)
        path.write_bytes(content)
        meta.write_text(json.dumps({'url': url, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                                   'sha256': hashlib.sha256(content).hexdigest()}, indent=2))
    content = path.read_bytes()
    source = json.loads(meta.read_text())
    if hashlib.sha256(content).hexdigest() != source['sha256']:
        raise ValueError('archive hash changed')
    return json.loads(content), source


def fetch_revisions():
    out = {}
    for revision in (10, 11):
        rows, source = fetch(revision)
        if not isinstance(rows, list):
            raise ValueError('unexpected HTS structure')
        selected = [r for r in rows if str(r.get('htsno', '')).replace('.', '')[:8] in CODES]
        out[str(revision)] = {'source': source, 'rows': selected}
    path = ROOT / 'data/processed/policy_exposure/hts_revision_comparison.json'
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'output': str(path), 'rows': {r: len(v['rows']) for r, v in out.items()}}))


def check_transition(before, after):
    old = '3818000095'
    successors = {'3818000040', '3818000045', '3818000050', '3818000091'}
    unchanged = {'3818000010', '3818000020', '3818000030'}
    if set(before) != unchanged | {old} or set(after) != unchanged | successors | {old}:
        raise ValueError('unexpected observed code set; review required')
    if after[old] != 0:
        raise ValueError('retired code has nonzero current-month value; review required')
    if any(type(v) is not int or v < 0 for v in [*before.values(), *after.values()]):
        raise ValueError('invalid amounts')
    previous, current = sum(before.values()), sum(after.values())
    return {'reference_value_usd': previous, 'current_value_usd': current,
            'change_usd': current - previous,
            'change_percent': round((current / previous - 1) * 100, 4) if previous else None,
            'aggregation': 'complete HTS8 38180000, not individual successor codes',
            'successor_codes': sorted(successors)}


def main():
    sys.path.insert(0, str(ROOT))
    from src.tradeintel_ai.policy_exposure_tools import get_policy_exposure_series
    get_policy_exposure_series(start='2026-06', end='2026-07', hts8='38180000')
    monthly = ROOT / 'data/processed/policy_exposure/monthly'
    groups, sources = {}, []
    for month in ('06', '07'):
        path = monthly / f'us_301_review2025_tungsten_solar_2026_{month}.csv'
        group = defaultdict(int)
        with path.open() as handle:
            for row in csv.DictReader(handle):
                if row['canonical_hts8'] == '38180000':
                    group[row['hts10']] += int(row['import_value_consumption_usd'])
        groups[month] = dict(group)
        sources.append({'path': str(path.relative_to(ROOT)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    result = {'status': 'reviewed_specific_transition', 'reference_month': '2026-06', 'current_month': '2026-07',
              'source_url': 'https://www.usitc.gov/tariff_affairs/documents/list_of_committee_changes_for_july_1_2026-final.pdf',
              'source_pages': [43, 44], 'effective_date': '2026-07-01',
              'decision': 'Official transfer table keeps all four successors within 38180000. Aggregate all children; never fill prior successor months with zero.',
              'scope_limit': 'This verifies the June-to-July 2026 code transition only, not all 19 months or economic causality.',
              'sources': sources, 'observed_codes': groups, 'comparison': check_transition(groups['06'], groups['07'])}
    path = ROOT / 'data/processed/policy_exposure/code_transition_review.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result['comparison'], ensure_ascii=False))


if __name__ == '__main__':
    main()
