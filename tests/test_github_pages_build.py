"""Pages construction needs only the checked-in public assets."""
import copy
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts import build_github_pages as pages
from scripts.build_public_showcase import read_json, save_json


class PagesBuildTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "source"
        self.source.mkdir()
        for name in pages.FILES:
            target = self.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(pages.ROOT / "web/design-preview" / name, target)
        self.output = self.root / "site"

    def test_build_and_read_only_verify(self):
        self.assertEqual(pages.build(self.source, self.output),
                         {"status": "verified", "case_count": 4, "asset_count": 14})
        before = {p.relative_to(self.output): p.read_bytes()
                  for p in self.output.rglob("*") if p.is_file()}
        pages.verify(self.output)
        self.assertEqual(before, {p.relative_to(self.output): p.read_bytes()
                                 for p in self.output.rglob("*") if p.is_file()})
        self.assertNotIn("source", read_json(self.output / "data.json"))
        self.assertFalse((self.output / "live.js").exists())
        with self.assertRaises(ValueError):
            pages.build(self.source, self.output)

    def test_missing_asset_refused_before_output(self):
        (self.source / "cases/soybean-oil.json").unlink()
        with self.assertRaises(ValueError):
            pages.build(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_wrong_identity_or_amount_refused(self):
        path = self.source / "cases/soybean-trade.json"
        original = read_json(path)
        for mutation in ("id", "amount", "private"):
            case = copy.deepcopy(original)
            if mutation == "id": case["id"] = "soybean-oil"
            elif mutation == "amount": case["reports"][0]["summary"]["latest_value_usd"] += 1
            else: case["turns"][0]["text"]["en"] = "/Users/test/private"
            save_json(path, case)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                pages.build(self.source, self.output)
            self.assertFalse(self.output.exists())

    def test_source_symlink_refused(self):
        path = self.source / "style.css"
        path.unlink()
        path.symlink_to(pages.ROOT / "web/design-preview/style.css")
        with self.assertRaises(ValueError):
            pages.build(self.source, self.output)

    def test_unexpected_html_markers_refused(self):
        path = self.source / "index.html"
        path.write_text(path.read_text().replace('id="workspace"', 'id="different"'))
        with self.assertRaises(ValueError):
            pages.build(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_live_form_or_extra_file_refused(self):
        pages.build(self.source, self.output)
        path = self.output / "index.html"
        original = path.read_text()
        for fragment in ('<script src="live.js"></script>', '<form id="question-form">',
                         '<button id="open-model-settings">'):
            path.write_text(original + fragment)
            with self.subTest(fragment=fragment), self.assertRaises(ValueError):
                pages.verify(self.output)
        path.write_text(original)
        (self.output / "config.json").write_text('{}')
        with self.assertRaises(ValueError): pages.verify(self.output)

    def test_output_symlink_refused(self):
        self.output.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(ValueError): pages.build(self.source, self.output)
        with self.assertRaises(ValueError): pages.verify(self.output)


if __name__ == "__main__":
    unittest.main()
