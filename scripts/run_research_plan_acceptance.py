"""Offline development preflight. Live execution retired by review 0073.

The historical runner below is retained for audit, not online acceptance.
"""
import argparse
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
FIXED_BASE_URL = 'https://open.bigmodel.cn/api/paas/v4'
FIXED_MODEL = 'glm-4.7'
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))
from tradeintel_ai.acceptance_ledger import AcceptanceLedger
from tradeintel_ai.intent_repair import BoundedModel
from tradeintel_ai.model_adapter import OpenAICompatibleConfig, ModelAdapterError
from tradeintel_ai.policy_workflow import BoundedPolicyModel
from tradeintel_ai.unified_research import UnifiedResearchWorkflow
from scripts.preflight_research_plan_acceptance import (
    REFERENCE, load_questions, preflight,
)


def compare_plan(preview, reference):
    if preview.get('status') != 'needs_confirmation':
        return False
    plan = preview.get('plan', {})
    trade = plan.get('trade', {})
    return (
        plan.get('policy_question') == reference.get('policy_question')
        and plan.get('policy_as_of') == reference.get('policy_as_of')
        and trade.get('origin') == reference.get('origin')
        and trade.get('months') == reference.get('months')
        and trade.get('granularity') == reference.get('granularity')
        and trade.get('hs6') == reference.get('hs6')
        and trade.get('causal_effect') is False
    )


def expected_terminal(preview, reference):
    expected = reference['expected_status']
    if expected == 'capability_blocked':
        return preview.get('status') == 'needs_clarification' and bool(preview.get('assessment'))
    return preview.get('status') == expected


def run(*, execute=False, output=None, config=None):
    # 0073: this batch cannot establish the 0066 product contract. Keep the
    # original implementation available for inspection, but never run it live.
    if execute:
        raise ValueError('0073: acceptance batch retired to development; live execution disabled')
    preflight_report = preflight()
    questions = load_questions()
    references = json.loads(REFERENCE.read_text())
    ids = [row['id'] for row in questions]
    if not execute:
        return {
            'status': 'development_preflight_only',
            'online_eligible': False,
            'review_decision': '0073',
            'question_count': len(ids),
            'maximum_planning_calls': len(ids),
            'maximum_answer_calls': len(preflight_report['answerable_ids']),
            'maximum_total_model_calls': len(ids) + len(preflight_report['answerable_ids']),
            'model_calls': 0, 'online_run': False,
            'preflight_sha256': preflight_report['sha256'],
        }
    if config is None:
        raise ValueError('live execution requires a fixed model configuration')
    if (config.base_url != FIXED_BASE_URL or config.model != FIXED_MODEL
            or config.timeout_seconds != 60 or config.temperature != 0):
        raise ValueError('configuration differs from the frozen acceptance settings')
    if not config.api_key or not config.api_key.isascii() or any(c.isspace() for c in config.api_key):
        raise ValueError('invalid model key')
    output = Path(output or ROOT / 'tmp/research-plan-acceptance' /
                  (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex[:8]))
    if output.exists():
        raise ValueError('refusing to overwrite a previous acceptance run')
    output.mkdir(parents=True)
    ledger = AcceptanceLedger(ids, max_planning=24, max_answers=12)
    report = {'status': 'running', 'online_run': True,
              'started_at_utc': datetime.now(timezone.utc).isoformat(),
              'preflight_sha256': preflight_report['sha256'], 'questions': []}
    planner_model = BoundedModel(config)
    answer_model = BoundedPolicyModel(config)
    for row in questions:
        qid, question, ref = row['id'], row['question'], references[row['id']]
        try:
            workflow = UnifiedResearchWorkflow(planner_model)
            preview = workflow.prepare(question)
            plan_match = compare_plan(preview, ref) if ref['expected_status'] == 'plan' else None
            terminal_match = (plan_match if ref['expected_status'] == 'plan'
                              else expected_terminal(preview, ref))
            item = {'id': qid, 'category': row['category'], 'question': question,
                    'expected_status': ref['expected_status'], 'preview': preview,
                    'plan_match': plan_match, 'terminal_match': terminal_match,
                    'answer_attempted': False}
            if ref['expected_status'] == 'plan' and preview.get('status') == 'needs_confirmation':
                run_dir = output / qid
                result = workflow.confirm(preview['confirmation_token'], run_dir,
                                          model=answer_model, source_kind='live',
                                          secret=config.api_key)
                item['result'] = result
                item['answer_attempted'] = True
                terminal = result.get('status', 'unknown')
            else:
                terminal = preview.get('status', 'unknown')
            ledger.record(qid, terminal_status=terminal,
                          expected_status=ref['expected_status'],
                          planning_calls=1, answer_attempted=item['answer_attempted'],
                          detail={'plan_match': plan_match, 'terminal_match': terminal_match})
            report['questions'].append(item)
        except (ModelAdapterError, TimeoutError, OSError, ValueError) as exc:
            ledger.record(qid, terminal_status='provider_or_host_error',
                          expected_status=ref['expected_status'], planning_calls=1,
                          detail={'error_type': type(exc).__name__})
            report['questions'].append({'id': qid, 'category': row['category'],
                                        'question': question,
                                        'expected_status': ref['expected_status'],
                                        'terminal_match': False,
                                        'error_type': type(exc).__name__})
            ledger.stop(type(exc).__name__)
            break
    report.update(ledger.summary(), finished_at_utc=datetime.now(timezone.utc).isoformat(),
                  model_adopted=False, semantic_scores=None)
    (output / 'ledger.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return {'status': report['status'], 'recorded_questions': report['recorded_questions'],
            'total_model_calls': report['total_model_calls'], 'output': str(output),
            'model_adopted': False, 'semantic_scores': None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if not args.execute:
            print(json.dumps(run(), ensure_ascii=False, indent=2))
            return 0
        # Check retirement before asking for a credential.
        run(execute=True)
        key = os.environ.get('TRADEINTEL_MODEL_API_KEY') or getpass.getpass(
            '模型API key（隐藏输入，不保存）：')
        config = OpenAICompatibleConfig.from_env(
            {**os.environ, 'TRADEINTEL_MODEL_API_KEY': key})
        result = run(execute=True, output=args.output, config=config)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, ModelAdapterError):
        print('验收配置或冻结文件检查失败；没有显示密钥。')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
