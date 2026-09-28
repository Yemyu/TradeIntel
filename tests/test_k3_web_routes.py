"""K3 HTTP surface checks (static page and read-only coverage endpoint)."""
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.tradeintel_ai.web_app import create_server, _handle_announcement_import


class K3WebRouteTests(unittest.TestCase):
    def test_announcement_page_is_served(self):
        with tempfile.TemporaryDirectory(prefix="k3-web-") as directory:
            root = Path(directory)
            web = root / "web"
            web.mkdir()
            source = Path(__file__).resolve().parents[1] / "web" / "announcement-import.html"
            (web / "announcement-import.html").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            server = create_server(root=root, host="127.0.0.1", port=0, output_root=root / "runs")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urlopen(f"http://127.0.0.1:{server.server_port}/announcement-import") as response:
                    page = response.read().decode("utf-8")
                self.assertIn("新公告导入", page)
                self.assertIn("/api/announcements/enable", page)
            finally:
                server.shutdown()
                server.server_close()

    def test_coverage_endpoint_returns_not_checked_without_trade_query(self):
        with tempfile.TemporaryDirectory(prefix="k3-web-coverage-") as directory:
            root = Path(directory)
            result = _handle_announcement_import(root, {
                "policy_id": "policy-k3-web", "source_id": "notice:p1",
                "text": "A sufficiently long synthetic official notice for the coverage route. " * 2,
            })
            # The candidate is intentionally still disabled, so the endpoint
            # must not pretend that coverage exists or auto-enable it.
            server = create_server(root=root, host="127.0.0.1", port=0, output_root=root / "runs")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = (f"http://127.0.0.1:{server.server_port}/api/announcements/coverage"
                       f"?policy_id=policy-k3-web&doc_version={result['doc_version']}")
                request = Request(url)
                with self.assertRaises(HTTPError) as refused:
                    urlopen(request)
                self.assertEqual(refused.exception.code, 422)
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
