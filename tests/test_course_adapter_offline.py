import unittest
from pathlib import Path

from src.tradeintel_ai.course_adapters import (
    AdapterContractError,
    adapt_course_db_tool,
    adapt_course_source,
    cache_scope,
    validate_research_state,
)


class CourseAdapterOfflineTests(unittest.TestCase):
    def test_source_keeps_trade_identity_and_quote(self):
        card = adapt_course_source({
            "source_id": "S1", "policy_id": "p1", "data_version": "v1",
            "quote": "full condition", "location": "page 2",
        })
        self.assertEqual(card.data_version, "v1")
        self.assertEqual(card.quote, "full condition")

    def test_trade_tool_is_fixed_contract_not_sql(self):
        with self.assertRaises(AdapterContractError):
            adapt_course_db_tool({"sql": "select * from trade"})
        query = adapt_course_db_tool({
            "policy_id": "p1", "data_version": "v1", "month": "2026-07", "hts8": ["28046100"],
        })
        self.assertEqual(query.hts8, ("28046100",))

    def test_cache_scope_changes_with_data_version(self):
        self.assertNotEqual(
            cache_scope(policy_id="p", data_version="v1", month="2026-07", question="x"),
            cache_scope(policy_id="p", data_version="v2", month="2026-07", question="x"),
        )

    def test_empty_or_parse_failed_research_cannot_complete(self):
        for state in ({"source_index": []}, {"source_index": [{"source_id": "S1"}], "parse_failed": True}):
            with self.assertRaises(AdapterContractError):
                validate_research_state(state)

    def test_page_has_adapter_status_renderer(self):
        page = Path(__file__).resolve().parents[1] / "web" / "index.html"
        self.assertIn("appendCourseAdapter", page.read_text(encoding="utf-8"))
        self.assertIn("工具适配已通过", page.read_text(encoding="utf-8"))

    def test_review_page_exposes_separate_download_and_view_actions(self):
        page = Path(__file__).resolve().parents[1] / "web" / "interpretation-review.html"
        text = page.read_text(encoding="utf-8")
        self.assertIn("downloadLink.download", text)
        self.assertIn("查看人工审阅稿", text)


if __name__ == "__main__":
    unittest.main()
