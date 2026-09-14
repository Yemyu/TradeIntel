"""Natural-language research-plan entry; confirmation is always explicit."""
import argparse
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import sys
import uuid
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tradeintel_ai.model_adapter import OpenAICompatibleConfig
from tradeintel_ai.research_models import ResearchPlannerModel, ResearchPolicyModel
from tradeintel_ai.quote_gap_audit import digest_audit
from tradeintel_ai.unified_research import build_product_workflow, inspect_delivery
from tradeintel_ai.local_provider_config import load_config
from tradeintel_ai.prospective_runner import paired_policy_messages


class ProductPolicyModel(ResearchPolicyModel):
    """Use the policy message construction exercised by the 0140 batch."""
    def complete(self, *, messages, tools):
        users = [m for m in messages if m.get('role') == 'user']
        if len(users) != 1 or tools:
            raise ValueError('unexpected policy input')
        request = json.loads(users[0]['content'])
        return super().complete(messages=paired_policy_messages(
            request['question'], request.get('as_of_publication', request.get('as_of')),
            request['evidence']), tools=[])


def show_preview(preview, run, verbose=False):
    if verbose:
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return
    print('\n待确认计划：' + str(preview.get('status')))
    print(preview.get('response') or preview.get('coverage_preview') or '请查看计划文件中的缺失项。')
    plan = preview.get('plan') or {}
    trade = plan.get('trade')
    if trade:
        origins = {'other_origins': '其他原产地（不含中国）', 'China': '中国', 'all_origins': '全部原产地'}
        print('贸易范围：' + origins.get(trade.get('origin'), str(trade.get('origin'))))
        print('月份：' + '、'.join(trade.get('months') or []))
        print('商品：' + (trade.get('hs6') or 'List 1政策暴露整体'))
        print('指标：美元消费进口额；仅描述性分析，不估计因果。')
        comparison = plan.get('comparison') or {}
        if comparison.get('kind') == 'endpoint':
            print('比较：' + comparison['current_month'] + ' 相对于 ' + comparison['reference_month'])
    print('完整计划与记录：' + str(run))


def main(argv=None):
    parser = argparse.ArgumentParser(description='中文问题→待确认研究计划→证据约束简报；默认只展示计划。')
    entry = parser.add_mutually_exclusive_group(required=True)
    entry.add_argument('--question')
    entry.add_argument('--exposure-demo', action='store_true', help='新政策固定开发案例：最多三次模型请求，生成待审阅初稿')
    entry.add_argument('--inspect', type=Path, help='只核对已有交付文件，不调用模型')
    parser.add_argument('--confirm', action='store_true')
    parser.add_argument('--exposure-resume-selection', type=Path, help='复用指定演示已保存的规划响应，不重新调用规划模型')
    parser.add_argument('--exposure-case', choices=['july-scope', 'june-tungsten', 'may-tungsten'], default='july-scope')
    parser.add_argument('--generate', action='store_true', help='确认后再调用一次政策回答模型')
    parser.add_argument('--verbose', action='store_true', help='显示完整JSON诊断信息')
    parser.add_argument('--allow-host-gap-review', action='store_true',
                        help='允许对模型漏掉的普通分隔符进行独立逐项审查；默认严格拒绝')
    parser.add_argument('--output-root', type=Path, default=ROOT / 'tmp/unified-research')
    args = parser.parse_args(argv)
    if args.exposure_resume_selection and not args.exposure_demo:
        parser.error('--exposure-resume-selection 只适用于 --exposure-demo')
    if args.exposure_demo:
        if args.confirm or args.generate or args.allow_host_gap_review:
            parser.error('--exposure-demo 不与旧案例确认/生成选项混用')
        from tradeintel_ai.policy_exposure_workflow import run_exposure_demo
        class ExposureModel(ResearchPlannerModel):
            max_output_tokens = 4096
        config = replace(load_config(), timeout_seconds=180)
        if not config.api_key:
            parser.error('缺少本地 API 配置；未调用模型。')
        run = args.output_root / ('exposure-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8])
        result = run_exposure_demo(ExposureModel(config), run, secret=config.api_key,
                                  resume_selection=args.exposure_resume_selection, case=args.exposure_case)
        print(json.dumps({**result, 'output': str(run)}, ensure_ascii=False, indent=2))
        return 0 if result['status'] == 'draft_needs_review' else 2
    if args.inspect is not None:
        state = inspect_delivery(args.inspect)
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0 if state.get('verified') else 2
    if args.confirm and not sys.stdin.isatty():
        parser.error('交互确认需要终端；尚未调用模型。')
    config = load_config()
    key = config.api_key or ''
    if not key:
        key = getpass.getpass('GLM API key（隐藏输入，不保存）：')
    if not key.strip():
        parser.error('没有规划模型密钥，未执行。')
    config = replace(config, api_key=key)
    planner = ResearchPlannerModel(config)
    workflow = build_product_workflow(
        planner, planner_source_kind='live',
        allow_host_gap_review=args.allow_host_gap_review)
    run = args.output_root / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8])
    preview = workflow.prepare(args.question, audit_output=run / 'planning', secret=key)
    workflow._write_json(run, 'preview.json', preview, key)
    show_preview(preview, run, args.verbose)
    if preview['status'] not in ('needs_confirmation', 'needs_gap_review') or not args.confirm:
        if preview['status'] == 'needs_confirmation':
            print('尚未执行。--confirm进入交互确认模式，重新规划后须核对当次计划。')
        elif preview['status'] == 'needs_gap_review':
            print('检测到模型引文漏掉分隔符。请保留 --allow-host-gap-review 并加 --confirm，逐项审查后才可继续。')
        return 0 if preview['status'] in ('needs_confirmation', 'needs_gap_review',
                                          'needs_clarification', 'needs_scope_selection') else 2
    if not sys.stdin.isatty():
        workflow.cancel()
        parser.error('请在交互终端核对当次计划后确认；未执行。')
    if preview['status'] == 'needs_gap_review':
        audit = preview['gap_audit']
        gaps = [item for item in audit['segments']
                if item.get('source') == 'host_gap' and str(item.get('quote', '')).strip()]
        decisions = []
        for index, gap in enumerate(gaps, 1):
            prompt = ('gap ' + str(index) + '（原文位置 ' + str(gap['start']) + '–'
                      + str(gap['end']) + '，字符 ' + repr(gap['quote'])
                      + '）是否确认只是句间普通分隔符？输入 yes：')
            accepted = input(prompt).strip().lower() == 'yes'
            reason = input('请简述该分隔符是否改变需求含义及理由：').strip()
            accepted = accepted and bool(reason)
            decisions.append({'start': gap['start'], 'end': gap['end'],
                              'quote': gap['quote'],
                              'status': 'accepted_separator' if accepted else 'rejected',
                              'reason': reason or '未提供审查理由。'})
        all_accepted = all(item['status'] == 'accepted_separator' for item in decisions)
        submission = {'audit_sha256': digest_audit(audit), 'reviewer': 'interactive-user',
             'overall': {'status': 'pass' if all_accepted else 'fail',
                         'reason': ('用户已逐项核对全部gap。' if all_accepted
                                    else '至少一个gap未被确认，停止执行。')},
             'gaps': decisions}
        workflow._write_json(run, 'gap-review-submission.json', submission, key)
        reviewed = workflow.approve_gap_review(preview['gap_review_token'], submission)
        workflow._write_json(run, 'gap-review-result.json', reviewed, key)
        print(json.dumps(reviewed, ensure_ascii=False, indent=2))
        if reviewed['status'] != 'needs_confirmation':
            workflow.cancel()
            return 0
        preview = reviewed
    if input('确认执行上面这份计划？输入 yes：').strip().lower() != 'yes':
        workflow.cancel()
        print('已取消，未执行。')
        return 0
    output = run / 'delivery'
    model = None
    if args.generate:
        model = ProductPolicyModel(config)
    result = workflow.confirm(preview['confirmation_token'], output, model=model,
                              source_kind='live' if args.generate else 'fixture', secret=key)
    delivery = inspect_delivery(output)
    print(json.dumps({'status': result['status'], 'delivery': delivery,
                      'report': str(output / 'report.zh-CN.md') if delivery.get('verified') else None,
                      'planner_model_calls': result.get('planner_model_calls', 0),
                      'model_calls_total': result.get('model_calls_total',
                                                      result.get('total_model_calls', 0)),
                      'new_api_calls': result.get('new_api_calls', 0),
                      'new_api_calls_total': result.get('new_api_calls_total',
                                                        result.get('new_api_calls', 0))},
                     ensure_ascii=False, indent=2))
    return 0 if delivery.get('verified') and result['status'] in {'research_draft', 'trade_draft', 'policy_draft', 'policy_evidence_only'} else 2


if __name__ == '__main__':
    raise SystemExit(main())
