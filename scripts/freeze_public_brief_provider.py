"""Write a public-brief provider freeze after an explicit readiness decision.

This command never reads an API key and never calls a model.  It refuses the
current exploratory matrix entries until a reviewer changes exactly one
provider's status to ``ready_for_formal`` and reruns the preflight.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_public_brief_eval import (  # noqa: E402
    BUDGET_PROTOCOL_V2,
    BUDGET_PROTOCOL_V3,
    DEFAULT_MATRIX,
    DEFAULT_PACKAGE,
    build_freeze_spec,
    preflight,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-id", required=True)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budget-protocol", choices=(BUDGET_PROTOCOL_V2, BUDGET_PROTOCOL_V3),
                        default=BUDGET_PROTOCOL_V3,
                        help="正文预算协议；新冻结默认v3，v2仅用于复现历史配置")
    args = parser.parse_args()
    try:
        plan = preflight(matrix_path=args.matrix, package_path=args.package,
                         provider_id=args.provider_id)
        provider = plan["provider"]
        if provider.get("status") != "ready_for_formal":
            raise ValueError("该 provider 尚未被审阅为 ready_for_formal；只做预检，不生成冻结")
        if args.output.exists():
            raise ValueError("冻结文件已存在，不覆盖历史记录")
        freeze = build_freeze_spec(provider=provider, package_path=args.package,
                                   matrix_path=args.matrix,
                                   budget_protocol=args.budget_protocol)
        freeze["status"] = "ready_for_formal"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "frozen", "output": str(args.output.resolve()),
                      "api_calls": 0}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
