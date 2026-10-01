"""Serve a verified static candidate at root and a GitHub-like subpath."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from scripts.build_public_showcase import ASSETS, IDS, verify


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8897)
    args = parser.parse_args(); site = args.site.resolve(); verify(site)
    allowed = set(ASSETS) | {"data.json", "cases/index.json"} | {f"cases/{cid}.json" for cid in IDS}
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            requests.append(path)
            prefix = "/TradeIntel/preview/"
            name = path[len(prefix):] if path.startswith(prefix) else path.lstrip("/")
            name = name or "index.html"
            if name not in allowed:
                self.send_error(404); return
            mime = "text/html" if name.endswith("html") else "text/css" if name.endswith("css") else "application/javascript" if name.endswith(("js", "mjs")) else "application/json" if name.endswith("json") else "text/plain"
            content = (site / name).read_bytes()
            self.send_response(200); self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(content))); self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; base-uri 'self'")
            self.end_headers(); self.wfile.write(content)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"STATIC ONLY http://127.0.0.1:{server.server_address[1]}/TradeIntel/preview/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        (site.parent / "audit/http-requests.json").write_text(json.dumps(requests, indent=2))


if __name__ == "__main__":
    main()
