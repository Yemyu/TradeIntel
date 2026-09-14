import json
from pathlib import Path
import tempfile
import unittest

from scripts.verify_portable_data import verify


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/PORTABLE_DATA_MANIFEST.json"


class PortableDataManifestTests(unittest.TestCase):
    def test_current_ignored_artifacts_are_verified(self):
        result = verify()
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["counts"], {
            "verified": 4, "missing": 0, "size_mismatch": 0, "sha256_mismatch": 0,
        })
        self.assertEqual(result["network_calls"], 0)

    def test_missing_artifact_is_reported_without_network_or_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "data/PORTABLE_DATA_MANIFEST.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(MANIFEST.read_text(encoding="utf-8"), encoding="utf-8")
            result = verify(root=root, manifest_path=manifest)
            self.assertEqual(result["status"], "incomplete")
            self.assertEqual(result["counts"]["missing"], 4)
            self.assertEqual(result["network_calls"], 0)

    def test_manifest_has_no_absolute_or_parent_paths(self):
        value = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for item in value["artifacts"]:
            path = Path(item["path"])
            self.assertFalse(path.is_absolute())
            self.assertNotIn("..", path.parts)

    def test_incomplete_duplicate_and_malformed_manifests_cannot_report_ready(self):
        import copy
        original = json.loads(MANIFEST.read_text())
        variants = []
        for count in (0, 3):
            value = copy.deepcopy(original)
            value['artifacts'] = value['artifacts'][:count]
            variants.append(value)
        value = copy.deepcopy(original)
        value['artifacts'][3] = copy.deepcopy(value['artifacts'][0])
        variants.append(value)
        for field, bad in [('sha256', 'z' * 64), ('bytes', True), ('path', '.local/glm.json')]:
            value = copy.deepcopy(original)
            value['artifacts'][0][field] = bad
            variants.append(value)
        variants.extend([[], {'version': 'portable-data-manifest-1', 'artifacts': [None] * 4}])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / 'manifest.json'
            for value in variants:
                with self.subTest(value=value):
                    manifest.write_text(json.dumps(value))
                    with self.assertRaises(ValueError):
                        verify(root, manifest)


if __name__ == "__main__":
    unittest.main()
