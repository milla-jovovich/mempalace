"""Tests for Chinese entity detection."""

from mempalace.entity_detector import extract_candidates, score_entity


class TestExtractChineseNames:
    def test_chinese_name_detected(self):
        text = "张三说了很多话，张三还提到了项目进展。张三是团队负责人。"
        candidates = extract_candidates(text)
        assert "张三" in candidates

    def test_chinese_stopwords_filtered(self):
        text = "王国很大，王国有很多人。王国是一个很大的国家。"
        candidates = extract_candidates(text)
        assert "王国" not in candidates

    def test_traditional_chinese_name(self):
        text = "張三說了很多話，張三還提到了項目進展。張三是團隊負責人。"
        candidates = extract_candidates(text)
        assert "張三" in candidates

    def test_three_char_name(self):
        text = "王大明今天来了。王大明负责后端。王大明写了很多代码。"
        candidates = extract_candidates(text)
        assert "王大明" in candidates

    def test_english_detection_unchanged(self):
        text = "Simon said hello. Simon asked about the project. Simon told us the plan."
        candidates = extract_candidates(text)
        assert "Simon" in candidates


class TestScoreChineseEntity:
    def test_chinese_person_verb_signals(self):
        text = "小明说他喜欢Python。小明觉得这个框架不错。"
        lines = text.split("\n")
        result = score_entity("小明", text, lines)
        assert result["person_score"] > 0
        assert any("Chinese" in s for s in result["person_signals"])

    def test_traditional_chinese_verb_signals(self):
        text = "小明說他很開心。小明覺得這個設計很好。"
        lines = text.split("\n")
        result = score_entity("小明", text, lines)
        assert result["person_score"] > 0

    def test_chinese_dialogue_pattern(self):
        text = "小明：你好，今天的进展如何？\n小明：我觉得这个方案可以。"
        lines = text.split("\n")
        result = score_entity("小明", text, lines)
        assert result["person_score"] > 0

    def test_mixed_name_detection(self):
        """English names in Chinese text should still be detected."""
        text = "Simon said hello. Simon asked about it. Simon told us the plan."
        candidates = extract_candidates(text)
        assert "Simon" in candidates
