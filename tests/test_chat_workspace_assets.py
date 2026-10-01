"""Only the local web server may enable the preview's API handlers."""
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import urlopen

from tradeintel_ai.web_app import create_server

ROOT = Path(__file__).resolve().parents[1]


class ChatWorkspaceAssetsTests(unittest.TestCase):
    def test_source_defaults_to_static_showcase(self):
        html = (ROOT / "web/design-preview/index.html").read_text()
        self.assertEqual(html.count('data-runtime="showcase"'), 1)
        self.assertNotIn('data-runtime="local"', html)
        for element in ("chat-messages", "conversation-scroll", "question-form", "scope-preview"):
            self.assertEqual(html.count(f'id="{element}"'), 1)

    def test_preview_server_sets_local_marker_without_changing_the_source(self):
        source = ROOT / "web/design-preview/index.html"
        before = source.read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            server = create_server(root=Path(folder), port=0)
            server.RequestHandlerClass.static_root = ROOT / "web"
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                for path in ("/preview/", "/preview/index.html", "/preview/?runtime=showcase"):
                    with urlopen(base + path) as response:
                        html = response.read().decode()
                    self.assertEqual(html.count('data-runtime="local"'), 1)
                    self.assertNotIn('data-runtime="showcase"', html)
            finally:
                server.shutdown()
                thread.join(timeout=3)
                server.server_close()
        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
