"""Recheck the fixed development delivery, with no new model calls."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tradeintel_ai.research_brief import ResearchBrief, render_brief


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live-result', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.live_result.read_bytes()
    live = json.loads(raw)
    if live['policy']['audit']['source_kind'] != 'live':
        raise ValueError('Requires an explicitly labelled live record; not proof of provider authenticity')
    args.output.mkdir(parents=True, exist_ok=False)
    workflow = ResearchBrief()
    preview = workflow.prepare(live['request'])
    fresh = workflow.confirm(preview['confirmation_token'], args.output / 'offline')
    if fresh['summary'] != live['summary']:
        raise ValueError('Current trade calculation differs from archived live report')
    field = {'China': 'target_import_value_consumption_usd',
             'other_origins': 'other_origins_import_value_consumption_usd',
             'all_origins': 'all_origins_import_value_consumption_usd'}[live['request']['trade']['origin']]
    if live['request']['trade']['hs6'] is not None:
        raise ValueError('This independent check covers policy aggregate only')
    source = ROOT / 'data/processed/analysis/policy_case_monthly.csv'
    with source.open() as stream:
        values = {row['month_label']: int(row[field]) for row in csv.DictReader(stream)}
    for row in live['summary']['series']:
        if row['value_usd'] != values[row['month']]:
            raise ValueError('Independent CSV comparison failed')
    if live['policy_evidence'] != fresh['policy_evidence']:
        raise ValueError('Current evidence differs from saved live context')
    manifest = {'new_api_calls': 0, 'operation': 'offline_recheck_and_saved_live_render',
                'trade_matches_independent_csv': True, 'trade_matches_fresh_workflow': True,
                'policy_context_matches': True, 'semantic_accuracy_measured': False,
                'saved_live_result_sha256': hashlib.sha256(raw).hexdigest(),
                'csv_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'implementation_sha256': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in [ROOT/'src/tradeintel_ai/research_brief.py', ROOT/'src/tradeintel_ai/policy_focus.py',
                                 ROOT/'src/tradeintel_ai/policy_context_window.py']}}
    (args.output / 'saved-live-result.json').write_bytes(raw)
    response = args.live_result.parent / 'policy-attempt/raw_response.json'
    if response.is_file():
        (args.output / 'saved-raw-response.json').write_bytes(response.read_bytes())
    (args.output / 'review.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    report = '> 本页重新呈现已保存的真实调用；本次呈现和核查没有新调用模型。\n\n' + render_brief(live)
    (args.output / 'report.zh-CN.md').write_text(report)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
