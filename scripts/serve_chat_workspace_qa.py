"""Temporary chat UI QA with real stored data and a scripted (not AI) model."""
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from tradeintel_ai.web_app import create_server
from tests.test_trade_agent_mainline import ScriptedModel

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tmp/handoff-runs/trade-demo-data-20260925"


def guard(event, args):
    if event == "socket.connect" and (
        not isinstance(args[1], tuple) or args[1][0] not in {"127.0.0.1", "::1"}
    ):
        raise RuntimeError("UI QA forbids external connections")


def main():
    sys.addaudithook(guard)
    status = {"configured": True, "provider": "deepseek", "model": "offline-scripted-fixture",
              "connection": "untested", "reasoning": "default",
              "models": {"deepseek": ["offline-scripted-fixture"], "glm": [], "qianwen": []}}
    with tempfile.TemporaryDirectory(prefix="trade-chat-qa-") as folder, \
            patch("tradeintel_ai.local_provider_config.product_status", return_value=status), \
            patch("tradeintel_ai.local_provider_config.save_product_config", side_effect=RuntimeError("QA does not save model configuration")), \
            patch("tradeintel_ai.local_provider_config.probe_product_model", side_effect=RuntimeError("QA does not call model APIs")):
        server = create_server(root=Path(folder), trade_data_root=DATA,
                               host="127.0.0.1", port=0,
                               trade_model_factory=lambda *_: ScriptedModel())
        server.RequestHandlerClass.static_root = ROOT / "web"
        print(f"OFFLINE SCRIPTED FIXTURE http://127.0.0.1:{server.server_address[1]}/preview/#workspace", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
