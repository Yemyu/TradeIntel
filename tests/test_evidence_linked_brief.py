import copy
import json
import tempfile
import unittest
from pathlib import Path

from src.tradeintel_ai.brief_fact_catalog import (
    build_fact_catalog,
    render_fact_catalog,
    validate_fact_catalog,
)
from src.tradeintel_ai.evidence_bundle import build_evidence_bundle
from src.tradeintel_ai.evidence_linked_brief import messages, render_pending, validate
from tests.test_research_brief_v2 import synthetic_sheet, synthetic_trade


def bundle(focus="contrast"):
    return build_evidence_bundle(synthetic_trade(), synthetic_sheet(), focus=focus)


def catalog(focus="contrast"):
    return build_fact_catalog(bundle(focus))


def finding(c, kind="amount_leader", text="这个商品是本次范围内需要优先阅读的对象，仍应结合政策原文限定理解。"):
    observation = next(item for item in c["observations"] if item["type"] == kind)
    fact = next(item for item in c["facts"] if observation["id"] in item["observation_ids"])
    return {
        "observation_id": observation["id"],
        "fact_ids": [fact["id"]],
        "policy_refs": [ref for ref in c["policy_refs"] if ref["hts8"] == fact["product_scope"]],
        "interpretation": text,
        "limitation_ids": [],
    }


class FactCatalogTests(unittest.TestCase):
    def test_catalog_exposes_both_denominators_in_program_text(self):
        c = catalog()
        text = render_fact_catalog(c)
        self.assertIn("美国从所有原产地进口该商品", text)
        self.assertIn("中国原产金额占美国从所有来源进口该商品", text)
        self.assertIn("本次所选商品范围中国原产消费进口合计金额", text)
        validate_fact_catalog(c)

    def test_catalog_hash_detects_tampering(self):
        c = catalog()
        c["facts"][0]["text"] = "被改写的事实"
        with self.assertRaises(ValueError):
            validate_fact_catalog(c)

    def test_unknown_or_cross_case_policy_reference_is_rejected(self):
        c = catalog()
        bad = copy.deepcopy(c)
        bad["policy_refs"][0]["source_id"] = "not-in-sources"
        # Recalculate the outer hash to prove the reference closure catches it.
        import hashlib
        unsigned = copy.deepcopy(bad); unsigned.pop("catalog_sha256")
        bad["catalog_sha256"] = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self.assertRaises(ValueError):
            validate_fact_catalog(bad)

    def test_single_product_zero_denominator_is_unknown(self):
        trade = synthetic_trade()
        trade["data"]["hts8"] = "11111111"
        trade["data"]["series"][0]["product_breakdown"] = [{
            "hts8": "11111111", "all_origins_value_usd": 0, "china_value_usd": 0,
        }]
        c = build_fact_catalog(build_evidence_bundle(trade, synthetic_sheet(), focus="china_amount"))
        unknown = next(item for item in c["facts"] if item["kind"] == "china_share_of_product_percent")
        self.assertEqual(unknown["status"], "unknown")
        self.assertIn("未知", render_fact_catalog(c))


class EvidenceLinkedBriefTests(unittest.TestCase):
    def test_messages_contain_catalog_binding_and_no_raw_bundle(self):
        c = catalog()
        payload = json.loads(messages("解释金额规模", c)[1]["content"])
        self.assertEqual(payload["catalog_sha256"], c["catalog_sha256"])
        self.assertIn("美国从中国原产地进口该商品", json.dumps(payload, ensure_ascii=False))
        self.assertNotIn("evidence-bundle-v2", json.dumps(payload, ensure_ascii=False))

    def test_valid_answer_is_manual_review_only(self):
        c = catalog("china_amount")
        answer = {
            "schema_version": "evidence-linked-brief-v3",
            "catalog_sha256": c["catalog_sha256"],
            "findings": [finding(c)],
            "followups": [],
        }
        result = validate(answer, c)
        self.assertEqual(result["status"], "manual_review_required")
        self.assertFalse(result["approved"])
        self.assertTrue(result["task_coverage"]["structural_coverage_complete"])
        output = render_pending(answer, c, result)
        self.assertIn("程序事实", output)
        self.assertIn("AI解释（原文）", output)
        self.assertIn("美国从中国原产地进口该商品", output)

    def test_numeric_and_dependency_word_are_flags_not_approval(self):
        c = catalog("china_amount")
        answer = {
            "schema_version": "evidence-linked-brief-v3",
            "catalog_sha256": c["catalog_sha256"],
            "findings": [finding(c, text="该商品金额为4.7%，显示对中国依赖较高。")],
            "followups": [],
        }
        result = validate(answer, c)
        self.assertEqual(result["status"], "manual_review_required")
        self.assertFalse(result["semantic_approval"])
        self.assertTrue({flag["reason"] for flag in result["flags"]} >= {
            "numeric_claim_in_interpretation", "possible_supply_claim",
        })

    def test_fact_must_be_bound_to_the_claimed_observation(self):
        c = catalog("contrast")
        amount = next(item for item in c["observations"] if item["type"] == "amount_leader")
        unrelated = next(item for item in c["facts"] if not amount["id"] in item["observation_ids"])
        answer = {
            "schema_version": "evidence-linked-brief-v3",
            "catalog_sha256": c["catalog_sha256"],
            "findings": [{**finding(c), "fact_ids": [unrelated["id"]]}],
            "followups": [],
        }
        with self.assertRaises(ValueError):
            validate(answer, c)

    def test_irrelevant_policy_ref_is_rejected(self):
        c = catalog("china_amount")
        f = finding(c)
        other = next(ref for ref in c["policy_refs"] if ref["hts8"] != f["policy_refs"][0]["hts8"])
        f["policy_refs"] = [other]
        answer = {
            "schema_version": "evidence-linked-brief-v3",
            "catalog_sha256": c["catalog_sha256"], "findings": [f], "followups": [],
        }
        # The reference is valid for the request but unrelated to this finding;
        # the validator must reject it before any semantic review.
        self.assertRaises(ValueError, validate, answer, c)

    def test_extra_fields_and_duplicate_observations_are_rejected(self):
        c = catalog("contrast")
        f = finding(c)
        answer = {"schema_version": "evidence-linked-brief-v3", "catalog_sha256": c["catalog_sha256"],
                  "findings": [f, copy.deepcopy(f)], "followups": []}
        with self.assertRaises(ValueError):
            validate(answer, c)
        extra = {"schema_version": "evidence-linked-brief-v3", "catalog_sha256": c["catalog_sha256"],
                 "findings": [{**f, "amount": 1}], "followups": []}
        with self.assertRaises(ValueError):
            validate(extra, c)


if __name__ == "__main__":
    unittest.main()
