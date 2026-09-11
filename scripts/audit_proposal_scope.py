"""Official proposal exposure and two explicit correction events; no trade amounts."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re
import sys
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_control_eligibility import load_mapping, sha256_file

RAW = ROOT / 'data/raw/policy'
PRIMARY = RAW / 'ustr-section301-proposed-2018-04-03.pdf'
PUBLIC = RAW / 'ustr-section301-proposed-2018-04-06.pdf'
CORRECTION = RAW / 'ustr-list1-exclusions-2019-07-09.pdf'
SOURCE_URL = 'https://ustr.gov/sites/default/files/files/Press/Releases/301FRN.pdf'
PUBLIC_URL = 'https://ustr.gov/sites/default/files/enforcement/301Investigations/FRN301.pdf'
CORRECTION_URL = 'https://www.govinfo.gov/content/pkg/FR-2019-07-09/pdf/2019-14562.pdf'
PREP = ROOT / 'docs/experiments/preannouncement-preparation'
CAUSAL = ROOT / 'data/processed/causal'


def code_rows(pages, start, stop):
    rows = []
    for index in range(start, stop):
        for line in pages[index].splitlines():
            match = re.match(r'^\s*(\d{8})(?!\d)', line)
            if match:
                rows.append({'hts8':match[1], 'page':index+1, 'source_line':line.strip()})
    return rows


def validate_codes(rows, final):
    codes = [r['hts8'] for r in rows]
    if len(codes) != 1333 or len(set(codes)) != 1333:
        raise ValueError('Expected 1333 unique proposal lines; do not guess missing codes')
    if len(final) != 818 or not final <= set(codes):
        raise ValueError('Final List1 subset check failed')
    return set(codes)


def correction_events(text):
    events = []
    normalized = ' '.join(text.split())
    for old, note in [('8404.40.4000','53'), ('8504.40.0000','54')]:
        pattern = (r'U\.S\. note 20\(m\)\(' + note + r'\).*?modified by deleting\s*'
                   r'[‘’“”"\s]*' + re.escape(old) + r'[‘’“”"\s]*and inserting\s*'
                   r'[‘’“”"\s]*8504\.40\.4000')
        if not re.search(pattern, normalized):
            raise ValueError(f'Official correction sentence missing: {old}')
        events.append({'note':f'20(m)({note})','old_code':old.replace('.',''),
            'new_code':'8504404000','publication_date':'2019-07-09',
            'retroactive_effective_date':'2018-07-06','source_page':6,
            'source_url':CORRECTION_URL,'description_conditions_still_required':True})
    return events


def write_rows(path, rows):
    with path.open('x',newline='') as handle:
        writer=csv.DictWriter(handle,list(rows[0]));writer.writeheader();writer.writerows(rows)


def audit(output):
    if output.exists():raise ValueError('Output exists')
    inputs=[PRIMARY,PUBLIC,CORRECTION,CAUSAL/'hts_history_mapping.csv',
            CAUSAL/'trade_action_exposure.csv',CAUSAL/'list1_exclusion_timeline.csv',
            PREP/'candidate_eligibility.csv',ROOT/'docs/decisions/0068-proposal-and-correction-audit.zh-CN.md',
            Path(__file__).resolve(),ROOT/'scripts/build_control_eligibility.py']
    hashes={str(p.relative_to(ROOT)):sha256_file(p) for p in inputs}
    pages=[p.extract_text() or '' for p in PdfReader(PRIMARY).pages]
    if len(pages)!=58 or 'ANNEX' not in pages[13]:raise ValueError('Unexpected primary document layout')
    rows=code_rows(pages,13,58)
    with (CAUSAL/'trade_action_exposure.csv').open() as handle:
        final={r['hts_code'].replace('.','') for r in csv.DictReader(handle) if r['policy_id']=='us_301_list1_2018'}
    codes=validate_codes(rows,final)
    public_pages=[p.extract_text() or '' for p in PdfReader(PUBLIC).pages]
    public_rows=code_rows(public_pages,4,48)
    public_codes={r['hts8'] for r in public_rows}
    mapping,valid,_=load_mapping(CAUSAL/'hts_history_mapping.csv')
    by8=defaultdict(set)
    for row in valid:by8[row['source_hts10'][:8]].add(row['hs6_2017'])
    byhs6=defaultdict(set);fallback=[]
    for row in rows:
        code=row['hts8']; targets=by8[code] or {code[:6]}
        if not by8[code]:fallback.append(code)
        row.update(final_list1=code in final,canonical_hs6='|'.join(sorted(targets)),
                   mapping_kind='official_2018_mapping' if by8[code] else 'same_revision_scope_prefix_no_trade_line',
                   source_url=SOURCE_URL,source_sha256=hashes[str(PRIMARY.relative_to(ROOT))])
        for target in targets:byhs6[target].add(code)
    candidate_rows=[]
    with (PREP/'candidate_eligibility.csv').open() as handle:
        for r in csv.DictReader(handle):
            if r['primary_role']=='excluded':continue
            hits=byhs6[r['hs6_2017']]
            candidate_rows.append({'hs6_2017':r['hs6_2017'],'candidate_role':r['primary_role'],
                'naics3_candidates':r['naics3_candidates'],'proposal_hts8_hits':'|'.join(sorted(hits)),
                'proposal_overlap':bool(hits),'review_status':'proposal_exposure_present' if hits else 'no_overlap_with_april_proposal_only',
                'candidate_removed':False,'causal_adopted':False})
    correction_pages=[p.extract_text() or '' for p in PdfReader(CORRECTION).pages]
    events=correction_events(correction_pages[5])
    with (CAUSAL/'list1_exclusion_timeline.csv').open() as handle:
        legacy={c.replace('.','') for r in csv.DictReader(handle) for c in r['explicit_hts10_codes'].split('|') if c}
    replacements={e['old_code']:e['new_code'] for e in events}
    corrected={replacements.get(code,code) for code in legacy}
    unresolved=[code for code in sorted(corrected) if not any(
        mapping.get(y,{}).get(code,{}).get('hs6_2017') and mapping[y][code]['historical_validity_status']=='valid' for y in (2018,2019))]
    if any(sha256_file(ROOT/k)!=v for k,v in hashes.items()):raise ValueError('Inputs changed')
    report={'status':'scope_audit_complete_not_causal_adoption','input_sha256':hashes,
        'sources':{'primary':SOURCE_URL,'public_copy':PUBLIC_URL,'correction':CORRECTION_URL},
        'proposal_count':len(codes),'final_count':len(final),'proposal_not_final_list1':len(codes-final),
        'final_missing_from_proposal':sorted(final-codes),'same_revision_prefix_fallback':fallback,
        'public_copy_strict_extraction_count':len(public_rows),
        'public_copy_missing_in_machine_text':sorted(codes-public_codes),
        'public_copy_extra_in_machine_text':sorted(public_codes-codes),
        'public_copy_comparison_status':'machine_text_disagrees_do_not_use_as_complete_index',
        'candidate_counts':dict(Counter(f"{r['candidate_role']}|proposal={r['proposal_overlap']}" for r in candidate_rows)),
        'correction_events':events,'legacy_code_string_count':len(legacy),
        'corrected_distinct_code_string_count':len(corrected),'unresolved_after_two_corrections':unresolved,
        'whole_hts10_exemption_claim_allowed':False,'description_scope_complete':False,
        'model_calls':0,'optimization_calls':0,'trade_amounts_read':False,'causal_adopted':False}
    output.mkdir(parents=True,exist_ok=False)
    write_rows(output/'proposal_hts8.csv',rows)
    write_rows(output/'candidate_proposal_risk.csv',candidate_rows)
    write_rows(output/'correction_events.csv',events)
    report['output_sha256']={p.name:sha256_file(p) for p in output.glob('*.csv')}
    with (output/'summary.json').open('x') as handle:json.dump(report,handle,ensure_ascii=False,indent=2);handle.write('\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path)
    report=audit(parser.parse_args().output)
    print(json.dumps({k:report[k] for k in ['proposal_count','final_count','candidate_counts','unresolved_after_two_corrections','corrected_distinct_code_string_count']},ensure_ascii=False,indent=2))
