#!/usr/bin/env python3
"""CLI for the actual provider experiment executor (offline; see module doc).

Examples:
    python scripts/run_provider_experiment.py --package <brief-view包> \
        --contract C --output <run目录> --stub ok
    python scripts/run_provider_experiment.py --package ... --contract B \
        --output ... --stub timeout

Without --stub the real path is considered, but it refuses unless the
frozen-model marker exists AND --authorize-real-call is passed.  This phase
has no frozen marker, so every run is stub-based.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tradeintel_ai.provider_executor import run_experiment


def _builtin_stub(kind: str):
    import json
    import time

    def stub(messages, timeout):
        stub.calls = getattr(stub, "calls", 0) + 1
        time.sleep(0.01)
        if kind == "timeout":
            raise TimeoutError("provider did not answer within the timeout")
        if kind == "error":
            raise RuntimeError("provider connection reset")
        if kind == "overlong":
            raw = json.dumps({"text": "长" * 4000}, ensure_ascii=False)
        else:
            # The user message IS the view JSON; build a minimal valid C answer
            # from it exactly like the offline fake pipeline does.
            from scripts.run_fake_experiment import _fake_answer_from_view
            view = json.loads(messages[1]["content"])
            raw = json.dumps(_fake_answer_from_view(
                view, "stub回答：两个排序衡量不同问题，需结合政策范围人工审阅。"), ensure_ascii=False)
        return raw, {"prompt_tokens": 100, "completion_tokens": 50, "stub": True, "kind": kind}

    stub.model_name = f"builtin-stub-{kind}"
    return stub


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--contract", choices=("B", "C", "E"), required=True,
                        help="B自由文本、C旧证据合同、E固定事实最小解释合同")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stub", choices=("ok", "timeout", "error", "overlong"), default=None,
                        help="injected provider stub (offline acceptance)")
    parser.add_argument("--authorize-real-call", action="store_true",
                        help="explicit human authorization for a REAL provider call "
                             "(also requires the frozen-model marker)")
    parser.add_argument("--experiment-id", default=None,
                        help="explicit isolated experiment namespace; required for S3 runs")
    args = parser.parse_args()
    provider = _builtin_stub(args.stub) if args.stub else None
    result = run_experiment(ROOT, package=args.package, contract=args.contract,
                            output=args.output, provider=provider,
                            authorize_real_call=args.authorize_real_call,
                            experiment_id=args.experiment_id)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") in ("completed",) else 2


if __name__ == "__main__":
    raise SystemExit(main())
