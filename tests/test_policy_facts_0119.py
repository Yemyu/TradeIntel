"""Schema guards for the independent policy reference; no network calls."""
import json
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory
import unittest

from tradeintel_ai.policy_facts import REFERENCE_RELATIVE, load_frozen_policy_reference


class PolicyFacts0119Tests(unittest.TestCase):
    def _copy_reference_tree(self, root: Path) -> Path:
        source_root = Path(__file__).resolve().parents[1]
        facts_path = root / REFERENCE_RELATIVE
        facts_path.parent.mkdir(parents=True)
        copy2(source_root / REFERENCE_RELATIVE, facts_path)
        corpus_relative = "docs/experiments/phase13a-policy-retrieval/corpus.json"
        corpus_path = root / corpus_relative
        corpus_path.parent.mkdir(parents=True)
        copy2(source_root / corpus_relative, corpus_path)
        source_relative = "data/raw/policy/ustr-section301-list1-2018.pdf"
        source_path = root / source_relative
        source_path.parent.mkdir(parents=True)
        copy2(source_root / source_relative, source_path)
        return facts_path

    def test_invalid_review_date_or_fact_source_fields_fail_closed(self):
        mutations = (
            ("reviewed_at", "not-a-date"),
            ("acceptable_paraphrases", []),
            ("evidence_ids", [123]),
        )
        for field, value in mutations:
            with self.subTest(field=field), TemporaryDirectory() as tmp:
                facts_path = self._copy_reference_tree(Path(tmp))
                reference = json.loads(facts_path.read_text(encoding="utf-8"))
                if field in reference["facts"][0]:
                    reference["facts"][0][field] = value
                else:
                    reference[field] = value
                facts_path.write_text(
                    json.dumps(reference, ensure_ascii=False), encoding="utf-8"
                )
                with self.assertRaisesRegex(ValueError, "无效|不完整"):
                    load_frozen_policy_reference(Path(tmp))


if __name__ == "__main__":
    unittest.main()
