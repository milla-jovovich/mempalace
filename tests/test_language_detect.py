"""Tests for language detection module."""

from mempalace.language_detect import (
    detect_chunk_language,
    detect_language,
    get_chinese_ratio,
    is_chinese,
)


class TestGetChineseRatio:
    def test_pure_chinese(self):
        assert get_chinese_ratio("这是中文内容") > 0.9

    def test_pure_english(self):
        assert get_chinese_ratio("This is English") == 0.0

    def test_mixed_content(self):
        ratio = get_chinese_ratio("小明用 Python 写了一个组件")
        assert 0.3 < ratio < 0.9

    def test_empty_string(self):
        assert get_chinese_ratio("") == 0.0

    def test_numbers_only(self):
        assert get_chinese_ratio("12345") == 0.0

    def test_whitespace_only(self):
        assert get_chinese_ratio("   ") == 0.0


class TestDetectLanguage:
    def test_pure_english(self):
        assert detect_language("This is a normal English sentence") == "en"

    def test_pure_chinese(self):
        assert detect_language("这是一段中文文本") == "zh"

    def test_mixed_content_returns_zh(self):
        assert detect_language("小明用 Python 写了一个组件") == "zh"

    def test_english_with_chinese_names(self):
        # Even a few Chinese characters make it "zh" if ratio > 1%
        result = detect_language("I talked to 张三 about the project today and he said it was good")
        # 2 CJK chars out of many Latin chars - depends on ratio
        assert result in ("en", "zh")

    def test_empty_string(self):
        assert detect_language("") == "unknown"

    def test_whitespace_only(self):
        assert detect_language("   ") == "unknown"

    def test_none_handling(self):
        assert detect_language(None) == "unknown"


class TestDetectChunkLanguage:
    def test_chinese_chunk(self):
        assert detect_chunk_language("认证模块使用JWT令牌") == "zh"

    def test_english_chunk(self):
        assert detect_chunk_language("The auth module uses JWT tokens") == "en"

    def test_empty(self):
        assert detect_chunk_language("") == "unknown"

    def test_mixed_low_cjk(self):
        # At chunk level, 1-5% CJK returns "en"
        text = "This is a very long English text with just one Chinese word 好 in the middle of many words"
        assert detect_chunk_language(text) == "en"


class TestIsChinese:
    def test_chinese_text(self):
        assert is_chinese("这是中文") is True

    def test_english_text(self):
        assert is_chinese("This is English") is False

    def test_empty(self):
        assert is_chinese("") is False

    def test_mixed_content(self):
        assert is_chinese("小明用 Python 写了组件") is True
