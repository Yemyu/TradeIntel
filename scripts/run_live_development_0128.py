#!/usr/bin/env python3
"""Preflight or run the bounded 0128 live-development batch.

Default is a no-network inspection. --freeze persists the exact preflight;
--execute starts that batch, --pending reads review packets, --submit records
an explicit host decision, and --resume continues a waiting-review batch.
Credentials are read only for preflight/execution, never for review commands.

Required environment:

    TRADEINTEL_MODEL_NAME=provider-model-name

Optional environment:

    TRADEINTEL_MODEL_BASE_URL=https://open.bigmodel.cn/api/paas/v4
    TRADEINTEL_MODEL_API_KEY=...
    TRADEINTEL_MODEL_TIMEOUT=60
    TRADEINTEL_MODEL_TEMPERATURE=0

Exit codes: 0 successful command, 2 invalid/not-ready, 3 stopped run,
4 waiting for host review. A stopped batch cannot be resumed or retried.
"""

from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tradeintel_ai.live_development import live_preflight, run_live_development, pending_reviews, review_store
from tradeintel_ai.model_adapter import ModelAdapterError, OpenAICompatibleConfig
from tradeintel_ai.local_provider_config import load_config, save_glm_key


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",
                        help="批次目录；预检/首次执行用新目录，审核/恢复用同一已有目录")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--configure', action='store_true', help='隐藏输入GLM密钥，保存到项目.local/glm.json（不上传Git）')
    parser.add_argument('--model', default='glm-4.7', help='首次配置的模型，默认glm-4.7')
    parser.add_argument('--profile', choices=('four-scenes', 'policy-followup'), default=None,
                        help='仅预检/冻结时选择；执行和恢复自动读取冻结范围')
    actions.add_argument('--freeze', action='store_true', help='零网络检查并保存本批预检快照')
    actions.add_argument('--execute', action='store_true', help='从冻结预检启动，到待审处暂停')
    actions.add_argument('--resume', action='store_true', help='校验后继续待审批次')
    actions.add_argument('--pending', action='store_true', help='读取完整待审材料，不需要密钥')
    actions.add_argument('--submit', metavar='JSON_FILE', help='提交包含slot和submission的宿主审核JSON')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.configure:
            if not sys.stdin.isatty():
                raise ValueError('configure requires an interactive local terminal')
            key = getpass.getpass('GLM API key（隐藏输入，保存于本项目，不上传Git）：').strip()
            path = save_glm_key(key, model=args.model)
            print('配置已保存：', path, '；未发送模型请求。')
            return 0
        if not args.output:
            raise ValueError('output required')
        if args.profile and (args.execute or args.resume or args.pending or args.submit):
            raise ValueError('profile is selected at freeze only')
        output = Path(args.output).expanduser()
        if args.pending:
            summary = pending_reviews(output)
        elif args.submit:
            payload = json.loads(Path(args.submit).read_text())
            decision = review_store(output).submit(payload['slot'], payload['submission'])
            summary = {'status': 'review_recorded', 'decision': decision, 'network_calls': 0}
        else:
            config = load_config()
            if args.execute or args.resume:
                summary = run_live_development(output, config, resume=args.resume)
            else:
                summary = live_preflight(output, config, persist=args.freeze,
                                         profile=args.profile or 'four-scenes')
    except (ModelAdapterError, ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "command_failed", "error_type": type(exc).__name__},
                         ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if (args.execute or args.resume) and summary.get('status') == 'waiting_review':
        return 4
    if (args.execute or args.resume) and summary.get("status") != "completed":
        return 3
    if not any((args.execute, args.resume, args.pending, args.submit)) and not summary.get("ready_for_bounded_run"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
