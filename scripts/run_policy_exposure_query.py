"""Run the registered policy-exposure query tool from the project checkout."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.tradeintel_ai.policy_exposure_tools import (
    POLICY_EXPOSURE_ID,
    get_policy_exposure_series,
)
from src.tradeintel_ai.repository import RepositoryError
from src.tradeintel_ai.exposure_report import FACTS, render_exposure_report
from datetime import datetime, timezone


def _month(value: str) -> str:
    if len(value) != 7 or value[4] != "-":
        raise argparse.ArgumentTypeError("月份必须使用 YYYY-MM 格式")
    try:
        year, month = int(value[:4]), int(value[5:])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("月份必须使用 YYYY-MM 格式") from exc
    if year < 1900 or not 1 <= month <= 12:
        raise argparse.ArgumentTypeError("月份无效")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-id", default=POLICY_EXPOSURE_ID)
    parser.add_argument("--origin", choices=("China", "other_origins", "all_origins"), default="China")
    parser.add_argument("--hts8")
    parser.add_argument("--start", type=_month, default="2025-01")
    parser.add_argument("--end", type=_month, default="2026-07")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown-output", type=Path, help="仅单月：输出明确标注为程序生成的中文分析表，不调用 AI")
    args = parser.parse_args(argv)
    if args.markdown_output and args.start != args.end:
        parser.error('--markdown-output 目前仅支持单月')
    try:
        result = get_policy_exposure_series(
            policy_id=args.policy_id, origin=args.origin, hts8=args.hts8,
            start=args.start, end=args.end,
        )
    except (OSError, ValueError, KeyError, RepositoryError) as exc:
        print(f"查询失败：{exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.markdown_output:
        actions = ['origin_breakdown'] if args.hts8 else ['product_breakdown', 'origin_breakdown']
        draft = render_exposure_report(json.dumps({'next_steps': actions}),
                                       [result], report_date=datetime.now(timezone.utc).date().isoformat())
        draft = draft.replace('贸易暴露简报（受约束初稿，待审阅）', '贸易暴露分项表（程序生成，非 AI 回答）')
        draft = draft.replace('AI 选择的后续调查顺序', '程序预设的后续调查建议')
        draft = draft.replace('AI 选择调查方向', '本表未调用 AI，调查方向为程序预设')
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(draft, encoding='utf-8')
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(json.dumps({"status": result["status"], "output": str(args.output)}, ensure_ascii=False, indent=2))
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
