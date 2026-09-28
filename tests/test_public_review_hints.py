import unittest

from src.tradeintel_ai.public_review_hints import review_hints


class PublicReviewHintsTests(unittest.TestCase):
    def answer(self, text, *, kind="meaning", observation="x:level"):
        return {"interpretations": [{"observation_id": observation, "kind": kind, "text": text}], "watchlist": []}

    def test_amount_ambiguity_requires_review_not_rewrite(self):
        answer = self.answer("总体贸易量下降")
        self.assertEqual(review_hints(answer, question="变化如何")[0]["code"], "amount_quantity_ambiguity")
        self.assertEqual(answer["interpretations"][0]["text"], "总体贸易量下降")

    def test_amount_wording_is_not_flagged(self):
        self.assertEqual(review_hints(self.answer("总进口金额下降"), question="变化如何"), [])

    def test_origin_check_does_not_claim_country_error(self):
        hints = review_hints(self.answer("主要来源为越南", observation="x:origins"), question="来源如何")
        self.assertEqual(hints[0]["code"], "origin_rows_manual_check")

    def test_price_refusal_needs_mechanism_review(self):
        hints = review_hints(self.answer("不能判断涨价"), question="会涨价吗")
        self.assertEqual(hints[0]["code"], "price_mechanism_review")

    def test_hypothesis_does_not_prove_acceptance(self):
        self.assertEqual(review_hints(self.answer("成本可能传导，尚待验证", kind="hypothesis"), question="会涨价吗"), [])
