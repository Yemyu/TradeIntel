"""Offline v2 evidence demo by default; --live explicitly calls the configured model."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.tradeintel_ai.agent import ModelResponse, ModelToolCall
from src.tradeintel_ai.evidence_v2 import EvidenceAgentV2
from src.tradeintel_ai.model_adapter import OpenAICompatibleModel, ModelAdapterError


class DemoModel:
    def complete(self, *, messages, tools):
        if len(messages) == 1:
            return ModelResponse(tool_calls=(
                ModelToolCall("policy", "get_policy_event", {}),
                ModelToolCall("change", "get_descriptive_change", {"comparison_id":"immediate_post_same_months"}),
                ModelToolCall("matching", "get_causal_readiness", {})))
        return ModelResponse(text="只能报告描述性变化，不能说关税导致了变化。", metadata={"finish_reason":"stop"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?", default="请报告2018年8—12月中国原产进口变化及匹配情况。")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        model = OpenAICompatibleModel.from_env() if args.live else DemoModel()
        result = EvidenceAgentV2(model).answer(args.question)
        result["execution_mode"] = "live_v2_unvalidated" if args.live else "offline_fixed_calls_demo"
    except ModelAdapterError:
        print("模型连接或配置失败，请检查本地配置；未显示密钥。")
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("真实模型试运行" if args.live else "离线固定工具演示：不代表模型能理解任意提问")
        print(result.get("response", result.get("error")))
    return 1 if result["status"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
