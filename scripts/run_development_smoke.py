"""Default zero-call preflight; explicit interactive review for live development."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tradeintel_ai.model_adapter import OpenAICompatibleConfig
from tradeintel_ai.development_smoke import preflight, run_batch
from tradeintel_ai.answer_checklist import template


def main(argv=None):
    parser = argparse.ArgumentParser(description='0089四场景开发检查；默认零API预检，不是正式准确率验收。')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--allow-host-gap-review', action='store_true', help='0103原文gap独立审查模式')
    parser.add_argument('--neutral-trade-mapping', action='store_true',
                        help='0105贸易领域标签与比较字段分离；需独立审查，默认关闭')
    parser.add_argument('--output', type=Path, help='真实运行必须使用全新目录；不续跑')
    parser.add_argument('--reviewer', help='审查者标识；每次执行和答复均须显式审查')
    args = parser.parse_args(argv)
    env = {**os.environ}
    env.setdefault('TRADEINTEL_MODEL_BASE_URL', 'https://open.bigmodel.cn/api/paas/v4')
    env.setdefault('TRADEINTEL_MODEL_NAME', 'glm-4.7')
    config = OpenAICompatibleConfig.from_env(env)
    try:
        if not args.execute:
            print(json.dumps(preflight(config, checklist_review=True,
                                       host_gap_review=args.allow_host_gap_review,
                                       neutral_trade_mapping=args.neutral_trade_mapping), ensure_ascii=False, indent=2))
            return 0
        if not args.output or not args.reviewer or not sys.stdin.isatty():
            parser.error('真实运行需要全新--output、--reviewer和可交互终端；未调用。')

        def reviewer(packet):
            print(json.dumps(packet, ensure_ascii=False, indent=2))
            print('请核对原文与结果，填写下面的逐项审查JSON。未核验应停止，不接受单词approve。')
            print(json.dumps(template(packet), ensure_ascii=False, indent=2))
            print('计划状态：covered/omitted/wrong_scope/needs_clarification；回答：supported/missing/contradicted/unverifiable。')
            print('supported政策项需witnesses：claim_index/claim_text/citation_id/evidence_excerpt；贸易项需原样记录清单checks。')
            print('overall须pass/fail和理由，检查额外无支持主张及因果边界。输入JSON，独立一行END结束；空内容停止。')
            lines = []
            while True:
                line = input()
                if line == 'END':
                    break
                lines.append(line)
            return json.loads('\n'.join(lines)) if lines else None

        result = run_batch(config, args.output, reviewer=reviewer, reviewer_id=args.reviewer,
                           checklist_review=True, host_gap_review=args.allow_host_gap_review,
                           neutral_trade_mapping=args.neutral_trade_mapping)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['status'] == 'development_review_complete' else 2
    except (ValueError, OSError):
        print('配置、来源或输出路径未通过检查；不自动重试。请核对本地配置和独立输出目录。')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
