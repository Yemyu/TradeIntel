"""Run the deterministic TradeShock AI tool-calling baseline locally."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.tradeintel_ai.router import answer_question  # noqa: E402
from src.tradeintel_ai.tools import ToolRegistry  # noqa: E402
from src.tradeintel_ai.agent import MODEL_TOOL_NAMES, MockModel, ToolCallingAgent  # noqa: E402
from src.tradeintel_ai.model_adapter import ModelAdapterError, OpenAICompatibleModel  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?", default="2018 年 Section 301 List 1 后中国进口下降了多少？这能证明关税导致下降吗？")
    parser.add_argument(
        "--comparison-id",
        default="immediate_post_same_months",
        help="已登记的描述性比较 ID",
    )
    parser.add_argument("--schemas", action="store_true", help="只打印模型可调用的五个查询工具 schema")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--mock-agent",
        action="store_true",
        help="使用离线 Mock 模型演示模型—工具循环和因果安全后卫",
    )
    mode.add_argument(
        "--live-agent",
        action="store_true",
        help="使用环境变量配置的 OpenAI-compatible 真实模型",
    )
    args = parser.parse_args()
    registry = ToolRegistry()
    if args.schemas:
        print(json.dumps([s for s in registry.schemas() if s["name"] in MODEL_TOOL_NAMES], ensure_ascii=False, indent=2))
        return 0
    if args.mock_agent:
        result = ToolCallingAgent(MockModel(), registry=registry).answer(args.question)
        execution_mode = "mock_agent"
    elif args.live_agent:
        try:
            model = OpenAICompatibleModel.from_env()
        except ModelAdapterError as exc:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "error": {"type": "model_adapter_config", "message": str(exc)},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        try:
            result = ToolCallingAgent(model, registry=registry).answer(args.question)
        except ModelAdapterError as exc:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "error": {"type": "model_adapter", "message": str(exc)},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        execution_mode = "live_agent"
    else:
        result = answer_question(args.question, registry=registry, comparison_id=args.comparison_id)
        execution_mode = "deterministic_router"
    result["run_metadata"] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "execution_mode": execution_mode,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # 3 explicitly distinguishes an unverified draft from a verified response.
    if result["status"] == "needs_review":
        return 3
    return 0 if result["status"] in {"ok", "needs_clarification"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
