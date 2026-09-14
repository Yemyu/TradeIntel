import tempfile
import unittest
from pathlib import Path
from scripts.build_research_review import build, RUN, PINNED

class ReviewPageTests(unittest.TestCase):
    def test_saved_run_render_and_no_active_model_content(self):
        with tempfile.TemporaryDirectory() as folder:
            output=build(destination=Path(folder)/'page.html')
            html=output.read_text()
            for value in ('360,659,187','361,358,006','不采纳为优先调查','有限用途','整份未批准','完整来源资料包'):
                self.assertIn(value,html)
            self.assertNotIn('<script',html.lower())
            self.assertNotIn('fetch(',html)
            self.assertNotIn('file:///Users/',html)
            self.assertIn('&quot;notes&quot;',html)
    def test_changed_input_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in PINNED:
                (root/name).write_bytes((RUN/name).read_bytes())
            (root/'interpretation-response.json').write_text('<script>alert(1)</script>')
            with self.assertRaises(ValueError): build(root,root/'out.html')
            self.assertFalse((root/'out.html').exists())
