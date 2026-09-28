"""Offline review aid: validate an answer, then print non-binding review hints."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.tradeintel_ai.public_brief_explanation import parse
from src.tradeintel_ai.public_review_hints import review_hints


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--answer", type=Path, required=True)
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    answer = parse(args.answer.read_text(encoding="utf-8"), snapshot["report"])
    print(json.dumps({"status": "manual_review_required", "raw_sha256": answer["raw_sha256"],
                      "hints": review_hints(answer, question=snapshot["question"]),
                      "boundary": "提示仅供审阅，不自动改答、判错或批准；无提示也不代表正确。"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
