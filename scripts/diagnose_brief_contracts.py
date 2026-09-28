"""Offline contract diagnostics for the 2026-09-15 design review.

Reads the saved primary development run. No provider, key, or network access.
Synthetic counterexamples are NOT new model responses or policy conclusions.
Temporary copies isolate the parser probe from the original experiment.
"""
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from tradeintel_ai.business_workflow import object_response, validate_plan
from tradeintel_ai.exposure_policy import scope_check
from tradeintel_ai.fact_interpretation import review, trade_context
from tradeintel_ai.interpretation_review_store import FILES, packet


def diagnose(root=ROOT):
    run = root / 'tmp/primary-interpretation-v1'
    missing = [name for name in FILES if not (run / name).is_file()]
    if missing:
        return {'status': 'local_evidence_unavailable', 'missing': missing,
                'api_calls': 0, 'boundary': '本机开发记录不是干净仓库的测试 fixture。'}
    read = lambda name: json.loads((run / name).read_text())
    sheet, trade = read('policy-facts.json'), read('trade-evidence.json')
    probes = []
    samples = [
        ('safe_negation', ['policy.entry_events'], '不能仅凭生效前入库认定豁免。'),
        ('unsupported_inference', ['policy.entry_events'], '提前存放仓库的货物可以免交此次附加税。'),
        ('unrelated_reference', ['policy.effective'], '建议优先核查钨制品来源集中度。'),
        ('numeric_restatement', ['trade.2026-07.81019910'], '81019910的中国来源份额为28.629%。'),
    ]
    for name, ids, text in samples:
        result = review({'notes': [{'kind': 'investigation', 'fact_ids': ids, 'text': text}]}, sheet, trade)
        probes.append({'probe': name, 'synthetic_text': text, 'fact_ids': ids,
                       'result': result['status'], 'flags': result['flags'],
                       'approved': result['approved']})

    answer = {'notes': [{'kind': 'limitation', 'fact_ids': ['trade.measure'],
                         'text': '贸易规模不等于实际企业税负。'}]}
    fenced = '```json\n' + json.dumps(answer, ensure_ascii=False) + '\n```'
    with tempfile.TemporaryDirectory(prefix='tradeintel-contract-probe-') as folder:
        copy = Path(folder)
        for name in FILES:
            (copy / name).write_bytes((run / name).read_bytes())
        response = read('interpretation-response.json')
        response['text'] = fenced
        (copy / 'interpretation-response.json').write_text(json.dumps(response))
        try:
            packet(copy)
            result = 'accepted'
        except (ValueError, KeyError, TypeError) as exc:
            result = type(exc).__name__
        probes.append({'probe': 'fenced_json_review_parity',
                       'business_parser_accepts': object_response(fenced) == answer,
                       'review_packet': result})

    context = trade_context(trade, sheet)
    raw_row = trade['data']['series'][0]['product_breakdown'][0]
    context_row = next(f['value'] for f in context['facts'] if isinstance(f['value'], dict))
    probes.append({'probe': 'omitted_analysis_inputs',
                   'tool_has_product_scope_weight': 'share_of_scope_imports_percent' in raw_row,
                   'context_has_product_scope_weight': 'share_of_scope_imports_percent' in context_row,
                   'context_has_source_limitations': 'limitations' in context})
    questions = [
        '请使用目前已有的2026-07数据说明存档政策全部登记商品的贸易规模。',
        '请分析2026-07全部登记商品，不做因果分析或预测。',
    ]
    for question in questions:
        try:
            validate_plan({'kind': 'brief', 'month': '2026-07', 'hts8': None}, question)
            result = 'accepted'
        except ValueError as exc:
            result = str(exc)
        probes.append({'probe': 'scope_filter', 'question': question,
                       'plan_result': result, 'policy_filter': scope_check(question)})

    return {'status': 'diagnostics_recorded', 'api_calls': 0,
            'evidence_run': str(run.relative_to(root)),
            'boundary': '合成反例检查接口行为，不是模型准确率；无提醒仍待人工审阅。',
            'evidence_hashes': {name: hashlib.sha256((run / name).read_bytes()).hexdigest() for name in FILES},
            'code_hashes': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in (
                'src/tradeintel_ai/fact_interpretation.py',
                'src/tradeintel_ai/business_workflow.py',
                'src/tradeintel_ai/interpretation_review_store.py')},
            'probes': probes}


if __name__ == '__main__':
    print(json.dumps(diagnose(), ensure_ascii=False, indent=2))
