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
            "docs/handoff/US_AGENT_RETEST_DESIGN_20261001.zh-CN.md",
            "docs/handoff/US_RETEST_FINAL_EXECUTION_PLAN_20261001.zh-CN.md",
            "docs/handoff/US_RETEST_REFERENCE_AND_CONTINUATION_20261001.zh-CN.md",
            "docs/experiments/phase13a-policy-retrieval/corpus.json",
            "docs/handoff/runs/20261002-GLM-FLASH-REVIEW.zh-CN.md",
        ):
            with self.subTest(file=name):
                self.assertIn(name, files)

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


if __name__ == "__main__":
    unittest.main()
