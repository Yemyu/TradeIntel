"""Combine audited archived-plan trade output with real official policy retrieval.

Integration harness only: confirmation is simulated, zero live model calls.
"""
import argparse
import json
from pathlib import Path
from check_business_delivery import check_delivery
from run_policy_retrieval import PolicyRetriever, build_corpus, markdown_report

ROOT = Path(__file__).resolve().parents[1]


def check_combined():
    business_audit, business_report = check_delivery()
    retriever = PolicyRetriever(build_corpus(ROOT))
    evidence = retriever.search('第一批关税何时生效，额外税率是多少？', as_of='2018-07-06')
    joined = ' '.join(h['text'] for h in evidence['hits'])
    checks = {
        'existing_business_audit_passed': business_audit['passed'],
        'initial_notice_only': bool(evidence['hits']) and all(h['source']=='initial_notice' for h in evidence['hits']),
        'effective_date_present_in_retrieved_text': 'July 6, 2018' in joined,
        'rate_present_in_retrieved_text': '25 percent' in joined or '25%' in joined,
        'page_links_present': all('#page=' in h['citation_url'] for h in evidence['hits']),
        'causal_block_preserved': business_audit['checks']['causal_block_preserved'],
    }
    report = '# TradeShock：政策原文 + 贸易金额联合演示\n\n'
    report += '> 零 API 集成测试：金额报告使用已归档规划，确认由测试程序模拟；政策证据为本次本地检索。不是一次新模型端到端验收。\n\n'
    report += business_report + '\n---\n\n' + markdown_report(evidence)
    audit = {'passed':all(checks.values()), 'checks':checks, 'business_audit':business_audit,
             'new_api_calls':0, 'confirmation_actor':'test_harness',
             'retrieved_evidence_ids':[h['id'] for h in evidence['hits']],
             'semantic_answer_accuracy_measured':False}
    return audit, report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT/'tmp/policy-business-delivery')
    args = parser.parse_args()
    audit, report = check_combined()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir/'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2)+'\n')
    (args.output_dir/'report.zh-CN.md').write_text(report)
    print(json.dumps(audit,ensure_ascii=False,indent=2))
    raise SystemExit(0 if audit['passed'] else 1)
