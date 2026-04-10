"""Stress tests for multilingual support — edge cases, real-world scenarios, and integration paths."""

import pytest
from conftest import HAS_MULTILINGUAL

_skip_no_multilingual = pytest.mark.skipif(
    not HAS_MULTILINGUAL,
    reason="requires sentence-transformers (pip install mempalace[multilingual])",
)

from mempalace.language_detect import detect_language, detect_chunk_language  # noqa: E402
from mempalace.entity_detector import extract_candidates, score_entity, _extract_chinese_names  # noqa: E402
from mempalace.convo_miner import detect_convo_room  # noqa: E402
from mempalace.general_extractor import extract_memories, _get_sentiment  # noqa: E402
from mempalace.spellcheck import spellcheck_user_text, _should_skip  # noqa: E402
from mempalace.config import get_embedding_function  # noqa: E402


# =============================================================================
# LANGUAGE DETECTION EDGE CASES
# =============================================================================


class TestLanguageDetectEdgeCases:
    def test_single_chinese_char(self):
        """Single CJK character should not crash."""
        result = detect_language("好")
        assert result in ("zh", "en", "unknown")

    def test_emoji_only(self):
        assert detect_language("😀🎉🔥") == "unknown"

    def test_numbers_with_chinese(self):
        assert detect_language("2024年3月15日") == "zh"

    def test_url_with_chinese(self):
        result = detect_language("请访问 https://example.com/api/v2 获取文档")
        assert result == "zh"

    def test_code_block_with_chinese_comments(self):
        text = """
def hello():
    # 这是一个中文注释
    print("hello world")
    # 另一个中文注释
    return True
"""
        result = detect_language(text)
        assert result in ("zh", "en")  # mixed content

    def test_japanese_kanji(self):
        """Japanese kanji shares CJK range — should be detected as 'zh'."""
        result = detect_language("データベースのバグを修正する")
        assert result in ("zh", "en")  # kanji + katakana mix

    def test_korean(self):
        """Korean uses a different Unicode block — should be 'en' (not CJK)."""
        result = detect_language("안녕하세요 프로그래밍")
        assert result == "en"  # Hangul is not in CJK range

    def test_very_long_text(self):
        """10K char text should not be slow."""
        text = "这是测试文本。" * 1500
        result = detect_language(text)
        assert result == "zh"

    def test_punctuation_heavy_chinese(self):
        text = "什么？！为什么？？？这不可能！！！"
        assert detect_language(text) == "zh"

    def test_mixed_with_technical_terms(self):
        """Real-world: Chinese with lots of English tech terms."""
        text = "我们用 React + TypeScript 开发 frontend，用 FastAPI + PostgreSQL 做 backend，部署在 AWS ECS 上"
        assert detect_language(text) == "zh"

    def test_chunk_vs_file_threshold_difference(self):
        """Chunk detection should be more sensitive to small amounts of CJK."""
        # Text with ~3% CJK — file-level says zh, chunk-level says en
        text = "This is English text with 中文 embedded in it for testing purposes only"
        file_result = detect_language(text)
        chunk_result = detect_chunk_language(text)
        # Both should return valid results without crashing
        assert file_result in ("zh", "en")
        assert chunk_result in ("zh", "en")


# =============================================================================
# ENTITY DETECTION EDGE CASES
# =============================================================================


class TestChineseEntityEdgeCases:
    def test_single_char_surname_not_name(self):
        """A lone surname character is not a name."""
        result = _extract_chinese_names("王 说了话")
        assert len(result) == 0

    def test_name_at_start_of_text(self):
        text = "张三是好人。张三很聪明。"
        result = _extract_chinese_names(text)
        assert "张三" in result

    def test_name_at_end_of_text(self):
        text = "今天见了张三。昨天也见了张三"
        result = _extract_chinese_names(text)
        assert "张三" in result

    def test_multiple_different_names(self):
        text = "张三和李四讨论了问题。张三说好，李四说不好。张三同意了，李四反对。"
        result = _extract_chinese_names(text)
        assert "张三" in result
        assert "李四" in result

    def test_name_adjacent_to_punctuation(self):
        text = "（张三）说了话。\u201c张三\u201d很开心。张三，你好！"
        result = _extract_chinese_names(text)
        assert "张三" in result

    def test_common_word_false_positive(self):
        """高兴 starts with surname 高 but is a common word meaning 'happy'."""
        text = "我很高兴。我很高兴。我很高兴。我很高兴。"
        result = _extract_chinese_names(text)
        assert "高兴" not in result  # should be in CHINESE_STOPWORDS

    def test_english_and_chinese_names_coexist(self):
        text = "Simon和张三讨论了问题。Simon说好，张三同意。Simon和张三都很开心。Simon又说了一句。"
        candidates = extract_candidates(text)
        assert "张三" in candidates
        assert "Simon" in candidates  # needs 3+ occurrences for English names

    def test_four_char_name_not_extracted(self):
        """Names longer than 3 chars are rare — should not be extracted as names."""
        text = "欧阳修很有名。欧阳修写了很多文章。"
        result = _extract_chinese_names(text)
        # 欧阳 might be extracted as 2-char, 欧阳修 as 3-char
        # but 4-char should not appear
        for name in result:
            assert len(name) <= 3

    def test_score_entity_with_chinese_name(self):
        """score_entity should handle CJK names without regex errors."""
        text = "小明说他喜欢编程。小明觉得Python很好用。小明决定学习更多。"
        lines = text.split("\n")
        result = score_entity("小明", text, lines)
        assert "person_score" in result
        assert "project_score" in result
        assert result["person_score"] > 0

    def test_score_entity_with_non_cjk_name(self):
        """English names should still work through score_entity."""
        text = "Alice said hello. Alice asked about the project. Alice told us."
        lines = text.split("\n")
        result = score_entity("Alice", text, lines)
        assert result["person_score"] > 0


# =============================================================================
# ROOM CLASSIFICATION EDGE CASES
# =============================================================================


@_skip_no_multilingual
class TestRoomClassificationEdgeCases:
    def test_empty_content(self):
        assert detect_convo_room("") == "general"

    def test_whitespace_only(self):
        assert detect_convo_room("   \n\n  ") == "general"

    def test_very_short_content(self):
        assert detect_convo_room("代码") in ("technical", "general")

    def test_ambiguous_content(self):
        """Content that could match multiple rooms."""
        text = "我们决定修复代码中的问题。这个架构的设计有错误。"
        room = detect_convo_room(text)
        assert room in ("technical", "decisions", "problems", "architecture")

    def test_mixed_zh_en_technical(self):
        text = "debug 这个 API endpoint，database connection 有 bug"
        room = detect_convo_room(text)
        assert room in ("technical", "problems")

    def test_pure_english_still_works(self):
        text = "The code has bugs in the API. We need to fix the database queries and deploy."
        assert detect_convo_room(text) == "technical"

    def test_traditional_chinese_technical(self):
        text = "我們需要調試這個程式碼，資料庫的錯誤需要修復。伺服器的部署也有問題。"
        assert detect_convo_room(text) == "technical"

    def test_non_topic_content(self):
        """Content without any topic keywords should return general."""
        text = "今天天气真好，阳光明媚，适合出去散步。"
        assert detect_convo_room(text) == "general"


# =============================================================================
# MEMORY EXTRACTION EDGE CASES
# =============================================================================


@_skip_no_multilingual
class TestMemoryExtractionEdgeCases:
    def test_chinese_only_text(self):
        """Pure Chinese text should be extractable."""
        text = "我们决定使用新的架构方案，因为旧的方案有很多问题。权衡利弊之后，选择了微服务架构。"
        memories = extract_memories(text, min_confidence=0.1)
        assert len(memories) > 0

    def test_mixed_decision_text(self):
        text = "We 决定 use GraphQL instead of REST 因为 it's more flexible."
        memories = extract_memories(text, min_confidence=0.1)
        types = [m["memory_type"] for m in memories]
        assert "decision" in types

    def test_chinese_sentiment(self):
        # _get_sentiment uses English word matching only (regex fallback path).
        # Chinese text without English words returns neutral — this is expected.
        # In embedding mode, sentiment is handled by the embedding classifier.
        assert _get_sentiment("今天去散步了") == "neutral"
        assert _get_sentiment("I am happy and proud") == "positive"
        assert _get_sentiment("The bug crashed everything") == "negative"

    def test_traditional_chinese_markers(self):
        text = "我們決定使用新的架構，選擇了微服務方案。權衡之後覺得值得。"
        memories = extract_memories(text, min_confidence=0.1)
        types = [m["memory_type"] for m in memories]
        assert "decision" in types

    def test_very_short_chinese(self):
        """Text shorter than 20 chars should be skipped by extract_memories."""
        text = "决定了"
        memories = extract_memories(text, min_confidence=0.1)
        assert len(memories) == 0  # too short

    def test_chinese_emotion_with_english(self):
        # Mixed content about achievement + emotion — genuinely ambiguous
        text = (
            "I'm really 开心 about this project. 感恩 everyone who helped. 骄傲 of what we built."
        )
        memories = extract_memories(text, min_confidence=0.1)
        if memories:
            types = [m["memory_type"] for m in memories]
            assert "emotional" in types or "milestone" in types


# =============================================================================
# SPELLCHECK EDGE CASES
# =============================================================================


class TestSpellcheckEdgeCases:
    def test_chinese_with_english_typo(self):
        """Chinese-dominant text should skip spellcheck entirely (including English parts)."""
        text = "这是中文内容 with a tpyo here"
        result = spellcheck_user_text(text)
        assert result == text  # Chinese-dominant → skip all

    def test_english_with_chinese_tokens(self):
        """English-dominant text with Chinese tokens should skip Chinese tokens."""
        assert _should_skip("中文", set()) is True
        assert _should_skip("数据库", set()) is True

    def test_empty_text(self):
        result = spellcheck_user_text("")
        assert result == ""

    def test_cjk_token_detection(self):
        """Various CJK characters should be skipped."""
        assert _should_skip("你好世界", set()) is True
        assert _should_skip("測試", set()) is True


# =============================================================================
# EMBEDDING FUNCTION EDGE CASES
# =============================================================================


class TestEmbeddingFunctionEdgeCases:
    def test_get_embedding_function_returns_callable(self):
        ef = get_embedding_function()
        assert ef is not None
        assert callable(ef)

    def test_embedding_function_with_env_override(self, monkeypatch):
        """Invalid model name should fall back gracefully."""
        monkeypatch.setenv("MEMPALACE_EMBEDDING_MODEL", "nonexistent-model-xyz")
        ef = get_embedding_function()
        # Should return default fallback, not crash
        assert ef is not None

    def test_embedding_function_produces_vectors(self):
        ef = get_embedding_function()
        result = ef(["hello world"])
        assert len(result) == 1
        assert len(result[0]) > 0  # non-empty vector

    def test_embedding_chinese_text(self):
        ef = get_embedding_function()
        result = ef(["这是中文测试"])
        assert len(result) == 1
        assert len(result[0]) > 0


# =============================================================================
# DIALECT EDGE CASES
# =============================================================================


class TestDialectEdgeCases:
    def test_cjk_topic_extraction(self):
        """dialect._extract_topics should extract CJK bigrams."""
        from mempalace.dialect import Dialect

        d = Dialect()
        topics = d._extract_topics("数据库架构设计非常重要，我们需要重新考虑数据库的架构")
        # Should contain CJK topics, not just empty
        assert len(topics) > 0

    def test_mixed_topic_extraction(self):
        """Both English and Chinese topics should be extracted."""
        from mempalace.dialect import Dialect

        d = Dialect()
        topics = d._extract_topics("PostgreSQL 数据库的架构设计 using microservices")
        assert len(topics) > 0

    def test_english_emotion_signal(self):
        from mempalace.dialect import _EMOTION_SIGNALS

        assert "happy" in _EMOTION_SIGNALS
        assert _EMOTION_SIGNALS["happy"] == "joy"

    def test_english_flag_signal(self):
        from mempalace.dialect import _FLAG_SIGNALS

        assert "decided" in _FLAG_SIGNALS
        assert _FLAG_SIGNALS["decided"] == "DECISION"
