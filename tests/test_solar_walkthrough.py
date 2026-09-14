from pathlib import Path
import tempfile
import unittest
from scripts.build_solar_demo import build, RUN


class SolarWalkthroughTests(unittest.TestCase):
    def test_readonly_demo_contains_numbers_and_review_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            page = build(RUN, Path(directory)/'demo.html').read_text()
            for text in ['$351,366,193', '$276,580', '0.08%', '只读流程演示',
                         '离线规范化重放', '单商品', '双商品验收通过',
                         '仅在依法适用时', '不是模型原回答']:
                self.assertIn(text, page)
            self.assertNotIn('<script', page)
            self.assertNotIn('fetch(', page)
