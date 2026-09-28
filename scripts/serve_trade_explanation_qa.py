"""Browser QA for the generic report with an offline model stub.

This does not use the saved product key or make any external request.  Its
answers are test fixtures and must never be reported as model-quality results.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from tradeintel_ai.agent import ModelResponse
from tradeintel_ai import local_provider_config
from tradeintel_ai.trade_explanation import PROTOCOL
from tradeintel_ai.web_app import create_server


def network_guard(event, args):
    if event == "socket.connect" and (
        not isinstance(args[1], tuple) or args[1][0] not in {"127.0.0.1", "::1"}
    ):
        raise RuntimeError("offline QA cannot connect to an external service")


class FakeModel:
    def complete(self, *, messages, tools):
        payload = json.loads(messages[-1]["content"])
        first_by_direction = {}
        for observation in payload["observations"]:
            direction = observation["id"].split(".", 1)[0]
            first_by_direction.setdefault(direction, observation["id"])
        selected = payload["required_observation_ids"] or list(first_by_direction.values())
        by_id = {item["id"]: item for item in payload["observations"]}
        answer = {"schema_version": PROTOCOL,
                  "report_sha256": payload["report_sha256"],
                  "interpretations": [
                      {"observation_id": key,
                       "text": (f"离线替身文字：金额较上月{by_id[key]['trend']}，还需核对数量和价格资料。"
                                if "trend" in by_id[key] else
                                "离线替身文字：金额需要结合数量和价格资料才能进一步理解。")}
                      for key in selected]}
        return ModelResponse(text=json.dumps(answer, ensure_ascii=False),
                             metadata={"model": "offline-stub", "usage": {"total_tokens": 0}})


if __name__ == "__main__":
    sys.addaudithook(network_guard)
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="trade-explanation-qa-") as folder:
        path = Path(folder) / "product-model.json"
        with patch.object(local_provider_config, "PRODUCT_CONFIG_PATH", path):
            local_provider_config.save_product_config("deepseek", "offline-stub", "x" * 24,
                                                      reasoning="none")
            server = create_server(root=root, port=8897,
                                   trade_model_factory=lambda config, params: FakeModel())
            print("OFFLINE STUB ONLY http://127.0.0.1:8897/preview/", flush=True)
            try:
                server.serve_forever()
            finally:
                server.server_close()
