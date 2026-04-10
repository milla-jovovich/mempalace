"""Integration tests for the full multilingual pipeline."""

import pytest
from conftest import HAS_MULTILINGUAL

pytestmark = pytest.mark.skipif(
    not HAS_MULTILINGUAL,
    reason="requires sentence-transformers (pip install mempalace[multilingual])",
)

from mempalace.config import MempalaceConfig, get_embedding_function  # noqa: E402
from mempalace.convo_miner import detect_convo_room  # noqa: E402
from mempalace.entity_detector import extract_candidates, score_entity  # noqa: E402
from mempalace.general_extractor import extract_memories  # noqa: E402
from mempalace.language_detect import detect_language, is_chinese  # noqa: E402
from mempalace.spellcheck import spellcheck_user_text  # noqa: E402


class TestFullChinesePipeline:
    """End-to-end: Chinese content → mine → search → detect entities."""

    def test_chinese_conversation_mining(self, tmp_path):
        """Chinese conversation is mined and classified into correct rooms."""
        convo_file = tmp_path / "chinese_convo.txt"
        convo_file.write_text(
            "> 我们今天讨论了代码架构的问题\n"
            "是的，数据库需要重新设计，部署流程也要改\n"
            "> 那测试怎么处理？\n"
            "先写单元测试，然后再调试\n",
            encoding="utf-8",
        )
        room = detect_convo_room(convo_file.read_text(encoding="utf-8"))
        assert room == "technical"

    def test_chinese_entity_detection_pipeline(self):
        """Chinese names are detected and scored in a full pipeline."""
        text = (
            "张三说他喜欢用 Python 写代码。张三觉得这个框架很好用。\n"
            "张三告诉我们下周会完成部署。\n"
        )
        candidates = extract_candidates(text)
        assert "张三" in candidates

        lines = text.split("\n")
        result = score_entity("张三", text, lines)
        assert result["person_score"] > 0

    def test_chinese_memory_extraction_pipeline(self):
        """Chinese text triggers correct memory type extraction."""
        text = "经过讨论，我们决定使用 PostgreSQL 而不是 MySQL。这个方案更适合我们的需求，因为我们需要更好的 JSON 支持。"
        memories = extract_memories(text, min_confidence=0.1)
        assert len(memories) > 0
        assert any(m["memory_type"] == "decision" for m in memories)

    def test_chinese_spellcheck_bypass(self):
        """Chinese text bypasses spellcheck without corruption."""
        text = "这是一段中文文本，不应该被修改"
        assert spellcheck_user_text(text) == text


class TestMixedContentPipeline:
    """Both languages work in the same pipeline."""

    def test_mixed_language_detection(self):
        """Mixed content is correctly detected."""
        assert detect_language("小明用 Python 写了一个组件") == "zh"
        assert detect_language("This is a pure English text about programming") == "en"

    def test_mixed_room_classification(self):
        """Mixed Chinese-English content classifies correctly."""
        content = "我们需要 debug 这个 API，数据库连接有错误"
        room = detect_convo_room(content)
        assert room == "technical"

    def test_mixed_entity_detection(self):
        """English names in Chinese text are detected."""
        text = "Simon said he likes Python. Simon asked about the project. Simon told us the plan."
        candidates = extract_candidates(text)
        assert "Simon" in candidates

    def test_mixed_memory_extraction(self):
        """Both English and Chinese patterns fire in the same text."""
        text_en = "We decided to use GraphQL because it has better flexibility. The trade-off was worth it."
        text_zh = "我们决定使用 GraphQL 而不是 REST，因为它更灵活。权衡之后觉得值得。"
        memories_en = extract_memories(text_en, min_confidence=0.1)
        memories_zh = extract_memories(text_zh, min_confidence=0.1)
        assert any(m["memory_type"] == "decision" for m in memories_en)
        assert any(m["memory_type"] == "decision" for m in memories_zh)


class TestEnglishRegression:
    """Existing English functionality is unchanged."""

    def test_english_room_detection(self):
        content = "The code has a bug in the database query function. Need to debug the API server."
        assert detect_convo_room(content) == "technical"

    def test_english_entity_detection(self):
        text = "Alice said hello. Alice asked about the project. Alice told us the plan."
        candidates = extract_candidates(text)
        assert "Alice" in candidates

    def test_english_memory_extraction(self):
        text = "We decided to use PostgreSQL because it has better JSON support. The trade-off was worth it."
        memories = extract_memories(text, min_confidence=0.1)
        assert any(m["memory_type"] == "decision" for m in memories)

    def test_english_language_detection(self):
        assert detect_language("This is a normal English sentence") == "en"
        assert is_chinese("This is English") is False


class TestEmbeddingConfiguration:
    """Embedding model configuration works correctly."""

    def test_default_embedding_model(self):
        config = MempalaceConfig()
        assert "multilingual" in config.embedding_model.lower()

    def test_embedding_function_returns_valid(self):
        ef = get_embedding_function()
        assert ef is not None

    def test_embedding_model_env_override(self, monkeypatch):
        monkeypatch.setenv("MEMPALACE_EMBEDDING_MODEL", "test-model-name")
        config = MempalaceConfig()
        assert config.embedding_model == "test-model-name"

    def test_language_default(self):
        config = MempalaceConfig()
        assert config.language == "auto"
