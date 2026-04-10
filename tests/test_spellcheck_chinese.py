"""Tests for Chinese handling in spellcheck.

Regression tests for CJK text corruption reported in upstream issues:
- Issue #37: spellcheck corrupts CJK text
- Issue #231: non-English users get broken spellcheck
"""

from mempalace.spellcheck import spellcheck_user_text, _should_skip


class TestChineseSpellcheck:
    def test_chinese_text_skipped(self):
        """Chinese-dominant text should be returned unchanged."""
        text = "这是中文内容，不需要拼写检查"
        assert spellcheck_user_text(text) == text

    def test_chinese_token_skipped(self):
        """Individual Chinese tokens should be skipped by _should_skip."""
        assert _should_skip("中文", set()) is True
        assert _should_skip("数据库", set()) is True

    def test_english_text_still_works(self):
        """English text should still go through spellcheck."""
        # Without autocorrect installed, text is returned as-is
        text = "This is normal English text"
        result = spellcheck_user_text(text)
        assert isinstance(result, str)

    def test_mixed_text_with_chinese_majority(self):
        """Mixed text with Chinese majority should skip spellcheck."""
        text = "我们今天讨论了很多关于系统架构的问题，包括 database 的选择"
        assert spellcheck_user_text(text) == text


class TestCJKCorruptionRegression:
    """Regression tests: CJK text must NEVER be corrupted by spellcheck.

    These tests verify the fix for the core problem reported in #37/#231:
    the original spellcheck treated CJK characters as misspelled English
    and would corrupt, mangle, or delete them.
    """

    def test_simplified_chinese_preserved(self):
        """Simplified Chinese content passes through unchanged."""
        text = "我决定使用 PostgreSQL 作为主数据库，因为它支持 JSONB 类型"
        assert spellcheck_user_text(text) == text

    def test_traditional_chinese_preserved(self):
        """Traditional Chinese content passes through unchanged."""
        text = "我決定使用 PostgreSQL 作為主資料庫，因為它支持 JSONB 類型"
        assert spellcheck_user_text(text) == text

    def test_japanese_preserved(self):
        """Japanese (hiragana + katakana + kanji) passes through unchanged."""
        text = "データベースの設計について議論しました。PostgreSQLを選びました。"
        assert spellcheck_user_text(text) == text

    def test_korean_preserved(self):
        """Korean (hangul) passes through unchanged."""
        text = "데이터베이스 설계에 대해 논의했습니다. PostgreSQL을 선택했습니다."
        assert spellcheck_user_text(text) == text

    def test_chinese_with_code_snippets(self):
        """Chinese text with inline code is preserved."""
        text = "使用 git rebase -i 来整理提交历史，然后 git push --force-with-lease"
        assert spellcheck_user_text(text) == text

    def test_chinese_entity_names_preserved(self):
        """Chinese person names are not corrupted."""
        text = "张三和李四讨论了项目的技术架构，王五负责前端开发"
        assert spellcheck_user_text(text) == text

    def test_chinese_technical_discussion(self):
        """Real-world Chinese technical discussion preserved verbatim."""
        text = (
            "我们团队使用 React 和 TypeScript 开发前端，"
            "后端用 Python FastAPI，部署在 AWS ECS 上。"
            "遇到了内存泄漏的问题，排查了三天才找到根因。"
        )
        assert spellcheck_user_text(text) == text

    def test_emoji_with_chinese_preserved(self):
        """Chinese text with emoji is not corrupted."""
        text = "今天的会议很顺利 🎉 大家都同意了新方案 👍"
        assert spellcheck_user_text(text) == text

    def test_multiline_chinese_preserved(self):
        """Multi-line Chinese content preserved."""
        text = "第一行中文内容\n第二行中文内容\n第三行混合 English 内容"
        assert spellcheck_user_text(text) == text

    def test_empty_and_whitespace_safe(self):
        """Edge cases don't crash."""
        assert spellcheck_user_text("") == ""
        assert spellcheck_user_text("   ") == "   "
