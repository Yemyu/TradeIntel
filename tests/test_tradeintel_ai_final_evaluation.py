import csv
import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "evals/final_questions.jsonl"
GOLD = ROOT / "evals/final_gold.json"


class FinalEvaluationFreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.questions = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
        cls.gold = json.loads(GOLD.read_text(encoding="utf-8"))
        cls.answers = cls.gold["answers"]
        with (ROOT / "data/processed/analysis/policy_case_monthly.csv").open(newline="", encoding="utf-8") as handle:
            cls.monthly = {row["month_label"]: row for row in csv.DictReader(handle)}

    def test_question_and_gold_structure_is_complete(self):
        self.assertEqual(len(self.questions), 40)
        template_counts = Counter(item["template_id"] for item in self.questions)
        self.assertEqual(len(template_counts), 10)
        self.assertEqual(set(template_counts.values()), {4})
        ids = {item["id"] for item in self.questions}
        self.assertEqual(ids, set(self.answers))
        self.assertEqual(hashlib.sha256(QUESTIONS.read_bytes()).hexdigest(), self.gold["questions_sha256"])
        self.assertEqual(sum(answer["must_refuse_causal"] for answer in self.answers.values()), 10)
        self.assertEqual(sum(fact["kind"] == "numeric" for answer in self.answers.values() for fact in answer["facts"]), 70)

    def test_every_fact_has_unique_id_and_known_sources(self):
        known = set(self.gold["source_catalog"])
        for answer in self.answers.values():
            fact_ids = [fact["id"] for fact in answer["facts"]]
            self.assertEqual(len(fact_ids), len(set(fact_ids)))
            for fact in answer["facts"]:
                self.assertTrue(set(fact["source_ids"]).issubset(known))
                self.assertIn(fact["kind"], {"numeric", "date", "text"})

    def test_local_source_fingerprints_are_current(self):
        for source in self.gold["source_catalog"].values():
            if "path" not in source:
                continue
            actual = hashlib.sha256((ROOT / source["path"]).read_bytes()).hexdigest()
            self.assertEqual(actual, source["sha256"], source["path"])

    def test_final_manifest_freezes_protocol_gold_runtime_and_questions(self):
        manifest = json.loads((ROOT / "evals/final_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "frozen_for_first_run")
        for path_key, hash_key in (("questions", "questions_sha256"), ("gold", "gold_sha256"),
                                   ("protocol", "protocol_sha256")):
            actual = hashlib.sha256((ROOT / manifest[path_key]).read_bytes()).hexdigest()
            self.assertEqual(actual, manifest[hash_key], manifest[path_key])
        for group in ("runtime_files", "scoring_files"):
            for path, expected in manifest[group].items():
                actual = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                self.assertEqual(actual, expected, path)

    def test_monthly_identity_and_sum_gold_are_independent_csv_calculations(self):
        fields = {
            "china": "target_import_value_consumption_usd",
            "other": "other_origins_import_value_consumption_usd",
            "all": "all_origins_import_value_consumption_usd",
        }
        identity = {"F05": "2017-07", "F06": "2018-07", "F07": "2018-08", "F08": "2019-12"}
        for question_id, month in identity.items():
            facts = {fact["id"]: fact["expected"] for fact in self.answers[question_id]["facts"]}
            for name, field in fields.items():
                self.assertEqual(facts[name], int(self.monthly[month][field]))
            self.assertEqual(facts["china"] + facts["other"], facts["all"])
        windows = {
            "F09": ("china", ["2016-01", "2016-02", "2016-03"]),
            "F10": ("other", ["2017-10", "2017-11", "2017-12"]),
            "F11": ("all", ["2018-08", "2018-09", "2018-10"]),
            "F12": ("china", ["2019-01", "2019-02", "2019-03", "2019-04"]),
            "F13": ("china", ["2017-01", "2017-03", "2017-05"]),
            "F14": ("other", ["2018-02", "2018-04", "2018-06"]),
            "F15": ("all", ["2019-08", "2019-10", "2019-12"]),
            "F16": ("china", ["2018-07", "2018-08", "2018-09"]),
        }
        for question_id, (origin, months) in windows.items():
            facts = {fact["id"]: fact["expected"] for fact in self.answers[question_id]["facts"]}
            values = [int(self.monthly[month][fields[origin]]) for month in months]
            self.assertEqual([facts[month] for month in months], values)
            self.assertEqual(facts["total"], sum(values))

    def test_comparison_gold_matches_frozen_summary(self):
        summary = json.loads((ROOT / "data/processed/analysis/statistical_baseline_summary.json").read_text())
        specifications = {
            "F17": ("immediate_post_same_months", {"china_change": "target_change_pct", "other_change": "other_origins_change_pct"}),
            "F18": ("immediate_post_same_months", {"all_change": "all_origins_change_pct", "share_change": "target_share_change_percentage_points"}),
            "F19": ("pre_policy_placebo_same_months", {"china_change": "target_change_pct", "share_change": "target_share_change_percentage_points"}),
            "F20": ("persistence_monitoring_same_months", {"china_change": "target_change_pct", "other_change": "other_origins_change_pct", "all_change": "all_origins_change_pct"}),
        }
        for question_id, (comparison, fields) in specifications.items():
            facts = {fact["id"]: fact for fact in self.answers[question_id]["facts"]}
            data = summary["comparisons"][comparison]
            for fact_id, field in fields.items():
                expected = data[field] if field.endswith("percentage_points") else data[field] * 100
                self.assertAlmostEqual(facts[fact_id]["expected"], expected, places=12)


if __name__ == "__main__":
    unittest.main()
