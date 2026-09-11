"""A single confirmed entry for trade evidence + policy explanation."""
import argparse
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))
from tradeintel_ai.model_adapter import OpenAICompatibleConfig
from tradeintel_ai.policy_workflow import BoundedPolicyModel
from tradeintel_ai.research_brief import ResearchBrief, trade_request


def main(argv=None):
    parser = argparse.ArgumentParser(description='生成可追溯的中文贸易政策研究简报；默认零API。')
    parser.add_argument('--question', required=True)
    parser.add_argument('--natural-language', action='store_true', help='由模型规划问题，现场核对后确认')
    parser.add_argument('--months', nargs='+')
    parser.add_argument('--origin', choices=['China', 'other_origins', 'all_origins'])
    parser.add_argument('--hs6')
    parser.add_argument('--policy-as-of')
    parser.add_argument('--comparison-kind', choices=['sequence', 'endpoint', 'registered'],
                        help='可选：明确逐月序列、指定基准月比较或登记同期窗口')
    parser.add_argument('--reference-month', help='endpoint 的基准月，例如 2018-09')
    parser.add_argument('--current-month', help='endpoint 的比较月，例如 2018-10')
    parser.add_argument('--comparison-id', help='registered 的登记ID')
    parser.add_argument('--generate', action='store_true', help='确认后调用一次GLM；不自动重试')
    parser.add_argument('--confirm', action='store_true', help='明确确认本次命令给出的范围')
    parser.add_argument('--output-root', type=Path, default=ROOT / 'tmp/research-brief')
    args = parser.parse_args(argv)
    if args.natural_language:
        if (args.months or args.hs6 or args.origin or args.policy_as_of or args.comparison_kind
                or args.reference_month or args.current_month or args.comparison_id):
            parser.error('自然语言模式请把范围写入问题，不与显式范围选项混用。')
        from scripts.run_unified_research import main as natural_main
        forwarded = ['--question', args.question, '--output-root', str(args.output_root)]
        if args.confirm:
            forwarded.append('--confirm')
        if args.generate:
            forwarded.append('--generate')
        return natural_main(forwarded)
    if not args.months:
        parser.error('显式参数模式需要 --months；自然语言模式请使用 --natural-language。')
    if not args.policy_as_of:
        parser.error('显式参数模式必须提供 --policy-as-of；不能悄悄代入资料截止日。')
    workflow = ResearchBrief()
    request = dict(policy_question=args.question, policy_as_of=args.policy_as_of or '2018-07-06',
                   trade=trade_request(args.months, args.origin or 'China', args.hs6))
    comparison = None
    if args.comparison_kind:
        if args.comparison_kind == 'sequence':
            if any((args.reference_month, args.current_month, args.comparison_id)):
                parser.error('sequence 不接受基准月或登记ID。')
            comparison = {'kind': 'sequence'}
        elif args.comparison_kind == 'endpoint':
            if not args.reference_month or not args.current_month or args.comparison_id:
                parser.error('endpoint 必须同时提供 --reference-month 和 --current-month，且不能提供登记ID。')
            comparison = {'kind': 'endpoint', 'reference_month': args.reference_month,
                          'current_month': args.current_month}
        else:
            if not args.comparison_id or any((args.reference_month, args.current_month)):
                parser.error('registered 必须提供 --comparison-id，且不能提供基准月。')
            comparison = {'kind': 'registered', 'comparison_id': args.comparison_id}
    elif any((args.reference_month, args.current_month, args.comparison_id)):
        parser.error('请先提供 --comparison-kind，再提供比较参数。')
    if comparison is not None:
        request['comparison'] = comparison
    try:
        preview = workflow.prepare(request)
    except (ValueError, TypeError):
        parser.error('输入日期或字段不符合要求；未执行。')
    print(json.dumps(preview, ensure_ascii=False, indent=2))
    if preview['status'] != 'needs_confirmation':
        return 2
    if not args.confirm:
        print('尚未执行。核对范围后添加 --confirm；添加 --generate 才会请求模型。')
        return 0
    model = None
    key = ''
    if args.generate and preview['policy_candidate_count']:
        key = os.environ.get('TRADEINTEL_MODEL_API_KEY') or getpass.getpass('GLM API key（隐藏输入，不保存）：')
        if not key.strip():
            parser.error('没有密钥，未执行。')
        model = BoundedPolicyModel(OpenAICompatibleConfig(
            base_url='https://open.bigmodel.cn/api/paas/v4', model='glm-4.7', api_key=key,
            timeout_seconds=60, temperature=0))
    run = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
    output = args.output_root / run
    result = workflow.confirm(preview['confirmation_token'], output, model=model, secret=key)
    print(json.dumps({'status': result['status'], 'new_api_calls': result['new_api_calls'],
                      'policy_status': result.get('policy', {}).get('generation', {}).get('status'),
                      'report': str(output / 'report.zh-CN.md')}, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'research_draft' else 2


if __name__ == '__main__':
    raise SystemExit(main())
