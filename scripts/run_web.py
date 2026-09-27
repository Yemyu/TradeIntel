"""Start the local Chinese TradeShock AI page.

The server binds to localhost by default.  It does not open a browser and it
does not expose the project-local model key.  Stop it with Ctrl-C.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.trade_demo_data_bundle import verify as verify_trade_data_bundle  # noqa: E402
from tradeintel_ai.web_app import DEFAULT_WEB_HOST, DEFAULT_WEB_PORT, create_server  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动 TradeShock AI 本地中文页面")
    parser.add_argument("--host", default=DEFAULT_WEB_HOST, help="监听地址，默认只允许本机访问")
    parser.add_argument("--port", type=int, default=DEFAULT_WEB_PORT)
    parser.add_argument("--output-root", type=Path, default=ROOT / "tmp/unified-research",
                        help="AI 演示运行记录目录")
    parser.add_argument("--trade-data-root", type=Path,
                        help="独立贸易数据包目录（包含 BUNDLE_MANIFEST.json 和 data/）")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port 必须位于 1 到 65535")
    if args.trade_data_root is not None:
        try:
            verify_trade_data_bundle(args.trade_data_root)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            parser.error(f"独立贸易数据包核验失败：{exc}")
    server = create_server(root=ROOT, host=args.host, port=args.port,
                           output_root=args.output_root, trade_data_root=args.trade_data_root)
    print(f"TradeShock AI 页面：http://{args.host}:{args.port}")
    print("确定性查询不调用模型；AI 演示仅在页面明确点击后运行。按 Ctrl-C 停止。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止 TradeShock AI 页面。")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
