"""Public guides should have usable links, paired languages, and no private notes."""
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
PAIRS = (
    ("README.md", "README.zh-CN.md"),
    ("docs/README.md", "docs/README.zh-CN.md"),
    ("docs/LOCAL_RUN.md", "docs/LOCAL_RUN.zh-CN.md"),
    ("docs/CURRENT_PRODUCT.md", "docs/CURRENT_PRODUCT.zh-CN.md"),
    ("docs/PUBLIC_SHOWCASE.md", "docs/PUBLIC_SHOWCASE.zh-CN.md"),
    ("docs/TESTING.md", "docs/TESTING.zh-CN.md"),
    ("docs/MODEL_SELECTION.md", "docs/MODEL_SELECTION.zh-CN.md"),
    ("data/README.md", "data/README.zh-CN.md"),
    ("web/design-preview/README.md", "web/design-preview/README.zh-CN.md"),
    ("evals/README.md", "evals/README.zh-CN.md"),
)
GUIDES = tuple(name for pair in PAIRS for name in pair) + (
    "docs/USAGE.zh-CN.md", "docs/AGENT_REVIEWER_QUICKSTART.zh-CN.md",
)
PRIVATE_FILES = (
    "PROJECT_PLAN.md",
    "docs/PROJECT_CONTEXT_REFERENCE.zh-CN.md",
    "docs/PROJECT_CONTEXT_HISTORY.zh-CN.md",
    "docs/PROJECT_REVIEW_20261002.zh-CN.md",
    "docs/DELIVERY.zh-CN.md",
    "docs/COMPETITIVE_POSITIONING.zh-CN.md",
    "docs/handoff/README.zh-CN.md",
    "docs/handoff/STATUS.zh-CN.md",
    "docs/handoff/MASTER_PLAN.zh-CN.md",
)
PUBLIC_DOCS = {
    name for pair in PAIRS for name in pair if name.startswith("docs/")
} | {
    "docs/USAGE.zh-CN.md", "docs/AGENT_REVIEWER_QUICKSTART.zh-CN.md",
    "docs/releases/showcase-20261002.md", "docs/releases/SHA256SUMS-20261002.txt",
}


def tracked_files():
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    )
    return {name.decode("utf-8") for name in result.stdout.split(b"\0") if name}


class PublicDocumentationTests(unittest.TestCase):
    def test_language_pairs_have_same_shell_commands(self):
        for english, chinese in PAIRS:
            with self.subTest(english=english):
                en = (ROOT / english).read_text(encoding="utf-8")
                zh = (ROOT / chinese).read_text(encoding="utf-8")
                self.assertIn(Path(chinese).name, en)
                self.assertIn(Path(english).name, zh)
                commands = lambda text: re.findall(
                    r"```(?:bash|sh)\n(.*?)```", text, flags=re.S
                )
                self.assertEqual(commands(en), commands(zh))

    def test_current_guide_links_resolve(self):
        for name in GUIDES:
            path = ROOT / name
            text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
            for target in re.findall(r"\]\(([^)]+)\)", text):
                target = target.strip("<>")
                parsed = urlsplit(target)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                resolved = (path.parent / unquote(parsed.path)).resolve()
                with self.subTest(file=name, link=target):
                    self.assertTrue(resolved.is_relative_to(ROOT))
                    self.assertTrue(resolved.exists(), target)

    def test_private_planning_is_not_tracked(self):
        files = tracked_files()
        for name in PRIVATE_FILES:
            with self.subTest(file=name):
                self.assertNotIn(name, files)
        for name in files:
            self.assertFalse(name.startswith("docs/learning/"), name)
            self.assertFalse(name.startswith("docs/PROJECT_CONTEXT"), name)
            self.assertFalse(name.startswith("docs/ASTRA_"), name)

    def test_docs_contains_only_current_public_guides(self):
        files = tracked_files()
        self.assertEqual({name for name in files if name.startswith("docs/")}, PUBLIC_DOCS)
        # New working notes are ignored by default, not just the old filenames.
        result = subprocess.run(
            ["git", "check-ignore", "--stdin"], cwd=ROOT,
            input="docs/handoff/new-note.md\ndocs/decisions/new-note.md\ndocs/push-record.md\n",
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 3)

    def test_tracked_markdown_does_not_link_to_ignored_notes(self):
        links = []
        for name in tracked_files():
            path = ROOT / name
            if path.suffix != ".md" or not path.exists():
                continue
            text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
            for target in re.findall(r"\]\(([^\s)]+)\)", text):
                parsed = urlsplit(target.strip("<>"))
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                resolved = (path.parent / unquote(parsed.path)).resolve()
                if resolved.is_relative_to(ROOT):
                    links.append((name, resolved.relative_to(ROOT).as_posix()))
        result = subprocess.run(
            ["git", "check-ignore", "--stdin"], cwd=ROOT,
            input="\n".join(target for _, target in links),
            capture_output=True, text=True,
        )
        self.assertIn(result.returncode, (0, 1), result.stderr)
        ignored = set(result.stdout.splitlines())
        for name, target in links:
            with self.subTest(file=name, link=target):
                self.assertNotIn(target, ignored)

    def test_required_evaluation_sources_remain_tracked(self):
        files = tracked_files()
        for name in (
            "evals/us_agent_retest_v1/scenarios.json",
            "docs/MODEL_SELECTION.md", "docs/MODEL_SELECTION.zh-CN.md",
            "data/policy/section301-list1/corpus.json",
            "data/policy/section301-list1/development_results.json",
            "tests/fixtures/evaluation/development-checklist-0093.json",
        ):
            with self.subTest(file=name):
                self.assertIn(name, files)

    def test_private_evaluation_runs_are_not_tracked(self):
        for name in tracked_files():
            for prefix in (
                "evals/announcement_reading_v2/", "evals/announcement_reading_v3/",
                "evals/trade_followup_v1/", "evals/trade_model_v3/frozen/",
            ):
                self.assertFalse(name.startswith(prefix), name)
        files = tracked_files()
        for name in (
            "evals/policy_extraction_v1/development_reference.zh-CN.md",
            "evals/policy_extraction_v1/r2_reading_reference_v2.zh-CN.md",
            "evals/public_brief_v1/SCORING_V3.zh-CN.md",
        ):
            self.assertNotIn(name, files)

    def test_installation_and_api_scope_are_explicit(self):
        for name in ("README.md", "README.zh-CN.md", "docs/LOCAL_RUN.md", "docs/LOCAL_RUN.zh-CN.md"):
            with self.subTest(file=name):
                text = (ROOT / name).read_text(encoding="utf-8")
                for token in ("python3.13 --version", "python3.13 -m venv .venv",
                              "fcntl", "GLM", "DeepSeek", "Codex", "shasum -a 256"):
                    self.assertIn(token, text)
                self.assertNotIn("/Users/ye/", text)

    def test_public_guides_do_not_instruct_personal_model_switching(self):
        for name in GUIDES:
            text = (ROOT / name).read_text(encoding="utf-8")
            for phrase in ("用户已确认", "用户确认收尾", "下一步模型", "请先切换",
                           "申请材料可用的事实草稿", "不要关闭其他应用",
                           "不会替访客支付", "不限于早期五种"):
                with self.subTest(file=name, phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_public_text_has_no_private_development_handoff_language(self):
        private_phrases = (
            "本步结果：", "下一步模型：", "用户确认收尾", "用户已切换",
            "隔壁对话框", "减少AI痕迹", "减少 AI 痕迹", "/Users/ye/",
        )
        for name in tracked_files():
            # Tests intentionally contain forbidden text as rejection fixtures.
            if name.startswith(("tests/", "web/design-preview/vendor/")):
                continue
            path = ROOT / name
            if path.suffix not in {".md", ".txt", ".py", ".js", ".html", ".json", ".jsonl", ".yml", ".yaml"}:
                continue
            text = path.read_text(encoding="utf-8")
            for phrase in private_phrases:
                with self.subTest(file=name, phrase=phrase):
                    self.assertNotIn(phrase, text)
            self.assertIsNone(re.search(r"请先切换到\s*GPT", text), name)


if __name__ == "__main__":
    unittest.main()
