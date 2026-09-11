"""Natural-language research-plan entry; confirmation is always explicit."""
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
from tradeintel_ai.model_adapter import OpenAICompatibleConfig
from tradeintel_ai.research_models import ResearchPlannerModel, ResearchPolicyModel
from tradeintel_ai.unified_research import UnifiedResearchWorkflow, inspect_delivery


def main(argv=None):
    parser = argparse.ArgumentParser(description='中文问题→待确认研究计划→证据约束简报；默认只展示计划。')
    entry = parser.add_mutually_exclusive_group(required=True)
    entry.add_argument('--question')
    entry.add_argument('--inspect', type=Path, help='只核对已有交付文件，不调用模型')
    parser.add_argument('--confirm', action='store_true')
    parser.add_argument('--generate', action='store_true', help='确认后再调用一次政策回答模型')
    parser.add_argument('--output-root', type=Path, default=ROOT / 'tmp/unified-research')
    args = parser.parse_args(argv)
    if args.inspect is not None:
        state = inspect_delivery(args.inspect)
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0 if state.get('verified') else 2
    key = os.environ.get('TRADEINTEL_MODEL_API_KEY', '')
    if not key:
        key = getpass.getpass('GLM API key（隐藏输入，不保存）：')
    if not key.strip():
        parser.error('没有规划模型密钥，未执行。')
    config = OpenAICompatibleConfig.from_env({**os.environ, 'TRADEINTEL_MODEL_API_KEY': key})
    planner = ResearchPlannerModel(config)
    workflow = UnifiedResearchWorkflow(planner, require_comparison=True,
                                       require_search_query=True,
                                       require_request_units=True,
                                       derive_request_offsets=True,
                                       planner_source_kind='live')
    run = args.output_root / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8])
    preview = workflow.prepare(args.question, audit_output=run / 'planning', secret=key)
    print(json.dumps(preview, ensure_ascii=False, indent=2))
    if preview['status'] != 'needs_confirmation' or not args.confirm:
        if preview['status'] == 'needs_confirmation':
            print('尚未执行。--confirm进入交互确认模式，重新规划后须核对当次计划。')
        return 0 if preview['status'] in ('needs_confirmation', 'needs_clarification', 'needs_scope_selection') else 2
    if not sys.stdin.isatty():
        workflow.cancel()
        parser.error('请在交互终端核对当次计划后确认；未执行。')
    if input('确认执行上面这份计划？输入 yes：').strip().lower() != 'yes':
        workflow.cancel()
        print('已取消，未执行。')
        return 0
    output = run / 'delivery'
    model = None
    if args.generate:
        model = ResearchPolicyModel(config)
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
