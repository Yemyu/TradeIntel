"""Record a semantic review for one public-brief model answer.

The reviewer sees the saved raw answer and the deterministic report.  This
command only records the decision; it never edits the answer and never opens
the next question automatically.  A major error closes the provider run.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.tradeintel_ai.public_eval_ledger import file_sha256, record_review  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--ledger-root", type=Path, default=ROOT)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--verdict", choices=("pass", "minor_error", "major_error"), required=True)
    parser.add_argument("--note", default="")
    parser.add_argument("--checks", type=Path, required=True,
                        help="四项审阅JSON，每项包含passed和reason")
    parser.add_argument("--ai-assisted", action="store_true",
                        help="审阅过程使用了模型辅助；仍需人工承担最终判断")
    args = parser.parse_args()
    try:
        records = [path for path in args.run_dir.glob("q*/run.json")
                   if json.loads(path.read_text(encoding="utf-8")).get("run_id") == args.run_id]
        if len(records) != 1:
            raise ValueError("目录中找不到与 run-id 匹配的唯一运行记录")
        raw = records[0].parent / "raw-response.txt"
        event = record_review(args.ledger_root, run_id=args.run_id,
                              raw_sha256=file_sha256(raw), verdict=args.verdict,
                              reviewer=args.reviewer, ai_assisted=args.ai_assisted,
                              note=args.note, checks=json.loads(args.checks.read_text(encoding="utf-8")))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "recorded", **event}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
